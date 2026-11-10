"""Thin OpenRouter HTTP client: model discovery and single-model chat calls (ADR-009).

Provider integration only; no domain logic. Retries apply to 429, 5xx,
timeouts and connection errors, with exponential backoff and `Retry-After`.
Every attempt produces an `Attempt` so the caller can record usage.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.llm.settings import LlmSettings

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_BACKOFF_S = 30.0
MODELS_CACHE_S = 3600.0


class OpenRouterError(Exception):
    """Base class. `kind` is a stable code; messages never contain the API key.

    `attempt` is set when an HTTP request was actually sent (so the caller can record it).
    """

    kind = "error"
    attempt: "Attempt | None" = None
    attempts: "list[Attempt]" = []   # T055: every attempt of the call, including earlier retries


class AuthenticationError(OpenRouterError):
    kind = "auth"


class PaymentRequiredError(OpenRouterError):
    kind = "payment_required"


class ModelUnavailableError(OpenRouterError):
    kind = "model_unavailable"


class TransientError(OpenRouterError):
    kind = "transient"


def failure_category(http_status: int | None, error_kind: str | None = None,
                     body: Any = None) -> str | None:
    """Stable failure category (T055). Never inferred from free-form message text.

    402 is `insufficient_credits` only when the error body confirms code 402; otherwise `payment_required`.
    429 is a rate limit, never a billing problem; timeouts, connection errors and 5xx are provider failures.
    """
    if error_kind in ("timeout", "connection") or (http_status is not None and http_status >= 500):
        return "provider_failure"
    if error_kind in ("truncated", "empty", "invalid_response"):
        return "invalid_output"
    if error_kind == "budget":
        return "budget_blocked"
    if http_status == 402:
        code = ((body or {}).get("error") or {}).get("code") if isinstance(body, dict) else None
        return "insufficient_credits" if code == 402 else "payment_required"
    return {401: "auth_invalid", 403: "forbidden", 408: "provider_failure", 429: "rate_limited"}.get(
        http_status, "request_rejected" if http_status and http_status >= 400 else None)


def retry_after_seconds(value: str | None) -> float | None:
    """Retry-After in seconds (delta form only; an HTTP date or garbage is ignored)."""
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    context_length: int | None
    prompt_price: str
    completion_price: str
    supported_parameters: tuple[str, ...]
    input_modalities: tuple[str, ...] = ("text",)
    output_modalities: tuple[str, ...] = ("text",)
    request_price: str = ""            # USD per request, when OpenRouter lists one (T055)
    reasoning_price: str = ""          # USD per internal reasoning token, when priced separately (T055)

    @property
    def is_text_chat(self) -> bool:
        """Accepts text and produces only text (excludes e.g. audio or image generators)."""
        return "text" in self.input_modalities and tuple(self.output_modalities) == ("text",)

    @property
    def is_free(self) -> bool:
        return _is_zero(self.prompt_price) and _is_zero(self.completion_price)


@dataclass
class Attempt:
    """One HTTP attempt; mapped to an LlmUsageRecord by app.llm.usage."""

    model_requested: str
    attempt: int
    status: str                      # ok | error | rate_limited | timeout | invalid_output | budget_blocked
    latency_ms: int
    http_status: int | None = None
    model_used: str | None = None
    provider: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    cost_source: str = "missing"     # provider_reported | generation_endpoint | missing
    generation_id: str | None = None
    content: str | None = None
    error_kind: str | None = None
    reasoning_tokens: int | None = None
    failure_category: str | None = None
    retry_after_s: float | None = None   # T064: the provider's Retry-After on a 429/5xx, in seconds

    def __post_init__(self) -> None:
        if self.failure_category is None and self.status != "ok":
            self.failure_category = failure_category(self.http_status, self.error_kind)


NATIVE_LENGTH_REASONS = frozenset({"length", "max_tokens", "max_output_tokens", "model_length"})


def reached_output_limit(choice: dict[str, Any], tokens_out: int | None, max_tokens: int) -> bool:
    """True when a reply stopped at its output-token limit, so its content is incomplete.

    OpenRouter normalizes the stop to `finish_reason: "length"`; some providers only set
    `native_finish_reason`, and some report no reason at all, in which case output tokens
    reaching the limit are taken as truncation.
    """
    if choice.get("finish_reason") == "length":
        return True
    if str(choice.get("native_finish_reason") or "").lower() in NATIVE_LENGTH_REASONS:
        return True
    return choice.get("finish_reason") is None and tokens_out is not None and tokens_out >= max_tokens


def _is_zero(price: Any) -> bool:
    try:
        return float(price) == 0.0
    except (TypeError, ValueError):
        return False


class OpenRouterClient:
    def __init__(self, settings: LlmSettings, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.settings = settings
        self._sleep = sleep
        self._clock = clock
        self._models: tuple[float, list[ModelInfo]] | None = None
        self._http = httpx.Client(
            base_url=settings.base_url,
            timeout=httpx.Timeout(settings.timeout_s, connect=min(10.0, settings.timeout_s)),
            transport=transport,
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "X-Title": settings.app_title,
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OpenRouterClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------ discovery

    def list_models(self, refresh: bool = False) -> list[ModelInfo]:
        """GET /models, cached for an hour. Prices and availability are never hardcoded."""
        if self._models and not refresh and self._clock() - self._models[0] < MODELS_CACHE_S:
            return self._models[1]
        response = self._request("GET", "/models")
        models = [
            ModelInfo(
                id=m["id"],
                name=m.get("name", m["id"]),
                context_length=m.get("context_length"),
                prompt_price=str(m.get("pricing", {}).get("prompt", "")),
                completion_price=str(m.get("pricing", {}).get("completion", "")),
                supported_parameters=tuple(m.get("supported_parameters") or ()),
                input_modalities=tuple((m.get("architecture") or {}).get("input_modalities") or ("text",)),
                output_modalities=tuple((m.get("architecture") or {}).get("output_modalities") or ("text",)),
                request_price=str(m.get("pricing", {}).get("request", "") or ""),
                reasoning_price=str(m.get("pricing", {}).get("internal_reasoning", "") or ""),
            )
            for m in response.json().get("data", [])
            if isinstance(m, dict) and m.get("id")
        ]
        self._models = (self._clock(), models)
        return models

    # ------------------------------------------------------------------ chat

    def chat(self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None,
             temperature: float = 0.0, before_attempt: Callable[[], bool] | None = None,
             extra_body: dict[str, Any] | None = None) -> list[Attempt]:
        """Call one model, retrying transient failures. Returns all attempts; the last is final.

        `before_attempt` is asked before every HTTP attempt (budget reservation); if it returns False
        no request is sent and a final `budget_blocked` attempt is returned. `extra_body` adds optional
        request fields (e.g. `reasoning`) that the caller has checked the model supports.

        @throws AuthenticationError on 401/403 (stop everything)
        @throws PaymentRequiredError on 402
        """
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens or self.settings.max_tokens,
            "temperature": temperature,
            "usage": {"include": True},  # ask OpenRouter to report tokens and cost
            **(extra_body or {}),
        }
        attempts: list[Attempt] = []
        for number in range(1, self.settings.max_retries + 2):
            if before_attempt is not None and not before_attempt():
                attempts.append(Attempt(model, number, "budget_blocked", 0, error_kind="budget"))
                return attempts
            started = self._clock()
            try:
                response = self._http.post("/chat/completions", json=payload)
            except httpx.TimeoutException:
                attempts.append(Attempt(model, number, "timeout", self._elapsed(started), error_kind="timeout"))
                if number <= self.settings.max_retries:
                    self._backoff(number, None)
                    continue
                return attempts
            except httpx.TransportError:
                attempts.append(Attempt(model, number, "error", self._elapsed(started), error_kind="connection"))
                if number <= self.settings.max_retries:
                    self._backoff(number, None)
                    continue
                return attempts

            latency = self._elapsed(started)
            if response.status_code in (401, 402):
                body = _json(response)
                sent = Attempt(model, number, "error", latency, response.status_code,
                               error_kind=f"http_{response.status_code}",
                               failure_category=failure_category(response.status_code, body=body))
                exc: OpenRouterError = (AuthenticationError("OpenRouter rejected the API key (HTTP 401)")
                                        if response.status_code == 401 else
                                        PaymentRequiredError(f"OpenRouter returned HTTP 402 ({sent.failure_category})"))
                exc.attempt, exc.attempts = sent, [*attempts, sent]
                raise exc
            if response.status_code in RETRY_STATUSES:
                status = "rate_limited" if response.status_code == 429 else "error"
                wait = retry_after_seconds(response.headers.get("Retry-After"))
                attempts.append(Attempt(model, number, status, latency, response.status_code,
                                        error_kind=f"http_{response.status_code}", retry_after_s=wait))
                # T064: a wait longer than the maximum back-off is not slept through; the router cools the model.
                if number <= self.settings.max_retries and (wait is None or wait <= MAX_BACKOFF_S):
                    self._backoff(number, response.headers.get("Retry-After"))
                    continue
                return attempts
            if response.status_code >= 400:
                # 400/403/404 etc.: this model is unusable for this request or account; try the next one.
                attempts.append(Attempt(model, number, "error", latency, response.status_code,
                                        error_kind=f"http_{response.status_code}"))
                return attempts

            attempts.append(self._parse_success(model, number, latency, response, payload["max_tokens"]))
            return attempts
        return attempts

    def _parse_success(self, model: str, number: int, latency: int, response: httpx.Response,
                       max_tokens: int) -> Attempt:
        try:
            body = response.json()
            choice = body["choices"][0]
            content = choice["message"].get("content")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            return Attempt(model, number, "error", latency, response.status_code, error_kind="invalid_response")
        usage = body.get("usage") or {}
        attempt = Attempt(
            model_requested=model,
            attempt=number,
            status="ok",
            latency_ms=latency,
            http_status=response.status_code,
            model_used=body.get("model"),
            provider=body.get("provider"),
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            generation_id=body.get("id"),
            content=content,
        )
        if reached_output_limit(choice, attempt.tokens_out, max_tokens):
            # Cut off by max_tokens (often reasoning models): the answer is incomplete.
            attempt.status, attempt.error_kind, attempt.failure_category = "invalid_output", "truncated", "invalid_output"
        elif not (content or "").strip():
            attempt.status, attempt.error_kind, attempt.failure_category = "invalid_output", "empty", "invalid_output"
        if isinstance(usage.get("cost"), (int, float)):
            attempt.cost_usd, attempt.cost_source = float(usage["cost"]), "provider_reported"
        elif attempt.generation_id:
            self._fill_cost_from_generation(attempt)
        return attempt

    def generation_stats(self, generation_id: str) -> dict[str, Any] | None:
        """GET /generation?id=... (read-only, app key): OpenRouter's settled metadata, or None (T055 reconcile)."""
        try:
            response = self._http.get("/generation", params={"id": generation_id})
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        return (_json(response) or {}).get("data") or None

    def key_info(self) -> tuple[dict[str, Any] | None, str | None]:
        """GET /key with the application key (T055): (data, None) or (None, failure category)."""
        return self._read_only("/key", None)

    def account_credits(self, management_key: str) -> tuple[dict[str, Any] | None, str | None]:
        """GET /credits with a separate management key, read-only (T055). The key is sent only in this request's
        Authorization header and is never logged or returned."""
        return self._read_only("/credits", management_key)

    def _read_only(self, path: str, key: str | None) -> tuple[dict[str, Any] | None, str | None]:
        headers = {"Authorization": f"Bearer {key}"} if key else None
        try:
            response = self._http.get(path, headers=headers)
        except httpx.TimeoutException:
            return None, "provider_failure"
        except httpx.TransportError:
            return None, "provider_failure"
        if response.status_code != 200:
            return None, failure_category(response.status_code, body=_json(response))
        data = (_json(response) or {}).get("data")
        return (data, None) if isinstance(data, dict) else (None, "invalid_output")

    def _fill_cost_from_generation(self, attempt: Attempt) -> None:
        """Fallback: GET /generation?id=... (stats can lag; one short retry)."""
        for delay in (0.0, 1.0):
            if delay:
                self._sleep(delay)
            try:
                response = self._http.get("/generation", params={"id": attempt.generation_id})
            except httpx.HTTPError:
                return
            if response.status_code == 200:
                data = (response.json() or {}).get("data") or {}
                if isinstance(data.get("total_cost"), (int, float)):
                    attempt.cost_usd, attempt.cost_source = float(data["total_cost"]), "generation_endpoint"
                    attempt.tokens_in = attempt.tokens_in if attempt.tokens_in is not None else data.get("tokens_prompt")
                    attempt.tokens_out = (attempt.tokens_out if attempt.tokens_out is not None
                                          else data.get("tokens_completion"))
                return

    # ------------------------------------------------------------------ helpers

    def _request(self, method: str, path: str) -> httpx.Response:
        for number in range(1, self.settings.max_retries + 2):
            try:
                response = self._http.request(method, path)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if number > self.settings.max_retries:
                    raise TransientError(f"{method} {path} failed: {type(exc).__name__}") from None
                self._backoff(number, None)
                continue
            if response.status_code in (401, 403):
                raise AuthenticationError(f"OpenRouter rejected the API key (HTTP {response.status_code})")
            if response.status_code in RETRY_STATUSES and number <= self.settings.max_retries:
                self._backoff(number, response.headers.get("Retry-After"))
                continue
            if response.status_code >= 400:
                raise TransientError(f"{method} {path} failed with HTTP {response.status_code}")
            return response
        raise TransientError(f"{method} {path} failed")  # pragma: no cover

    def _backoff(self, number: int, retry_after: str | None) -> None:
        delay = min(MAX_BACKOFF_S, 2 ** (number - 1) + random.uniform(0, 0.5))
        if retry_after:
            try:
                delay = min(MAX_BACKOFF_S, max(0.0, float(retry_after)))
            except ValueError:
                pass
        self._sleep(delay)

    def _elapsed(self, started: float) -> int:
        return max(0, int((self._clock() - started) * 1000))

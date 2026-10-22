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
    """Base class. `kind` is a stable code; messages never contain the API key."""

    kind = "error"


class AuthenticationError(OpenRouterError):
    kind = "auth"


class PaymentRequiredError(OpenRouterError):
    kind = "payment_required"


class ModelUnavailableError(OpenRouterError):
    kind = "model_unavailable"


class TransientError(OpenRouterError):
    kind = "transient"


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
    status: str                      # ok | error | rate_limited | timeout
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
            )
            for m in response.json().get("data", [])
            if isinstance(m, dict) and m.get("id")
        ]
        self._models = (self._clock(), models)
        return models

    # ------------------------------------------------------------------ chat

    def chat(self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None,
             temperature: float = 0.0) -> list[Attempt]:
        """Call one model, retrying transient failures. Returns all attempts; the last is final.

        @throws AuthenticationError on 401/403 (stop everything)
        @throws PaymentRequiredError on 402
        """
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens or self.settings.max_tokens,
            "temperature": temperature,
            "usage": {"include": True},  # ask OpenRouter to report tokens and cost
        }
        attempts: list[Attempt] = []
        for number in range(1, self.settings.max_retries + 2):
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
            if response.status_code == 401:
                raise AuthenticationError("OpenRouter rejected the API key (HTTP 401)")
            if response.status_code == 402:
                raise PaymentRequiredError("OpenRouter reports insufficient credit (HTTP 402)")
            if response.status_code in RETRY_STATUSES:
                status = "rate_limited" if response.status_code == 429 else "error"
                attempts.append(Attempt(model, number, status, latency, response.status_code,
                                        error_kind=f"http_{response.status_code}"))
                if number <= self.settings.max_retries:
                    self._backoff(number, response.headers.get("Retry-After"))
                    continue
                return attempts
            if response.status_code >= 400:
                # 400/403/404 etc.: this model is unusable for this request or account; try the next one.
                attempts.append(Attempt(model, number, "error", latency, response.status_code,
                                        error_kind=f"http_{response.status_code}"))
                return attempts

            attempts.append(self._parse_success(model, number, latency, response))
            return attempts
        return attempts

    def _parse_success(self, model: str, number: int, latency: int, response: httpx.Response) -> Attempt:
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
            generation_id=body.get("id"),
            content=content,
        )
        if choice.get("finish_reason") == "length":
            # Cut off by max_tokens (often reasoning models): the answer is incomplete.
            attempt.status, attempt.error_kind = "invalid_output", "truncated"
        if isinstance(usage.get("cost"), (int, float)):
            attempt.cost_usd, attempt.cost_source = float(usage["cost"]), "provider_reported"
        elif attempt.generation_id:
            self._fill_cost_from_generation(attempt)
        return attempt

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

"""OpenRouter settings from the environment or the git-ignored `.env` (ADR-009).

The API key is server-side only: never logged, never returned by any endpoint,
and excluded from `repr`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class LlmConfigurationError(RuntimeError):
    """Raised when required LLM configuration is missing or invalid."""


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not key.lstrip().startswith("#"):
                values[key.strip()] = value.strip()
    return values


def _bool(value: str) -> bool:
    if value.lower() in ("1", "true", "yes", "on"):
        return True
    if value.lower() in ("", "0", "false", "no", "off"):
        return False
    raise LlmConfigurationError(f"not a boolean: {value!r}")


# Generation output limit (T011, restored to 4000 in T012: 6000 gave no measured gain, more latency).
GENERATION_MAX_TOKENS_DEFAULT = 4000
GENERATION_MAX_TOKENS_MIN = 1000
GENERATION_MAX_TOKENS_MAX = 16000
# T012: models never used for question generation (still used for blind solve and review).
GENERATION_EXCLUDED_DEFAULT = "nvidia/nemotron-3.5-super-vl:free"
# OpenRouter unified `reasoning.effort` values accepted for generation; "" sends nothing.
REASONING_EFFORTS = ("", "minimal", "low", "medium", "high")


@dataclass(frozen=True)
class LlmSettings:
    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    free_models: tuple[str, ...] = ()       # ordered preference; empty = auto-select discovered free models
    paid_model: str | None = None
    allow_paid: bool = False
    timeout_s: float = 60.0
    max_retries: int = 2                    # retries per model on 429 / 5xx / timeout
    max_tokens: int = 1024
    generation_max_tokens: int = GENERATION_MAX_TOKENS_DEFAULT  # question generation only (ADR-010)
    generation_excluded_models: tuple[str, ...] = (GENERATION_EXCLUDED_DEFAULT,)
    generation_reasoning_effort: str = ""   # optional; sent only to models that support `reasoning`
    max_requests_per_day: int = 50
    max_usd_per_day: float = 0.0
    app_title: str = "Mentor Pro"

    @classmethod
    def load(cls, env_file: Path = REPO_ROOT / ".env") -> "LlmSettings":
        """Environment variables override `.env`; missing key -> LlmConfigurationError."""
        file_values = read_env_file(env_file)

        def get(name: str, default: str = "") -> str:
            return os.environ.get(name, file_values.get(name, default)).strip()

        api_key = get("OPENROUTER_API_KEY")
        if not api_key:
            raise LlmConfigurationError("OPENROUTER_API_KEY is not set (run scripts/dev/setup_secrets.py)")
        try:
            settings = cls(
                api_key=api_key,
                base_url=get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
                free_models=tuple(m.strip() for m in get("OPENROUTER_FREE_MODELS").split(",") if m.strip()),
                paid_model=get("OPENROUTER_PAID_MODEL") or None,
                allow_paid=_bool(get("OPENROUTER_ALLOW_PAID", "false")),
                timeout_s=float(get("OPENROUTER_TIMEOUT_S", "60")),
                max_retries=int(get("OPENROUTER_MAX_RETRIES", "2")),
                max_tokens=int(get("OPENROUTER_MAX_TOKENS", "1024")),
                generation_max_tokens=int(get("OPENROUTER_GENERATION_MAX_TOKENS", str(GENERATION_MAX_TOKENS_DEFAULT))),
                generation_excluded_models=tuple(
                    m.strip() for m in get("OPENROUTER_GENERATION_EXCLUDED_MODELS", GENERATION_EXCLUDED_DEFAULT)
                    .split(",") if m.strip()),
                generation_reasoning_effort=get("OPENROUTER_GENERATION_REASONING_EFFORT").lower(),
                max_requests_per_day=int(get("OPENROUTER_MAX_REQUESTS_PER_DAY", "50")),
                max_usd_per_day=float(get("OPENROUTER_MAX_USD_PER_DAY", "0")),
            )
        except ValueError as exc:
            raise LlmConfigurationError(f"invalid OpenRouter setting: {exc}") from exc
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.base_url.startswith("https://"):
            raise LlmConfigurationError("OPENROUTER_BASE_URL must use https")
        if not 0 <= self.max_retries <= 5:
            raise LlmConfigurationError("OPENROUTER_MAX_RETRIES must be 0..5")
        if self.timeout_s <= 0 or self.max_tokens <= 0 or self.max_requests_per_day < 0 or self.max_usd_per_day < 0:
            raise LlmConfigurationError("timeouts, token and budget limits must be positive")
        if not GENERATION_MAX_TOKENS_MIN <= self.generation_max_tokens <= GENERATION_MAX_TOKENS_MAX:
            raise LlmConfigurationError(f"OPENROUTER_GENERATION_MAX_TOKENS must be "
                                        f"{GENERATION_MAX_TOKENS_MIN}..{GENERATION_MAX_TOKENS_MAX}")
        if self.generation_reasoning_effort not in REASONING_EFFORTS:
            raise LlmConfigurationError("OPENROUTER_GENERATION_REASONING_EFFORT must be empty, minimal, low, "
                                        "medium or high")
        if self.allow_paid and not self.paid_model:
            raise LlmConfigurationError("OPENROUTER_ALLOW_PAID=true requires OPENROUTER_PAID_MODEL")

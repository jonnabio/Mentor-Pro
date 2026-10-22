"""Developer-only OpenRouter connectivity check (ADR-009). Not exposed by the web app.

Lists models, sends one tiny prompt through free-first routing, records usage
and prints model, tokens, cost (USD) and latency. Never prints the API key.

Usage:
    .venv/Scripts/python.exe -m app.llm.connectivity [--no-store] [--prompt TEXT]
"""

from __future__ import annotations

import argparse
import json
import sys

from app.llm.client import OpenRouterClient
from app.llm.router import free_candidates, route
from app.llm.settings import LlmConfigurationError, LlmSettings
from app.llm.usage import MemoryUsageStore, UsageStore

DEFAULT_PROMPT = "Responda solo con la palabra: listo"


def run(settings: LlmSettings, store, prompt: str = DEFAULT_PROMPT, client: OpenRouterClient | None = None) -> dict:
    owns_client = client is None
    client = client or OpenRouterClient(settings)
    try:
        models = client.list_models()
        free = [m for m in models if m.is_free]
        result = route(client, store, [{"role": "user", "content": prompt}], purpose="connectivity_test",
                       max_tokens=16)
        final = result.final
        return {
            "status": result.status,
            "message": result.message,
            "models_listed": len(models),
            "free_models_listed": len(free),
            "candidates": result.candidates or free_candidates(client),
            "attempts": len(result.records),
            "model_requested": final.model_requested if final else None,
            "model_used": final.model_used if final else None,
            "provider": final.provider if final else None,
            "tier": result.tier,
            "tokens_in": final.tokens_in if final else None,
            "tokens_out": final.tokens_out if final else None,
            "cost_usd": final.cost_usd if final else None,
            "cost_source": final.cost_source if final else None,
            "latency_ms": final.latency_ms if final else None,
            "response_preview": (result.content or "")[:80],
        }
    finally:
        if owns_client:
            client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Developer-only OpenRouter connectivity check.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--no-store", action="store_true", help="keep usage records in memory only")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        settings = LlmSettings.load()
    except LlmConfigurationError as exc:
        print(json.dumps({"status": "not_configured", "message": str(exc)}, indent=2))
        return 2
    if args.no_store:
        store = MemoryUsageStore()
    else:
        from curriculum.db import database_url

        store = UsageStore(database_url())
    report = run(settings, store, args.prompt)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

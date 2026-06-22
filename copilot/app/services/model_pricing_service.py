"""Model pricing lookup for ledger cost estimates.

Prices are operational data. Keep production prices out of business logic and
prefer environment/config maintenance. The built-in table only contains test
models used by regression tests.
"""

from __future__ import annotations

import json
import os
from typing import Any


_BUILTIN_PRICING: dict[tuple[str, str], dict[str, Any]] = {
    ("test_provider", "cheap-test"): {
        "prompt_per_1k_tokens": 0.001,
        "completion_per_1k_tokens": 0.002,
        "currency": "USD",
    },
}


def estimate_model_cost(
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> dict[str, Any]:
    pricing = get_model_pricing(provider, model)
    if not pricing:
        return {"estimated_cost": 0.0, "currency": "USD", "cost_unknown": True}

    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    prompt_rate = float(pricing.get("prompt_per_1k_tokens") or 0.0)
    completion_rate = float(pricing.get("completion_per_1k_tokens") or 0.0)
    return {
        "estimated_cost": (prompt / 1000.0) * prompt_rate + (completion / 1000.0) * completion_rate,
        "currency": str(pricing.get("currency") or "USD"),
        "cost_unknown": False,
    }


def get_model_pricing(provider: str, model: str) -> dict[str, Any] | None:
    key = (_normalize(provider), _normalize(model))
    configured = _load_env_pricing()
    if key in configured:
        return configured[key]
    return _BUILTIN_PRICING.get(key)


def _load_env_pricing() -> dict[tuple[str, str], dict[str, Any]]:
    raw = os.environ.get("COPILOT_MODEL_PRICING_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    rows: list[dict[str, Any]]
    if isinstance(parsed, list):
        rows = [row for row in parsed if isinstance(row, dict)]
    elif isinstance(parsed, dict):
        rows = []
        for key, value in parsed.items():
            if not isinstance(value, dict):
                continue
            provider, _, model = str(key).partition("/")
            row = dict(value)
            row.setdefault("provider", provider)
            row.setdefault("model", model)
            rows.append(row)
    else:
        return {}

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        provider = _normalize(row.get("provider"))
        model = _normalize(row.get("model"))
        if not provider or not model:
            continue
        result[(provider, model)] = {
            "prompt_per_1k_tokens": float(row.get("prompt_per_1k_tokens") or 0.0),
            "completion_per_1k_tokens": float(row.get("completion_per_1k_tokens") or 0.0),
            "currency": str(row.get("currency") or "USD"),
        }
    return result


def _normalize(value: Any) -> str:
    return str(value or "").strip()

"""
Token accounting and cost metering.

Every LLM call in the research pipeline goes through `invoke_llm`, which keeps
a running per-run cost so the UI can show a real number instead of a guess.
Pricing is approximate USD per 1M tokens and can be overridden with the
`MODEL_PRICING_JSON` env var if a model's rate changes.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# USD per 1M tokens: (input, output)
_DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "opus": (15.0, 75.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
    "fable": (3.0, 15.0),
}
_FALLBACK_PRICING = (3.0, 15.0)


def _pricing_table() -> dict[str, tuple[float, float]]:
    table = dict(_DEFAULT_PRICING)
    raw = os.getenv("MODEL_PRICING_JSON")
    if raw:
        try:
            for name, pair in json.loads(raw).items():
                table[name.lower()] = (float(pair[0]), float(pair[1]))
        except (ValueError, TypeError, IndexError):
            logger.warning("MODEL_PRICING_JSON is not valid JSON — using built-in pricing")
    return table


def price_for(model: str) -> tuple[float, float]:
    """Return (input, output) USD-per-1M-token pricing for a model name."""
    name = (model or "").lower()
    table = _pricing_table()
    if name in table:
        return table[name]
    for key, pair in table.items():
        if key in name:
            return pair
    return _FALLBACK_PRICING


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = price_for(model)
    return round((input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate, 6)


def _read_usage(response: Any) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from a LangChain message, if present."""
    usage = getattr(response, "usage_metadata", None) or {}
    if not usage:
        meta = getattr(response, "response_metadata", None) or {}
        usage = meta.get("usage") or {}
    return int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)


@dataclass
class CostMeter:
    """Accumulates calls, tokens and cost for a single research run."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def add(self, *, model: str, label: str, input_tokens: int, output_tokens: int) -> float:
        cost = estimate_cost(model, input_tokens, output_tokens)
        self.calls.append(
            {
                "model": model,
                "label": label,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost,
            }
        )
        return cost

    @property
    def total_usd(self) -> float:
        return round(sum(c["cost_usd"] for c in self.calls), 6)

    @property
    def total_tokens(self) -> int:
        return sum(c["input_tokens"] + c["output_tokens"] for c in self.calls)

    def trace(self) -> list[dict[str, Any]]:
        return list(self.calls)


def invoke_llm(llm: Any, messages: list[Any], meter: CostMeter | None = None, label: str = "") -> Any:
    """
    Invoke an LLM and record its usage on the meter.

    Keeps agent code free of bookkeeping while still producing a per-run
    `model_trace` for the report footer.
    """
    response = llm.invoke(messages)
    if meter is not None:
        model = getattr(llm, "model", None) or getattr(llm, "model_name", "") or "unknown"
        input_tokens, output_tokens = _read_usage(response)
        meter.add(
            model=str(model),
            label=label or "llm_call",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    return response

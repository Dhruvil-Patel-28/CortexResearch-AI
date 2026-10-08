"""
Guardrail trace — per-run visibility of what the guardrails caught.

Sanitization happens inside tools and adapters, on worker threads that have no
access to run state, so this uses the same accepted pattern as the S1
DecisionLog: process-wide monotonic totals, and per-run figures computed as a
delta between snapshots taken at run start and finalisation.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_totals: dict[str, float] = {
    "scanned": 0,
    "pii_redacted": 0,
    "injections_stripped": 0,
    "output_redactions": 0,
    "output_injection_risk": 0.0,
}

_KEYS = tuple(_totals)


def record_content(summary: dict) -> None:
    """Fold one `sanitize_content` summary into the totals. Never raises."""
    try:
        with _lock:
            _totals["scanned"] += 1
            _totals["pii_redacted"] += len(summary.get("pii_kinds") or [])
            if summary.get("injection_action") == "strip":
                _totals["injections_stripped"] += summary.get("injection_count") or 0
    except Exception as exc:  # noqa: BLE001 — tracing must never break sanitization
        logger.debug("guardrail trace record_content failed: %s", exc)


def record_output(redactions: list[dict], injection_risk: float) -> None:
    """Fold one LLM-output check into the totals. Never raises."""
    try:
        with _lock:
            _totals["output_redactions"] += sum(r.get("count", 0) for r in redactions or [])
            _totals["output_injection_risk"] = max(_totals["output_injection_risk"], injection_risk or 0.0)
    except Exception as exc:  # noqa: BLE001 — tracing must never break a run
        logger.debug("guardrail trace record_output failed: %s", exc)


def snapshot() -> dict:
    """Current totals (copy)."""
    with _lock:
        return dict(_totals)


def attach_guardrail_trace(model_trace: dict | list, start: dict) -> dict | list:
    """
    Attach per-run guardrail deltas to a report's model_trace.

    `start` is the snapshot taken when the run began; the deltas are
    totals-minus-start. Lists (legacy bare call log) pass through wrapped by
    the caller — here we only add the guardrails key when a dict is given.
    """
    if not isinstance(model_trace, dict):
        return model_trace
    now = snapshot()
    delta = {k: round(now[k] - start.get(k, 0), 3) for k in _KEYS}
    model_trace["guardrails"] = delta
    return model_trace


def reset_for_tests() -> None:
    with _lock:
        for k in _KEYS:
            _totals[k] = 0

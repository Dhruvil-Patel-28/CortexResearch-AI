"""
Thread-safe event emitter for live run streaming.

Agents call `emit_event(state, kind, ...)` which fans out to the job's queue
(consumed by the SSE endpoint) and to the log. When no hook is attached —
CLI runs, tests — emitting is a no-op.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class NullEmitter:
    """Swallows events (used for CLI runs and tests)."""

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        return None


def emit_event(state: dict[str, Any], event_type: str, **payload: Any) -> None:
    """Emit one streaming event if the current run has a hook attached."""
    emit = state.get("emit") if isinstance(state, dict) else None
    if emit is None:
        return
    body = {"type": event_type, "ts": time.time(), **payload}
    try:
        emit(event_type, body)
    except Exception as exc:  # noqa: BLE001 — never let telemetry break a run
        logger.debug("event emit failed: %s", exc)

    # Mirror scalar event fields into the active Langfuse trace, if any.
    try:
        from utils import tracing

        trace = tracing.current_trace()
        if trace is not None and trace.enabled:
            scalars = {
                k: v
                for k, v in payload.items()
                if isinstance(v, (str, int, float, bool)) or v is None
            }
            trace.event(event_type, scalars)
    except Exception as exc:  # noqa: BLE001
        logger.debug("trace event mirror failed: %s", exc)


def step_event(agent: str, action: str, **extra: Any) -> dict[str, Any]:
    """Canonical agent-step event body (also used for the persisted trace)."""
    return {
        "agent_name": agent,
        "action": action,
        "tools_used": extra.pop("tools_used", []),
        **extra,
    }

"""
Langfuse run tracing — observability wrapper, failure-isolated by design.

One `RunTrace` per research run records LLM generations, S1/guardrail events,
and eval scores into the user's Langfuse instance. Everything degrades to a
no-op when Langfuse is unconfigured, unreachable, or raises: tracing must
never fail a run.

The active trace lives in a ContextVar; `LLMClient.invoke` records a
generation whenever one is set (batch/ingest paths stay untraced unless
wrapped in `active_trace`).
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import threading
import time

from utils.config import settings

logger = logging.getLogger(__name__)

_current: contextvars.ContextVar["RunTrace | None"] = contextvars.ContextVar(
    "run_trace", default=None
)

_client = None  # Langfuse instance, False sentinel (init failed), or None (unbuilt)
_client_lock = threading.Lock()


def _build_client():
    """Build the real Langfuse client (imported here only)."""
    from langfuse import Langfuse

    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )


def _get_client():
    """Lazily build the client; None when disabled or previously failed."""
    global _client
    if not (
        settings.langfuse_enabled
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    ):
        return None
    if _client is None:
        with _client_lock:
            if _client is None:
                try:
                    _client = _build_client()
                except Exception as exc:  # noqa: BLE001 — tracing must never block startup
                    logger.warning("Langfuse init failed — tracing disabled: %s", exc)
                    _client = False
    return _client if _client else None


class RunTrace:
    """One research run in Langfuse. All methods are no-op-safe."""

    def __init__(self, enabled: bool, trace=None) -> None:
        self.enabled = enabled
        self._trace = trace

    @classmethod
    def start(cls, query: str, depth: str, job_id: str = "") -> "RunTrace":
        """Open a trace; degrades to a disabled no-op on any failure."""
        try:
            client = _get_client()
            if client is None:
                return cls(False)
            return cls(True, client.trace(
                name="research-run",
                input=query,
                metadata={"depth": depth, "job_id": job_id},
            ))
        except Exception as exc:  # noqa: BLE001
            logger.debug("RunTrace.start failed: %s", exc)
            return cls(False)

    def generation(self, model: str, label: str, input_tokens: int = 0,
                   output_tokens: int = 0, latency_ms: float = 0.0) -> None:
        if not self.enabled:
            return
        try:
            self._trace.generation(
                name=label,
                model=model,
                usage={"input": input_tokens, "output": output_tokens},
                metadata={"latency_ms": round(latency_ms, 1)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("trace.generation failed: %s", exc)

    def event(self, name: str, payload: dict | None = None) -> None:
        if not self.enabled:
            return
        try:
            self._trace.event(name=name, metadata=payload or {})
        except Exception as exc:  # noqa: BLE001
            logger.debug("trace.event failed: %s", exc)

    def score(self, name: str, value: float, comment: str = "") -> None:
        if not self.enabled:
            return
        try:
            self._trace.score(name=name, value=value, comment=comment)
        except Exception as exc:  # noqa: BLE001
            logger.debug("trace.score failed: %s", exc)

    def finish(self, status: str) -> None:
        self.event("run_completed", {"status": status})


@contextlib.contextmanager
def active_trace(query: str = "", depth: str = "", job_id: str = ""):
    """Open a RunTrace and make it current for this context."""
    trace = RunTrace.start(query, depth, job_id=job_id)
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


def current_trace() -> "RunTrace | None":
    """The trace active in this context, or None."""
    return _current.get()


def reset_for_tests() -> None:
    global _client
    _client = None
    _current.set(None)

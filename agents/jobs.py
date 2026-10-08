"""
Background research jobs with live event streaming.

A run happens in a worker thread; every agent step, tool call and verification
result is appended to the job's trace. The API's SSE endpoint tails that trace
and forwards events to the browser, so the UI shows the real pipeline instead
of a timer-driven fake progress bar.

State lives in this process (single-user local app). The trace is also mirrored
into the `jobs` table so a page reload can replay what happened.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from agents.research_agent import run_research
from store import db as store

logger = logging.getLogger(__name__)

MAX_TRACE_EVENTS = 1000
PERSIST_EVERY = 5


@dataclass
class RunStream:
    """Live event trace for one research job."""

    job_id: str
    kind: str = "research"
    brief_id: str | None = None
    status: str = "pending"
    events: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _since_persist: int = 0

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = dict(payload or {})
        event.setdefault("type", event_type)
        event["job_id"] = self.job_id
        with self._lock:
            self.events.append(event)
            if len(self.events) > MAX_TRACE_EVENTS:
                del self.events[: len(self.events) - MAX_TRACE_EVENTS]
            self._since_persist += 1
            should_persist = self._since_persist >= PERSIST_EVERY
            if should_persist:
                self._since_persist = 0
        if should_persist:
            self._persist_progress()

    def close(self, status: str = "done") -> None:
        self.status = status
        self._persist_progress()

    def since(self, index: int) -> tuple[list[dict[str, Any]], int]:
        """Return (events after `index`, new index) — safe against trace trimming."""
        with self._lock:
            if index > len(self.events):
                index = 0
            return list(self.events[index:]), len(self.events)

    @property
    def finished(self) -> bool:
        return self.status in {"done", "error"}

    @property
    def pct(self) -> int:
        return max([e.get("pct", 0) for e in self.events] or [0])

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "brief_id": self.brief_id,
            "pct": self.pct,
            "events": list(self.events),
        }

    def _persist_progress(self) -> None:
        stage = next((e.get("stage") for e in reversed(self.events) if e.get("stage")), None)
        store.update_job(
            self.job_id,
            status=self.status,
            progress={
                "stage": stage,
                "pct": self.pct,
                "events": list(self.events[-80:]),
                "brief_id": self.brief_id,
            },
        )


_registry: dict[str, RunStream] = {}
_registry_lock = threading.Lock()


def get_run(job_id: str) -> RunStream | None:
    """Live run, or None when the job belongs to a previous process."""
    with _registry_lock:
        return _registry.get(job_id)


def replay_events(job_id: str) -> list[dict[str, Any]]:
    """Event history for a job — from memory when live, else from the DB."""
    run = get_run(job_id)
    if run:
        return list(run.events)
    job = store.get_job(job_id)
    if not job:
        return []
    return list((job.get("progress") or {}).get("events") or [])


def _register(run: RunStream) -> None:
    with _registry_lock:
        _registry[run.job_id] = run


def start_research_job(
    query: str,
    *,
    depth: str = "standard",
    item_id: str | None = None,
    topic_id: str | None = None,
    session_id: str | None = None,
    persist_brief: bool = True,
    kind: str = "research",
) -> dict[str, str]:
    """
    Start a deep-research run in the background.

    Args:
        kind: "research" for free-form questions, "delta" for topic delta
              briefs, "brief" for item briefs — recorded on the job row so the
              UI can label the run.

    Returns:
        {"job_id", "brief_id"} — the brief id is where the finished report lands.
    """
    query = query.strip()
    brief_id = (
        store.create_brief(query=query, item_id=item_id, topic_id=topic_id)
        if persist_brief
        else None
    )
    job_id = store.create_job(
        kind,
        {
            "query": query,
            "depth": depth,
            "item_id": item_id,
            "brief_id": brief_id,
            "session_id": session_id,
        },
    )

    run = RunStream(job_id=job_id, kind=kind, brief_id=brief_id)
    _register(run)
    run.emit("queued", {"label": "Queued", "pct": 0})

    def worker() -> None:
        run.status = "running"
        run.emit("stage", {"stage": "starting", "label": "Starting the research team", "pct": 2})
        try:
            result = run_research(
                query,
                session_id=session_id,
                depth=depth,
                item_id=item_id,
                emit=run.emit,
            )
            if brief_id:
                store.finish_brief(
                    brief_id,
                    report=result["report"],
                    citations=result.get("citations", []),
                    cost_usd=result.get("cost_usd", 0.0),
                )
            # Remember the published report (no-op when Supermemory is off).
            try:
                from memory.remember import remember_report

                remember_report({**(result.get("report") or {}), "id": brief_id or ""})
            except Exception as exc:  # noqa: BLE001 — memory is best-effort
                logger.debug("remember_report failed: %s", exc)
            run.emit(
                "done",
                {
                    "label": "Report ready",
                    "pct": 100,
                    "brief_id": brief_id,
                    "report": result["report"],
                    "verification": result.get("verification", {}),
                    "cost_usd": result.get("cost_usd", 0.0),
                    "duration_s": result.get("duration_s", 0.0),
                },
            )
            run.close("done")
            logger.info("Research job %s finished (brief=%s)", job_id, brief_id)
        except Exception as exc:
            logger.exception("Research job %s failed", job_id)
            if brief_id:
                store.finish_brief(
                    brief_id,
                    report={"title": f"Research failed: {query[:80]}", "error": str(exc)},
                    status="error",
                )
            run.emit("error", {"label": f"Run failed: {exc}", "message": str(exc)})
            run.close("error")

    threading.Thread(target=worker, name=f"research-{job_id}", daemon=True).start()
    return {"job_id": job_id, "brief_id": brief_id or ""}


def start_item_brief_job(item_id: str, *, depth: str = "standard") -> dict[str, str]:
    """
    Generate a deep brief for one market-pulse item.

    The query is built from the item plus the context the pulse ranked it in, so
    the report answers "what is this and why do I care" rather than restating a
    headline.
    """
    item = store.get_item(item_id)
    if not item:
        raise ValueError(f"Unknown item: {item_id}")
    return start_research_job(build_item_query(item), depth=depth, item_id=item_id)


def build_item_query(item: dict[str, Any]) -> str:
    """Turn a ranked feed item into a research question worth a full report."""
    title = (item.get("title") or "").strip()
    rationale = (item.get("rationale") or "").strip()
    context = (item.get("raw_text") or "").strip()
    metrics = item.get("metrics") or {}

    parts = [f'Deep brief on: "{title}"']
    if item.get("url"):
        parts.append(f"Primary source: {item['url']}")
    if rationale:
        parts.append(f"Why it was surfaced for me: {rationale}")
    if metrics:
        signals = ", ".join(f"{k}={v}" for k, v in list(metrics.items())[:4])
        parts.append(f"Signals: {signals}")
    if context:
        parts.append(f"Excerpt: {context[:600]}")
    parts.append(
        "Cover what this actually is, what is genuinely new versus hype, who is behind it, "
        "how it compares to the alternatives I would otherwise use, and what I should do about it."
    )
    return "\n".join(parts)

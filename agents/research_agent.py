"""
Research pipeline v2 — Planner → Researcher → Writer → Verifier → Reviser.

Each agent does one job and hands structured output to the next, which is what
makes the report auditable: the plan is explicit, every source has an id, every
claim cites ids, and the verifier checks those claims against the exact
evidence before the report is published.

`run_research` is the single entry point used by the API, the job runner and the
CLI. Pass an `emit` callable to stream events (see `agents/jobs.py`).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from agents.events import emit_event
from agents.planner import planner_node
from agents.researcher import researcher_node
from agents.state import ResearchState
from agents.verifier import verifier_node
from agents.writer import reviser_node, writer_node
from schemas.report import ResearchReportV2, coerce_report
from utils.cost import CostMeter
from utils.memory import session_manager
from utils.system1 import DecisionLog, get_router

from guardrails import trace as guardrail_trace

logger = logging.getLogger(__name__)


def attach_decision_trace(model_trace: dict | list, log: DecisionLog) -> dict:
    """Merge the S1 decision log into a report's model_trace (≤ 50 entries).

    `model_trace` is normally a dict; a list (bare call log) is wrapped so the
    decision trace always has a stable object shape for the frontend.
    """
    base = model_trace if isinstance(model_trace, dict) else {"calls": model_trace}
    return {**base, "decisions": log.recent(50)}


def build_research_graph() -> StateGraph:
    """
    Planner → Researcher → Writer → Verifier → Reviser → END.

    The reviser short-circuits when verification found nothing to repair, so a
    clean run costs exactly four model calls regardless of report length.
    """
    graph = StateGraph(ResearchState)

    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("writer", writer_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("reviser", reviser_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", "verifier")
    graph.add_edge("verifier", "reviser")
    graph.add_edge("reviser", END)

    compiled = graph.compile()
    logger.info("Deep-research graph compiled (planner → researcher → writer → verifier → reviser)")
    return compiled


research_graph = build_research_graph()


def run_research(
    query: str,
    session_id: str | None = None,
    *,
    depth: str = "standard",
    item_id: str | None = None,
    emit: Callable[[str, dict], None] | None = None,
) -> dict[str, Any]:
    """
    Execute the full deep-research pipeline.

    Args:
        query: The research question or topic.
        session_id: Optional session id for conversation memory.
        depth: "brief" | "standard" | "deep" — controls plan size and report length.
        item_id: Optional market-pulse item this brief was generated from.
        emit: Optional `emit(event_type, payload)` hook for live streaming.

    Returns:
        {session_id, report, citations, agent_steps, verification, cost_usd, model_trace, duration_s}
    """
    session_id = session_id or str(uuid.uuid4())
    depth = depth if depth in {"brief", "standard", "deep"} else "standard"
    meter = CostMeter()
    started = time.time()
    gr_start = guardrail_trace.snapshot()

    logger.info("Research v2 starting | depth=%s | session=%s | query=%s", depth, session_id, query[:120])
    if emit:
        emit("run_started", {"type": "run_started", "query": query, "depth": depth, "item_id": item_id})

    initial_state: ResearchState = {
        "messages": [],
        "research_query": query,
        "depth": depth,
        "item_id": item_id or "",
        "conversation_context": session_manager.get_context(session_id),
        "research_plan": {},
        "research_data": "",
        "source_registry": [],
        "sub_findings": [],
        "report_draft": {},
        "report": {},
        "verification": {},
        "analysis": "",
        "citations": [],
        "completed_agents": [],
        "agent_steps": [],
        "session_id": session_id,
        "meter": meter,
        "emit": emit,
    }

    try:
        final_state = research_graph.invoke(initial_state)
    except Exception as exc:  # noqa: BLE001 — always return a schema-valid report
        logger.error("Deep-research pipeline failed: %s", exc, exc_info=True)
        emit_event(initial_state, "error", message=str(exc), label="Research pipeline failed")
        report = coerce_report({}, query=query, depth=depth)
        report.title = f"Research failed: {query[:80]}"
        report.tldr = ["This run failed before producing findings."]
        report.risks_and_uncertainty = (
            f"The pipeline stopped with an error: {exc}. "
            "Nothing in this report should be treated as a finding — re-run the question."
        )
        report.cost_usd = meter.total_usd
        report.model_trace = guardrail_trace.attach_guardrail_trace(
            attach_decision_trace(meter.trace(), get_router().log), gr_start
        )
        return {
            "session_id": session_id,
            "report": report.model_dump(),
            "citations": [],
            "agent_steps": [],
            "verification": {"checked": 0, "supported": 0, "unsupported": 0, "unsupported_claims": [], "notes": "run failed"},
            "cost_usd": meter.total_usd,
            "model_trace": report.model_trace,
            "error": str(exc),
            "duration_s": round(time.time() - started, 2),
        }

    report = _finalise_report(final_state, query=query, depth=depth, meter=meter, started=started)
    report.model_trace = guardrail_trace.attach_guardrail_trace(report.model_trace, gr_start)
    verification = report.verification.model_dump() if hasattr(report.verification, "model_dump") else dict(final_state.get("verification") or {})

    session_manager.add_interaction(session_id, query, report.executive_summary[:500] or report.title)

    result = {
        "session_id": session_id,
        "report": report.model_dump(),
        "citations": [
            {
                "source_name": s.title,
                "page_number": None,
                "content_snippet": s.quote,
                "relevance_score": None,
                "url": s.url,
            }
            for s in report.sources
        ],
        "agent_steps": final_state.get("agent_steps", []),
        "verification": verification,
        "cost_usd": report.cost_usd,
        "model_trace": report.model_trace,
        "duration_s": round(time.time() - started, 2),
    }

    if emit:
        emit(
            "run_completed",
            {
                "type": "run_completed",
                "session_id": session_id,
                "duration_s": result["duration_s"],
                "cost_usd": result["cost_usd"],
                "sources": len(report.sources),
                "verification": verification,
                "title": report.title,
                "reading_time_min": report.reading_time_min,
            },
        )

    logger.info(
        "Research v2 done | %ss | %d sources | %d/%d claims supported | $%.4f",
        result["duration_s"],
        len(report.sources),
        verification.get("supported", 0),
        verification.get("checked", 0),
        report.cost_usd,
    )
    return result


def _finalise_report(
    final_state: dict[str, Any],
    *,
    query: str,
    depth: str,
    meter: CostMeter,
    started: float,
) -> ResearchReportV2:
    """Attach pipeline-computed metadata to the finished report."""
    raw = final_state.get("report") or final_state.get("report_draft") or {}
    report = coerce_report(raw, query=query, depth=depth, keep_verification=True)
    report.depth = depth
    report.cost_usd = meter.total_usd
    report.model_trace = attach_decision_trace(meter.trace(), get_router().log)

    verification = final_state.get("verification") or {}
    # The reviser is authoritative when it ran: it re-labels each flagged claim as
    # flagged/softened/removed against the *published* text. Only fall back to the
    # verifier's raw verdict when the report carries no verification of its own.
    if verification and not (report.verification.checked or report.verification.unsupported_claims):
        from schemas.report import Verification

        report.verification = Verification.model_validate(verification)
    elif report.verification.checked == 0:
        report.verification.notes = report.verification.notes or "This run completed without a verification pass."

    logger.debug("Report finalised in %.1fs", time.time() - started)
    return report

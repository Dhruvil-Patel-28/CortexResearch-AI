"""
MCP tool functions — the SDK-free core of the MCP server.

Plain functions over the store/retriever/job-runner so they are fully
unit-testable without the `mcp` package. `server.py` wraps these with
FastMCP for stdio transport.

All tools are read-only except `start_research`, which fires a research job
(the same path the /research API uses) and returns immediately.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from store import db


def list_items(since_hours: int = 24, limit: int = 50) -> list[dict[str, Any]]:
    """Recent pulse-feed items (newest first), with scores when available."""
    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    rows = db.list_items(since=since, limit=limit, order="newest")
    return [
        {
            "id": r.get("id", ""),
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "source": r.get("source", ""),
            "published_at": r.get("published_at", ""),
            "score": r.get("relevance"),
            "rationale": r.get("rationale", ""),
            "bookmarked": bool(r.get("bookmarked")),
        }
        for r in rows
    ]


def get_item(item_id: str) -> dict[str, Any] | None:
    """One pulse item with full text and score rationale, or None."""
    row = db.get_item(item_id)
    if not row:
        return None
    return {
        "id": row.get("id", ""),
        "title": row.get("title", ""),
        "url": row.get("url", ""),
        "source": row.get("source", ""),
        "published_at": row.get("published_at", ""),
        "raw_text": (row.get("raw_text") or "")[:3000],
        "score": row.get("relevance"),
        "rationale": row.get("rationale", ""),
        "bookmarked": bool(row.get("bookmarked")),
    }


def list_reports(limit: int = 20) -> list[dict[str, Any]]:
    """Published research reports, newest first."""
    briefs = db.list_briefs(limit=limit)
    return [
        {
            "id": b.get("id", ""),
            "query": b.get("query", ""),
            "title": (b.get("report") or {}).get("title", ""),
            "depth": (b.get("report") or {}).get("depth", ""),
            "cost_usd": b.get("cost_usd"),
            "created_at": b.get("created_at", ""),
        }
        for b in briefs
    ]


def get_report(report_id: str) -> dict[str, Any] | None:
    """One full report (schema-v2 JSON) by id, or None."""
    brief = db.get_brief(report_id)
    if not brief:
        return None
    return {
        "id": brief.get("id", ""),
        "query": brief.get("query", ""),
        "report": brief.get("report") or {},
        "created_at": brief.get("created_at", ""),
    }


def search_library(query: str, k: int = 8) -> dict[str, Any]:
    """
    Hybrid retrieval over your saved corpus (items + reports).

    When GraphRAG is enabled the response also carries the knowledge-graph's
    synthesized answer for multi-hop "how do X and Y connect" questions.
    """
    from rag.retriever import get_retriever

    raw = get_retriever().search(query, k=k)
    results = [
        {
            "ref_id": r.get("ref_id", ""),
            "kind": r.get("kind", ""),
            "title": r.get("title", ""),
            "text": (r.get("text") or "")[:800],
            "url": r.get("url", ""),
            "score": r.get("score"),
        }
        for r in raw
    ]
    response: dict[str, Any] = {"query": query, "results": results}
    from utils.config import settings

    if settings.enable_graph_rag:
        from rag.graph import graph_results

        response["graph"] = graph_results(query)
    return response


def start_research(query: str, depth: str = "brief") -> dict[str, Any]:
    """Start a research run; returns immediately with a job id."""
    from agents import jobs as job_runner

    return job_runner.start_research_job(query, depth=depth)


def get_research(job_id: str) -> dict[str, Any]:
    """Research job status; includes the report summary when finished."""
    job = db.get_job(job_id)
    if not job:
        return {"job_id": job_id, "status": "unknown"}
    status = job.get("status", "unknown")
    response: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "brief_id": (job.get("payload") or {}).get("brief_id"),
    }
    if status == "done" and response["brief_id"]:
        brief = db.get_brief(response["brief_id"]) or {}
        report = brief.get("report") or {}
        response["summary"] = {
            "title": report.get("title", ""),
            "tldr": report.get("tldr", []),
            "sources": [
                {"id": s.get("id"), "title": s.get("title"), "url": s.get("url")}
                for s in (report.get("sources") or [])
            ],
        }
    return response

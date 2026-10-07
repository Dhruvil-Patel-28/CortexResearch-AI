"""
Deep-research API — job streaming, the report library and exports.

The pipeline runs in a background thread (`agents.jobs`); this router exposes
start/poll/stream endpoints plus the saved-report library the reader UI uses.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from agents import jobs as job_runner
from reports.markdown import render_filename, render_markdown
from schemas.report import ResearchReportV2
from store import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research", tags=["research"])

DepthLiteral = Literal["brief", "standard", "deep"]


# ─── Models ───


class StartResearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000, description="The research question")
    depth: DepthLiteral = "standard"
    item_id: str | None = Field(default=None, description="Market-pulse item this brief came from")
    session_id: str | None = None


class RunStarted(BaseModel):
    job_id: str
    brief_id: str = ""
    status: str = "pending"


class RunSnapshot(BaseModel):
    job_id: str
    kind: str = "research"
    status: str
    brief_id: str | None = None
    pct: int = 0
    events: list[dict[str, Any]] = Field(default_factory=list)


class ReportSummary(BaseModel):
    id: str
    query: str = ""
    status: str = "done"
    item_id: str | None = None
    title: str = ""
    tldr: list[str] = Field(default_factory=list)
    depth: str = "standard"
    reading_time_min: int = 1
    source_count: int = 0
    verification: dict[str, Any] = Field(default_factory=dict)
    cost_usd: float = 0.0
    created_at: str = ""
    finished_at: str | None = None


class ReportDetail(BaseModel):
    id: str
    query: str = ""
    status: str = "done"
    item_id: str | None = None
    created_at: str = ""
    finished_at: str | None = None
    report: dict[str, Any] = Field(default_factory=dict)
    markdown: str = ""


# ─── Helpers ───


def _summary(brief: dict[str, Any]) -> ReportSummary:
    report = brief.get("report") or {}
    verification = report.get("verification") or {}
    return ReportSummary(
        id=brief.get("id", ""),
        query=brief.get("query", "") or report.get("query", ""),
        status=brief.get("status", "done"),
        item_id=brief.get("item_id"),
        title=report.get("title", "") or (brief.get("query") or "")[:80],
        tldr=list(report.get("tldr") or [])[:5],
        depth=report.get("depth", "standard"),
        reading_time_min=int(report.get("reading_time_min") or 1),
        source_count=len(report.get("sources") or []),
        verification={
            "checked": verification.get("checked", 0),
            "supported": verification.get("supported", 0),
            "unsupported": verification.get("unsupported", 0),
        },
        cost_usd=float(brief.get("cost_usd") or report.get("cost_usd") or 0.0),
        created_at=brief.get("created_at", "") or report.get("created_at", ""),
        finished_at=brief.get("finished_at"),
    )


def _sse(event: dict[str, Any]) -> str:
    event_type = str(event.get("type", "message"))
    return f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


# ─── Runs ───


@router.post("/start", response_model=RunStarted)
async def start_research(body: StartResearchRequest):
    """
    Launch a deep-research run. Returns immediately with job + brief ids.

    Follow it live on `/research/jobs/{job_id}/stream`, or poll
    `/research/jobs/{job_id}`. The finished report appears at
    `/research/reports/{brief_id}`.
    """
    db.init_db()
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    started = await asyncio.to_thread(
        job_runner.start_research_job,
        body.query,
        depth=body.depth,
        item_id=body.item_id,
        session_id=body.session_id,
    )
    logger.info("Started research job %s (depth=%s)", started["job_id"], body.depth)
    return RunStarted(job_id=started["job_id"], brief_id=started["brief_id"], status="pending")


@router.post("/items/{item_id}/brief", response_model=RunStarted)
async def start_item_brief(
    item_id: str,
    depth: DepthLiteral = Query(default="standard"),
):
    """Generate a deep brief for one market-pulse item."""
    db.init_db()
    try:
        started = await asyncio.to_thread(job_runner.start_item_brief_job, item_id, depth=depth)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return RunStarted(job_id=started["job_id"], brief_id=started["brief_id"], status="pending")


@router.get("/jobs/{job_id}", response_model=RunSnapshot)
async def get_run(job_id: str):
    """Current state of a run, including the full event trace."""
    run = job_runner.get_run(job_id)
    if run:
        return RunSnapshot(**run.snapshot())

    job = await asyncio.to_thread(db.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    progress = job.get("progress") or {}
    return RunSnapshot(
        job_id=job_id,
        kind=job.get("kind", "research"),
        status=job.get("status", "unknown"),
        brief_id=progress.get("brief_id"),
        pct=int(progress.get("pct") or 0),
        events=list(progress.get("events") or []),
    )


@router.get("/jobs/{job_id}/stream")
async def stream_run(job_id: str, replay: bool = Query(default=True)):
    """
    Server-sent events for a live run.

    Emits `stage`, `plan`, `tools`, `sources`, `verification`, `done` and
    `error` events as they happen. Already-emitted events are replayed first
    (unless `replay=false`) so a late subscriber sees the whole pipeline.
    """
    run = job_runner.get_run(job_id)

    async def event_stream():
        if run is None:
            for event in job_runner.replay_events(job_id):
                yield _sse(event)
            yield _sse({"type": "closed", "job_id": job_id, "label": "Run is no longer live"})
            return

        index = 0
        if not replay:
            index = len(run.events)
        while True:
            events, index = run.since(index)
            for event in events:
                yield _sse(event)
            if run.finished and index >= len(run.events):
                break
            if not events:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # `no-transform` stops downstream compression (Next.js gzip) from
            # buffering the stream — compressed SSE only flushes when the run
            # ends, so a live run would render nothing until it finished.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─── Report library ───


@router.get("/reports", response_model=list[ReportSummary])
async def list_reports(
    limit: int = Query(default=50, ge=1, le=200),
    item_id: str | None = None,
    status: str | None = None,
):
    """Saved reports, newest first."""
    db.init_db()
    briefs = await asyncio.to_thread(db.list_briefs, limit=limit, item_id=item_id, status=status)
    return [_summary(b) for b in briefs]


@router.get("/reports/{brief_id}", response_model=ReportDetail)
async def get_report(brief_id: str):
    """A single saved report plus its rendered Markdown."""
    brief = await asyncio.to_thread(db.get_brief, brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail="Report not found")

    report = brief.get("report") or {}
    markdown = ""
    if report.get("title") and report.get("tldr") is not None:
        try:
            markdown = render_markdown(ResearchReportV2.model_validate(report))
        except Exception as e:  # noqa: BLE001 — stored payloads may predate the schema
            logger.warning("Could not render stored report %s: %s", brief_id, e)

    return ReportDetail(
        id=brief.get("id", ""),
        query=brief.get("query", ""),
        status=brief.get("status", "done"),
        item_id=brief.get("item_id"),
        created_at=brief.get("created_at", ""),
        finished_at=brief.get("finished_at"),
        report=report,
        markdown=markdown,
    )


@router.delete("/reports/{brief_id}")
async def delete_report(brief_id: str):
    """Delete a saved report."""
    brief = await asyncio.to_thread(db.get_brief, brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail="Report not found")
    await asyncio.to_thread(db.delete_brief, brief_id)
    return {"deleted": brief_id}


@router.get("/reports/{brief_id}/export")
async def export_report(brief_id: str, format: Literal["md", "json"] = "md"):
    """Export a report as Markdown or raw JSON."""
    brief = await asyncio.to_thread(db.get_brief, brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = brief.get("report") or {}
    try:
        report = ResearchReportV2.model_validate(report_data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=409, detail=f"Stored report is not exportable: {e}") from e

    filename = render_filename(report)
    if format == "json":
        return PlainTextResponse(
            json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )
    return PlainTextResponse(
        render_markdown(report),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.md"'},
    )

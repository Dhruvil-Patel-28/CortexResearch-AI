"""
Digest API — history, preview, manual trigger and delta briefs.

Digests are normally built by the scheduler worker; these endpoints let the UI
list/read them, trigger one on demand, and launch a topic delta brief
("what changed in X since the last digest") as a live research run.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from store import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/digests", tags=["digests"])


class DigestSummary(BaseModel):
    id: str
    created_at: str
    story_count: int = 0
    delivered: list[str] = Field(default_factory=list)
    preview: str = ""


class DigestDetail(BaseModel):
    id: str
    created_at: str
    item_ids: list[str] = Field(default_factory=list)
    delivered: list[str] = Field(default_factory=list)
    markdown: str = ""


class DigestPreview(BaseModel):
    markdown: str
    story_count: int
    delta: dict = Field(default_factory=dict)
    since: str = ""


class DeltaBriefRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=120)
    since: str | None = Field(default=None, max_length=30, description="ISO date to diff from")


@router.get("", response_model=list[DigestSummary])
async def list_digests(limit: int = Query(default=50, ge=1, le=200)):
    """Digest history, newest first."""
    db.init_db()
    digests = await asyncio.to_thread(db.list_digests, limit=limit)
    return [
        DigestSummary(
            id=d["id"],
            created_at=d["created_at"],
            story_count=len(d.get("item_ids") or []),
            delivered=d.get("delivered") or [],
            preview=d.get("preview") or "",
        )
        for d in digests
    ]


@router.get("/preview", response_model=DigestPreview)
async def preview_digest(
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    min_score: float | None = Query(default=None, ge=0, le=10),
):
    """Build a digest in memory (nothing persisted) so the UI can show it live."""
    db.init_db()
    from watch.digest import build_digest

    result = await asyncio.to_thread(
        build_digest, window_hours=window_hours, min_score=min_score, persist=False
    )
    return DigestPreview(
        markdown=result["markdown"],
        story_count=len(result["items"]),
        delta=result["delta"],
        since=result["since"],
    )


@router.get("/{digest_id}", response_model=DigestDetail)
async def get_digest(digest_id: str):
    """One digest with its full markdown."""
    digest = await asyncio.to_thread(db.get_digest, digest_id)
    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")
    return DigestDetail(
        id=digest["id"],
        created_at=digest["created_at"],
        item_ids=digest.get("item_ids") or [],
        delivered=digest.get("delivered") or [],
        markdown=digest.get("rendered_md") or "",
    )


@router.post("/run", response_model=DigestSummary)
async def run_digest():
    """Build + persist + deliver a digest right now (what the scheduler does daily)."""
    db.init_db()
    from watch.digest import build_digest

    result = await asyncio.to_thread(build_digest, persist=True)
    logger.info("Manual digest built: %s (%d stories)", result["id"], len(result["items"]))
    return DigestSummary(
        id=result["id"],
        created_at=db.get_digest(result["id"])["created_at"],
        story_count=len(result["items"]),
        delivered=result["delivered"],
        preview=result["markdown"][:200],
    )


@router.post("/delta")
async def start_delta_brief(body: DeltaBriefRequest):
    """
    Launch a delta research brief for a topic: "what changed since the last
    digest/report". Streams via /research/jobs/{job_id}/stream like any run.
    """
    from agents import jobs as job_runner
    from watch.digest import build_delta_query

    db.init_db()
    query = build_delta_query(body.topic.strip(), since=body.since)
    started = await asyncio.to_thread(
        job_runner.start_research_job, query, depth="standard", kind="delta"
    )
    return {"job_id": started["job_id"], "brief_id": started["brief_id"], "query": query}

"""
Topic Watch API routes — the market pulse layer.

Endpoints power the Pulse feed, item detail, bookmarks, the interest profile
editor, and background refresh jobs (ingest + score).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from store import db
from utils.config import settings
from watch.profile import load_profile, save_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/watch", tags=["watch"])

SOURCE_LABELS = {
    "hackernews": "Hacker News",
    "arxiv": "arXiv",
    "rss": "Blogs & RSS",
    "reddit": "Reddit",
    "github": "GitHub",
    "producthunt": "Product Hunt",
}


# ─── Response models ───


class ItemOut(BaseModel):
    id: str
    source: str
    source_label: str = ""
    title: str
    url: str = ""
    author: str = ""
    published_at: str = ""
    first_seen_at: str = ""
    raw_text: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    relevance: float | None = None
    rationale: str = ""
    tags: list[str] = Field(default_factory=list)
    bookmarked: bool = False
    cluster_key: str = ""
    cluster_size: int = 1
    cluster_sources: list[str] = Field(default_factory=list)


class FeedResponse(BaseModel):
    items: list[ItemOut]
    count: int
    total: int
    stats: dict[str, Any]


class ItemDetailResponse(BaseModel):
    item: ItemOut
    also_covered_by: list[ItemOut] = Field(default_factory=list)


class StatsResponse(BaseModel):
    total_items: int
    by_source: dict[str, int]
    scored_items: int
    bookmarks: int
    last_ingest_at: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)


class ProfileModel(BaseModel):
    name: str = ""
    interests: list[str] = Field(default_factory=list)
    stack: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    boost: list[str] = Field(default_factory=list)
    mute: list[str] = Field(default_factory=list)
    arxiv_keywords: list[str] = Field(default_factory=list)
    version: str = ""


class RefreshRequest(BaseModel):
    ingest: bool = True
    score: bool = True
    sources: list[str] | None = None


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    progress: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class BookmarkRequest(BaseModel):
    note: str = ""


# ─── Helpers ───


def _to_item(row: dict[str, Any]) -> ItemOut:
    raw_sources = (row.get("cluster_sources") or row.get("source") or "").split(",")
    return ItemOut(
        id=row.get("id", ""),
        source=row.get("source", ""),
        source_label=SOURCE_LABELS.get(row.get("source", ""), row.get("source", "")),
        title=row.get("title", ""),
        url=row.get("url", ""),
        author=row.get("author", "") or "",
        published_at=row.get("published_at", "") or "",
        first_seen_at=row.get("first_seen_at", "") or "",
        raw_text=row.get("raw_text", "") or "",
        metrics=row.get("metrics") or {},
        relevance=row.get("relevance"),
        rationale=row.get("rationale") or "",
        tags=row.get("tags") or [],
        bookmarked=bool(row.get("bookmarked")),
        cluster_key=row.get("cluster_key") or "",
        cluster_size=int(row.get("cluster_size") or 1),
        cluster_sources=[s for s in raw_sources if s],
    )


def _since_from(window: str) -> str | None:
    """Translate a window keyword into an ISO timestamp."""
    now = datetime.now(timezone.utc)
    windows = {
        "today": now - timedelta(days=1),
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
    }
    dt = windows.get(window)
    return dt.isoformat() if dt else None


# ─── Feed & stats ───


@router.get("/feed", response_model=FeedResponse)
async def get_feed(
    source: str | None = None,
    window: Literal["today", "week", "month", "all"] = "week",
    min_score: float | None = Query(default=None, ge=0, le=10),
    q: str | None = None,
    bookmarked: bool = False,
    order: Literal["newest", "relevance"] = "relevance",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Ranked story feed (one card per cross-source story cluster)."""
    db.init_db()
    rows = await asyncio.to_thread(
        db.list_items,
        source=source,
        since=_since_from(window) if window != "all" else None,
        min_score=min_score,
        q=q,
        bookmarked=bookmarked or None,
        order=order,
        limit=limit,
        offset=offset,
    )
    all_stats = await asyncio.to_thread(db.stats)
    return FeedResponse(
        items=[_to_item(r) for r in rows],
        count=len(rows),
        total=all_stats["total_items"],
        stats=all_stats,
    )


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Dashboard counters, per-source totals and last ingest time."""
    db.init_db()
    s = await asyncio.to_thread(db.stats)
    enabled = [x.strip() for x in settings.watch_sources.split(",") if x.strip()]
    return StatsResponse(
        total_items=s["total_items"],
        by_source=s["by_source"],
        scored_items=s["scored_items"],
        bookmarks=s["bookmarks"],
        last_ingest_at=s["last_ingest_at"],
        sources=[
            {
                "key": name,
                "label": SOURCE_LABELS.get(name, name),
                "enabled": name in enabled,
                "items": s["by_source"].get(name, 0),
            }
            for name in SOURCE_LABELS
        ],
    )


# ─── Item detail & bookmarks ───


@router.get("/items/{item_id}", response_model=ItemDetailResponse)
async def get_item(item_id: str):
    """Item detail plus every other source that covered the same story."""
    db.init_db()
    row = await asyncio.to_thread(db.get_item, item_id)
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")

    others = await asyncio.to_thread(db.get_cluster_items, row.get("cluster_key") or "")
    return ItemDetailResponse(
        item=_to_item(row),
        also_covered_by=[_to_item(r) for r in others if r["id"] != item_id],
    )


@router.post("/items/{item_id}/bookmark", response_model=ItemOut)
async def bookmark_item(item_id: str, body: BookmarkRequest | None = None):
    db.init_db()
    row = await asyncio.to_thread(db.get_item, item_id)
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    await asyncio.to_thread(db.set_bookmark, item_id, (body.note if body else ""))
    row = await asyncio.to_thread(db.get_item, item_id)
    return _to_item(row)


@router.delete("/items/{item_id}/bookmark", response_model=ItemOut)
async def unbookmark_item(item_id: str):
    db.init_db()
    row = await asyncio.to_thread(db.get_item, item_id)
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    await asyncio.to_thread(db.remove_bookmark, item_id)
    row = await asyncio.to_thread(db.get_item, item_id)
    return _to_item(row)


# ─── Profile ───


@router.get("/profile", response_model=ProfileModel)
async def get_profile():
    """Current interest profile — drives relevance scoring."""
    p = await asyncio.to_thread(load_profile)
    return ProfileModel(
        name=p.name,
        interests=p.interests,
        stack=p.stack,
        goals=p.goals,
        boost=p.boost,
        mute=p.mute,
        arxiv_keywords=p.arxiv_keywords,
        version=p.version,
    )


@router.put("/profile", response_model=ProfileModel)
async def put_profile(body: ProfileModel):
    """Update the interest profile; new items are re-scored on the next run."""
    p = await asyncio.to_thread(
        save_profile, body.model_dump(exclude={"version"})
    )
    return ProfileModel(
        name=p.name,
        interests=p.interests,
        stack=p.stack,
        goals=p.goals,
        boost=p.boost,
        mute=p.mute,
        arxiv_keywords=p.arxiv_keywords,
        version=p.version,
    )


# ─── Refresh jobs (ingest + score) ───


def _run_refresh(job_id: str, body: RefreshRequest) -> None:
    """Background worker: ingest new items, then score unscored ones."""
    def progress(stage: str, detail: dict) -> None:
        job = db.get_job(job_id) or {}
        merged = {**(job.get("progress") or {}), stage: detail, "stage": stage}
        db.update_job(job_id, progress=merged)

    try:
        db.update_job(job_id, status="running")
        summary: dict[str, Any] = {}

        if body.ingest:
            from watch.ingest import run_ingest

            summary["ingest"] = run_ingest(sources=body.sources, progress=progress)
            db.update_job(job_id, progress={**summary, "stage": "ingest_done"})

        if body.score:
            from watch.ranker import score_unscored

            # Drain more than the per-run default so the feed is populated in one refresh
            summary["score"] = score_unscored(limit=settings.prefilter_k, progress=progress)

        db.update_job(job_id, status="done", progress={**summary, "stage": "done"})
    except Exception as e:  # noqa: BLE001
        logger.error(f"Refresh job {job_id} failed: {e}", exc_info=True)
        db.update_job(job_id, status="failed", progress={"stage": "failed", "error": str(e)})


@router.post("/refresh", response_model=JobOut)
async def refresh(body: RefreshRequest | None = None):
    """
    Start a background refresh (fetch new items + score them).

    Returns immediately with a job id — poll /watch/jobs/{id} for progress.
    """
    db.init_db()
    body = body or RefreshRequest()
    job_id = db.create_job("refresh", payload=body.model_dump())
    thread = threading.Thread(target=_run_refresh, args=(job_id, body), daemon=True)
    thread.start()
    job = db.get_job(job_id)
    return JobOut(**job)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job_status(job_id: str):
    """Poll a background job's progress."""
    job = await asyncio.to_thread(db.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut(**job)

"""
Library search API — hybrid retrieval over everything you have saved.

Sources + past reports via the hybrid retriever (BM25 + dense + rerank).
Two optional upgrades are feature-flagged and degrade gracefully:

- GraphRAG (LightRAG): multi-hop entity-graph answers ("how do X and Y
  connect") — enabled with ENABLE_GRAPH_RAG, requires the `lightrag-hku`
  package; when off or missing, the endpoint just returns hybrid results.
- Supermemory (local): cross-session memory documents — enabled with
  ENABLE_SUPERMEMORY + SUPERMEMORY_URL; when off, memory results are absent.
"""

from __future__ import annotations

import logging
from contextlib import closing

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from store import db
from utils.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


class SearchHit(BaseModel):
    ref_id: str
    kind: str  # "item" | "brief"
    title: str
    url: str = ""
    snippet: str = ""
    source: str = ""
    published_at: str = ""
    score: float = 0.0
    relevance: float | None = None  # personalized score, items only
    brief_id: str | None = None  # reports link back to the report reader


class GraphAnswer(BaseModel):
    available: bool
    answer: str = ""
    reason: str = ""


class MemoryHit(BaseModel):
    text: str
    score: float = 0.0


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHit] = Field(default_factory=list)
    graph: GraphAnswer | None = None
    memory: list[MemoryHit] = Field(default_factory=list)
    flags: dict[str, bool] = Field(default_factory=dict)


def _attach_relevance(hits: list[SearchHit]) -> None:
    item_ids = [h.ref_id for h in hits if h.kind == "item"]
    if not item_ids:
        return
    placeholders = ",".join("?" for _ in item_ids)
    try:
        with closing(db.connect()) as con:
            rows = con.execute(
                f"""SELECT item_id, relevance FROM scores WHERE item_id IN ({placeholders})
                    AND scored_at = (SELECT MAX(scored_at) FROM scores s2
                                     WHERE s2.item_id = scores.item_id)""",
                item_ids,
            ).fetchall()
        relevance = {r["item_id"]: r["relevance"] for r in rows}
    except Exception:  # noqa: BLE001 — decoration only
        return
    for h in hits:
        if h.kind == "item" and h.ref_id in relevance:
            h.relevance = relevance[h.ref_id]


@router.get("", response_model=SearchResponse)
async def search(
    q: str = Query(min_length=1, max_length=512),
    k: int = Query(default=10, ge=1, le=50),
    kind: str | None = Query(default=None, pattern="^(item|brief)$"),
) -> SearchResponse:
    from rag.retriever import get_retriever

    kinds = (kind,) if kind else ("item", "brief")
    try:
        raw = get_retriever().search(q, k=k, kinds=kinds)
    except Exception as e:  # noqa: BLE001 — a broken index must not 500 the UI
        logger.warning("Library search failed: %s", e)
        raw = []

    hits = [SearchHit(**h) for h in raw]
    _attach_relevance(hits)

    graph = None
    if settings.enable_graph_rag:
        from rag.graph import graph_results

        graph = GraphAnswer(**graph_results(q))

    memory: list[MemoryHit] = []
    if settings.enable_supermemory:
        from memory.supermemory import get_memory

        mem = get_memory()
        if mem is not None:
            memory = [MemoryHit(**m) for m in mem.search(q, k=5)]

    return SearchResponse(
        query=q,
        results=hits,
        graph=graph,
        memory=memory,
        flags={
            "graph_rag": settings.enable_graph_rag,
            "supermemory": settings.enable_supermemory,
        },
    )

"""
Graph RAG adapter — multi-hop entity-graph retrieval (optional, flagged).

Uses LightRAG (lighter and cheaper than Microsoft GraphRAG) to build a
knowledge graph over your saved items + reports, enabling "how do X and Y
connect" queries that pure vector retrieval answers poorly.

Design constraints:
- Disabled by default (`ENABLE_GRAPH_RAG=false`). The app never hard-depends
  on it: every failure path returns an "unavailable" answer and the hybrid
  retriever keeps working.
- Lazy imports: `lightrag-hku` is only imported when the flag is on.
- Insertion is idempotent: already-indexed doc ids are tracked in the store's
  meta table, so only new documents hit the graph.
"""

from __future__ import annotations

import logging
from typing import Any

from store import db
from utils.config import settings

logger = logging.getLogger(__name__)

_lightrag_instance: Any | None = None
_unavailable_reason = ""


def graph_results(query: str, k: int = 5) -> dict[str, Any]:
    """
    Query the knowledge graph. Returns {"available", "answer", "reason"} —
    never raises.
    """
    if not settings.enable_graph_rag:
        return {"available": False, "answer": "", "reason": "GraphRAG is disabled (ENABLE_GRAPH_RAG)"}
    rag = _get_lightrag()
    if rag is None:
        return {"available": False, "answer": "", "reason": _unavailable_reason}
    try:
        from lightrag import QueryParam

        answer = rag.query(query, param=QueryParam(mode="mix", top_k=k))
        return {"available": True, "answer": str(answer), "reason": ""}
    except Exception as e:  # noqa: BLE001 — the graph layer must never break search
        logger.warning("GraphRAG query failed: %s", e)
        return {"available": False, "answer": "", "reason": f"GraphRAG query failed: {e}"}


def index_docs(docs: list[Any]) -> None:
    """
    Insert not-yet-indexed docs into the graph. Best-effort: failures are
    logged, never raised.
    """
    if not settings.enable_graph_rag:
        return
    rag = _get_lightrag()
    if rag is None:
        return
    try:
        already = set((db.get_meta("graph_indexed_ids") or "").split(","))
        new = [d for d in docs if d.ref_id not in already]
        if not new:
            return
        for d in new:
            rag.ainsert(f"{d.title}\n\n{d.text}")
        db.set_meta("graph_indexed_ids", ",".join(already | {d.ref_id for d in new}))
        logger.info("GraphRAG: inserted %d new documents", len(new))
    except Exception as e:  # noqa: BLE001
        logger.warning("GraphRAG indexing failed: %s", e)


def _get_lightrag() -> Any | None:
    global _lightrag_instance, _unavailable_reason
    if _lightrag_instance is not None:
        return _lightrag_instance
    try:
        from lightrag import LightRAG
    except ImportError:
        _unavailable_reason = (
            "lightrag-hku is not installed — pip install lightrag-hku to enable"
        )
        return None
    try:
        _lightrag_instance = LightRAG(
            working_dir=settings.graph_working_dir,
            embedding_model=settings.embedding_model,
        )
        return _lightrag_instance
    except Exception as e:  # noqa: BLE001
        _unavailable_reason = f"LightRAG init failed: {e}"
        logger.warning("LightRAG init failed: %s", e)
        return None

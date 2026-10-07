"""
Radar store search — hybrid retrieval over what the watch pipeline ingested.

This is what makes deep briefs grounded in *your* feed: before hitting the open
web, the researcher queries the local store (Hacker News, arXiv, RSS, Reddit,
GitHub, Product Hunt) for items related to each sub-question. Ranking is done
by the hybrid retriever (SQLite FTS5 BM25 + dense embeddings, fused), which
replaced the naive LIKE-matching scan.
"""

from __future__ import annotations

import logging
import re
from contextlib import closing
from typing import Any

from store import db

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "are", "was",
    "how", "what", "why", "when", "which", "who", "does", "did", "can", "should",
    "about", "their", "there", "have", "has", "been", "will", "would", "could",
    "vs", "versus", "best", "new", "latest", "using", "use", "used", "more",
    "most", "than", "then", "them", "his", "her", "its", "not", "but",
}

_TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9+#.\-]{1,}")


def tokens(text: str, *, min_len: int = 3, limit: int = 8) -> list[str]:
    """Extract search keywords from a natural-language query."""
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text or ""):
        token = raw.lower().strip(".-")
        if len(token) < min_len or token in _STOPWORDS or token in out:
            continue
        out.append(token)
        if len(out) >= limit:
            break
    return out


def store_results(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """
    Find radar items matching a query in the local store.

    Returns [] when the store is empty (a fresh install) or nothing matches —
    retrieval problems degrade to [] instead of breaking a research run.
    """
    try:
        from rag.retriever import get_retriever

        hits = get_retriever().search(query, k=limit, kinds=("item",))
    except Exception as e:  # noqa: BLE001 — a broken index must not break research
        logger.warning("Radar store search unavailable: %s", e)
        return []

    if not hits:
        return []

    # Enrich with the personalized relevance score when one exists.
    relevance: dict[str, float] = {}
    try:
        with closing(db.connect()) as con:
            placeholders = ",".join("?" for _ in hits)
            rows = con.execute(
                f"""SELECT item_id, relevance FROM scores WHERE item_id IN ({placeholders})
                    AND scored_at = (SELECT MAX(scored_at) FROM scores s2
                                     WHERE s2.item_id = scores.item_id)""",
                [h["ref_id"] for h in hits],
            ).fetchall()
            relevance = {r["item_id"]: r["relevance"] for r in rows}
    except Exception:  # noqa: BLE001 — scores are optional decoration
        pass

    return [
        {
            "id": h["ref_id"],
            "title": h["title"],
            "url": h["url"],
            "source": h["source"],
            "published_at": h.get("published_at") or "",
            "snippet": h["snippet"],
            "relevance": float(relevance.get(h["ref_id"], 0.0)),
        }
        for h in hits
    ]

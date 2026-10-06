"""
Radar store search — retrieval over what the watch pipeline has already ingested.

This is what makes deep briefs grounded in *your* feed: before hitting the open
web, the researcher queries the local SQLite store (Hacker News, arXiv, RSS,
Reddit, GitHub, Product Hunt) for items related to each sub-question.
"""

from __future__ import annotations

import logging
import re
from contextlib import closing
from typing import Any

from store.db import connect

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

    Ranks by number of matched keywords, then by recency. Returns [] when the
    store is empty (a fresh install) or the query carries no usable keywords.
    """
    keywords = tokens(query)
    if not keywords:
        return []

    likes = [f"%{kw}%" for kw in keywords]
    score_sql = " + ".join(
        "(CASE WHEN i.title LIKE ? THEN 2 ELSE 0 END) + (CASE WHEN i.raw_text LIKE ? THEN 1 ELSE 0 END)"
        for _ in keywords
    )
    params: list[Any] = []
    for like in likes:
        params += [like, like]

    where = " OR ".join(["i.title LIKE ? OR i.raw_text LIKE ?" for _ in keywords])
    params += [like for like in likes for _ in range(2)]

    sql = f"""
        SELECT i.id, i.source, i.title, i.url, i.author, i.published_at, i.first_seen_at,
               COALESCE(i.raw_text, '') AS raw_text,
               COALESCE(s.relevance, 0) AS relevance,
               ({score_sql}) AS hits
        FROM items i
        LEFT JOIN scores s
               ON s.item_id = i.id
              AND s.scored_at = (SELECT MAX(scored_at) FROM scores s2 WHERE s2.item_id = i.id)
        WHERE {where}
        ORDER BY hits DESC, COALESCE(NULLIF(i.published_at, ''), i.first_seen_at) DESC
        LIMIT ?
    """
    params.append(limit)

    try:
        with closing(connect()) as con:
            rows = con.execute(sql, params).fetchall()
    except Exception as e:  # noqa: BLE001 — a missing DB must not break research
        logger.warning("Radar store search unavailable: %s", e)
        return []

    results = []
    for row in rows:
        d = dict(row)
        snippet = (d.pop("raw_text") or "").strip()
        results.append(
            {
                "id": d["id"],
                "title": d["title"],
                "url": d["url"] or "",
                "source": d["source"],
                "published_at": d.get("published_at") or d.get("first_seen_at") or "",
                "snippet": snippet[:600],
                "relevance": float(d.get("relevance") or 0.0),
            }
        )
    logger.debug("Radar store search '%s' → %d items", query[:60], len(results))
    return results

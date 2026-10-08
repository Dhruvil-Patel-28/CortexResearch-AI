"""
Memory write/recall — best-effort hooks into Supermemory (flagged, optional).

Every function is a no-op (or returns False/"") when Supermemory is disabled
or unreachable; SQLite remains the source of truth. Search remembers are
deduped in-process so repeat queries don't pollute the memory store.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

_recent_searches: OrderedDict[str, None] = OrderedDict()
_RECENT_LIMIT = 200


def get_memory():
    from memory.supermemory import get_memory as _get

    return _get()


def _remember(text: str, metadata: dict[str, Any]) -> bool:
    mem = get_memory()
    if mem is None:
        return False
    try:
        return bool(mem.remember(text, metadata))
    except Exception as exc:  # noqa: BLE001 — memory must never break a run
        logger.warning("Supermemory remember failed: %s", exc)
        return False


def remember_report(report: dict[str, Any]) -> bool:
    """Store a published research report summary."""
    report = report or {}
    title = str(report.get("title") or "").strip()
    query = str(report.get("query") or "").strip()
    if not title and not query:
        return False
    tldr = [str(t).strip() for t in (report.get("tldr") or []) if str(t).strip()]
    lines = [f"Research report: {title}"]
    if query and query != title:
        lines.append(f"Query: {query}")
    lines.extend(f"- {t}" for t in tldr[:5])
    return _remember(
        "\n".join(lines),
        {
            "kind": "report",
            "report_id": str(report.get("id") or ""),
            "query": query,
            "depth": str(report.get("depth") or ""),
        },
    )


def remember_bookmark(item: dict[str, Any], note: str = "") -> bool:
    """Store a bookmarked pulse item."""
    item = item or {}
    title = str(item.get("title") or "").strip()
    if not title:
        return False
    text = f"Bookmarked: {title} ({item.get('source') or 'unknown source'})"
    if item.get("url"):
        text += f" — {item['url']}"
    if note:
        text += f"\nNote: {note}"
    return _remember(
        text,
        {
            "kind": "bookmark",
            "item_id": str(item.get("id") or ""),
            "url": str(item.get("url") or ""),
        },
    )


def remember_search(query: str) -> bool:
    """Store a search query (deduped — repeats are skipped)."""
    normalized = " ".join(str(query or "").split()).lower()
    if not normalized:
        return False
    if normalized in _recent_searches:
        _recent_searches.move_to_end(normalized)
        return False
    _recent_searches[normalized] = None
    while len(_recent_searches) > _RECENT_LIMIT:
        _recent_searches.popitem(last=False)
    return _remember(f"Search query: {normalized}", {"kind": "search"})


def remember_digest(digest: dict[str, Any]) -> bool:
    """Store a digest summary."""
    digest = digest or {}
    markdown = str(digest.get("markdown") or digest.get("rendered_md") or "").strip()
    if not markdown:
        return False
    return _remember(
        f"Digest summary:\n{markdown[:2000]}",
        {"kind": "digest", "digest_id": str(digest.get("id") or "")},
    )


def recall(query: str, k: int = 3) -> str:
    """Related past work from the personal memory store ('' when unavailable)."""
    mem = get_memory()
    if mem is None:
        return ""
    try:
        results = mem.search(query, k=k)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Supermemory recall failed: %s", exc)
        return ""
    if not results:
        return ""
    lines = [f"[from your personal memory store] {r.get('text', '')}".strip() for r in results]
    return "\n".join(lines)

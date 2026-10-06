"""
Cross-source story clustering.

The same news story typically lands on HN, a couple of RSS feeds and Reddit
within hours. Without clustering the Pulse feed shows it three times, which
is exactly the noise this project exists to remove.

`assign_clusters` groups items by title token similarity (Jaccard) or by
identical URL, and returns item_id -> cluster_key. The first item that
creates a cluster becomes its representative.
"""

from __future__ import annotations

import re
from hashlib import sha1
from typing import Iterable

STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "from", "into", "onto", "over", "under",
    "to", "of", "in", "on", "at", "by", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "as", "new", "now", "how", "why", "what",
    "you", "your", "we", "our", "us", "they", "their", "his", "her", "he", "she", "i",
    "show", "ask", "hn", "vs", "via", "about", "after", "before", "than", "then", "so",
}

# Source-specific prefixes that add no semantic value ("Show HN:", "[AINews]", "New:")
_PREFIX_RE = re.compile(
    r"^\s*(\[[^\]]{0,25}\]|show\s+hn|ask\s+hn|tell\s+hn|launch\s+hn|new|update|announcing)\s*[:\-–—]\s*",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")

DEFAULT_THRESHOLD = 0.62


def tokens(title: str) -> frozenset[str]:
    """Significant lowercase tokens of a title."""
    cleaned = _PREFIX_RE.sub("", title or "")
    return frozenset(t for t in _TOKEN_RE.findall(cleaned.lower()) if len(t) > 2 and t not in STOPWORDS)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _key_for(toks: frozenset[str], fallback: str) -> str:
    return sha1(" ".join(sorted(toks)).encode() if toks else fallback.encode()).hexdigest()[:16]


def assign_clusters(
    items: Iterable,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, str]:
    """
    Group items into story clusters.

    Args:
        items: objects exposing `.id`, `.title` and `.url`.
        threshold: Jaccard similarity above which two titles are the same story.

    Returns:
        Mapping of item id -> cluster key.
    """
    reps: list[tuple[str, frozenset[str]]] = []
    by_url: dict[str, str] = {}
    out: dict[str, str] = {}

    for item in items:
        url = (getattr(item, "url", "") or "").strip().lower().rstrip("/")
        toks = tokens(getattr(item, "title", ""))

        # 1) Identical URL is the strongest signal
        if url and url in by_url:
            out[item.id] = by_url[url]
            continue

        # 2) Title similarity against existing cluster representatives
        best: str | None = None
        for key, rep_toks in reps:
            if jaccard(toks, rep_toks) >= threshold:
                best = key
                break

        if best is None:
            best = _key_for(toks, fallback=url or getattr(item, "title", ""))
            reps.append((best, toks))

        out[item.id] = best
        if url:
            by_url[url] = best

    return out

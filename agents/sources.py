"""
Source registry — the citation backbone of a research run.

Every piece of evidence the researcher collects is registered here and given a
stable short id (`s1`, `s2`, ...). The writer then cites those ids, and the
verifier checks each claim against the exact snippet stored for that id — which
is what turns "citations" from decoration into something checkable.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid", "gclid"}

_KIND_BY_SOURCE = {
    "hackernews": "forum",
    "reddit": "forum",
    "arxiv": "paper",
    "github": "repo",
    "producthunt": "product",
    "rss": "rss",
    "web": "web",
    "knowledge_base": "knowledge_base",
}


def canonical_url(url: str) -> str:
    """Normalise a URL so the same page from two sources dedupes to one entry."""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return url.lower()
    host = (parsed.netloc or "").lower()
    host = host[4:] if host.startswith("www.") else host
    path = (parsed.path or "").rstrip("/")
    return f"{host}{path}".lower()


class SourceRegistry:
    """Insertion-ordered, deduplicated set of citable sources."""

    def __init__(self, limit: int = 60) -> None:
        self._items: list[dict[str, Any]] = []
        self._by_key: dict[str, str] = {}
        self.limit = limit

    def __len__(self) -> int:
        return len(self._items)

    def add(
        self,
        *,
        kind: str,
        title: str,
        url: str = "",
        snippet: str = "",
        published_at: str | None = None,
        sub_question: str = "",
        score: float | None = None,
    ) -> str | None:
        """
        Register a source and return its id.

        Returns the existing id when the same page/title was already registered
        (so a claim can cite it without a duplicate entry), or None when the
        registry is full.
        """
        title = (title or "").strip()
        url = (url or "").strip()
        key = canonical_url(url) or _title_key(title)
        if not key:
            return None

        existing = self._by_key.get(key)
        if existing:
            entry = next(i for i in self._items if i["id"] == existing)
            if sub_question and sub_question not in entry["sub_questions"]:
                entry["sub_questions"].append(sub_question)
            if snippet and len(snippet) > len(entry["snippet"]):
                entry["snippet"] = snippet[:1200]
            return existing

        if len(self._items) >= self.limit:
            return None

        source_id = f"s{len(self._items) + 1}"
        self._items.append(
            {
                "id": source_id,
                "title": title or url or "Untitled source",
                "url": url,
                "kind": _KIND_BY_SOURCE.get(kind, kind or "web"),
                "published_at": published_at or None,
                "snippet": (snippet or "").strip()[:1200],
                "sub_questions": [sub_question] if sub_question else [],
                "score": score,
            }
        )
        self._by_key[key] = source_id
        return source_id

    def get(self, source_id: str) -> dict[str, Any] | None:
        for item in self._items:
            if item["id"] == source_id:
                return item
        return None

    def ids(self) -> list[str]:
        return [i["id"] for i in self._items]

    def as_list(self, *, include_snippet: bool = True) -> list[dict[str, Any]]:
        """Public shape for the report/frontend (drops internal bookkeeping)."""
        out = []
        for item in self._items:
            entry = {
                "id": item["id"],
                "title": item["title"],
                "url": item["url"],
                "kind": item["kind"],
                "published_at": item["published_at"],
                "quote": item["snippet"][:400] if include_snippet else "",
            }
            out.append(entry)
        return out

    def render(self, *, max_snippet: int = 400) -> str:
        """Numbered evidence block handed to the writer, keyed by source id."""
        lines = []
        for item in self._items:
            head = f"[{item['id']}] {item['title']}"
            if item["url"]:
                head += f" — {item['url']}"
            meta = [f"kind={item['kind']}"]
            if item["published_at"]:
                meta.append(f"published={item['published_at'][:10]}")
            if item["score"] is not None:
                meta.append(f"relevance={item['score']:.2f}")
            lines.append(f"{head}\n({', '.join(meta)})\n{item['snippet'][:max_snippet]}")
        return "\n\n".join(lines)


def _title_key(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    if len(slug) < 12:
        return ""
    return "title:" + hashlib.sha1(slug.encode()).hexdigest()[:16]

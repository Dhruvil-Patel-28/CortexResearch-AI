"""
arXiv adapter — free Atom API, no key required.

https://info.arxiv.org/help/api/index.html
"""

from __future__ import annotations

import logging

import feedparser

from sources.base import FeedItem, SourceAdapter, http_get
from utils.config import settings

logger = logging.getLogger(__name__)

API = "http://export.arxiv.org/api/query"


def build_query(keywords: list[str] | None, categories: list[str]) -> str:
    """Keyword query when keywords exist, otherwise a category query."""
    if keywords:
        return " OR ".join(f'all:"{k}"' for k in keywords[:6] if k.strip())
    cats = [c.strip() for c in categories if c.strip()]
    return " OR ".join(f"cat:{c}" for c in cats) if cats else "cat:cs.AI"


def parse_arxiv_feed(xml_text: str) -> list[FeedItem]:
    """
    Parse an arXiv Atom response into FeedItems.

    Handles both live API responses and recorded fixtures.
    """
    parsed = feedparser.parse(xml_text)
    items: list[FeedItem] = []

    for entry in parsed.entries:
        title = " ".join((entry.get("title") or "").split())
        summary = " ".join((entry.get("summary") or "").split())
        link = entry.get("link") or ""
        if not title or not link:
            continue

        authors = ""
        if entry.get("authors"):
            authors = ", ".join(a.get("name", "") for a in entry["authors"])

        categories = [t.get("term", "") for t in entry.get("tags", [])]

        items.append(
            FeedItem(
                source="arxiv",
                external_id=link,
                title=title,
                url=link,
                author=authors,
                published_at=entry.get("published") or "",
                raw_text=summary,
                metrics={"categories": categories},
            )
        )

    return items


class ArxivAdapter(SourceAdapter):
    name = "arxiv"

    def fetch(self, limit: int = 25, keywords: list[str] | None = None) -> list[FeedItem]:
        categories = settings.arxiv_categories.split(",")
        query = build_query(keywords, categories)

        try:
            resp = http_get(
                API,
                params={
                    "search_query": query,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                    "max_results": min(limit, settings.arxiv_max_results),
                },
                timeout=30.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("arXiv request failed: %s", e)
            return []

        items = parse_arxiv_feed(resp.text)
        logger.info("arXiv: %s papers for query '%s'", len(items), query[:80])
        return items[:limit]

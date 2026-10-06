"""
Hacker News adapter — free Firebase API, no key required.

https://github.com/HackerNews/API
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from sources.base import FeedItem, SourceAdapter, http_get
from utils.config import settings

logger = logging.getLogger(__name__)

API = "https://hacker-news.firebaseio.com/v0"


def parse_hn_item(raw: dict, min_score: int = 0) -> FeedItem | None:
    """Convert a raw HN item JSON into a FeedItem (pure — unit-testable)."""
    if not raw or raw.get("type") != "story" or raw.get("deleted") or raw.get("dead"):
        return None

    score = int(raw.get("score") or 0)
    if score < min_score:
        return None

    hn_url = f"https://news.ycombinator.com/item?id={raw.get('id')}"
    published = ""
    if raw.get("time"):
        published = datetime.fromtimestamp(int(raw["time"]), tz=timezone.utc).isoformat()

    return FeedItem(
        source="hackernews",
        external_id=str(raw.get("id", "")),
        title=(raw.get("title") or "").strip(),
        url=raw.get("url") or hn_url,
        author=raw.get("by", ""),
        published_at=published,
        raw_text=(raw.get("text") or "").strip(),
        metrics={
            "score": score,
            "comments": int(raw.get("descendants") or 0),
            "hn_url": hn_url,
        },
    )


class HackerNewsAdapter(SourceAdapter):
    name = "hackernews"

    def fetch(self, limit: int = 35, keywords: list[str] | None = None) -> list[FeedItem]:
        try:
            ids = http_get(f"{API}/topstories.json").json()
        except Exception as e:  # noqa: BLE001 — never break the ingest run
            logger.warning(f"HN topstories failed: {e}")
            return []

        if not isinstance(ids, list):
            return []

        ids = ids[: max(limit * 2, limit)]

        items: list[FeedItem] = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(self._detail, story_id) for story_id in ids]
            for fut in as_completed(futures):
                item = fut.result()
                if item:
                    items.append(item)

        # Keep the most-discussed stories first
        items.sort(key=lambda i: i.metrics.get("score", 0), reverse=True)
        logger.info(f"HN: kept {len(items)} stories above {settings.hn_min_score} points")
        return items[:limit]

    def _detail(self, story_id: int) -> FeedItem | None:
        try:
            raw = http_get(f"{API}/item/{story_id}.json").json()
            return parse_hn_item(raw, min_score=settings.hn_min_score)
        except Exception:  # noqa: BLE001
            return None

"""
Product Hunt adapter — public RSS feed (best-effort; the GraphQL API
requires a paid token, the RSS feed is free).
"""

from __future__ import annotations

import logging

from sources.base import FeedItem, SourceAdapter, http_get
from sources.rss import parse_rss_feed

logger = logging.getLogger(__name__)

FEED = "https://www.producthunt.com/feed"


class ProductHuntAdapter(SourceAdapter):
    name = "producthunt"

    def fetch(self, limit: int = 15, keywords: list[str] | None = None) -> list[FeedItem]:
        try:
            resp = http_get(FEED, timeout=15.0)
        except Exception as e:  # noqa: BLE001
            logger.warning("Product Hunt feed failed: %s", e)
            return []

        items = parse_rss_feed(resp.text, feed_name="Product Hunt", source="producthunt")
        logger.info("Product Hunt: %s launches", len(items))
        return items[:limit]

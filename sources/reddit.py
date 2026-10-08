"""
Reddit adapter — free RSS endpoints, no key.

The unauthenticated JSON API is blocked for many clients (HTTP 403), but
the .rss endpoints stay freely accessible, so the radar drives those.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import feedparser

from sources.base import FeedItem, SourceAdapter, http_get
from utils.config import settings

logger = logging.getLogger(__name__)

RSS_URL = "https://www.reddit.com/r/{sub}/new/.rss"
# Reddit 429s aggressive clients; a short gap between subreddits keeps us polite.
SUB_DELAY_S = 0.8


def parse_reddit_rss(text: str, subreddit: str = "") -> list[FeedItem]:
    """Parse a subreddit Atom feed into FeedItems (pure — unit-testable)."""
    parsed = feedparser.parse(text)
    items: list[FeedItem] = []

    for e in parsed.entries:
        link = e.get("link") or ""
        title = " ".join((e.get("title") or "").split())
        if not link or not title:
            continue

        published = ""
        if e.get("updated_parsed"):
            published = datetime(*e["updated_parsed"][:6], tzinfo=UTC).isoformat()

        author = (e.get("author") or "").replace("/u/", "").strip()

        items.append(
            FeedItem(
                source="reddit",
                external_id=link,
                title=title,
                url=link,
                author=author,
                published_at=published,
                raw_text="",
                metrics={"subreddit": subreddit or "reddit"},
            )
        )

    return items


class RedditAdapter(SourceAdapter):
    name = "reddit"

    def fetch(self, limit: int = 15, keywords: list[str] | None = None) -> list[FeedItem]:
        subs = [s.strip() for s in settings.reddit_subreddits.split(",") if s.strip()]
        items: list[FeedItem] = []

        for i, sub in enumerate(subs):
            if i:
                time.sleep(SUB_DELAY_S)
            try:
                resp = http_get(RSS_URL.format(sub=sub), timeout=12.0)
                items.extend(parse_reddit_rss(resp.text, sub)[:limit])
            except Exception as e:  # noqa: BLE001 — never break the ingest run
                logger.warning("Reddit r/%s failed: %s", sub, e)

        logger.info("Reddit: %s posts from %s subreddits", len(items), len(subs))
        return items

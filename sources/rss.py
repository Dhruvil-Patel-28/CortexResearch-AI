"""
RSS / blog adapter — free. The feed list is user-editable (watch/feeds.yaml).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import feedparser
import yaml

from sources.base import FeedItem, SourceAdapter, http_get
from utils.config import settings

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return _TAG_RE.sub(" ", text or "").replace("&nbsp;", " ").strip()


def load_feeds(path: str | None = None) -> list[dict]:
    p = Path(path or settings.feeds_path)
    if not p.exists():
        logger.warning("Feeds file not found: %s", p)
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return [f for f in (data.get("feeds") or []) if f.get("url")]


def parse_rss_feed(text: str, feed_name: str = "", source: str = "rss") -> list[FeedItem]:
    """Parse an RSS/Atom document into FeedItems (pure — unit-testable)."""
    parsed = feedparser.parse(text)
    resolved_name = feed_name or ((parsed.feed.get("title") if parsed.feed else "") or "RSS")
    items: list[FeedItem] = []

    for e in parsed.entries:
        link = e.get("link") or ""
        title = " ".join((e.get("title") or "").split())
        if not link or not title:
            continue

        published = ""
        if e.get("published_parsed"):
            published = datetime(*e["published_parsed"][:6], tzinfo=UTC).isoformat()
        elif e.get("updated_parsed"):
            published = datetime(*e["updated_parsed"][:6], tzinfo=UTC).isoformat()

        summary = strip_html(e.get("summary") or e.get("description") or "")

        items.append(
            FeedItem(
                source=source,
                external_id=link,
                title=title,
                url=link,
                author=(e.get("author") or "").strip(),
                published_at=published,
                raw_text=summary[:2000],
                metrics={"feed": resolved_name},
            )
        )

    return items


class RssAdapter(SourceAdapter):
    name = "rss"

    def fetch(self, limit: int = 80, keywords: list[str] | None = None) -> list[FeedItem]:
        feeds = load_feeds()
        items: list[FeedItem] = []

        for feed in feeds:
            name = feed.get("name") or feed["url"]
            try:
                resp = http_get(feed["url"], timeout=12.0)
                parsed = parse_rss_feed(resp.text, feed_name=name, source="rss")
                items.extend(parsed[: settings.rss_max_per_feed])
            except Exception as e:  # noqa: BLE001 — one dead feed must not break the run
                logger.warning("RSS feed failed (%s): %s", name, e)

        logger.info("RSS: %s entries from %s feeds", len(items), len(feeds))
        return items[:limit]

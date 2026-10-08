"""Shared test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture()
def seeded_db(tmp_path, monkeypatch):
    """A tmp SQLite store seeded with two pulse items."""
    from sources.base import FeedItem
    from store import db
    from utils.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "mcp.db"))
    db.init_db()
    db.upsert_items(
        [
            FeedItem(
                source="hn",
                external_id="m1",
                title="Agent memory systems",
                url="https://e.com/m1",
                raw_text="A story about agent memory.",
                published_at="2026-10-08T00:00:00Z",
            ),
            FeedItem(
                source="arxiv",
                external_id="m2",
                title="Retrieval survey",
                url="https://e.com/m2",
                raw_text="A survey of retrieval methods.",
                published_at="2026-10-08T01:00:00Z",
            ),
        ]
    )
    return db

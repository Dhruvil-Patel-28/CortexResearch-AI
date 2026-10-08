"""Shared test fixtures."""

from __future__ import annotations

import os

import pytest

# Settings requires an Anthropic key, and a clean checkout (CI included) has no
# .env. A placeholder set before the first app import keeps the suite runnable
# anywhere — and because real environment variables outrank .env values, tests
# can never make live, billable model calls even when a working key is on disk.
os.environ["ANTHROPIC_API_KEY"] = "placeholder-set-by-tests"


@pytest.fixture(autouse=True)
def _no_live_system1(monkeypatch):
    """Keep the suite offline.

    A developer's real ``JEV_API_KEY`` in ``.env`` must never turn System 1
    into a live network call: tests either stub ``get_router`` or exercise the
    local calibrated backend. Clear the singleton too, so no router built by an
    earlier test leaks into this one.
    """
    from utils import system1
    from utils.config import settings

    monkeypatch.setattr(settings, "jev_api_key", "")
    monkeypatch.setattr(system1, "_router", None)


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

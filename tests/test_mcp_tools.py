"""MCP tool tests — SDK-free core functions against a seeded tmp store."""

from __future__ import annotations

import pytest


@pytest.fixture()
def seeded_db(tmp_path, monkeypatch):
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


def test_list_items_returns_recent(seeded_db):
    from mcp_server import tools

    items = tools.list_items(since_hours=48, limit=10)
    assert len(items) == 2
    assert {"title", "url", "source", "id"} <= set(items[0])


def test_get_item_found_and_missing(seeded_db):
    from mcp_server import tools

    items = tools.list_items(limit=1)
    found = tools.get_item(items[0]["id"])
    assert found and found["title"]
    assert tools.get_item("nope") is None


def test_list_reports_empty(seeded_db):
    from mcp_server import tools

    assert tools.list_reports() == []


def test_get_report_roundtrip(seeded_db):
    from mcp_server import tools

    brief_id = seeded_db.create_brief(query="What is new?", item_id=None, topic_id=None)
    seeded_db.finish_brief(
        brief_id,
        report={"title": "Report T", "tldr": ["x"], "sources": [{"id": "s1", "title": "S", "url": "https://e"}]},
        citations=[],
        cost_usd=0.01,
    )
    reports = tools.list_reports()
    assert len(reports) == 1
    detail = tools.get_report(brief_id)
    assert detail["report"]["title"] == "Report T"
    assert tools.get_report("nope") is None


def test_search_library_uses_retriever(seeded_db, monkeypatch):
    from mcp_server import tools

    class FakeRetriever:
        def search(self, query, k=8, kinds=("item", "brief")):
            return [
                {"ref_id": "item:m1", "kind": "item", "title": "Agent memory systems", "text": "A story about agent memory.", "score": 0.9, "url": "https://e.com/m1"},
            ]

    import rag.retriever as retriever_mod

    monkeypatch.setattr(retriever_mod, "get_retriever", lambda: FakeRetriever())
    response = tools.search_library("agent memory", k=5)
    assert response["results"] and response["results"][0]["title"] == "Agent memory systems"


def test_start_and_get_research(seeded_db, monkeypatch):
    from mcp_server import tools

    def fake_start(query, depth="standard", item_id=None, session_id=None):
        job_id = seeded_db.create_job("research", {"query": query})
        return {"job_id": job_id, "brief_id": None, "status": "pending"}

    import agents.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "start_research_job", fake_start)
    started = tools.start_research("test question", depth="brief")
    assert started["job_id"]

    # Unfinished job → status only
    status = tools.get_research(started["job_id"])
    assert status["status"] == "pending"


def test_get_research_unknown_job(seeded_db):
    from mcp_server import tools

    result = tools.get_research("missing")
    assert result["status"] == "unknown"

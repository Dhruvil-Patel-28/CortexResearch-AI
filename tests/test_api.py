"""
API contract tests for the Topic Watch routes.

Uses FastAPI's TestClient without the lifespan context so no embedding model
is loaded. Each test points settings.db_path at a temp database.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sources.base import FeedItem
from store import db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from utils.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "api.db"))
    monkeypatch.setattr(settings, "profile_path", str(tmp_path / "profile.yaml"))

    from api.main import app

    db.init_db()
    # Plain TestClient (no context manager) skips the lifespan warmup so tests
    # stay fast and never download models.
    yield TestClient(app)


def seed() -> None:
    db.upsert_items(
        [
            FeedItem(
                source="hackernews",
                title="An agent framework ships evals",
                url="https://example.com/a",
                external_id="1",
                published_at="2026-10-05T10:00:00+00:00",
                raw_text="Evaluation tooling for agents",
                cluster_key="cl1",
            ),
            FeedItem(
                source="rss",
                title="Agent framework ships evals, now with dashboards",
                url="https://blog.example.com/a",
                external_id="2",
                published_at="2026-10-05T11:00:00+00:00",
                cluster_key="cl1",
            ),
            FeedItem(
                source="arxiv",
                title="Unrelated paper on cache coherence",
                url="https://arxiv.org/abs/1",
                external_id="3",
                published_at="2026-10-04T09:00:00+00:00",
                cluster_key="cl2",
            ),
        ]
    )
    items = db.list_items(collapse=False, order="newest")
    subject = next(i for i in items if i["title"].startswith("An agent framework"))
    db.save_scores(
        [
            {
                "item_id": subject["id"],
                "topic_id": "general",
                "relevance": 9.0,
                "rationale": "You build agents; evals are your stated goal.",
                "tags": ["agents", "evals"],
                "model": "fast",
                "profile_version": "v1",
            }
        ]
    )


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_feed_returns_clustered_cards(client):
    seed()
    r = client.get("/watch/feed")
    assert r.status_code == 200
    body = r.json()

    assert body["count"] == 2  # two clusters, not three items
    top = body["items"][0]
    assert top["relevance"] == 9.0
    assert top["cluster_size"] == 2
    assert set(top["cluster_sources"]) == {"hackernews", "rss"}
    assert top["rationale"].startswith("You build agents")
    assert body["stats"]["total_items"] == 3


def test_feed_min_score_filter(client):
    seed()
    only_high = client.get("/watch/feed?min_score=8").json()
    assert only_high["count"] == 1
    assert only_high["items"][0]["relevance"] == 9.0


def test_stats_lists_sources(client):
    seed()
    body = client.get("/watch/stats").json()
    assert body["total_items"] == 3
    assert body["by_source"]["arxiv"] == 1
    keys = {s["key"] for s in body["sources"]}
    assert {"hackernews", "arxiv", "rss", "reddit", "github", "producthunt"} <= keys


def test_item_detail_and_cluster_members(client):
    seed()
    items = db.list_items(collapse=False, order="newest")
    subject = next(i for i in items if i["title"].startswith("An agent framework"))

    body = client.get(f"/watch/items/{subject['id']}").json()
    assert body["item"]["id"] == subject["id"]
    assert len(body["also_covered_by"]) == 1
    assert body["also_covered_by"][0]["source"] == "rss"

    assert client.get("/watch/items/does-not-exist").status_code == 404


def test_bookmark_roundtrip(client):
    seed()
    items = db.list_items(collapse=False, order="newest")
    subject = items[0]["id"]

    assert client.post(f"/watch/items/{subject}/bookmark", json={"note": "read"}).json()[
        "bookmarked"
    ]
    assert client.get("/watch/feed?bookmarked=true").json()["count"] == 1

    assert not client.delete(f"/watch/items/{subject}/bookmark").json()["bookmarked"]
    assert client.get("/watch/feed?bookmarked=true").json()["count"] == 0


def test_profile_roundtrip(client):
    initial = client.get("/watch/profile").json()
    assert initial["version"] in ("", "default")  # no profile file yet

    updated = client.put(
        "/watch/profile",
        json={
            "name": "Dhruvil",
            "interests": ["AI agents"],
            "stack": ["Python"],
            "goals": ["ship a portfolio project"],
            "boost": ["MCP"],
            "mute": ["crypto"],
            "arxiv_keywords": ["retrieval augmented generation"],
        },
    ).json()

    assert updated["name"] == "Dhruvil"
    assert updated["interests"] == ["AI agents"]
    assert updated["version"]  # hash present once the file exists

    reloaded = client.get("/watch/profile").json()
    assert reloaded["boost"] == ["MCP"]
    assert reloaded["version"] == updated["version"]


def test_job_status_404(client):
    assert client.get("/watch/jobs/nope").status_code == 404


def test_health_reports_s1_status(client, monkeypatch):
    from utils import system1
    from utils.config import settings

    monkeypatch.setattr(settings, "s1_enabled", False)  # avoid model loads in tests
    monkeypatch.setattr(system1, "_router", None)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["s1"]["enabled"] is False
    assert body["s1"]["backend"] == "off"
    assert body["s1"]["healthy"] is True

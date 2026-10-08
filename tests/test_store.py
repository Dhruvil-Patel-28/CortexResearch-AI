"""Offline tests for the SQLite store (each test uses a temp database)."""

from __future__ import annotations

import pytest

from sources.base import FeedItem
from store import db


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    db.init_db(path)
    return path


def make_item(**kw) -> FeedItem:
    base = {"source": "hn", "title": "An item", "url": "https://example.com/a", "external_id": "1"}
    base.update(kw)
    return FeedItem(**base)


def test_upsert_dedupes(db_path):
    new, dup = db.upsert_items([make_item()], path=db_path)
    assert (new, dup) == (1, 0)

    new, dup = db.upsert_items([make_item()], path=db_path)
    assert (new, dup) == (0, 1)


def test_list_items_filters_and_scoring(db_path):
    db.upsert_items(
        [
            make_item(external_id="1", title="Agent framework release"),
            make_item(external_id="2", title="Crypto token launch"),
        ],
        path=db_path,
    )
    items = db.list_items(path=db_path)
    assert len(items) == 2

    agent = next(i for i in items if "Agent" in i["title"])
    db.save_scores(
        [
            {
                "item_id": agent["id"],
                "topic_id": "general",
                "relevance": 9.0,
                "rationale": "You build agents, so this matters.",
                "tags": ["agents"],
                "model": "fast",
                "profile_version": "v1",
            }
        ],
        path=db_path,
    )

    high = db.list_items(min_score=7.0, path=db_path)
    assert len(high) == 1
    assert high[0]["relevance"] == 9.0
    assert high[0]["tags"] == ["agents"]

    by_q = db.list_items(q="Crypto", path=db_path)
    assert len(by_q) == 1

    ordered = db.list_items(order="relevance", path=db_path)
    assert ordered[0]["relevance"] == 9.0


def test_scored_cache_lookup(db_path):
    item = make_item()
    db.upsert_items([item], path=db_path)
    assert db.scored_item_ids("v1", path=db_path) == set()

    db.save_scores(
        [{"item_id": item.id, "relevance": 5, "profile_version": "v1"}],
        path=db_path,
    )
    assert db.scored_item_ids("v1", path=db_path) == {item.id}
    assert db.scored_item_ids("v2", path=db_path) == set()


def test_bookmarks(db_path):
    item = make_item()
    db.upsert_items([item], path=db_path)

    db.set_bookmark(item.id, note="read later", path=db_path)
    assert db.list_items(bookmarked=True, path=db_path)[0]["bookmarked"] is True
    assert len(db.list_items(bookmarked=True, path=db_path)) == 1

    db.remove_bookmark(item.id, path=db_path)
    assert db.list_items(bookmarked=True, path=db_path) == []


def test_meta_and_jobs(db_path):
    db.set_meta("last_ingest_at", "2026-06-01T00:00:00Z", path=db_path)
    assert db.get_meta("last_ingest_at", path=db_path) == "2026-06-01T00:00:00Z"

    job_id = db.create_job("brief", {"item_id": "x"}, path=db_path)
    db.update_job(job_id, status="running", progress={"step": "research"}, path=db_path)

    job = db.get_job(job_id, path=db_path)
    assert job["status"] == "running"
    assert job["progress"]["step"] == "research"
    assert job["payload"]["item_id"] == "x"


def test_cluster_collapse_merges_cross_source_stories(db_path):
    items = [
        make_item(external_id="a", title="Story A from HN"),
        make_item(external_id="b", title="Story A from RSS", source="rss"),
        make_item(external_id="c", title="Unrelated story", source="arxiv"),
    ]
    for it, key in zip(items, ["cluster1", "cluster1", "cluster2"]):
        it.cluster_key = key
    db.upsert_items(items, path=db_path)

    collapsed = db.list_items(path=db_path)
    assert len(collapsed) == 2

    c1 = next(r for r in collapsed if r["cluster_key"] == "cluster1")
    assert c1["cluster_size"] == 2
    assert set(c1["cluster_sources"].split(",")) == {"hn", "rss"}

    expanded = db.list_items(collapse=False, path=db_path)
    assert len(expanded) == 3

    cluster_only = db.get_cluster_items("cluster1", path=db_path)
    assert len(cluster_only) == 2


def test_stats(db_path):
    db.upsert_items([make_item(external_id="1"), make_item(external_id="2", source="arxiv")], path=db_path)
    s = db.stats(path=db_path)
    assert s["total_items"] == 2
    assert s["by_source"] == {"hn": 1, "arxiv": 1}
    assert s["bookmarks"] == 0

"""
Offline tests for the /search (library) API and the optional GraphRAG /
Supermemory adapters. Flags default off; adapters degrade gracefully.
"""

from __future__ import annotations

import pytest

from store import db as store
from utils.config import settings


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api.main import app

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "search-api.db"))
    monkeypatch.setattr(settings, "rag_index_dir", str(tmp_path / "rag"))
    monkeypatch.setattr(settings, "rag_rerank", False)
    store.init_db()
    return TestClient(app)


def _fake_retriever(monkeypatch):
    def fake_search(query, k=8, *, kinds=("item", "brief")):
        hits = []
        if "item" in kinds:
            hits.append(
                {
                    "ref_id": "item-1",
                    "kind": "item",
                    "title": "Hybrid search item",
                    "url": "https://example.com/1",
                    "snippet": "retrieval snippet",
                    "source": "hackernews",
                    "published_at": "2026-10-07T00:00:00+00:00",
                    "score": 0.9,
                }
            )
        if "brief" in kinds:
            hits.append(
                {
                    "ref_id": "brief-1",
                    "kind": "brief",
                    "title": "Past report",
                    "url": "",
                    "snippet": "report snippet",
                    "source": "report",
                    "published_at": "2026-10-07T00:00:00+00:00",
                    "score": 0.5,
                }
            )
        return hits[:k]

    monkeypatch.setattr(
        "rag.retriever.get_retriever",
        lambda: type("R", (), {"search": staticmethod(fake_search)})(),
    )


def test_search_contract_flags_off(client, monkeypatch):
    _fake_retriever(monkeypatch)

    response = client.get("/search", params={"q": "hybrid search"})
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "hybrid search"
    assert [h["kind"] for h in data["results"]] == ["item", "brief"]
    assert data["graph"] is None
    assert data["memory"] == []
    assert data["flags"] == {"graph_rag": False, "supermemory": False}


def test_search_kind_filter_and_relevance(client, monkeypatch):
    _fake_retriever(monkeypatch)
    store.save_scores(
        [
            {
                "item_id": "item-1",
                "relevance": 7.5,
                "rationale": "test",
                "tags": [],
                "model": "test",
                "profile_version": "test",
                "scored_at": "2026-10-07T00:00:00+00:00",
            }
        ]
    )

    only_items = client.get("/search", params={"q": "x", "kind": "item"}).json()
    assert [h["kind"] for h in only_items["results"]] == ["item"]
    assert only_items["results"][0]["relevance"] == 7.5

    only_briefs = client.get("/search", params={"q": "x", "kind": "brief"}).json()
    assert [h["kind"] for h in only_briefs["results"]] == ["brief"]
    assert only_briefs["results"][0]["brief_id"] is None


def test_search_validation(client):
    assert client.get("/search", params={"q": ""}).status_code == 422
    assert client.get("/search", params={"q": "x", "kind": "bogus"}).status_code == 422


def test_graph_rag_disabled_by_default():
    from rag.graph import graph_results

    result = graph_results("how do X and Y connect")
    assert result["available"] is False
    assert "disabled" in result["reason"]


def test_graph_rag_enabled_with_fake_backend(monkeypatch):
    import sys
    import types

    from rag import graph as graph_mod

    monkeypatch.setattr(settings, "enable_graph_rag", True)

    class FakeQueryParam:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeRAG:
        def query(self, query, param=None):
            return "X and Y connect via Z."

        def ainsert(self, doc):
            return True

    # Provide a fake lightrag module so the lazy imports resolve offline.
    monkeypatch.setitem(
        sys.modules,
        "lightrag",
        types.SimpleNamespace(LightRAG=FakeRAG, QueryParam=FakeQueryParam),
    )
    monkeypatch.setattr(graph_mod, "_get_lightrag", lambda: FakeRAG())
    result = graph_mod.graph_results("connect")
    assert result["available"] is True
    assert "X and Y" in result["answer"]


def test_graph_rag_missing_package_degrades(monkeypatch):
    from rag import graph as graph_mod

    monkeypatch.setattr(settings, "enable_graph_rag", True)
    monkeypatch.setattr(graph_mod, "_get_lightrag", lambda: None)
    monkeypatch.setattr(graph_mod, "_unavailable_reason", "lightrag-hku is not installed")

    result = graph_mod.graph_results("connect")
    assert result["available"] is False
    assert "lightrag-hku" in result["reason"]


def test_supermemory_off_by_default():
    from memory.supermemory import get_memory

    assert get_memory() is None


def test_supermemory_client_offline_parse(monkeypatch):
    from memory import supermemory as sm

    monkeypatch.setattr(settings, "enable_supermemory", True)
    monkeypatch.setattr(settings, "supermemory_url", "http://127.0.0.1:9876")
    monkeypatch.setattr(settings, "supermemory_api_key", "")

    mem = sm.get_memory()
    assert mem is not None

    # Unreachable service → empty results, never an exception.
    assert mem.search("anything", k=3) == []
    assert mem.remember("note") is False

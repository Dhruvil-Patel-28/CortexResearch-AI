"""
Offline tests for the hybrid retriever (BM25 FTS5 + dense + rerank fusion).

No network, no model downloads: the embedder and reranker are deterministic
fakes, and all stores are temporary databases.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from store import db as store
from utils.config import settings

_DIM = 256


@pytest.fixture()
def store_db(tmp_path, monkeypatch):
    """Temporary store + isolated dense-index directory."""
    path = str(tmp_path / "rag-test.db")
    monkeypatch.setattr(settings, "db_path", path)
    monkeypatch.setattr(settings, "rag_index_dir", str(tmp_path / "rag"))
    monkeypatch.setattr(settings, "rag_rerank", False)  # never load real models in tests
    store.init_db(path)
    return path


def _fake_embedder(texts: list[str]) -> np.ndarray:
    """Deterministic bag-of-words hashing embedder: similar text → similar vector."""

    def embed_one(text: str) -> np.ndarray:
        vec = np.zeros(_DIM, dtype="float32")
        for word in (text or "").lower().split():
            bucket = int(hashlib.sha1(word.encode()).hexdigest(), 16) % _DIM
            vec[bucket] += 1.0
        norm = np.linalg.norm(vec)
        return vec / norm if norm else vec

    return np.stack([embed_one(t) for t in texts])


def _seed_item(item_id: str, *, title: str, body: str, score: float | None = None) -> str:
    from datetime import datetime, timezone
    from sources.base import FeedItem

    item = FeedItem(
        source="hackernews",
        title=title,
        url=f"https://example.com/{item_id}",
        external_id=item_id,
        published_at=datetime.now(timezone.utc).isoformat(),
        raw_text=body,
        metrics={},
        cluster_key="",
    )
    store.upsert_items([item])
    if score is not None:
        store.save_scores(
            [{
                "item_id": item.id,
                "relevance": score,
                "rationale": "test",
                "tags": [],
                "model": "test",
                "profile_version": "test",
                "scored_at": datetime.now(timezone.utc).isoformat(),
            }]
        )
    return item.id


def _retriever(**kwargs):
    from rag.retriever import Retriever

    kwargs.setdefault("embedder", _fake_embedder)
    return Retriever(**kwargs)


def test_hybrid_search_ranks_relevant_item_first(store_db):
    id_vec = _seed_item("vec", title="Vector database ships hybrid search",
                        body="The vector database now supports hybrid BM25 and dense retrieval out of the box.")
    _seed_item("cook", title="Pasta recipe thread",
               body="Slow simmered tomato sauce with garlic and basil, a weeknight classic.")
    _seed_item("gpu", title="GPU prices climb",
               body="Memory prices are pushing GPU costs up across the board this quarter.")

    hits = _retriever().search("vector database hybrid retrieval", k=3)
    assert hits, "matches exist, so hits must be returned"
    assert hits[0]["ref_id"] == id_vec
    assert hits[0]["kind"] == "item"
    assert "vector database" in hits[0]["title"].lower()
    assert 0.0 <= hits[0]["score"] <= 1.0


def test_search_returns_briefs_and_items_by_kind(store_db):
    _seed_item("topic-a", title="LangGraph update", body="LangGraph released checkpointing improvements.")
    brief_id = store.create_brief(query="LangGraph checkpointing")
    store.finish_brief(
        brief_id,
        report={
            "title": "LangGraph checkpointing deep dive",
            "executive_summary": "How LangGraph checkpointing works and why it matters for durable agents.",
            "tldr": ["Checkpointing makes agent runs resumable."],
        },
    )

    retriever = _retriever()
    both = retriever.search("LangGraph checkpointing", k=5)
    kinds = {h["kind"] for h in both}
    assert kinds == {"item", "brief"}, "both legs of the store are searchable"

    only_briefs = retriever.search("LangGraph checkpointing", k=5, kinds=("brief",))
    assert {h["kind"] for h in only_briefs} == {"brief"}
    assert only_briefs[0]["ref_id"] == brief_id


def test_ensure_index_rebuilds_only_when_store_changes(store_db):
    _seed_item("one", title="First item", body="alpha beta gamma")
    retriever = _retriever()

    assert retriever.ensure_index() is True, "first call builds"
    assert retriever.ensure_index() is False, "unchanged store must not rebuild"

    _seed_item("two", title="Second item", body="delta epsilon zeta")
    assert retriever.ensure_index() is True, "new item changes the fingerprint"


def test_reranker_reorders_candidates(store_db):
    _seed_item("close", title="Agent memory systems", body="Agent memory systems for long running tasks.")
    id_far = _seed_item("far", title="Agent memory systems", body="Completely unrelated filler text about gardening.")

    def reverse_rerank(query: str, texts: list[str]) -> list[float]:
        # Boost the "far" doc (the one RRF would rank lower) to test reordering.
        return [10.0 if "gardening" in t else -10.0 for t in texts]

    reranked = _retriever(reranker=reverse_rerank).search("agent memory systems", k=2)
    assert reranked[0]["ref_id"] == id_far, "reranker output must drive final order"
    assert reranked[0]["score"] > 0.5, "sigmoid-mapped rerank scores are normalized"


def test_store_results_keeps_shape_and_relevance(store_db, monkeypatch):
    id_rel = _seed_item("rel", title="Mistral Large 4 released", body="Mistral shipped a new frontier model today.",
                        score=8.5)
    _seed_item("noise", title="Cooking thread", body="Best chili recipe arguments.")

    # Use a fake-embedder retriever: the global singleton would try to load
    # real models, which tests must never do.
    monkeypatch.setattr("rag.retriever.get_retriever", lambda: _retriever())

    from tools.store_search import store_results

    results = store_results("Mistral Large 4 frontier model", limit=4)
    assert results and results[0]["id"] == id_rel
    row = results[0]
    assert {"id", "title", "url", "source", "published_at", "snippet", "relevance"} <= set(row)
    assert row["relevance"] == 8.5, "personalized score is attached from the scores table"


def test_rag_results_serve_published_briefs(store_db, monkeypatch):
    brief_id = store.create_brief(query="SWE-Race benchmark")
    store.finish_brief(
        brief_id,
        report={
            "title": "SWE-Race: concurrency bug benchmark",
            "key_developments": [{"claim": "SWE-Race tests coding agents on 188 real concurrency bugs."}],
        },
    )
    # A still-running brief must not be indexed.
    store.create_brief(query="running brief")

    monkeypatch.setattr("rag.retriever.get_retriever", lambda: _retriever())

    from tools.rag_tool import rag_results

    hits = rag_results("SWE-Race concurrency benchmark")
    assert len(hits) == 1
    assert hits[0]["title"] == "SWE-Race: concurrency bug benchmark"
    assert "SWE-Race" in hits[0]["snippet"]


def test_dense_leg_failure_degrades_to_bm25(store_db):
    def broken_embedder(texts):
        raise RuntimeError("model offline")

    id_bm = _seed_item("bm", title="SQLite FTS5 full text", body="FTS5 powers BM25 ranking inside SQLite.")

    hits = _retriever(embedder=broken_embedder).search("SQLite FTS5 full text", k=3)
    assert hits and hits[0]["ref_id"] == id_bm, "BM25 alone must still answer"


def test_no_matches_returns_empty(store_db):
    hits = _retriever().search("quantum llama dynamics", k=3)
    assert hits == []

"""Supermemory write/recall hook tests — fake client, offline."""

from __future__ import annotations

import pytest


class FakeMemory:
    def __init__(self):
        self.docs = []

    def remember(self, text: str, metadata: dict | None = None) -> bool:
        self.docs.append({"text": text, "metadata": metadata or {}})
        return True

    def search(self, query: str, k: int = 5) -> list[dict]:
        return [
            {"text": f"memory for {query}", "score": 0.9, "metadata": {"kind": "report"}},
        ][:k]


@pytest.fixture()
def fake(monkeypatch):
    import memory.remember as remember

    fake = FakeMemory()
    monkeypatch.setattr(remember, "get_memory", lambda: fake)
    return fake


def test_remember_report_payload(fake):
    from memory.remember import remember_report

    ok = remember_report(
        {"id": "rep1", "title": "T", "query": "Q", "tldr": ["a", "b"], "depth": "brief"}
    )
    assert ok
    doc = fake.docs[0]
    assert "T" in doc["text"] and "a" in doc["text"]
    assert doc["metadata"] == {"kind": "report", "report_id": "rep1", "query": "Q", "depth": "brief"}


def test_remember_report_noop_without_memory(monkeypatch):
    import memory.remember as remember

    monkeypatch.setattr(remember, "get_memory", lambda: None)
    assert remember.remember_report({"title": "x"}) is False


def test_remember_bookmark_payload(fake):
    from memory.remember import remember_bookmark

    remember_bookmark({"id": "it1", "title": "Story", "url": "https://e.com", "source": "hn"}, "great find")
    doc = fake.docs[0]
    assert "Story" in doc["text"] and "great find" in doc["text"]
    assert doc["metadata"]["kind"] == "bookmark"
    assert doc["metadata"]["item_id"] == "it1"


def test_remember_search_dedupes_repeats(fake):
    from memory.remember import remember_search

    assert remember_search("jevons paradox")
    assert not remember_search("jevons paradox")  # same query → skipped
    assert not remember_search("  jevons paradox  ")  # whitespace-normalized
    assert remember_search("different query")
    assert len(fake.docs) == 2


def test_remember_digest_payload(fake):
    from memory.remember import remember_digest

    remember_digest({"id": "d1", "markdown": "Weekly digest body", "item_ids": ["a", "b"]})
    doc = fake.docs[0]
    assert "Weekly digest body" in doc["text"]
    assert doc["metadata"]["kind"] == "digest"


def test_remember_failure_is_swallowed(monkeypatch):
    import memory.remember as remember

    class Broken:
        def remember(self, text, metadata=None):
            raise RuntimeError("service down")

    monkeypatch.setattr(remember, "get_memory", lambda: Broken())
    assert remember.remember_report({"title": "x", "query": "q"}) is False


def test_recall_formats_results(fake):
    from memory.remember import recall

    text = recall("agent memory", k=3)
    assert "memory for agent memory" in text
    assert "personal memory store" in text.lower()


def test_recall_empty_without_memory(monkeypatch):
    import memory.remember as remember

    monkeypatch.setattr(remember, "get_memory", lambda: None)
    assert remember.recall("anything") == ""

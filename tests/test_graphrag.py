"""GraphRAG tests — construction wiring, indexing hook, failure isolation (fake lightrag module)."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import ClassVar

import pytest


class FakeLightRAG:
    """Records construction + inserts; canned query answer."""

    instances: ClassVar[list[FakeLightRAG]] = []
    query_answer: ClassVar[str] = "graph says: connected"

    def __init__(self, working_dir="", llm_model_func=None, llm_model_name=None, embedding_func=None):
        self.working_dir = working_dir
        self.llm_model_func = llm_model_func
        self.llm_model_name = llm_model_name
        self.embedding_func = embedding_func
        self.inserted: list[str] = []
        self.query_calls: list[str] = []
        FakeLightRAG.instances.append(self)

    async def ainsert(self, text):
        self.inserted.append(text)

    def query(self, query, param=None):
        self.query_calls.append(query)
        if self.query_answer is None:
            raise RuntimeError("graph exploded")
        return self.query_answer


class FakeEmbeddingFunc:
    def __init__(self, embedding_dim=None, func=None):
        self.embedding_dim = embedding_dim
        self.func = func


@pytest.fixture()
def fake_lightrag(monkeypatch):
    module = types.ModuleType("lightrag")
    module.LightRAG = FakeLightRAG
    module.EmbeddingFunc = FakeEmbeddingFunc

    class QueryParam:
        def __init__(self, mode=None, top_k=None):
            self.mode = mode
            self.top_k = top_k

    module.QueryParam = QueryParam
    monkeypatch.setitem(sys.modules, "lightrag", module)

    from rag import graph as graph_mod

    graph_mod._lightrag_instance = None
    graph_mod._unavailable_reason = ""
    FakeLightRAG.instances = []
    monkeypatch.setattr(graph_mod, "_run_async", lambda coro: asyncio.run(coro))
    yield graph_mod
    graph_mod._lightrag_instance = None
    graph_mod._unavailable_reason = ""
    FakeLightRAG.instances = []


@pytest.fixture()
def graph_enabled(monkeypatch, tmp_path):
    from utils.config import settings

    monkeypatch.setattr(settings, "enable_graph_rag", True)
    monkeypatch.setattr(settings, "graph_working_dir", str(tmp_path / "graph"))
    monkeypatch.setattr(settings, "graph_llm_tier", "fast")


class FakeDoc:
    def __init__(self, ref_id, title, text):
        self.ref_id = ref_id
        self.title = title
        self.text = text


def test_construction_wires_our_llm_and_embeddings(fake_lightrag, graph_enabled):
    result = fake_lightrag.graph_results("how do X and Y connect")
    assert result["available"]
    rag = FakeLightRAG.instances[-1]
    assert rag.llm_model_func is not None
    assert rag.embedding_func is not None
    assert rag.embedding_func.embedding_dim == 384  # MiniLM


def test_llm_model_func_returns_text(fake_lightrag, graph_enabled, monkeypatch):
    result = fake_lightrag.graph_results("q")
    assert result["available"]
    rag = FakeLightRAG.instances[-1]

    from langchain_core.messages import AIMessage

    import utils.llm as llm_mod

    class FakeLLM:
        def invoke(self, messages, **kwargs):
            return AIMessage(content="synthesized graph answer")

    monkeypatch.setattr(llm_mod, "_build", lambda model, temperature, max_tokens: FakeLLM())
    answer = asyncio.run(rag.llm_model_func("prompt here"))
    assert answer == "synthesized graph answer"


def test_embedding_func_embeds_texts(fake_lightrag, graph_enabled, monkeypatch):
    fake_lightrag.graph_results("q")
    rag = FakeLightRAG.instances[-1]

    import numpy as np

    import rag.retriever as retriever_mod

    monkeypatch.setattr(
        retriever_mod, "get_embedder", lambda: lambda texts: np.zeros((len(texts), 384), dtype="float32")
    )
    vectors = asyncio.run(rag.embedding_func.func(["a", "b"]))
    assert vectors.shape == (2, 384)


def test_query_failure_degrades(fake_lightrag, graph_enabled):
    FakeLightRAG.query_answer = None
    result = fake_lightrag.graph_results("q")
    assert not result["available"]
    assert "failed" in result["reason"].lower()


def test_disabled_returns_unavailable(fake_lightrag, monkeypatch):
    from utils.config import settings

    monkeypatch.setattr(settings, "enable_graph_rag", False)
    result = fake_lightrag.graph_results("q")
    assert not result["available"]
    assert "disabled" in result["reason"].lower()


def test_missing_package_reports_reason(fake_lightrag, graph_enabled, monkeypatch):
    monkeypatch.setitem(sys.modules, "lightrag", None)  # import fails
    result = fake_lightrag.graph_results("q")
    assert not result["available"]
    assert "install" in result["reason"].lower()


def test_index_docs_inserts_only_new(fake_lightrag, graph_enabled, monkeypatch, tmp_path):
    from utils.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "g.db"))
    from store import db

    db.init_db()

    docs = [FakeDoc("d1", "T1", "body one"), FakeDoc("d2", "T2", "body two")]
    fake_lightrag.index_docs(docs)
    fake_lightrag.index_docs(docs)  # second pass: all already indexed

    rag = FakeLightRAG.instances[-1]
    inserted_count = sum(len(x) if isinstance(x, list) else 1 for x in rag.inserted)
    assert inserted_count == 2  # each doc inserted exactly once
    assert set(fake_lightrag.db.get_meta("graph_indexed_ids").split(",")) == {"d1", "d2"}


def test_index_docs_disabled_noop(fake_lightrag, monkeypatch):
    from utils.config import settings

    monkeypatch.setattr(settings, "enable_graph_rag", False)
    fake_lightrag.index_docs([FakeDoc("d1", "T", "b")])
    assert FakeLightRAG.instances == []


def test_retriever_rebuild_triggers_graph_indexing(fake_lightrag, graph_enabled, monkeypatch, tmp_path):
    """Auto-reindex fans new docs out to the graph (already flag-guarded)."""
    called_with = []
    monkeypatch.setattr(fake_lightrag, "index_docs", lambda docs: called_with.append(list(docs)))

    from utils.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "r.db"))
    from sources.base import FeedItem
    from store import db

    db.init_db()
    db.upsert_items(
        [
            FeedItem(
                source="hn",
                external_id="g1",
                title="Graph fodder",
                url="https://e.com/g1",
                raw_text="text for the graph",
                published_at="2026-10-08T00:00:00Z",
            )
        ]
    )

    from rag.retriever import Retriever

    Retriever().ensure_index()
    assert called_with and all(hasattr(d, "ref_id") for d in called_with[0])

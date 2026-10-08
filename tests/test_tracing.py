"""Langfuse tracing wrapper tests — no-op without keys, recording with a fake client."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _fresh_tracing():
    from utils import tracing

    tracing.reset_for_tests()
    yield
    tracing.reset_for_tests()


def _enable(monkeypatch):
    from utils.config import settings

    monkeypatch.setattr(settings, "langfuse_enabled", True)
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-test")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-test")
    monkeypatch.setattr(settings, "langfuse_host", "http://localhost:3000")


class FakeLangfuse:
    def __init__(self, **kwargs):
        FakeLangfuse.last_init = kwargs
        self.traces = []
        self.generations = []
        self.events = []
        self.scores = []

    def trace(self, **kwargs):
        self.traces.append(kwargs)
        return self

    def generation(self, **kwargs):
        self.generations.append(kwargs)

    def event(self, **kwargs):
        self.events.append(kwargs)

    def score(self, **kwargs):
        self.scores.append(kwargs)


def test_disabled_without_keys(monkeypatch):
    from utils.config import settings
    from utils.tracing import RunTrace

    monkeypatch.setattr(settings, "langfuse_enabled", True)
    monkeypatch.setattr(settings, "langfuse_public_key", "")
    trace = RunTrace.start("test query", "brief")
    assert not trace.enabled
    trace.finish("ok")  # must not raise


def test_disabled_master_switch(monkeypatch):
    from utils.config import settings
    from utils.tracing import RunTrace

    monkeypatch.setattr(settings, "langfuse_enabled", False)
    assert not RunTrace.start("q", "brief").enabled


def test_records_generations_events_scores(monkeypatch):
    from utils import tracing

    _enable(monkeypatch)
    fake = FakeLangfuse()
    monkeypatch.setattr(tracing, "_build_client", lambda: fake)

    trace = tracing.RunTrace.start("test query", "standard")
    assert trace.enabled
    trace.generation(model="m1", label="plan", input_tokens=100, output_tokens=50, latency_ms=120.0)
    trace.event("route", {"task": "query_class", "backend": "local"})
    trace.score("verification", 1.0, "3/3 supported")
    trace.finish("ok")

    assert fake.traces and fake.traces[0]["name"] == "research-run"
    assert fake.traces[0]["input"] == "test query"
    assert len(fake.generations) == 1
    assert fake.generations[0]["model"] == "m1"
    assert fake.events[0]["name"] == "route"
    assert fake.scores[0]["name"] == "verification"


def test_langfuse_failure_swallowed(monkeypatch):
    from utils import tracing

    _enable(monkeypatch)

    class Broken:
        def __init__(self, **kwargs):
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(tracing, "_build_client", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    trace = tracing.RunTrace.start("q", "brief")
    assert not trace.enabled  # degraded to no-op, never raised


def test_active_trace_context_for_llm_client(monkeypatch):
    from utils import tracing

    _enable(monkeypatch)
    fake = FakeLangfuse()
    monkeypatch.setattr(tracing, "_build_client", lambda: fake)

    with tracing.active_trace() as trace:
        assert trace is not None
        current = tracing.current_trace()
        assert current is trace
    assert tracing.current_trace() is None


def test_llm_client_records_generation(monkeypatch):
    from utils import tracing
    import utils.llm as llm_mod
    from langchain_core.messages import AIMessage

    _enable(monkeypatch)
    fake = FakeLangfuse()
    monkeypatch.setattr(tracing, "_build_client", lambda: fake)

    class FakeLLM:
        def invoke(self, messages, **kwargs):
            return AIMessage(content="hello")

    monkeypatch.setattr(llm_mod, "_build", lambda model, temperature, max_tokens: FakeLLM())
    client = llm_mod.LLMClient("fake-model", None, 64)

    with tracing.active_trace():
        client.invoke("say hi")

    # generation recorded through the trace wrapper
    assert len(fake.generations) == 1
    assert fake.generations[0]["model"] == "fake-model"

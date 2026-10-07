"""Planner S1 query-classification tests — router stubbed, offline."""

from __future__ import annotations

from agents import planner
from utils.system1 import Decision, DecisionLog, CircuitBreaker, S1Request, S1S2Router


class SequenceRouter(S1S2Router):
    """Returns canned decisions in order (domain, then kb_relevance)."""

    def __init__(self, labels: list[str]) -> None:
        super().__init__(backend=None, fallback=None, escalate=None, threshold=0.75, log=DecisionLog(), breaker=CircuitBreaker())
        self._labels = list(labels)
        self.requests: list[S1Request] = []

    def decide(self, request: S1Request) -> Decision:
        self.requests.append(request)
        label = self._labels.pop(0) if self._labels else "other"
        return Decision(label=label, score=0.9, confidence=0.95, backend="stub", latency_ms=1)


def test_classify_query_returns_both_fields(monkeypatch):
    router = SequenceRouter(["devtools", "relevant"])
    monkeypatch.setattr(planner, "get_router", lambda: router)
    result = planner.classify_query("Which devtools shipped vector search in 2026?")
    assert result["domain"] == "devtools"
    assert result["kb_relevant"] is True
    assert result["backend"] == "stub"
    assert [r.task for r in router.requests] == ["query_domain", "kb_relevance"]


def test_planner_prompt_contains_hint(monkeypatch):
    from utils.llm_json import JsonCallError

    monkeypatch.setattr(planner, "get_router", lambda: SequenceRouter(["ai", "relevant"]))
    captured: dict = {}

    def fake_call_json(llm, *, system, user, **kw):
        captured["user"] = user
        raise JsonCallError("captured — force fallback plan")

    monkeypatch.setattr(planner, "call_json", fake_call_json)
    planner.planner_node({"research_query": "state of open-weight models", "depth": "brief"})
    assert "classification hint:" in captured["user"]
    assert "ai" in captured["user"]


def test_classification_failure_is_non_fatal(monkeypatch):
    class BoomRouter(S1S2Router):
        def __init__(self) -> None:
            super().__init__(backend=None, fallback=None, escalate=None, threshold=0.75, log=DecisionLog(), breaker=CircuitBreaker())

        def decide(self, request: S1Request) -> Decision:
            raise RuntimeError("jev down")

    monkeypatch.setattr(planner, "get_router", lambda: BoomRouter())
    assert planner.classify_query("anything") == {}

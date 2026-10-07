"""Verifier S1 integration tests — offline, router and chat path stubbed."""

from __future__ import annotations

import pytest

from agents import verifier
from agents.verifier import ClaimVerdict, VerifierOutput
from utils.system1 import Decision, DecisionLog, CircuitBreaker, S1Request, S1S2Router


class StubRouter(S1S2Router):
    def __init__(self, label: str, confidence: float) -> None:
        super().__init__(backend=None, fallback=None, escalate=None, threshold=0.75, log=DecisionLog(), breaker=CircuitBreaker())
        self.label = label
        self.confidence = confidence

    def decide(self, request: S1Request) -> Decision:
        return Decision(label=self.label, score=0.9, confidence=self.confidence, backend="stub", latency_ms=1)


def _pending(n: int) -> list[dict]:
    return [
        {"id": f"c{i}", "claim": f"claim {i}", "evidence": "evidence", "sources": "[s1] Source — https://x\nquote text"}
        for i in range(1, n + 1)
    ]


def _state(events: list | None = None) -> dict:
    return {"emit": lambda t, body: events.append(body) if events is not None else None}


def test_high_confidence_s1_verdict_skips_llm(monkeypatch):
    events: list = []
    monkeypatch.setattr(verifier, "get_router", lambda: StubRouter("supported", 0.9))

    def boom(*a, **kw):  # chat path must not be touched
        raise AssertionError("chat model called for a high-confidence S1 verdict")

    monkeypatch.setattr(verifier, "call_json", boom)
    verdicts, notes = verifier._judge(_pending(2), meter=None, state=_state(events))
    assert verdicts["c1"].supported is True
    assert verdicts["c1"].backend == "stub"
    assert verdicts["c1"].confidence == pytest.approx(0.9)
    assert notes == ""


def test_low_confidence_claims_grouped_into_one_s2_call(monkeypatch):
    monkeypatch.setattr(verifier, "get_router", lambda: StubRouter("supported", 0.4))
    calls = []

    def fake_call_json(llm, **kw):
        calls.append(1)
        pending = kw["user"]
        ids = [line for line in pending.splitlines() if line.startswith("c")]
        return VerifierOutput(verdicts=[ClaimVerdict(id=i, supported=False, reason="weak") for i in ids], notes="mixed")

    monkeypatch.setattr(verifier, "call_json", fake_call_json)
    verdicts, notes = verifier._judge(_pending(3), meter=None, state=_state())
    assert calls == [1]  # all three low-confidence claims in ONE chat call
    assert verdicts["c2"].supported is False
    assert verdicts["c2"].backend == f"s2:{__import__('utils.config', fromlist=['settings']).settings.model_fast}"
    assert verdicts["c2"].confidence == 1.0
    assert notes == "mixed"


def test_route_events_emitted_per_claim(monkeypatch):
    events: list = []
    monkeypatch.setattr(verifier, "get_router", lambda: StubRouter("unsupported", 0.95))
    verifier._judge(_pending(2), meter=None, state=_state(events))
    route = [e for e in events if e["type"] == "route"]
    assert len(route) == 2
    assert all(e["task"] == "claim_support" and e["backend"] == "stub" for e in route)
    assert all(e["escalated"] is False for e in route)


def test_route_emit_failure_does_not_break_verifier(monkeypatch):
    def bad_emit(t, body):
        raise RuntimeError("socket gone")

    monkeypatch.setattr(verifier, "get_router", lambda: StubRouter("supported", 0.9))
    verdicts, _ = verifier._judge(_pending(2), meter=None, state={"emit": bad_emit})
    assert set(verdicts) == {"c1", "c2"}


def test_s1_disabled_uses_legacy_judge(monkeypatch):
    from utils.config import settings

    monkeypatch.setattr(settings, "s1_enabled", False)
    calls = []

    def fake_call_json(llm, **kw):
        calls.append(1)
        return VerifierOutput(verdicts=[ClaimVerdict(id="c1", supported=True, reason="ok")], notes="fine")

    monkeypatch.setattr(verifier, "call_json", fake_call_json)
    verdicts, notes = verifier._judge(_pending(1), meter=None, state=_state())
    assert calls == [1]
    assert verdicts["c1"].backend is None
    assert verdicts["c1"].confidence is None
    assert notes == "fine"

"""Report model_trace.decisions — S1 decision trace visibility."""

from __future__ import annotations

from agents.research_agent import attach_decision_trace
from utils.system1 import Decision, DecisionLog, S1Request


def test_attach_decision_trace_includes_decisions():
    log = DecisionLog()
    log.add(S1Request(task="claim_support", context="c", options=["supported", "unsupported"]),
            Decision(label="supported", score=0.9, confidence=0.9, backend="jev", latency_ms=12))
    trace = {"model": "x", "tokens": 100}
    merged = attach_decision_trace(trace, log)
    assert merged["decisions"][0]["task"] == "claim_support"
    assert merged["decisions"][0]["backend"] == "jev"
    assert merged["tokens"] == 100  # original fields preserved


def test_attach_decision_trace_caps_at_50():
    log = DecisionLog()
    for i in range(60):
        log.add(S1Request(task="t", context="c", options=["a", "b"]),
                Decision(label="a", score=0.5, confidence=0.5, backend="stub", latency_ms=i))
    merged = attach_decision_trace({}, log)
    assert len(merged["decisions"]) == 50


def test_attach_decision_trace_empty_log():
    merged = attach_decision_trace({"model": "x"}, DecisionLog())
    assert merged["decisions"] == []
    assert merged["model"] == "x"

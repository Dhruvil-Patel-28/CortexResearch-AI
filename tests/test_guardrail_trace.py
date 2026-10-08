"""Guardrail trace tests — per-run deltas from process-wide totals."""

from __future__ import annotations

import pytest

from guardrails import trace


@pytest.fixture(autouse=True)
def _clean_trace():
    trace.reset_for_tests()
    yield
    trace.reset_for_tests()


def test_record_content_counts_scanned_and_findings():
    trace.record_content(
        {"pii_kinds": ["email"], "injection_action": "allow", "injection_count": 0}
    )
    trace.record_content({"pii_kinds": [], "injection_action": "strip", "injection_count": 2})
    snap = trace.snapshot()
    assert snap["scanned"] == 2
    assert snap["pii_redacted"] == 1
    assert snap["injections_stripped"] == 2


def test_record_output_tracks_max_risk_and_redaction_count():
    trace.record_output([{"kind": "secret", "count": 3}], 0.4)
    trace.record_output([], 0.8)
    snap = trace.snapshot()
    assert snap["output_redactions"] == 3
    assert snap["output_injection_risk"] == 0.8


def test_attach_guardrail_trace_computes_deltas():
    start = trace.snapshot()
    trace.record_content(
        {"pii_kinds": ["email"], "injection_action": "strip", "injection_count": 1}
    )
    base = {"calls": []}
    out = trace.attach_guardrail_trace(base, start)
    assert out["guardrails"]["scanned"] == 1
    assert out["guardrails"]["injections_stripped"] == 1
    assert out["guardrails"]["pii_redacted"] == 1


def test_attach_guardrail_trace_passes_list_through():
    start = trace.snapshot()
    out = trace.attach_guardrail_trace([{"model": "m"}], start)
    assert out == [{"model": "m"}]


def test_snapshot_is_a_copy():
    snap = trace.snapshot()
    snap["scanned"] = 999
    assert trace.snapshot()["scanned"] == 0

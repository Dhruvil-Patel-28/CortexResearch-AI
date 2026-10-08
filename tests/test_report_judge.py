"""LLM-as-judge tests — rubric scoring with a stubbed judge, offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals import report_judge
from evals.report_judge import JudgePayload
from evals.results import JudgeDimension, JudgeResult
from schemas.report import coerce_report

GOLDEN = json.loads((Path(__file__).parent.parent / "evals" / "datasets" / "golden_report.json").read_text())


@pytest.fixture()
def golden_report():
    return coerce_report(GOLDEN, keep_verification=True)


def _stub_judge(monkeypatch, dimensions=None):
    dims = dimensions or [
        JudgeDimension(name="groundedness", score=9.0, rationale="claims match citations"),
        JudgeDimension(name="coverage", score=8.5, rationale="all depth-appropriate sections present"),
        JudgeDimension(name="coherence", score=8.0, rationale="reads as one analysis"),
        JudgeDimension(name="citation_hygiene", score=10.0, rationale="every development has sources"),
    ]
    captured = {}

    def fake_call_json(llm, **kwargs):
        captured["user"] = kwargs.get("user", "")
        return JudgePayload(dimensions=dims)

    monkeypatch.setattr(report_judge, "call_json", fake_call_json)
    return captured


def test_judge_scores_all_dimensions(golden_report, monkeypatch):
    _stub_judge(monkeypatch)
    result = report_judge.judge_report(golden_report)
    assert isinstance(result, JudgeResult)
    assert [d.name for d in result.dimensions] == [
        "groundedness", "coverage", "coherence", "citation_hygiene",
    ]
    assert result.verdict == "publishable"


def test_weighted_score_groundedness_doubled(golden_report, monkeypatch):
    _stub_judge(monkeypatch, dimensions=[
        JudgeDimension(name="groundedness", score=6.0),
        JudgeDimension(name="coverage", score=10.0),
        JudgeDimension(name="coherence", score=10.0),
        JudgeDimension(name="citation_hygiene", score=10.0),
    ])
    result = report_judge.judge_report(golden_report)
    # (6*2 + 10 + 10 + 10) / 5 = 8.4 — groundedness weighted 2x
    assert abs(result.weighted_score - 8.4) < 1e-6


def test_deterministic_facts_computed_in_python(golden_report, monkeypatch):
    captured = _stub_judge(monkeypatch)
    result = report_judge.judge_report(golden_report)
    assert "facts" in captured["user"]  # facts were embedded in the judge prompt
    assert result.facts["key_developments"] == 3
    assert result.facts["sources"] == 4
    assert result.facts["developments_without_sources"] == 0
    assert result.facts["has_tldr"] is True
    assert result.facts["has_background_primer"] is True


def test_malformed_judge_json_is_clean_error(golden_report, monkeypatch):
    def bad_call_json(prompt, **kwargs):
        raise RuntimeError("bad JSON day")

    monkeypatch.setattr(report_judge, "call_json", bad_call_json)
    result = report_judge.judge_report(golden_report)
    assert result.verdict == "error"
    assert result.error
    assert result.dimensions == []


def test_missing_report_is_clean_error(monkeypatch):
    _stub_judge(monkeypatch)
    result = report_judge.judge_report({"title": ""})
    assert result.verdict == "error"


def test_verdict_needs_review_below_threshold(golden_report, monkeypatch):
    _stub_judge(monkeypatch, dimensions=[
        JudgeDimension(name="groundedness", score=5.0),
        JudgeDimension(name="coverage", score=5.0),
        JudgeDimension(name="coherence", score=5.0),
        JudgeDimension(name="citation_hygiene", score=5.0),
    ])
    result = report_judge.judge_report(golden_report)
    assert result.verdict == "needs-review"

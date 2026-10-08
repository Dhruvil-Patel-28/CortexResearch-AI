"""Eval runner CLI tests — suites, persistence, threshold exit codes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals import runner
from evals.results import JudgeResult


@pytest.fixture(autouse=True)
def _results_dir(tmp_path, monkeypatch):
    from evals import results

    monkeypatch.setattr(results, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "results", results)
    yield


def test_guardrails_suite_writes_result_and_passes(capsys):
    code = runner.main(["--suite", "guardrails", "--no-save"])
    assert code == 0
    out = capsys.readouterr().out
    assert "precision" in out


def test_guardrails_suite_saves_result_file():
    code = runner.main(["--suite", "guardrails"])
    assert code == 0
    files = list(Path(runner.results.RESULTS_DIR).glob("*-guardrails.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert "precision" in data


def _stub_judge_ok(monkeypatch):
    from evals import report_judge
    from evals.report_judge import JudgePayload
    from evals.results import JudgeDimension

    monkeypatch.setattr(
        report_judge,
        "call_json",
        lambda llm, **kw: JudgePayload(
            dimensions=[
                JudgeDimension(name=name, score=9.0, rationale="ok")
                for name in report_judge.DIMENSIONS
            ]
        ),
    )


def test_judge_suite_with_stub(monkeypatch, capsys):
    _stub_judge_ok(monkeypatch)
    code = runner.main(["--suite", "judge", "--no-save"])
    assert code == 0
    assert "publishable" in capsys.readouterr().out


def test_all_suite_runs_both(monkeypatch, capsys):
    _stub_judge_ok(monkeypatch)
    code = runner.main(["--suite", "all", "--no-save"])
    assert code == 0
    out = capsys.readouterr().out
    assert "precision" in out and "publishable" in out


def test_threshold_breach_exits_nonzero(monkeypatch):
    from evals import guardrails_eval

    real_run = guardrails_eval.run

    def failing_run():
        r = real_run()
        r.precision = 0.5
        return r

    monkeypatch.setattr(guardrails_eval, "run", failing_run)
    assert runner.main(["--suite", "guardrails", "--no-save"]) == 1


def test_judge_error_suite_still_succeeds_for_reporting(monkeypatch, capsys):
    """A judge error is a result, not a runner crash — suite exits 0 with verdict shown."""
    from evals import report_judge

    def failing_judge(report):
        return JudgeResult(verdict="error", error="stubbed failure")

    monkeypatch.setattr(report_judge, "judge_report", failing_judge)
    code = runner.main(["--suite", "judge", "--no-save"])
    assert code == 0
    assert "Judge failed" in capsys.readouterr().out

"""
Eval runner CLI — `python -m evals.runner --suite guardrails|judge|all`.

- guardrails: offline confusion matrix + precision/recall; exits 1 when the
  configured thresholds are breached (mirrors the CI gate for local use).
- judge: LLM-as-judge on the golden report fixture, or a real stored report
  with --report-id.
- both: results printed and persisted to data/evals/ (disable with --no-save).
"""

from __future__ import annotations

import argparse
import sys

from evals import results
from evals import guardrails_eval
from evals.guardrails_eval import format_report
from evals.report_judge import format_report as format_judge
from evals.report_judge import judge_report
from utils.config import settings


def _load_report(report_id: str | None) -> dict:
    """Golden fixture by default; a stored report with --report-id."""
    if not report_id:
        from pathlib import Path

        path = Path(__file__).parent / "datasets" / "golden_report.json"
        import json

        return json.loads(path.read_text())

    from store import db

    stored = db.get_brief(report_id)
    if not stored:
        raise SystemExit(f"report '{report_id}' not found")
    return stored.get("report_json") or {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.runner", description="CortexResearch eval harness")
    parser.add_argument("--suite", choices=["guardrails", "judge", "all"], default="all")
    parser.add_argument("--report-id", default=None, help="judge a stored report instead of the golden fixture")
    parser.add_argument("--no-save", action="store_true", help="skip writing result files to data/evals/")
    args = parser.parse_args(argv)

    exit_code = 0

    if args.suite in ("guardrails", "all"):
        result = guardrails_eval.run()
        print(format_report(result))
        if (
            result.precision < settings.evals_guardrail_min_precision
            or result.recall < settings.evals_guardrail_min_recall
        ):
            print(
                f"THRESHOLD BREACH: precision/recall below "
                f"({settings.evals_guardrail_min_precision}/{settings.evals_guardrail_min_recall})",
                file=sys.stderr,
            )
            exit_code = 1
        if not args.no_save:
            path = results.save(result, "guardrails")
            print(f"saved → {path}")

    if args.suite in ("judge", "all"):
        report = _load_report(args.report_id)
        judged = judge_report(report)
        print(format_judge(judged))
        if not args.no_save:
            path = results.save(judged, "judge")
            print(f"saved → {path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

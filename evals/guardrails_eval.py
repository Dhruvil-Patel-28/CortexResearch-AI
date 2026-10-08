"""
Guardrail eval — precision/recall over the deliberate attack corpus.

Imports the same corpus file the fixture tests use, so metrics and tests can
never drift apart. Runs fully offline and deterministically; the threshold
assertions in tests/test_guardrails_eval.py are the CI regression gate for the
Phase 2 scanner.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from guardrails.injection import scan

CORPUS_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "injection_corpus.json"


class GuardrailEvalResult(BaseModel):
    confusion: dict[str, int] = Field(default_factory=dict)  # tp, fp, tn, fn
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    per_category: dict[str, dict[str, int]] = Field(default_factory=dict)
    action_correct: int = 0
    action_total: int = 0


def _load_corpus() -> tuple[list[dict], list[dict]]:
    corpus = json.loads(CORPUS_PATH.read_text())
    return corpus["attacks"], corpus["benign"]


def run() -> GuardrailEvalResult:
    """Score the injection scanner against the corpus. Never raises."""
    attacks, benign = _load_corpus()

    tp = fp = tn = fn = 0
    action_correct = action_total = 0
    per_category: dict[str, dict[str, int]] = {}

    for entry in attacks:
        report = scan(entry["text"])
        caught = len(report.findings) > 0
        tp += caught
        fn += not caught

        expect = entry["expect"]
        action_total += 1
        if report.action == expect["action"]:
            action_correct += 1

        for category in set(expect.get("categories", [])):
            stats = per_category.setdefault(category, {"total": 0, "caught": 0})
            stats["total"] += 1
            stats["caught"] += any(f["category"] == category for f in report.findings)

    for entry in benign:
        report = scan(entry["text"])
        flagged = len(report.findings) > 0
        fp += flagged
        tn += not flagged

        expect = entry["expect"]
        action_total += 1
        if report.action == expect["action"]:
            action_correct += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return GuardrailEvalResult(
        confusion={"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        per_category=per_category,
        action_correct=action_correct,
        action_total=action_total,
    )


def format_report(result: GuardrailEvalResult) -> str:
    """Human-readable confusion matrix + metrics for the CLI runner."""
    c = result.confusion
    lines = [
        "Guardrail eval — injection scanner vs corpus",
        f"  attacks: {c['tp'] + c['fn']} (caught {c['tp']}, missed {c['fn']})",
        f"  benign:  {c['tn'] + c['fp']} (passed {c['tn']}, flagged {c['fp']})",
        f"  precision={result.precision:.3f} recall={result.recall:.3f} f1={result.f1:.3f}",
        f"  action correctness: {result.action_correct}/{result.action_total}",
        "  per category:",
    ]
    for category, stats in sorted(result.per_category.items()):
        lines.append(f"    {category}: {stats['caught']}/{stats['total']} caught")
    return "\n".join(lines)

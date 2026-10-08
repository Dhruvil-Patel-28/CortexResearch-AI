"""
Eval result models + persistence.

`JudgeResult` / `JudgeDimension` are shared by the judge, the CLI runner and
the Langfuse export. Results persist to `data/evals/` (gitignored output):
`save()` appends a timestamped JSON file, `latest(suite)` loads the most
recent one.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel, Field

RESULTS_DIR = Path("data/evals")


class JudgeDimension(BaseModel):
    """One rubric dimension, scored 0-10 with a one-line rationale."""

    name: str
    score: float
    rationale: str = ""


class JudgeResult(BaseModel):
    """Full LLM-as-judge verdict on one report."""

    dimensions: list[JudgeDimension] = Field(default_factory=list)
    weighted_score: float = 0.0
    verdict: str = "needs-review"  # publishable | needs-review | error
    facts: dict = Field(default_factory=dict, description="Deterministic facts computed in Python (section presence, citation counts)")
    model: str = ""
    cost_usd: float = 0.0
    judged_at: float = Field(default_factory=time.time)
    report_title: str = ""
    error: str = ""


def save(result: BaseModel, suite: str) -> Path:
    """Persist a result as data/evals/<ts>-<suite>.json. Returns the path."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{int(time.time())}-{suite}.json"
    path.write_text(json.dumps(result.model_dump(), indent=2, default=str))
    return path


def latest(suite: str) -> dict | None:
    """Most recent persisted result for a suite, or None."""
    if not RESULTS_DIR.exists():
        return None
    candidates = sorted(RESULTS_DIR.glob(f"*-{suite}.json"))
    if not candidates:
        return None
    return json.loads(candidates[-1].read_text())

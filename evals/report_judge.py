"""
LLM-as-judge — structured rubric scoring of published reports.

Four dimensions (0-10, one-line rationale each): groundedness, coverage,
coherence, citation_hygiene. Groundedness is weighted 2x in the overall score.

Design rules:
- Deterministic facts (section presence, citation counts) are computed in
  Python first and handed to the judge — the LLM judges quality, not arithmetic.
- One structured-output call via utils.llm_json.call_json on the fast tier.
- "Score only, never rewrite" — the judge never produces report text.
- Any failure degrades to verdict="error"; judging never raises.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from evals.results import JudgeDimension, JudgeResult
from schemas.report import ResearchReportV2, coerce_report
from utils.config import settings
from utils.cost import CostMeter
from utils.llm import LLMClient
from utils.llm_json import call_json

logger = logging.getLogger(__name__)

DIMENSIONS = ["groundedness", "coverage", "coherence", "citation_hygiene"]
PUBLISH_THRESHOLD = 8.0


class JudgePayload(BaseModel):
    """Structured judge response schema."""

    dimensions: list[JudgeDimension] = Field(default_factory=list)

_DIMENSION_GUIDES = {
    "groundedness": "Are the key_developments claims actually supported by their cited sources? Spot-check at least three developments against their source quotes/urls.",
    "coverage": "Does the report fill the schema-v2 sections appropriate for its depth (tldr, executive_summary, background_primer, key_developments, implications, sources)? Penalise thin or empty sections for the stated depth.",
    "coherence": "Does it read as one coherent analysis rather than stitched-together snippets? Contradictions between sections are the main failure.",
    "citation_hygiene": "Does every key development cite at least one source? Are all cited ids resolvable in sources? (The deterministic facts below give exact counts.)",
}

def compute_facts(report: ResearchReportV2) -> dict:
    """Deterministic facts the judge receives as ground truth."""
    source_ids = {s.id for s in report.sources}
    developments_without_sources = sum(
        1 for d in report.key_developments if not d.sources
    )
    dangling_refs = sum(
        1
        for d in report.key_developments
        for sid in d.sources
        if sid not in source_ids
    )
    depth = report.depth
    expected_sections = {"tldr", "executive_summary", "key_developments", "sources"}
    if depth in ("standard", "deep"):
        expected_sections |= {"background_primer", "implications", "what_to_watch_next"}
    section_state = {
        "has_tldr": len(report.tldr) > 0,
        "has_executive_summary": bool(report.executive_summary.strip()),
        "has_background_primer": bool(report.background_primer.strip()),
        "has_implications": bool(report.implications.strip()),
    }
    missing = [
        name
        for name in sorted(expected_sections)
        if name == "tldr" and not section_state["has_tldr"]
        or name == "executive_summary" and not section_state["has_executive_summary"]
        or name == "background_primer" and not section_state["has_background_primer"]
        or name == "implications" and not section_state["has_implications"]
        or name == "key_developments" and not report.key_developments
        or name == "sources" and not report.sources
        or name == "what_to_watch_next" and not report.what_to_watch_next
    ]
    return {
        "depth": depth,
        "key_developments": len(report.key_developments),
        "sources": len(report.sources),
        "developments_without_sources": developments_without_sources,
        "dangling_source_refs": dangling_refs,
        "verification_supported": report.verification.supported,
        "verification_unsupported": report.verification.unsupported,
        "missing_sections": missing,
        **section_state,
    }


def _build_user_prompt(report: ResearchReportV2, facts: dict) -> str:
    guides = "\n".join(f"- {name}: {_DIMENSION_GUIDES[name]}" for name in DIMENSIONS)
    return f"""Deterministic facts (computed by code — trust these over your own counting):
{json.dumps(facts, indent=2)}

Score each dimension 0-10 with a one-line rationale.

Dimension guides:
{guides}

Respond with exactly these dimension names: {", ".join(DIMENSIONS)}

Report:
---
{report.model_dump_json(exclude={"model_trace", "verification", "cost_usd", "created_at"})}
---"""


def _weighted(dimensions: list[JudgeDimension]) -> float:
    """Groundedness counts double: (2*g + c + co + ch) / 5."""
    scores = {d.name: d.score for d in dimensions}
    g = scores.get("groundedness", 0.0)
    rest = sum(scores.get(n, 0.0) for n in DIMENSIONS if n != "groundedness")
    return round((2 * g + rest) / 5.0, 2)


JUDGE_SYSTEM = (
    "You are a strict but fair report-quality judge. Score the research report "
    "against the given rubric. Score ONLY — never rewrite the report. Respond "
    "with JSON matching the schema exactly."
)


def judge_report(report: dict | ResearchReportV2) -> JudgeResult:
    """Score one report. Never raises — failures become verdict="error"."""
    meter = CostMeter()
    try:
        if isinstance(report, dict):
            report = coerce_report(report, keep_verification=True)
        if not (report.key_developments or report.sources or report.executive_summary.strip()):
            raise ValueError("report has no developments, sources, or summary — nothing to judge")
        facts = compute_facts(report)

        model = settings.evals_judge_model or settings.model_fast
        llm = LLMClient(model, 0.0, settings.max_tokens_fast)
        payload = call_json(
            llm,
            system=JUDGE_SYSTEM,
            user=_build_user_prompt(report, facts),
            schema=JudgePayload,
            meter=meter,
            label="eval:report-judge",
        )
        dimensions = [
            d for d in payload.dimensions if d.name in DIMENSIONS
        ]
        if len(dimensions) < len(DIMENSIONS):
            raise ValueError(f"judge returned {len(dimensions)}/{len(DIMENSIONS)} valid dimensions")

        weighted = _weighted(dimensions)
        verdict = "publishable" if weighted >= PUBLISH_THRESHOLD else "needs-review"
        return JudgeResult(
            dimensions=dimensions,
            weighted_score=weighted,
            verdict=verdict,
            facts=facts,
            model=model,
            cost_usd=meter.total_usd,
            report_title=report.title,
        )
    except Exception as exc:  # noqa: BLE001 — judging must never crash the caller
        logger.warning("Report judging failed: %s", exc)
        return JudgeResult(verdict="error", error=str(exc))


def format_report(result: JudgeResult) -> str:
    """Human-readable judge summary for the CLI runner."""
    if result.verdict == "error":
        return f"Judge failed: {result.error}"
    lines = [
        f"Report: {result.report_title or '(untitled)'}",
        f"Verdict: {result.verdict} (weighted {result.weighted_score:.1f}/10, model={result.model})",
    ]
    for d in result.dimensions:
        lines.append(f"  {d.name}: {d.score:.1f}/10 — {d.rationale}")
    return "\n".join(lines)

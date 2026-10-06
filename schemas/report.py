"""
Report Schema v2 — the "no manual follow-up" contract.

A deep brief is only considered finished when it validates against
`ResearchReportV2`. The pipeline degrades gracefully (`coerce_report` fills
gaps) instead of crashing on a missing field, but the shape is always the
same, which is what lets the reader UI render every report identically and
what makes claim-level verification possible.

Keep this module pydantic-only (no app imports) so agents, the store, the API
and the exporters can all import it without cycles.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

logger = logging.getLogger(__name__)

Depth = Literal["brief", "standard", "deep"]
Confidence = Literal["high", "medium", "low"]
SourceKind = Literal["web", "paper", "forum", "repo", "rss", "knowledge_base", "product", "other"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_str_list(value: Any) -> list[str]:
    """Accept a string, a list of strings, or a list of {text: ...} objects."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        value = [value]
    out: list[str] = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                out.append(entry.strip())
            elif isinstance(entry, dict):
                for key in ("text", "point", "item", "question", "title", "value"):
                    if isinstance(entry.get(key), str) and entry[key].strip():
                        out.append(entry[key].strip())
                        break
    return out


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n\n".join(_as_str_list(value))
    if isinstance(value, dict):
        return "\n\n".join(f"**{k.replace('_', ' ').title()}**: {_as_str(v)}" for k, v in value.items())
    return str(value).strip()


# Models rarely stick to the exact field names we ask for. Rather than failing
# validation (and losing a whole report), the first present alias wins.
CLAIM_ALIASES = ("claim", "headline", "finding", "statement", "development", "title", "point")
EVIDENCE_ALIASES = ("evidence", "detail", "details", "explanation", "supporting_evidence", "support", "body", "context")
SOURCE_ALIASES = ("sources", "citations", "source_ids", "source_id", "refs", "references")
CONFIDENCE_ALIASES = ("confidence", "certainty", "confidence_level")

REPORT_ALIASES: dict[str, tuple[str, ...]] = {
    "executive_summary": ("executive_summary", "summary", "overview"),
    "tldr": ("tldr", "tl_dr", "takeaways", "key_takeaways", "highlights"),
    "background_primer": ("background_primer", "background", "primer", "introduction"),
    "key_developments": ("key_developments", "developments", "findings", "key_findings"),
    "technical_explainer": ("technical_explainer", "how_it_works", "technical_details", "technical_breakdown"),
    "implications": ("implications", "why_it_matters", "so_what", "significance", "impact"),
    "risks_and_uncertainty": (
        "risks_and_uncertainty", "risks", "uncertainty", "uncertainties", "caveats", "limitations",
    ),
    "what_to_watch_next": ("what_to_watch_next", "next_steps", "whats_next", "watch_next", "signals_to_watch"),
    "open_questions": ("open_questions", "unanswered_questions", "open_issues"),
    "faq": ("faq", "faqs", "questions_and_answers"),
    "glossary": ("glossary", "terms", "jargon", "key_terms"),
    "timeline": ("timeline", "chronology"),
    "comparison_table": ("comparison_table", "comparison", "comparisons", "table"),
}

_SCALAR_FIELDS = (
    "title", "tldr", "executive_summary", "background_primer", "technical_explainer",
    "implications", "risks_and_uncertainty", "what_to_watch_next", "open_questions",
)


def _remap(data: dict[str, Any], aliases: tuple[str, ...], target: str) -> None:
    """Move the first present alias onto `target` unless the target is already set."""
    if data.get(target) not in (None, "", [], {}):
        return
    for alias in aliases:
        if alias == target:
            continue
        value = data.get(alias)
        if value not in (None, "", [], {}):
            data[target] = value
            return


def _apply_report_aliases(raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    for target, aliases in REPORT_ALIASES.items():
        _remap(data, aliases, target)
    return data


def _safe_list(raw: Any, model: type[BaseModel]) -> list[Any]:
    """Validate list entries one by one, skipping the ones that do not fit."""
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: list[Any] = []
    for entry in raw:
        try:
            out.append(model.model_validate(entry))
        except ValidationError:
            continue
    return out


class Source(BaseModel):
    """One citable source. `id` (e.g. "s3") is what claims reference."""

    id: str
    title: str = "Untitled source"
    url: str = ""
    kind: SourceKind = "web"
    published_at: Optional[str] = None
    quote: str = ""

    @field_validator("title", "url", "quote", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return _as_str(v)

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v: Any) -> str:
        v = (v or "web").lower().strip() if isinstance(v, str) else "web"
        aliases = {
            "arxiv": "paper",
            "hackernews": "forum",
            "github": "repo",
            "blog": "rss",
            "news": "rss",
            "docs": "web",
            "web_search": "web",
            "rss": "rss",
            "producthunt": "product",
            "reddit": "forum",
        }
        v = aliases.get(v, v)
        allowed = {"web", "paper", "forum", "repo", "rss", "knowledge_base", "product", "other"}
        return v if v in allowed else "other"


class KeyDevelopment(BaseModel):
    """A single load-bearing finding. Must carry at least one source id."""

    claim: str = ""
    evidence: str = ""
    sources: list[str] = Field(default_factory=list, description="Source ids backing this claim")
    confidence: Confidence = "medium"

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> Any:
        """Accept the field-name drift models produce (headline/finding/detail...)."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        _remap(data, CLAIM_ALIASES, "claim")
        _remap(data, EVIDENCE_ALIASES, "evidence")
        _remap(data, SOURCE_ALIASES, "sources")
        _remap(data, CONFIDENCE_ALIASES, "confidence")
        return {k: v for k, v in data.items() if k in {"claim", "evidence", "sources", "confidence"}}

    @field_validator("claim", "evidence", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return _as_str(v)

    @field_validator("sources", mode="before")
    @classmethod
    def _sources(cls, v: Any) -> list[str]:
        return _as_str_list(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v: Any) -> str:
        v = v.lower().strip() if isinstance(v, str) else "medium"
        return v if v in {"high", "medium", "low"} else "medium"


class TimelineEntry(BaseModel):
    when: str = ""
    what: str = ""
    source_id: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        _remap(data, ("when", "date", "period", "time"), "when")
        _remap(data, ("what", "event", "description", "detail"), "what")
        _remap(data, ("source_id", "source", "sources", "citation"), "source_id")
        return data

    @field_validator("when", "what", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return _as_str(v)

    @field_validator("source_id", mode="before")
    @classmethod
    def _single_source(cls, v: Any) -> Optional[str]:
        if isinstance(v, list):
            v = v[0] if v else None
        return _as_str(v) or None


class ComparisonTable(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)

    @field_validator("columns", mode="before")
    @classmethod
    def _cols(cls, v: Any) -> list[str]:
        return _as_str_list(v)

    @field_validator("rows", mode="before")
    @classmethod
    def _rows(cls, v: Any) -> list[list[str]]:
        if not isinstance(v, list):
            return []
        out: list[list[str]] = []
        for row in v:
            if isinstance(row, dict):
                out.append([_as_str(row.get(c, "")) for c in row.keys()])
            elif isinstance(row, list):
                out.append([_as_str(cell) for cell in row])
        return out


class FAQItem(BaseModel):
    question: str = ""
    answer: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        _remap(data, ("question", "q", "title"), "question")
        _remap(data, ("answer", "a", "response"), "answer")
        return data

    @field_validator("question", "answer", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return _as_str(v)


class GlossaryTerm(BaseModel):
    term: str = ""
    definition: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        _remap(data, ("term", "name", "word"), "term")
        _remap(data, ("definition", "meaning", "explanation", "description"), "definition")
        return data

    @field_validator("term", "definition", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return _as_str(v)


class UnsupportedClaim(BaseModel):
    claim: str = ""
    reason: str = ""
    action: Literal["flagged", "softened", "removed"] = "flagged"

    @field_validator("claim", "reason", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return _as_str(v)


class Verification(BaseModel):
    """Claim-level citation check, produced by the verifier agent."""

    checked: int = 0
    supported: int = 0
    unsupported: int = 0
    unsupported_claims: list[UnsupportedClaim] = Field(default_factory=list)
    notes: str = ""


class ResearchReportV2(BaseModel):
    """The full deep-brief contract."""

    query: str = ""
    title: str = "Research Report"
    depth: Depth = "standard"
    tldr: list[str] = Field(default_factory=list, description="Up to 5 one-line takeaways")
    executive_summary: str = ""
    background_primer: str = Field(default="", description="Zero-prior-knowledge context")

    key_developments: list[KeyDevelopment] = Field(default_factory=list)
    technical_explainer: str = ""
    timeline: list[TimelineEntry] = Field(default_factory=list)
    comparison_table: Optional[ComparisonTable] = None

    implications: str = Field(default="", description="Why this matters to you specifically")
    risks_and_uncertainty: str = ""
    what_to_watch_next: list[str] = Field(default_factory=list)

    faq: list[FAQItem] = Field(default_factory=list)
    glossary: list[GlossaryTerm] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    sources: list[Source] = Field(default_factory=list)
    verification: Verification = Field(default_factory=Verification)

    reading_time_min: int = 1
    model_trace: list[dict[str, Any]] = Field(default_factory=list)
    cost_usd: float = 0.0
    created_at: str = Field(default_factory=_utc_now)

    @field_validator("title", "query", "executive_summary", "background_primer", "technical_explainer",
                     "implications", "risks_and_uncertainty", mode="before")
    @classmethod
    def _clean_text(cls, v: Any) -> str:
        return _as_str(v)

    @field_validator("tldr", "what_to_watch_next", "open_questions", mode="before")
    @classmethod
    def _clean_lists(cls, v: Any) -> list[str]:
        return _as_str_list(v)

    @field_validator("tldr", mode="after")
    @classmethod
    def _cap_tldr(cls, v: list[str]) -> list[str]:
        return v[:5]

    @field_validator("key_developments", "timeline", "faq", "glossary", "sources", mode="before")
    @classmethod
    def _wrap_single(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return [v]
        return v or []

    def source_map(self) -> dict[str, Source]:
        return {s.id: s for s in self.sources}

    def markdown(self) -> str:
        """Full editorial rendering (also used by the PDF exporter)."""
        from reports.markdown import render_markdown

        return render_markdown(self)


def coerce_report(
    raw: dict[str, Any],
    *,
    query: str = "",
    depth: str = "standard",
    keep_verification: bool = False,
) -> ResearchReportV2:
    """
    Build a valid report from partially-shaped LLM output.

    Missing sections become empty rather than fatal, so a slightly malformed
    model response still produces a readable, schema-valid report.

    `verification` is dropped unless `keep_verification=True`: the model is
    never trusted to grade its own citations. Only the pipeline (which computes
    claim-level verdicts from the real evidence) may set it.
    """
    data = _apply_report_aliases(dict(raw or {}))
    if not keep_verification:
        data.pop("verification", None)
    data.setdefault("query", query)
    data.setdefault("depth", depth if depth in {"brief", "standard", "deep"} else "standard")

    try:
        report = ResearchReportV2.model_validate(data)
    except ValidationError as exc:
        logger.warning("Report payload did not validate (%s) — salvaging what is usable", exc)
        report = _salvage(data)

    if not report.title.strip():
        report.title = f"Research Report: {query}" if query else "Research Report"
    if not report.tldr and report.executive_summary:
        report.tldr = [s.strip() for s in report.executive_summary.split("\n") if s.strip()][:5]
    return report


def _salvage(data: dict[str, Any]) -> ResearchReportV2:
    """
    Last-resort recovery: keep every section that validates on its own.

    A single malformed entry must never cost the reader the whole report, so
    structured lists are validated entry by entry and dropped individually.
    """
    scalars = {k: data[k] for k in _SCALAR_FIELDS if k in data}
    report = ResearchReportV2.model_validate(scalars)
    report.key_developments = [d for d in _safe_list(data.get("key_developments"), KeyDevelopment) if d.claim.strip()]
    report.timeline = _safe_list(data.get("timeline"), TimelineEntry)
    report.faq = _safe_list(data.get("faq"), FAQItem)
    report.glossary = _safe_list(data.get("glossary"), GlossaryTerm)
    report.sources = _safe_list(data.get("sources"), Source)
    if isinstance(data.get("comparison_table"), dict):
        try:
            report.comparison_table = ComparisonTable.model_validate(data["comparison_table"])
        except ValidationError:
            report.comparison_table = None
    return report


def estimate_reading_time(word_count: int) -> int:
    """Reading time in whole minutes (~220 wpm, minimum 1)."""
    return max(1, round(word_count / 220))

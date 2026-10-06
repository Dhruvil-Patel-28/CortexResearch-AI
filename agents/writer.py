"""
Writer agent — produces the Report Schema v2 deep brief.

Two passes share one implementation:

* `writer_node`   — drafts the report from the evidence
* `reviser_node`  — repairs claims the verifier could not support

Anti-hallucination measure: the `sources` array is **never** taken from the
model. It is attached from the researcher's `SourceRegistry`, so every URL in a
report is one that was actually fetched. Claims may only reference registered
source ids, and unknown ids are stripped before the report is persisted.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.events import emit_event
from agents.state import ResearchState
from schemas.report import ResearchReportV2, coerce_report, estimate_reading_time
from utils.cost import CostMeter, invoke_llm
from utils.llm import get_llm
from utils.llm_json import JsonCallError, json_object_from

logger = logging.getLogger(__name__)

DEPTH_TARGET_WORDS = {"brief": "700-1000", "standard": "1600-2400", "deep": "2600-3600"}

WRITER_SYSTEM = """You are the Writer of an autonomous research team.

You turn gathered evidence into a report the reader will not have to follow up
on: they should finish it understanding the topic, the current state of play,
what it means for them, and what remains uncertain.

Non-negotiable rules:
1. NEVER invent facts, URLs, numbers, dates, quotes, product names or versions.
   Everything must come from the EVIDENCE block.
2. Every entry in key_developments MUST cite at least one source id from the
   evidence (e.g. "s3"). Prefer 2-3 ids when they agree.
3. If the evidence does not support something the reader would want to know,
   say so explicitly in risks_and_uncertainty or open_questions instead of
   guessing. Honest gaps are more valuable than confident filler.
4. Explain jargon the first time it appears, then define it in glossary.
5. Be specific and concrete: name the product, the version, the number, the date.
6. Write for a technically literate reader who is NOT a specialist in this
   exact topic. Assume zero prior knowledge in background_primer.
7. Markdown is allowed inside text fields (bold, bullet lists). Do NOT use
   markdown headings or code fences inside a field.
8. Read the READER PROFILE: implications, and the framing of the whole report,
   must answer "why does this matter to me?".
9. Include every key of the schema. If a section genuinely does not apply,
   return an empty list rather than omitting the key — especially faq,
   glossary, timeline and what_to_watch_next, which the reader expects.
"""

WRITER_HINT = """{
  "title": "specific, informative report title",
  "tldr": ["up to 5 single-sentence takeaways, most important first"],
  "executive_summary": "3-6 short paragraphs: what happened, why now, what it changes",
  "background_primer": "what a newcomer needs to know first: concepts, players, history. Assume zero prior knowledge.",
  "key_developments": [
    {"claim": "one load-bearing factual statement", "evidence": "the supporting detail from the sources",
     "sources": ["s1", "s4"], "confidence": "high|medium|low"}
  ],
  "technical_explainer": "how it actually works / what is technically new, in plain language",
  "timeline": [{"when": "date or period", "what": "what happened", "source_id": "s2"}],
  "comparison_table": {"columns": ["Option", "What it is", "Strengths", "Weaknesses", "Best for"], "rows": [["..."]]},
  "implications": "why this matters — be personal to the reader and concrete about consequences",
  "risks_and_uncertainty": "what could be wrong, what is unverified, conflicting sources, what would change the picture",
  "what_to_watch_next": ["specific signals to monitor, with dates or triggers where known"],
  "faq": [{"question": "the question the reader would ask next", "answer": "direct, evidence-based answer"}],
  "glossary": [{"term": "jargon term", "definition": "plain-language definition"}],
  "open_questions": ["what remains genuinely unknown or unresolved"]
}"""


def writer_node(state: ResearchState) -> dict:
    """Draft the report from the gathered evidence."""
    emit_event(state, "stage", stage="writing", label="Writing the report", pct=58)
    report = _generate(state, revise=False)
    emit_event(state, "stage", stage="written", label=f"Draft ready — {report.reading_time_min} min read", pct=72)

    step = {
        "agent_name": "Writer",
        "action": f"Drafted a {report.depth} report ({report.reading_time_min} min read, {len(report.key_developments)} key developments)",
        "tools_used": ["ReportWriter"],
        "title": report.title,
    }
    return {
        "report_draft": report.model_dump(),
        "completed_agents": ["Writer"],
        "agent_steps": [step],
    }


def reviser_node(state: ResearchState) -> dict:
    """Repair unsupported claims, or pass the draft through when it is clean."""
    draft = state.get("report_draft") or {}
    verification = state.get("verification") or {}
    unsupported = verification.get("unsupported_claims") or []

    if not draft:
        fallback = coerce_report({}, query=state.get("research_query", ""), depth=state.get("depth", "standard"))
        return {"report": fallback.model_dump(), "agent_steps": [
            {"agent_name": "Reviser", "action": "No draft available — emitted an empty schema-valid report", "tools_used": []}
        ]}

    if not unsupported:
        emit_event(state, "stage", stage="verified", label="All claims supported — no revision needed", pct=92)
        return {
            "report": draft,
            "agent_steps": [
                {"agent_name": "Reviser", "action": "Verification clean — draft published unchanged", "tools_used": []}
            ],
        }

    emit_event(
        state,
        "stage",
        stage="revising",
        label=f"Repairing {len(unsupported)} unsupported claim(s)",
        pct=88,
    )
    revised = _generate(state, revise=True, draft=draft, unsupported=unsupported)
    revised.verification = _final_verification(revised, verification)

    step = {
        "agent_name": "Reviser",
        "action": f"Revised the report after verification flagged {len(unsupported)} unsupported claim(s)",
        "tools_used": ["ReportWriter"],
    }
    emit_event(state, "stage", stage="verified", label="Report revised and verified", pct=95)
    return {"report": revised.model_dump(), "agent_steps": [step]}


def _generate(
    state: ResearchState,
    *,
    revise: bool,
    draft: dict[str, Any] | None = None,
    unsupported: list[dict] | None = None,
) -> ResearchReportV2:
    """Call the writer model and return a schema-valid report."""
    query = (state.get("research_query") or "").strip()
    depth = state.get("depth") or "standard"
    plan = state.get("research_plan") or {}
    evidence = state.get("research_data") or ""
    registry = state.get("source_registry") or []
    meter: CostMeter | None = state.get("meter")

    valid_ids = {s.get("id") for s in registry}
    source_block = "\n".join(
        f"[{s.get('id')}] {s.get('title')} — {s.get('url') or 'no url'} "
        f"(kind={s.get('kind')}, published={(s.get('published_at') or 'unknown')[:10]})"
        for s in registry
    ) or "[no sources registered]"

    sub_questions = "\n".join(
        f"- {sq.get('question')}" for sq in (plan.get("sub_questions") or [])
    )
    reader_profile = _reader_profile_block()

    prompt = f"""Write the research report.

RESEARCH QUESTION
{query}

READER PROFILE
{reader_profile}

SUB-QUESTIONS THE READER EXPECTS ANSWERED
{sub_questions or '- ' + query}

TARGET LENGTH
{DEPTH_TARGET_WORDS.get(depth, DEPTH_TARGET_WORDS['standard'])} words across all text fields.

EVIDENCE (grouped by the sub-question it answers — the only facts you may use)
{evidence}

REGISTERED SOURCES (the only ids you may cite)
{source_block}

Reminder: cite source ids inside key_developments[].sources and timeline[].source_id.
Do not output a `sources` array — it is attached automatically from the registry above.
"""

    if revise and draft is not None:
        prompt += f"""

YOUR PREVIOUS DRAFT
{_compact_json(draft)}

A claim-level verifier could NOT support these claims from the evidence:
{_compact_json(unsupported)}

Rewrite the report so that:
- Each flagged claim is either removed, softened to what the evidence supports,
  or re-attributed to a source that genuinely backs it.
- Unresolved uncertainty is moved into risks_and_uncertainty (and open_questions).
- Everything else that was already supported stays as it was — do not rewrite
  the good parts.
"""

    llm = get_llm(temperature=0.35, tier="smart")
    label = "writer_revision" if revise else "writer"
    try:
        response = invoke_llm(llm, [SystemMessage(content=WRITER_SYSTEM), HumanMessage(content=prompt)], meter=meter, label=label)
        content = response.content
        if isinstance(content, list):
            content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        raw = json_object_from(str(content))
    except JsonCallError as exc:
        logger.error("Writer produced no usable JSON (%s)", exc)
        raw = {}
    except Exception as exc:  # noqa: BLE001 — LLM/network failures degrade to an empty report
        logger.error("Writer call failed: %s", exc)
        raw = {}

    report = coerce_report(raw, query=query, depth=depth)
    report.depth = depth if depth in {"brief", "standard", "deep"} else "standard"
    report.sources = [s for s in _registry_models(registry)]
    report.key_developments = [
        dev.model_copy(update={"sources": [sid for sid in dev.sources if sid in valid_ids]})
        for dev in report.key_developments
        if dev.claim.strip()
    ]
    report.timeline = [
        entry.model_copy(update={"source_id": entry.source_id if entry.source_id in valid_ids else None})
        for entry in report.timeline
    ]
    report.reading_time_min = estimate_reading_time(_word_count(report))
    return report


def _registry_models(registry: list[dict]) -> list:
    from schemas.report import Source

    return [Source.model_validate(s) for s in registry]


def _final_verification(report: ResearchReportV2, verification: dict[str, Any]) -> Verification:
    """Re-label each flagged claim: still present → flagged, gone → removed."""
    from schemas.report import UnsupportedClaim, Verification

    haystack = _compact_json(report.model_dump()).lower()
    entries: list[UnsupportedClaim] = []
    for raw in verification.get("unsupported_claims") or []:
        claim = str(raw.get("claim", ""))
        probe = claim[:80].lower().strip()
        still_there = bool(probe) and probe in haystack
        entries.append(
            UnsupportedClaim(
                claim=claim,
                reason=raw.get("reason", ""),
                action="flagged" if still_there else "removed",
            )
        )
    return Verification(
        checked=int(verification.get("checked", 0)),
        supported=max(0, int(verification.get("checked", 0)) - len(entries)),
        unsupported=len(entries),
        unsupported_claims=entries,
        notes=verification.get("notes", ""),
    )


def _reader_profile_block() -> str:
    try:
        from watch.profile import load_profile

        return load_profile().prompt_block()
    except Exception:  # noqa: BLE001 — profile is a nice-to-have here
        return "Reader: technically literate, wants depth and specifics."


def _word_count(report: ResearchReportV2) -> int:
    text = " ".join(
        [
            report.executive_summary,
            report.background_primer,
            report.technical_explainer,
            report.implications,
            report.risks_and_uncertainty,
            *report.tldr,
            *report.what_to_watch_next,
            *[d.claim + " " + d.evidence for d in report.key_developments],
            *[f.question + " " + f.answer for f in report.faq],
        ]
    )
    return len(text.split())


def _compact_json(data: Any, limit: int = 18_000) -> str:
    import json

    text = json.dumps(data, ensure_ascii=False, indent=1)
    return text[:limit]

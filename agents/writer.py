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
from pydantic import BaseModel, field_validator

from agents.events import emit_event
from agents.state import ResearchState
from schemas.report import (
    ResearchReportV2,
    Verification,
    coerce_report,
    estimate_reading_time,
)
from utils.cost import CostMeter, invoke_llm
from utils.llm import get_llm
from utils.llm_json import JsonCallError, call_json, json_object_from

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
    report = _generate(state)
    if _is_empty(report):
        # One retry with a stricter instruction before giving up loudly.
        logger.warning("Writer produced an empty report — retrying once")
        report = _generate(state, strict=True)
    if _is_empty(report):
        raise RuntimeError(
            "Writer failed twice to produce report content — failing the run "
            "rather than publishing an empty report"
        )
    emit_event(
        state,
        "stage",
        stage="written",
        label=f"Draft ready — {report.reading_time_min} min read",
        pct=72,
    )

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
        fallback = coerce_report(
            {}, query=state.get("research_query", ""), depth=state.get("depth", "standard")
        )
        return {
            "report": fallback.model_dump(),
            "agent_steps": [
                {
                    "agent_name": "Reviser",
                    "action": "No draft available — emitted an empty schema-valid report",
                    "tools_used": [],
                }
            ],
        }

    if not unsupported:
        emit_event(
            state,
            "stage",
            stage="verified",
            label="All claims supported — no revision needed",
            pct=92,
        )
        return {
            "report": draft,
            "agent_steps": [
                {
                    "agent_name": "Reviser",
                    "action": "Verification clean — draft published unchanged",
                    "tools_used": [],
                }
            ],
        }

    emit_event(
        state,
        "stage",
        stage="revising",
        label=f"Repairing {len(unsupported)} unsupported claim(s)",
        pct=88,
    )

    # Patch-based revision: the model returns only *edits for the flagged
    # claims*, spliced into the draft locally. Re-emitting the whole report
    # used to hit the output-token cap, truncate the JSON, and (before the
    # guards below) publish an empty shell over a good draft.
    patched = _patch_draft(state, draft, unsupported)
    if patched is not None:
        revised = coerce_report(
            patched, query=state.get("research_query", ""), depth=state.get("depth", "standard")
        )
        valid_ids = {s.get("id") for s in (state.get("source_registry") or [])}
        revised.sources = list(_registry_models(state.get("source_registry") or []))
        # Invariant: no claim may survive without at least one valid citation.
        revised.key_developments = [
            dev.model_copy(update={"sources": [sid for sid in dev.sources if sid in valid_ids]})
            for dev in revised.key_developments
            if dev.claim.strip() and any(sid in valid_ids for sid in dev.sources)
        ]
        revised.depth = state.get("depth") or "standard"
        revised.reading_time_min = estimate_reading_time(_word_count(revised))
        revised.verification = _final_verification(revised, verification)

        step = {
            "agent_name": "Reviser",
            "action": f"Patched {len(unsupported)} unsupported claim(s) in place after verification",
            "tools_used": ["ReportReviser"],
        }
        emit_event(state, "stage", stage="verified", label="Report revised and verified", pct=95)
        return {"report": revised.model_dump(), "agent_steps": [step]}

    logger.warning("Patch revision unavailable — publishing the verified draft with flags")
    draft_out = dict(draft)
    valid_ids = {s.get("id") for s in (state.get("source_registry") or [])}
    # Deterministic failures are machine-checked fact: a claim with no valid
    # citation is dropped even without a model patch. Judgement-flagged claims
    # stay, labelled for the reader.
    draft_out["key_developments"] = [
        dev
        for dev in (draft.get("key_developments") or [])
        if any(sid in valid_ids for sid in (dev.get("sources") or []))
    ]
    draft_report = coerce_report(
        draft_out, query=state.get("research_query", ""), depth=state.get("depth", "standard")
    )
    draft_report.sources = list(_registry_models(state.get("source_registry") or []))
    draft_report.verification = _final_verification(draft_report, verification)
    emit_event(
        state,
        "stage",
        stage="verified",
        label="Draft published with flagged claims labelled",
        pct=95,
    )
    return {
        "report": draft_report.model_dump(),
        "agent_steps": [
            {
                "agent_name": "Reviser",
                "action": "Could not patch — kept the verified draft and labelled flagged claims",
                "tools_used": [],
            }
        ],
    }


class ClaimPatch(BaseModel):
    """One edit to apply to the draft's key_developments list."""

    index: int = -1
    action: str = "rewrite"  # "rewrite" | "remove"
    claim: str = ""
    evidence: str = ""

    @field_validator("action", mode="before")
    @classmethod
    def _action(cls, v: Any) -> str:
        return str(v or "rewrite").strip().lower()


class PatchList(BaseModel):
    revisions: list[ClaimPatch] = []


REVISER_SYSTEM = """You are the Reviser of an autonomous research team.

A verifier could not support some claims in a finished report from the sources
they cite. For each flagged claim you return ONE patch:

- action="remove": the claim goes away (nothing salvageable).
- action="rewrite": replace it with a claim the cited evidence DOES support —
  narrower, hedged, or re-attributed. Keep it specific and concise.

Return JSON only:
{"revisions": [{"index": 0, "action": "rewrite", "claim": "...", "evidence": "..."}]}
`index` is the position of the flagged claim in the numbered list you receive.
"""


def _patch_draft(
    state: ResearchState,
    draft: dict[str, Any],
    unsupported: list[dict],
) -> dict[str, Any] | None:
    """
    Return a patched copy of the draft, or None when patching is impossible.

    The model only ever sees and returns the flagged claims — never the whole
    report — so the response is tiny and cannot truncate.
    """
    developments = draft.get("key_developments") or []
    registry: dict[str, dict] = {s.get("id"): s for s in (state.get("source_registry") or [])}
    meter: CostMeter | None = state.get("meter")

    # Match each flagged claim to its position in the draft.
    flagged: list[tuple[int, dict]] = []
    for raw in unsupported:
        probe = str(raw.get("claim", "")).strip().lower()[:100]
        for i, dev in enumerate(developments):
            if str(dev.get("claim", "")).strip().lower()[:100] == probe:
                flagged.append((i, raw))
                break

    if not flagged:
        return None

    numbered = []
    for pos, (i, raw) in enumerate(flagged):
        dev = developments[i]
        cited = [sid for sid in (dev.get("sources") or []) if sid in registry]
        evidence = (
            "\n\n".join(f"[{sid}] {(registry[sid].get('quote') or '')[:600]}" for sid in cited)
            or "(no usable evidence)"
        )
        numbered.append(
            f"{pos}. draft index {i}\nCLAIM: {dev.get('claim')}\n"
            f"VERIFIER REASON: {raw.get('reason', '')}\nCITED EVIDENCE:\n{evidence}"
        )

    prompt = f"""Flagged claims from the report draft:

{chr(10).join(numbered)}

Return one patch per flagged claim, using its position as `index`."""
    try:
        patches = call_json(
            get_llm(temperature=0.2, tier="smart"),
            system=REVISER_SYSTEM,
            user=prompt,
            schema=PatchList,
            meter=meter,
            label="reviser_patch",
            schema_hint='{"revisions": [{"index": 0, "action": "rewrite", "claim": "...", "evidence": "..."}]}',
        )
    except JsonCallError as exc:
        logger.warning("Reviser patch call failed: %s", exc)
        return None

    patched_devs = [dict(dev) for dev in developments]
    valid_ids = {s.get("id") for s in (state.get("source_registry") or [])}
    for rev in patches.revisions:
        if not 0 <= rev.index < len(patched_devs):
            continue
        if rev.action == "remove":
            patched_devs[rev.index] = None  # type: ignore[assignment]
        else:
            new_claim = rev.claim.strip() or str(patched_devs[rev.index].get("claim", ""))
            patched_devs[rev.index] = {
                **patched_devs[rev.index],
                "claim": new_claim,
                "evidence": rev.evidence.strip() or patched_devs[rev.index].get("evidence", ""),
                "sources": [
                    sid for sid in patched_devs[rev.index].get("sources") or [] if sid in valid_ids
                ],
                "confidence": "revised",
            }
    return {**draft, "key_developments": [d for d in patched_devs if d]}


def _generate(
    state: ResearchState,
    *,
    strict: bool = False,
) -> ResearchReportV2:
    """Call the writer model and return a schema-valid report."""
    query = (state.get("research_query") or "").strip()
    depth = state.get("depth") or "standard"
    plan = state.get("research_plan") or {}
    evidence = state.get("research_data") or ""
    registry = state.get("source_registry") or []
    meter: CostMeter | None = state.get("meter")

    valid_ids = {s.get("id") for s in registry}
    source_block = (
        "\n".join(
            f"[{s.get('id')}] {s.get('title')} — {s.get('url') or 'no url'} "
            f"(kind={s.get('kind')}, published={(s.get('published_at') or 'unknown')[:10]})"
            for s in registry
        )
        or "[no sources registered]"
    )

    sub_questions = "\n".join(f"- {sq.get('question')}" for sq in (plan.get("sub_questions") or []))
    reader_profile = _reader_profile_block()

    prompt = f"""Write the research report.

RESEARCH QUESTION
{query}

READER PROFILE
{reader_profile}

SUB-QUESTIONS THE READER EXPECTS ANSWERED
{sub_questions or "- " + query}

TARGET LENGTH
{DEPTH_TARGET_WORDS.get(depth, DEPTH_TARGET_WORDS["standard"])} words across all text fields.

EVIDENCE (grouped by the sub-question it answers — the only facts you may use)
{evidence}

REGISTERED SOURCES (the only ids you may cite)
{source_block}

Reminder: cite source ids inside key_developments[].sources and timeline[].source_id.
Do not output a `sources` array — it is attached automatically from the registry above.
"""

    llm = get_llm(temperature=0.35, tier="smart")
    label = "writer"
    last_error: Exception | None = None
    raw: dict[str, Any] = {}
    for attempt in (1, 2):
        nudge = (
            "\n\nCRITICAL: Your previous response could not be parsed as JSON. "
            "Return ONLY the raw JSON object — start with { and end with }. "
            "No prose, no markdown fence. Keep every string value concise so the "
            "response fits in the output limit."
            if attempt == 2 or strict
            else ""
        )
        try:
            response = invoke_llm(
                llm,
                [SystemMessage(content=WRITER_SYSTEM), HumanMessage(content=prompt + nudge)],
                meter=meter,
                label=label if attempt == 1 else f"{label}_retry",
            )
            content = response.content
            if isinstance(content, list):
                content = "".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                )
            raw = json_object_from(str(content))
            break
        except JsonCallError as exc:
            last_error = exc
            logger.error("Writer produced no usable JSON (attempt %d): %s", attempt, exc)
        except Exception as exc:  # noqa: BLE001 — LLM/network failures degrade to an empty report
            last_error = exc
            logger.error("Writer call failed (attempt %d): %s", attempt, exc)
    if raw == {} and last_error is not None:
        logger.error("Writer giving up after retries: %s", last_error)

    report = coerce_report(raw, query=query, depth=depth)
    report.depth = depth if depth in {"brief", "standard", "deep"} else "standard"
    report.sources = list(_registry_models(registry))
    report.key_developments = [
        dev.model_copy(update={"sources": [sid for sid in dev.sources if sid in valid_ids]})
        for dev in report.key_developments
        if dev.claim.strip()
    ]
    report.timeline = [
        entry.model_copy(
            update={"source_id": entry.source_id if entry.source_id in valid_ids else None}
        )
        for entry in report.timeline
    ]
    report.reading_time_min = estimate_reading_time(_word_count(report))
    return report


def _registry_models(registry: list[dict]) -> list:
    from schemas.report import Source

    return [Source.model_validate(s) for s in registry]


def _is_empty(report: ResearchReportV2) -> bool:
    """True when the report carries no usable content (only the shell)."""
    return (
        not report.key_developments
        and not report.tldr
        and not report.executive_summary.strip()
        and not report.background_primer.strip()
        and not report.technical_explainer.strip()
    )


def _is_empty_report_dict(draft: dict[str, Any]) -> bool:
    return not (
        draft.get("key_developments")
        or draft.get("tldr")
        or str(draft.get("executive_summary") or "").strip()
        or str(draft.get("background_primer") or "").strip()
        or str(draft.get("technical_explainer") or "").strip()
    )


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

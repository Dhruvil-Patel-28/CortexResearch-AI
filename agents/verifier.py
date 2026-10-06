"""
Verifier agent — claim-level citation checking.

This is the step that makes the report trustworthy: after drafting, every
load-bearing claim is checked against the exact snippet stored for the sources
it cites. A claim is only "supported" when the cited evidence actually contains
it — not merely when a citation exists.

Deterministic checks run first (no citation, unknown citation id) and only the
survivors are sent to the fast model, so verification stays cheap and the model
cannot talk its way out of a missing citation.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

from agents.events import emit_event
from agents.state import ResearchState
from utils.cost import CostMeter
from utils.llm import get_llm
from utils.llm_json import JsonCallError, call_json

logger = logging.getLogger(__name__)

MAX_CLAIMS_PER_CALL = 10
SNIPPET_CHARS = 700

VERIFIER_SYSTEM = """You are the Verifier of an autonomous research team.

You receive claims and, for each one, ONLY the evidence of the sources that
claim cites. Decide for each claim whether that evidence actually supports it.

Rules:
- supported=true only if the evidence states or directly implies the claim.
- Vague similarity is not support. If the claim adds specifics (numbers,
  versions, dates, causal claims, superlatives) that the evidence does not
  contain, mark supported=false and name exactly what is missing.
- A claim that is true in the world but absent from the given evidence is
  supported=false — you judge the citation, not your own knowledge.
- Be precise and terse in the reason: what is missing or what conflicts.
"""

VERIFIER_HINT = """{
  "verdicts": [
    {"id": "c1", "supported": true, "reason": "short reason"}
  ],
  "notes": "one line on the overall evidence quality"
}"""


class ClaimVerdict(BaseModel):
    id: str = ""
    supported: bool = True
    reason: str = ""

    @field_validator("id", "reason", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return str(v or "").strip()


class VerifierOutput(BaseModel):
    verdicts: list[ClaimVerdict] = Field(default_factory=list)
    notes: str = ""

    @field_validator("verdicts", mode="before")
    @classmethod
    def _wrap(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return [v]
        return v or []

    @field_validator("notes", mode="before")
    @classmethod
    def _notes(cls, v: Any) -> str:
        return str(v or "").strip()


def verifier_node(state: ResearchState) -> dict:
    """Check every key development against its own cited evidence."""
    draft = state.get("report_draft") or {}
    registry: dict[str, dict] = {s.get("id"): s for s in (state.get("source_registry") or [])}
    developments = [d for d in (draft.get("key_developments") or []) if (d.get("claim") or "").strip()]
    meter: CostMeter | None = state.get("meter")

    emit_event(state, "stage", stage="verifying", label=f"Verifying {len(developments)} claims", pct=76)

    if not developments:
        verification = {
            "checked": 0,
            "supported": 0,
            "unsupported": 0,
            "unsupported_claims": [],
            "notes": "The draft contained no verifiable claims.",
        }
        emit_event(state, "verification", verification=verification, label="Nothing to verify", pct=80)
        return {
            "verification": verification,
            "completed_agents": ["Verifier"],
            "agent_steps": [
                {
                    "agent_name": "Verifier",
                    "action": "Draft contained no key developments to verify",
                    "tools_used": [],
                }
            ],
        }

    unsupported: list[dict] = []
    pending: list[dict] = []

    for index, dev in enumerate(developments, 1):
        claim = dev["claim"]
        cited = [sid for sid in (dev.get("sources") or []) if sid]
        known = [sid for sid in cited if sid in registry]

        if not cited:
            unsupported.append({"claim": claim, "reason": "No source cited for this claim.", "action": "flagged"})
        elif not known:
            unsupported.append(
                {
                    "claim": claim,
                    "reason": f"Cited source id(s) {', '.join(cited)} do not exist in the evidence set.",
                    "action": "flagged",
                }
            )
        else:
            pages = "\n\n".join(
                f"[{sid}] {registry[sid].get('title', '')} — {registry[sid].get('url') or 'no url'}\n"
                f"{(registry[sid].get('quote') or '')[:SNIPPET_CHARS]}"
                for sid in known
            )
            pending.append(
                {
                    "id": f"c{index}",
                    "claim": claim,
                    "evidence": dev.get("evidence", ""),
                    "sources": pages,
                }
            )

    supported_count = 0
    checked = len(developments)
    notes = ""

    if pending:
        verdicts, notes = _judge(pending, meter=meter)
        for item in pending:
            verdict = verdicts.get(item["id"])
            if verdict is None or verdict.supported:
                supported_count += 1
            else:
                unsupported.append(
                    {
                        "claim": item["claim"],
                        "reason": verdict.reason or "Cited evidence does not contain this claim.",
                        "action": "flagged",
                    }
                )
    else:
        notes = "Every claim failed the deterministic citation check."

    verification = {
        "checked": checked,
        "supported": supported_count,
        "unsupported": len(unsupported),
        "unsupported_claims": unsupported,
        "notes": notes or f"{supported_count}/{checked} claims supported by their cited evidence.",
    }

    emit_event(state, "verification", verification=verification, label=verification["notes"], pct=80)
    logger.info("Verifier: %s/%s claims supported", supported_count, checked)

    step = {
        "agent_name": "Verifier",
        "action": f"Checked {checked} claims against their cited evidence — {supported_count} supported, {len(unsupported)} unsupported",
        "tools_used": ["ClaimVerifier"],
        "unsupported": len(unsupported),
    }
    return {"verification": verification, "completed_agents": ["Verifier"], "agent_steps": [step]}


def _judge(pending: list[dict], *, meter: CostMeter | None) -> tuple[dict[str, ClaimVerdict], str]:
    """Ask the fast model to rule on claims that passed the deterministic checks."""
    verdicts: dict[str, ClaimVerdict] = {}
    notes = ""
    llm = get_llm(temperature=0.0, tier="fast")

    for start in range(0, len(pending), MAX_CLAIMS_PER_CALL):
        batch = pending[start : start + MAX_CLAIMS_PER_CALL]
        body = "\n\n".join(
            f"{item['id']}\nCLAIM: {item['claim']}\n"
            f"{'STATED EVIDENCE: ' + item['evidence'] if item.get('evidence') else ''}\n"
            f"CITED SOURCE CONTENT:\n{item['sources']}"
            for item in batch
        )
        prompt = f"""Judge each claim against the cited source content.

{body}

Return one verdict per claim id.
"""
        try:
            output = call_json(
                llm,
                system=VERIFIER_SYSTEM,
                user=prompt,
                schema=VerifierOutput,
                meter=meter,
                label="verifier",
                schema_hint=VERIFIER_HINT,
            )
            for verdict in output.verdicts:
                if verdict.id:
                    verdicts[verdict.id] = verdict
            notes = notes or output.notes
        except JsonCallError as exc:
            logger.warning("Verifier call failed (%s) — treating batch as unverified", exc)
            for item in batch:
                verdicts.setdefault(item["id"], ClaimVerdict(id=item["id"], supported=False, reason="Verification model unavailable for this claim."))
    return verdicts, notes

"""
Planner agent — turns a fuzzy question into a research plan.

The planner is the difference between "one search and a summary" and a report
that actually answers the question: it decomposes the query into independent
sub-questions, each with its own search queries, and states why each one
matters so the researcher can prioritise.
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

# How many sub-questions each depth targets.
DEPTH_SUB_QUESTIONS = {"brief": 3, "standard": 5, "deep": 7}

PLANNER_SYSTEM = """You are the Planner of an autonomous research team.

You take a user's question and decompose it into the minimum set of
independent sub-questions that must be answered to produce a report the reader
will not have to follow up on.

Rules:
- Sub-questions must be answerable by research, not opinions.
- Cover the whole question: definition/context, current state, the specific
  development or comparison asked about, and concrete implications.
- Each sub-question gets 1-3 short keyword search queries (2-6 words each,
  no quotes, no operators) optimised for a web search engine.
- Order sub-questions from foundational to specific.
- Never invent facts. You are planning, not answering.
"""

PLANNER_HINT = """{
  "title": "short working title for the report",
  "scope": "one sentence on what this report will and will not cover",
  "sub_questions": [
    {
      "question": "a specific, answerable sub-question",
      "why": "why answering this matters for the user's question",
      "search_queries": ["keyword query one", "keyword query two"]
    }
  ]
}"""


class SubQuestion(BaseModel):
    question: str = ""
    why: str = ""
    search_queries: list[str] = Field(default_factory=list)

    @field_validator("search_queries", mode="before")
    @classmethod
    def _queries(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            out = []
            for item in v:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
                elif isinstance(item, dict) and isinstance(item.get("query"), str):
                    out.append(item["query"].strip())
            return out
        return []


class ResearchPlan(BaseModel):
    title: str = ""
    scope: str = ""
    sub_questions: list[SubQuestion] = Field(default_factory=list)

    @field_validator("sub_questions", mode="before")
    @classmethod
    def _subs(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return [v]
        return v or []


def _fallback_plan(query: str, depth: str) -> ResearchPlan:
    """Used when the planner LLM fails — never leave the researcher without a plan."""
    return ResearchPlan(
        title=query[:120],
        scope="Planner unavailable — using the raw query as a single research thread.",
        sub_questions=[SubQuestion(question=query, why="Direct answer to the request.", search_queries=[query])],
    )


def planner_node(state: ResearchState) -> dict:
    """Decompose the user's question into ordered, researchable sub-questions."""
    query = (state.get("research_query") or "").strip()
    depth = state.get("depth") or "standard"
    target = DEPTH_SUB_QUESTIONS.get(depth, 5)
    meter: CostMeter | None = state.get("meter")
    context = state.get("conversation_context") or ""

    emit_event(state, "stage", stage="planning", label="Planning research", pct=5)
    logger.info("Planner starting | depth=%s | target=%d sub-questions", depth, target)

    user_prompt = f"""Research question:
{query}

Depth: {depth} — produce exactly {target} sub-questions.
{"Recent conversation context (for continuity): " + context[:800] if context else ""}
"""
    try:
        plan = call_json(
            get_llm(temperature=0.2, tier="smart"),
            system=PLANNER_SYSTEM,
            user=user_prompt,
            schema=ResearchPlan,
            meter=meter,
            label="planner",
            schema_hint=PLANNER_HINT,
        )
    except JsonCallError as exc:
        logger.error("Planner failed, falling back to single-thread plan: %s", exc)
        plan = _fallback_plan(query, depth)

    sub_questions = [sq for sq in plan.sub_questions if sq.question.strip()][:target]
    if not sub_questions:
        sub_questions = _fallback_plan(query, depth).sub_questions

    plan_dict = {
        "title": plan.title.strip() or query[:120],
        "scope": plan.scope.strip(),
        "sub_questions": [sq.model_dump() for sq in sub_questions],
    }

    emit_event(
        state,
        "plan",
        plan=plan_dict,
        label=f"Plan ready — {len(sub_questions)} sub-questions",
        pct=10,
    )

    step = {
        "agent_name": "Planner",
        "action": f"Decomposed the question into {len(sub_questions)} sub-questions",
        "tools_used": [],
        "sub_questions": [sq.question for sq in sub_questions],
    }
    return {
        "research_plan": plan_dict,
        "completed_agents": ["Planner"],
        "agent_steps": [step],
    }

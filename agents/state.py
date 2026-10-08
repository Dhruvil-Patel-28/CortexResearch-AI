"""
Shared state definition for the multi-agent research pipeline.
All agents read from and write to this state as it flows through the graph.

Flow (v2):
    Planner → Researcher → Writer → Verifier → Reviser → FINISH
"""

import operator
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage


class ResearchState(TypedDict, total=False):
    """Shared state passed between all agents in the research pipeline."""

    # Core message history (accumulated across agent steps)
    messages: Annotated[list[BaseMessage], operator.add]

    # The original user query
    research_query: str

    # Research depth: brief | standard | deep
    depth: str

    # Optional item this brief was generated from (market-pulse "Generate brief")
    item_id: str

    # Conversation context from memory (previous turns)
    conversation_context: str

    # Planner output — decomposed sub-questions and their search queries
    research_plan: dict[str, Any]

    # Evidence gathered by the Researcher (markdown, source-id attributed)
    research_data: str

    # Source registry: [{"id", "title", "url", "kind", "quote", "published_at"}]
    source_registry: list[dict[str, Any]]

    # Per-sub-question evidence bundles, for traceability in the UI
    sub_findings: list[dict[str, Any]]

    # Draft report (schema v2 dict) produced by the Writer
    report_draft: dict[str, Any]

    # Final report (schema v2 dict)
    report: dict[str, Any]

    # Claim-level verification result
    verification: dict[str, Any]

    # Analysis produced by the Analyzer agent (legacy pipeline)
    analysis: str

    # Citation information collected during research
    citations: Annotated[list[dict], operator.add]

    # Supervisor's routing decision — which agent to invoke next
    next_agent: str

    # Tracking which agents have completed their work
    completed_agents: Annotated[list[str], operator.add]

    # Execution trace for observability
    agent_steps: Annotated[list[dict], operator.add]

    # Session ID for memory
    session_id: str

    # Run cost meter (utils.cost.CostMeter) — shared across agents
    meter: Any

    # Streaming hook: emit(event_type: str, payload: dict) -> None
    emit: Callable[[str, dict], None] | None

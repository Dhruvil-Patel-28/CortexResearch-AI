"""
Shared state definition for the multi-agent research pipeline.
All agents read from and write to this state as it flows through the graph.
"""

from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
import operator


class ResearchState(TypedDict):
    """
    Shared state passed between all agents in the research pipeline.

    Flow:
        User Query → Supervisor → Researcher → Supervisor → Analyzer → Supervisor → Writer → FINISH
    """
    # Core message history (accumulated across agent steps)
    messages: Annotated[list[BaseMessage], operator.add]

    # The original user query
    research_query: str

    # Conversation context from memory (previous turns)
    conversation_context: str

    # Raw data collected by the Researcher agent
    research_data: str

    # Analysis produced by the Analyzer agent
    analysis: str

    # Final structured report from the Writer agent
    report: str

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

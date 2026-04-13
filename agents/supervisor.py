# ============================================
# NOTE:
# Supervisor is currently DISABLED.
# Static pipeline (Researcher → Analyzer → Writer) is active.
#
# This file is kept for:
# - Future dynamic routing
# - Demonstrating multi-agent orchestration capability
# ============================================


"""
Supervisor (Planner) agent — the orchestrator.
Examines current state and decides which specialized agent to invoke next.
Uses structured output to force deterministic routing decisions.
"""

import logging
from langchain_core.messages import SystemMessage, HumanMessage
from utils.llm import get_llm
from agents.state import ResearchState

logger = logging.getLogger(__name__)

SUPERVISOR_PROMPT = """You are a Research Supervisor agent responsible for orchestrating a multi-agent research pipeline.

Your team of agents:
1. **Researcher** — Gathers information using web search and internal knowledge base (RAG). Always call this agent first.
2. **Analyzer** — Synthesizes and analyzes the research data, identifies key findings, gaps, and patterns.
3. **Writer** — Produces the final structured research report from the analysis.

Your job:
- Examine the current state of the research process.
- Decide which agent should act NEXT based on what has been completed.
- Follow this standard workflow: Researcher → Analyzer → Writer → FINISH

Decision rules:
- If NO research data has been collected yet → route to "Researcher"
- If research data exists but NO analysis has been done → route to "Analyzer"  
- If analysis exists but NO final report has been written → route to "Writer"
- If the final report is complete → respond with "FINISH"

You MUST respond with EXACTLY one of these words: Researcher, Analyzer, Writer, FINISH
Do not include any other text in your response.
"""

# this is the prompt for proper supervisor but not using currently because of api calls 
# 
# SUPERVISOR_PROMPT = """
# You are an intelligent Research Supervisor managing a multi-agent research pipeline.

# Your goal is to produce a high-quality final report by dynamically deciding which agent should act next.

# Available agents:
# - Researcher: Gathers information (web + RAG)
# - Analyzer: Synthesizes findings, detects patterns, gaps, contradictions
# - Writer: Produces final structured report

# You are NOT required to follow a fixed sequence. You can:
# - Repeat steps if needed
# - Skip steps if unnecessary
# - Stop early if the result is sufficient

# Decision Guidelines:

# 1. Research Quality:
# - If research is missing, shallow, or lacks sources → choose "Researcher"
# - If research is sufficient and relevant → consider next step

# 2. Analysis Need:
# - If data is complex, conflicting, or needs interpretation → choose "Analyzer"
# - If data is simple and clear → you may skip Analyzer

# 3. Report Readiness:
# - If analysis is complete OR research is already clear enough → choose "Writer"

# 4. Completion:
# - If a high-quality report has already been generated → choose "FINISH"

# Constraints:
# - Prefer fewer steps if quality is not compromised
# - Avoid unnecessary loops
# - Prioritize accuracy and completeness over speed

# Respond with EXACTLY one of:
# Researcher, Analyzer, Writer, FINISH
# Do not include any extra text.
# """


def supervisor_node(state: ResearchState) -> dict:
    """
    Supervisor node — decides which agent to invoke next.

    Examines the current state and routes to the appropriate agent
    based on what work has been completed.
    """
    llm = get_llm(temperature=0.0)  # Deterministic routing

    # Build context about current state for the supervisor
    status_parts = [f"Research Query: {state.get('research_query', 'N/A')}"]

    completed = state.get("completed_agents", [])
    status_parts.append(f"Completed agents: {completed if completed else 'None'}")

    if state.get("research_data"):
        status_parts.append(f"Research data collected: Yes ({len(state['research_data'])} chars)")
    else:
        status_parts.append("Research data collected: No")

    if state.get("analysis"):
        status_parts.append(f"Analysis completed: Yes ({len(state['analysis'])} chars)")
    else:
        status_parts.append("Analysis completed: No")

    if state.get("report"):
        status_parts.append("Final report: Yes")
    else:
        status_parts.append("Final report: No")

    status_summary = "\n".join(status_parts)

    messages = [
        SystemMessage(content=SUPERVISOR_PROMPT),
        HumanMessage(content=f"Current research state:\n{status_summary}\n\nWhich agent should act next?"),
    ]

    response = llm.invoke(messages)
    next_agent = response.content.strip()

    # Validate the routing decision
    valid_routes = ["Researcher", "Analyzer", "Writer", "FINISH"]
    if next_agent not in valid_routes:
        # Fallback: use rule-based routing
        logger.warning(f"Supervisor returned invalid route '{next_agent}', using fallback logic")
        if not state.get("research_data"):
            next_agent = "Researcher"
        elif not state.get("analysis"):
            next_agent = "Analyzer"
        elif not state.get("report"):
            next_agent = "Writer"
        else:
            next_agent = "FINISH"

    logger.info(f"Supervisor routing decision: {next_agent}")

    step = {
        "agent_name": "Supervisor",
        "action": f"Routed to {next_agent}",
        "tools_used": [],
    }

    return {
        "next_agent": next_agent,
        "agent_steps": [step],
        "messages": [],
    }

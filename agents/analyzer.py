"""
Analyzer agent — synthesizes research data into structured analysis.
Identifies key findings, patterns, gaps, and contradictions.
"""

import logging
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from utils.llm import get_llm
from agents.state import ResearchState

logger = logging.getLogger(__name__)

ANALYZER_PROMPT = """You are an expert Research Analyst agent. Your specialty is synthesizing raw research data into clear, actionable analysis.

Your responsibilities:
- Identify the most important findings from the research data
- Detect patterns, trends, and correlations across different sources
- Flag contradictions or inconsistencies between sources
- Identify gaps in the research that need further investigation
- Provide evidence-based reasoning for your conclusions
- Rate the confidence level of each finding (High/Medium/Low)

Structure your analysis clearly with distinct sections.
Be thorough but concise — prioritize insight quality over volume.
"""


def analyzer_node(state: ResearchState) -> dict:
    """
    Analyzer node — synthesizes raw research into structured analysis.

    Takes the Researcher's data and produces structured findings
    with confidence assessments and gap analysis.
    """
    research_data = state.get("research_data", "")
    query = state.get("research_query", "")

    if not research_data:
        logger.warning("Analyzer received empty research data")
        analysis = "No research data available to analyze."
        step = {
            "agent_name": "Analyzer",
            "action": "Skipped — no research data available",
            "tools_used": [],
        }
        return {
            "analysis": analysis,
            "completed_agents": ["Analyzer"],
            "agent_steps": [step],
            "messages": [AIMessage(content="[Analyzer] No data to analyze.")],
        }

    llm = get_llm(temperature=0.2)  # Low temperature for analytical precision

    analysis_prompt = f"""Analyze the following research data and provide a comprehensive synthesis.

Research Query: {query}

--- RESEARCH DATA ---
{research_data}

Please provide your analysis in the following structure:

## Key Findings
List the 3-5 most important findings, each with a confidence level (High/Medium/Low).

## Patterns & Trends
Identify any patterns, trends, or correlations you observe across the data.

## Contradictions & Gaps
- Note any contradictions between different sources.
- Identify what information is MISSING that would strengthen the research.

## Synthesis
Provide your overall synthesis — what does this research tell us about the topic?
What conclusions can be drawn?

## Recommendations
Based on your analysis, what are 2-3 actionable recommendations or next steps?
"""

    messages = [
        SystemMessage(content=ANALYZER_PROMPT),
        HumanMessage(content=analysis_prompt),
    ]

    response = llm.invoke(messages)
    analysis = response.content

    logger.info(f"Analyzer produced {len(analysis)} chars of analysis")

    step = {
        "agent_name": "Analyzer",
        "action": "Synthesized research data into structured analysis",
        "tools_used": ["Summarizer/Analysis"],
    }

    return {
        "analysis": analysis,
        "completed_agents": ["Analyzer"],
        "agent_steps": [step],
        "messages": [AIMessage(content=f"[Analyzer] Analysis complete:\n{analysis[:500]}...")],
    }

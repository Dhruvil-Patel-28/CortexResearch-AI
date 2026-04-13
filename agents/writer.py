"""
Writer agent — generates the final structured research report.
Produces a professional, well-formatted report from the analysis.
"""

import logging
import json
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from utils.llm import get_llm
from agents.state import ResearchState

logger = logging.getLogger(__name__)

WRITER_PROMPT = """You are a Professional Research Report Writer agent.

Your job is to take analyzed research findings and produce a polished, 
structured research report that is clear, professional, and actionable.

Output format — you MUST respond with valid JSON matching this exact structure:
{
    "title": "A clear, descriptive title for the research report",
    "summary": "Executive summary — 2-3 sentences covering the core findings",
    "key_findings": ["Finding 1", "Finding 2", "Finding 3"],
    "detailed_analysis": "Comprehensive analysis section in markdown format",
    "recommendations": ["Recommendation 1", "Recommendation 2"]
}

Rules:
- The title should be specific to the research topic
- The summary should be concise but informative
- Key findings should be clear, standalone statements
- Detailed analysis should use markdown formatting (headers, bullets, bold)
- Recommendations should be actionable and specific
- Respond ONLY with the JSON object, no other text
"""


def writer_node(state: ResearchState) -> dict:
    """
    Writer node — generates the final structured research report.

    Takes the Analyzer's output and produces a formatted JSON report
    with title, summary, key findings, detailed analysis, and recommendations.
    """
    analysis = state.get("analysis", "")
    query = state.get("research_query", "")
    research_data = state.get("research_data", "")

    if not analysis:
        logger.warning("Writer received empty analysis")
        report = json.dumps({
            "title": f"Research Report: {query}",
            "summary": "Insufficient data was available to produce a complete report.",
            "key_findings": ["No findings available due to insufficient data."],
            "detailed_analysis": "The research pipeline was unable to gather sufficient data for analysis.",
            "recommendations": ["Retry the research query with more specific terms."],
        })
        step = {
            "agent_name": "Writer",
            "action": "Generated placeholder report — insufficient data",
            "tools_used": [],
        }
        return {
            "report": report,
            "completed_agents": ["Writer"],
            "agent_steps": [step],
            "messages": [AIMessage(content="[Writer] Report generated (insufficient data).")],
        }

    llm = get_llm(temperature=0.4)  # Slightly creative for good writing

    write_prompt = f"""Create a structured research report based on the following analysis.

Research Query: {query}

--- ANALYSIS ---
{analysis}

--- SUPPORTING RESEARCH DATA ---
{research_data[:3000]}

Remember: Respond ONLY with a valid JSON object matching the required structure.
"""

    messages = [
        SystemMessage(content=WRITER_PROMPT),
        HumanMessage(content=write_prompt),
    ]

    response = llm.invoke(messages)
    report_text = response.content

    # Validate JSON output
    try:
        # Try to extract JSON if the LLM wrapped it in markdown code blocks
        cleaned = report_text.strip()
        if cleaned.startswith("```"):
            # Remove markdown code block markers
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1])

        report_json = json.loads(cleaned)

        # Ensure all required fields exist
        required_fields = ["title", "summary", "key_findings", "detailed_analysis", "recommendations"]
        for field in required_fields:
            if field not in report_json:
                report_json[field] = "" if field in ["title", "summary", "detailed_analysis"] else []

        report = json.dumps(report_json)
        logger.info("Writer produced valid structured report")

    except json.JSONDecodeError:
        # Fallback: wrap the raw text in a structured format
        logger.warning("Writer output was not valid JSON — using fallback structure")
        report = json.dumps({
            "title": f"Research Report: {query}",
            "summary": report_text[:300],
            "key_findings": [report_text[:500]],
            "detailed_analysis": report_text,
            "recommendations": ["Review the detailed analysis for specific recommendations."],
        })

    step = {
        "agent_name": "Writer",
        "action": "Generated final structured research report",
        "tools_used": ["ReportGenerator"],
    }

    return {
        "report": report,
        "completed_agents": ["Writer"],
        "agent_steps": [step],
        "messages": [AIMessage(content="[Writer] Final research report generated.")],
    }

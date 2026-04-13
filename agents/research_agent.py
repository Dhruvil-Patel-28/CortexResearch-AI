# ==================================================================================================
# NOTE:
# This project supports two execution modes:
#
# 1. Dynamic Multi-Agent Flow (with Supervisor)
#    - Flexible and intelligent
#    - Higher cost and latency
#
# 2. Static Pipeline Flow (current active)
#    - Researcher → Analyzer → Writer
#    - Optimized for cost and performance
#
# The supervisor-based approach is commented out
# but can be re-enabled for complex queries.
#===================================================================================================

# Architecture of the dynamic multi-agent flow:
#     User Query → Supervisor → Researcher → Supervisor → Analyzer → Supervisor → Writer → FINISH

# ==================================================================================================



import json
import uuid
import logging
from langgraph.graph import StateGraph, END

from agents.state import ResearchState
# from agents.supervisor import supervisor_node
from agents.researcher import researcher_node
from agents.analyzer import analyzer_node
from agents.writer import writer_node
from utils.memory import session_manager

logger = logging.getLogger(__name__)


# def route_supervisor(state: ResearchState) -> str:
#     """
#     Conditional edge function — routes from Supervisor to the next agent.
#     Returns the name of the next node to execute based on Supervisor's decision.
#     """
#     next_agent = state.get("next_agent", "FINISH")

#     if next_agent == "Researcher":
#         return "researcher"
#     elif next_agent == "Analyzer":
#         return "analyzer"
#     elif next_agent == "Writer":
#         return "writer"
#     else:
#         return END

def build_static_research_graph() -> StateGraph:
    """
    Simple deterministic pipeline:
    Researcher → Analyzer → Writer → END

    Optimized for low cost and latency.
    """
    graph = StateGraph(ResearchState)

    # Add agent nodes
    graph.add_node("researcher", researcher_node)
    graph.add_node("analyzer", analyzer_node)
    graph.add_node("writer", writer_node)

    # Entry point
    graph.set_entry_point("researcher")

    # Linear flow
    graph.add_edge("researcher", "analyzer")
    graph.add_edge("analyzer", "writer")
    graph.add_edge("writer", END)

    compiled = graph.compile()
    logger.info("Simple research pipeline compiled")

    return compiled

#=================================================================================================
# def build_research_graph() -> StateGraph:
#     """
#     Build the multi-agent research pipeline graph.

#     Returns:
#         Compiled LangGraph StateGraph ready for execution.
#     """
#     graph = StateGraph(ResearchState)

#     # Add agent nodes
#     graph.add_node("supervisor", supervisor_node)
#     graph.add_node("researcher", researcher_node)
#     graph.add_node("analyzer", analyzer_node)
#     graph.add_node("writer", writer_node)

#     # Set entry point
#     graph.set_entry_point("supervisor")

#     # Supervisor routes conditionally to the next agent
#     graph.add_conditional_edges(
#         "supervisor",
#         route_supervisor,
#         {
#             "researcher": "researcher",
#             "analyzer": "analyzer",
#             "writer": "writer",
#             END: END,
#         },
#     )

#     # All worker agents route back to supervisor after completion
#     graph.add_edge("researcher", "supervisor")
#     graph.add_edge("analyzer", "supervisor")
#     graph.add_edge("writer", "supervisor")

#     compiled = graph.compile()
#     logger.info("Research pipeline graph compiled successfully")

#     return compiled
#==========================================================================================


# ===== Choose execution mode =====

# research_graph = build_research_graph()  # Dynamic (expensive)
research_graph = build_static_research_graph()  # Static (optimized)

#==========================================================================================



def run_research(query: str, session_id: str = None) -> dict:
    """
    Execute the full multi-agent research pipeline.

    Args:
        query: The research question or topic.
        session_id: Optional session ID for conversation memory.

    Returns:
        Dict containing: report, citations, agent_steps, session_id
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    logger.info(f"Starting research pipeline | session={session_id} | query={query}")

    # Get conversation context from memory
    conversation_context = session_manager.get_context(session_id)

    # Initialize the state
    initial_state = {
        "messages": [],
        "research_query": query,
        "conversation_context": conversation_context,
        "research_data": "",
        "analysis": "",
        "report": "",
        "citations": [],
        # "next_agent": "",
        "completed_agents": [],
        "agent_steps": [],
        "session_id": session_id,
    }

    try:
        # Execute the graph
        logger.info("Running in SIMPLE PIPELINE mode")
        final_state = research_graph.invoke(initial_state)
        # can add here recursion limit if looped in future

        # Parse the report
        report_data = {}
        if final_state.get("report"):
            try:
                report_data = json.loads(final_state["report"])
            except json.JSONDecodeError:
                report_data = {
                    "title": f"Research Report: {query}",
                    "summary": final_state.get("report", ""),
                    "key_findings": [],
                    "detailed_analysis": "",
                    "recommendations": [],
                }

        # Store in memory
        report_summary = report_data.get("summary", "No summary generated.")
        session_manager.add_interaction(session_id, query, report_summary)

        result = {
            "session_id": session_id,
            "report": report_data,
            "citations": final_state.get("citations", []),
            "agent_steps": final_state.get("agent_steps", []),
        }
        logger.info(f"Research pipeline completed | session={session_id} | steps={len(result['agent_steps'])}")
        return result

    except Exception as e:
        logger.error(f"Research pipeline failed: {e}", exc_info=True)
        return {
            "session_id": session_id,
            "report": {
                "title": f"Research Report: {query}",
                "summary": f"An error occurred during research: {str(e)}",
                "key_findings": ["Research pipeline encountered an error."],
                "detailed_analysis": f"Error details: {str(e)}",
                "recommendations": ["Please try again with a different query."],
            },
            "citations": [],
            "agent_steps": [],
        }

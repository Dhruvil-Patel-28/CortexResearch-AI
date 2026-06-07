"""
Researcher agent — specialized for information gathering.
Uses web search and RAG tools to collect data on the research topic.

Performance: RAG search and web search run in parallel using ThreadPoolExecutor.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from utils.llm import get_llm
from tools.web_search import web_search
from tools.rag_tool import rag_tool
from agents.state import ResearchState

logger = logging.getLogger(__name__)

RESEARCHER_PROMPT = """You are a Research Agent specialized in gathering comprehensive information.

You have access to two information sources:
1. **WebSearch** — Search the internet for real-time, up-to-date information.
2. **Retriever** — Search the internal knowledge base (document store) for relevant stored information.

Your task:
- Given a research query, use BOTH tools to gather comprehensive information.
- Always search the knowledge base first, then supplement with web search.
- Collect diverse perspectives and data points.
- Include source attribution in your findings.

Respond with a comprehensive summary of ALL information you gathered, clearly attributing each piece of information to its source.
"""


def researcher_node(state: ResearchState) -> dict:
    """
    Researcher node — gathers information using web search and RAG.

    Calls both tools IN PARALLEL and compiles the raw research data with source attribution.
    """
    query = state.get("research_query", "")
    context = state.get("conversation_context", "")
    tools_used = []

    logger.info(f"Researcher agent starting for query: {query}")

    # ── Run RAG + Web Search in parallel ──
    rag_results = ""
    web_results = ""

    def _run_rag(q):
        return rag_tool(q)

    def _run_web(q):
        return web_search(q)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_rag = executor.submit(_run_rag, query)
        future_web = executor.submit(_run_web, query)

        # Collect RAG results
        try:
            rag_results = future_rag.result(timeout=30)
            tools_used.append("RAG/KnowledgeBase")
            logger.info("RAG retrieval completed")
        except Exception as e:
            logger.error(f"RAG retrieval failed: {e}")
            rag_results = "Knowledge base search was unavailable."

        # Collect Web results
        try:
            web_results = future_web.result(timeout=30)
            tools_used.append("WebSearch")
            logger.info("Web search completed")
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            web_results = "Web search was unavailable."

    # Step 3: Use LLM to compile and organize findings
    llm = get_llm(temperature=0.3)

    compile_prompt = f"""You are a research compiler. Organize the following raw research data into a clear, comprehensive research brief.

Research Query: {query}

{"Previous conversation context: " + context if context else ""}

--- KNOWLEDGE BASE RESULTS ---
{rag_results}

--- WEB SEARCH RESULTS ---
{web_results}

Instructions:
- Combine all information into a cohesive research brief
- Preserve source attribution (document names, URLs, page numbers)
- Flag any contradictions between sources
- Note the date/recency of web sources when available
- Organize by theme or subtopic
"""

    messages = [
        SystemMessage(content=RESEARCHER_PROMPT),
        HumanMessage(content=compile_prompt),
    ]

    response = llm.invoke(messages)
    compiled_research = response.content

    # Extract citations from RAG results
    citations = _extract_citations(rag_results, web_results)

    logger.info(f"Researcher compiled {len(compiled_research)} chars of research data")

    step = {
        "agent_name": "Researcher",
        "action": "Gathered information from knowledge base and web search",
        "tools_used": tools_used,
    }

    return {
        "research_data": compiled_research,
        "citations": citations,
        "completed_agents": ["Researcher"],
        "agent_steps": [step],
        "messages": [AIMessage(content=f"[Researcher] Gathered research data:\n{compiled_research[:500]}...")],
    }


def _extract_citations(rag_results: str, web_results: str) -> list[dict]:
    """Parse tool outputs to extract structured citation information."""
    citations = []

    # Parse RAG citations
    if rag_results and "No relevant documents" not in rag_results:
        for block in rag_results.split("---"):
            block = block.strip()
            if not block:
                continue
            source = "Unknown"
            page = None
            relevance_score = None
            content = ""
            for line in block.split("\n"):
                if line.startswith("Source:"):
                    source = line.replace("Source:", "").strip()
                elif line.startswith("Page:"):
                    try:
                        page = int(line.replace("Page:", "").strip())
                    except (ValueError, TypeError):
                        page = None
                elif line.startswith("Relevance Score:"):
                    try:
                        relevance_score = float(line.replace("Relevance Score:", "").strip())
                    except (ValueError, TypeError):
                        relevance_score = None
                elif line.startswith("Content:"):
                    content = line.replace("Content:", "").strip()
                elif not line.startswith("[Document"):
                    content += " " + line.strip()

            if source != "Unknown" or content:
                citations.append({
                    "source_name": source,
                    "page_number": page,
                    "content_snippet": content[:200].strip(),
                    "relevance_score": relevance_score,
                })

    # Parse web citations
    if web_results and "No results found" not in web_results:
        for block in web_results.split("---"):
            block = block.strip()
            if not block:
                continue
            source = "Web Source"
            content = ""
            for line in block.split("\n"):
                if line.startswith("[Source:"):
                    source = line.replace("[Source:", "").replace("]", "").strip()
                elif line.startswith("URL:"):
                    source += f" ({line.replace('URL:', '').strip()})"
                elif not line.startswith("[Source:") and not line.startswith("URL:"):
                    content += " " + line.strip()

            if content.strip():
                citations.append({
                    "source_name": source,
                    "page_number": None,
                    "content_snippet": content[:200].strip(),
                    "relevance_score": None,
                })

    return citations

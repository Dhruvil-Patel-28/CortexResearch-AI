"""
Web search tool using DuckDuckGo.
Returns structured results with source attribution.
"""

import logging
from ddgs import DDGS

logger = logging.getLogger(__name__)


def web_search(query: str) -> str:
    """
    Search the web for real-time information using DuckDuckGo.

    Args:
        query: The search query string.

    Returns:
        Formatted string with search results including source URLs and titles.
    """
    try:
        results = []
        ddgs = DDGS()
        for r in ddgs.text(query, max_results=5):
            source_title = r.get("title", "Unknown Source")
            source_url = r.get("href", "No URL")
            body = r.get("body", "")
            results.append(
                f"[Source: {source_title}]\n"
                f"URL: {source_url}\n"
                f"{body}"
            )

        if not results:
            logger.warning(f"No web search results found for: {query}")
            return "No results found for this search query."

        logger.info(f"Web search returned {len(results)} results for: {query}")
        return "\n\n---\n\n".join(results)

    except Exception as e:
        logger.error(f"Web search failed for '{query}': {e}")
        return f"Web search encountered an error: {str(e)}. Please try a different query."
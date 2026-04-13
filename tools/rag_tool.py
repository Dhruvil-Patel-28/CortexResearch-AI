"""
RAG retrieval tool with citation tracking and relevance filtering.
Searches the internal knowledge base and returns only results that meet
the similarity threshold, preventing irrelevant citations.
"""

import logging
from rag.vector_store import search_with_relevance

logger = logging.getLogger(__name__)


def rag_tool(query: str) -> str:
    """
    Retrieve relevant information from the internal document knowledge base.

    Uses similarity-score filtering to ensure only genuinely relevant documents
    are returned. Results include source attribution with document name,
    page number, relevance score, and content for citation tracking.

    Args:
        query: The search query to find relevant documents.

    Returns:
        Formatted string with retrieved content and source metadata,
        or a message indicating no relevant documents were found.
    """
    try:
        results = search_with_relevance(query)

        if not results:
            logger.info(f"No relevant documents above threshold for: {query}")
            return "No relevant documents found in the knowledge base for this query."

        formatted = []
        for i, (doc, score) in enumerate(results, 1):
            source_file = doc.metadata.get("source_file", doc.metadata.get("source", "Unknown"))
            page_num = doc.metadata.get("page", "N/A")

            formatted.append(
                f"[Document {i}]\n"
                f"Source: {source_file}\n"
                f"Page: {page_num}\n"
                f"Relevance Score: {score:.4f}\n"
                f"Content:\n{doc.page_content}"
            )

        logger.info(f"RAG retrieved {len(results)} relevant documents for: {query}")
        return "\n\n---\n\n".join(formatted)

    except Exception as e:
        logger.error(f"RAG retrieval failed for '{query}': {e}")
        return f"Knowledge base search encountered an error: {str(e)}"
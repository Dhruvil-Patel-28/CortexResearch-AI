"""
RAG retrieval tool with citation tracking and relevance filtering.

- `rag_results(query) -> list[dict]` : structured, threshold-filtered hits
- `rag_tool(query) -> str`           : formatted text for prompt-based callers

Only documents above the configured similarity threshold are returned, which is
what keeps irrelevant citations out of the final report.
"""

import logging

logger = logging.getLogger(__name__)


def rag_results(query: str, k: int | None = None) -> list[dict]:
    """
    Retrieve relevant chunks from the internal knowledge base.

    Returns:
        [{"title", "url", "snippet", "score"}] — empty when nothing clears the
        relevance threshold or the index is unavailable.
    """
    try:
        from rag.vector_store import search_with_relevance

        results = search_with_relevance(query, k=k) if k else search_with_relevance(query)
        if not results:
            logger.info("No knowledge-base documents above threshold for: %s", query[:60])
            return []

        hits: list[dict] = []
        for doc, score in results:
            meta = doc.metadata or {}
            source = meta.get("source_file") or meta.get("source") or "Knowledge base"
            page = meta.get("page")
            hits.append(
                {
                    "title": f"{source}" + (f" (p. {page})" if page not in (None, "N/A") else ""),
                    "url": str(meta.get("url") or ""),
                    "snippet": (doc.page_content or "").strip(),
                    "score": float(score),
                }
            )
        logger.info("Knowledge base returned %d chunks for: %s", len(hits), query[:60])
        return hits
    except Exception as e:  # noqa: BLE001 — index missing/corrupt must not kill a run
        logger.warning("Knowledge base retrieval unavailable for '%s': %s", query[:60], e)
        return []


def rag_tool(query: str) -> str:
    """Formatted knowledge-base output (kept for prompt-based callers)."""
    hits = rag_results(query)
    if not hits:
        return "No relevant documents found in the knowledge base for this query."
    blocks = [
        f"[Document {i}]\nSource: {h['title']}\nRelevance Score: {h['score']:.4f}\nContent:\n{h['snippet']}"
        for i, h in enumerate(hits, 1)
    ]
    return "\n\n---\n\n".join(blocks)

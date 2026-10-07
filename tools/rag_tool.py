"""
RAG retrieval tool over the knowledge base of *published research briefs*.

- `rag_results(query) -> list[dict]` : structured hits from past reports
- `rag_tool(query) -> str`           : formatted text for prompt-based callers

The knowledge base used to be a stale prebuilt PDF index; it now indexes every
brief the report engine has produced (via the hybrid retriever), so follow-up
questions build on your own past research.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def rag_results(query: str, k: int | None = None) -> list[dict]:
    """
    Retrieve relevant past reports from the knowledge base.

    Returns:
        [{"title", "url", "snippet", "score"}] — empty when nothing matches or
        the index is unavailable.
    """
    try:
        from rag.retriever import get_retriever

        hits = get_retriever().search(query, k=k or 6, kinds=("brief",))
        logger.info("Knowledge base returned %d briefs for: %s", len(hits), query[:60])
        return [
            {
                "title": h["title"],
                "url": h["url"],
                "snippet": h["snippet"],
                "score": float(h["score"]),
            }
            for h in hits
        ]
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

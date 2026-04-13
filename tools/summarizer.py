"""
Summarizer tool for condensing research information.
Produces structured summaries with key points extracted.
"""

import logging
from utils.llm import get_llm

logger = logging.getLogger(__name__)


def summarize(text: str) -> str:
    """
    Summarize research text into a structured format with key takeaways.

    Args:
        text: The research text to summarize.

    Returns:
        Structured summary with key points.
    """
    if not text or len(text.strip()) < 20:
        return "Insufficient text provided for summarization."

    try:
        llm = get_llm(temperature=0.3)  # Lower temperature for factual summaries

        prompt = f"""Analyze and summarize the following research information. 
Provide your response in this structure:

**Summary:** A concise 2-3 sentence overview.

**Key Points:**
- Point 1
- Point 2
- Point 3
(List the most important findings)

**Gaps & Limitations:** Note any missing information or limitations you observe.

---
Research Text:
{text}
"""
        result = llm.invoke(prompt).content
        logger.info(f"Summarized {len(text)} chars of text")
        return result

    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        return f"Summarization encountered an error: {str(e)}"
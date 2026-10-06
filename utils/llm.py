"""
LLM factory module.
Provides configured LLM instances for all agents and tools.

Tiered models:
- "smart" (frontier) — research, analysis and report synthesis
- "fast"  (cheap)    — relevance scoring, extraction and routing

Instances are cached by (model, temperature) to avoid re-creating clients.
"""

import logging
from langchain_anthropic import ChatAnthropic
from utils.config import settings

logger = logging.getLogger(__name__)

# ─── Cache LLM instances by (model, temperature) ───
_llm_cache: dict[tuple[str, float], ChatAnthropic] = {}


def get_llm(temperature: float | None = None, tier: str = "smart") -> ChatAnthropic:
    """
    Return a configured, cached LLM instance.

    Args:
        temperature: Override default temperature. Useful for agents that need
                     deterministic (0.0) vs creative (0.7+) outputs.
        tier: "smart" for frontier synthesis, "fast" for cheap scoring/extraction.

    Returns:
        Configured ChatAnthropic instance.
    """
    temp = temperature if temperature is not None else settings.temperature

    if tier == "fast":
        model = settings.model_fast
        max_tokens = settings.max_tokens_fast
    else:
        model = settings.model_name
        max_tokens = settings.max_tokens_smart

    key = (model, temp)
    if key in _llm_cache:
        return _llm_cache[key]

    logger.info(f"Initializing LLM: model={model}, temperature={temp}")

    llm = ChatAnthropic(
        model=model,
        temperature=temp,
        max_tokens=max_tokens,
        api_key=settings.anthropic_api_key,
    )

    _llm_cache[key] = llm
    return llm

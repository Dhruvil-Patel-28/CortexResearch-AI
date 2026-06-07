"""
LLM factory module.
Provides configured LLM instances for all agents and tools.

Performance: Caches LLM instances by temperature to avoid
re-creating client objects on every call.
"""

import logging
from langchain_anthropic import ChatAnthropic
from utils.config import settings

logger = logging.getLogger(__name__)

# ─── Cache LLM instances by temperature ───
_llm_cache: dict[float, ChatAnthropic] = {}


def get_llm(temperature: float = None) -> ChatAnthropic:
    """
    Create and return a configured LLM instance.
    Instances are cached by temperature to avoid redundant client creation.

    Args:
        temperature: Override default temperature. Useful for agents that need
                     deterministic (0.0) vs creative (0.7+) outputs.

    Returns:
        Configured ChatAnthropic instance.
    """
    temp = temperature if temperature is not None else settings.temperature

    if temp in _llm_cache:
        return _llm_cache[temp]

    logger.info(f"Initializing LLM: model={settings.model_name}, temperature={temp}")

    llm = ChatAnthropic(
        model=settings.model_name,
        temperature=temp,
        api_key=settings.anthropic_api_key,
    )

    _llm_cache[temp] = llm
    return llm

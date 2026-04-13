"""
LLM factory module.
Provides configured LLM instances for all agents and tools.
"""

import logging
from langchain_anthropic import ChatAnthropic
from utils.config import settings

logger = logging.getLogger(__name__)


def get_llm(temperature: float = None) -> ChatAnthropic:
    """
    Create and return a configured LLM instance.

    Args:
        temperature: Override default temperature. Useful for agents that need
                     deterministic (0.0) vs creative (0.7+) outputs.

    Returns:
        Configured ChatAnthropic instance.
    """
    temp = temperature if temperature is not None else settings.temperature

    logger.info(f"Initializing LLM: model={settings.model_name}, temperature={temp}")

    return ChatAnthropic(
        model=settings.model_name,
        temperature=temp,
        api_key=settings.anthropic_api_key,
    )

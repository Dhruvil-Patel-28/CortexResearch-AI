"""
LLM factory module.

Tiered models:
- "smart" (frontier) — planning, research synthesis and report writing
- "fast"  (cheap)    — relevance scoring, extraction, verification and gap checks

Instances are cached by (model, temperature).

Modern Claude models reject the deprecated `temperature` parameter. Instead of
hard-coding which models do, every client is wrapped so that the first
`temperature` rejection transparently retries without it and remembers the
decision for the rest of the process.
"""

from __future__ import annotations

import logging

from langchain_anthropic import ChatAnthropic

from utils.config import settings

logger = logging.getLogger(__name__)

_llm_cache: dict[tuple[str, float | None], "LLMClient"] = {}
_NO_TEMPERATURE: set[str] = set()


class LLMClient:
    """
    ChatAnthropic wrapper with a LangChain-compatible `invoke`.

    Adds one behaviour: if the API rejects `temperature` for this model, the
    call is retried without it and the model is remembered, so a run never dies
    because of a parameter the model has retired.
    """

    def __init__(self, model: str, temperature: float | None, max_tokens: int) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._llm = _build(model, temperature, max_tokens)

    def invoke(self, messages, **kwargs):
        try:
            return self._llm.invoke(messages, **kwargs)
        except Exception as exc:  # noqa: BLE001 — re-raised unless it is the temperature case
            if self.temperature is not None and _is_temperature_error(exc):
                logger.warning("Model %s rejects `temperature` — retrying without it", self.model)
                _NO_TEMPERATURE.add(self.model)
                self.temperature = None
                self._llm = _build(self.model, None, self.max_tokens)
                return self._llm.invoke(messages, **kwargs)
            raise

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._llm, name)


def _is_temperature_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "temperature" in text and ("deprecated" in text or "unsupported" in text or "not supported" in text)


def _build(model: str, temperature: float | None, max_tokens: int) -> ChatAnthropic:
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "api_key": settings.anthropic_api_key,
    }
    if temperature is not None and model not in _NO_TEMPERATURE:
        kwargs["temperature"] = temperature
    return ChatAnthropic(**kwargs)


def get_llm(temperature: float | None = None, tier: str = "smart") -> LLMClient:
    """
    Return a configured, cached LLM client.

    Args:
        temperature: Sampling temperature. Lower = more deterministic. Ignored
                     for models that no longer accept the parameter.
        tier: "smart" for frontier synthesis, "fast" for cheap extraction work.
    """
    temp = temperature if temperature is not None else settings.temperature

    if tier == "fast":
        model, max_tokens = settings.model_fast, settings.max_tokens_fast
    else:
        model, max_tokens = settings.model_name, settings.max_tokens_smart

    key = (model, temp)
    cached = _llm_cache.get(key)
    if cached is not None:
        return cached

    logger.info("Initializing LLM: model=%s, temperature=%s", model, temp)
    client = LLMClient(model, temp, max_tokens)
    _llm_cache[key] = client
    return client

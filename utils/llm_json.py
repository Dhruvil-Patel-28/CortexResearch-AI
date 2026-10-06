"""
Structured-output helper for agents.

Anthropic has no native JSON mode, so every structured agent call here asks for
a JSON object, parses it defensively (`json_object_from` survives code fences,
leading prose and trailing commentary) and validates it with Pydantic. One
retry is attempted with the validation error fed back to the model; if that
also fails we raise, and the caller decides whether to degrade or abort.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from utils.cost import CostMeter, invoke_llm

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class JsonCallError(RuntimeError):
    """Raised when the model never returned schema-valid JSON."""


def json_object_from(text: str) -> dict[str, Any]:
    """
    Extract the first JSON object from a model response.

    Handles bare JSON, fenced blocks, and prose followed by JSON. Uses a
    brace-depth scan so trailing commentary does not break parsing.
    """
    if not text:
        raise JsonCallError("empty response")

    candidates: list[str] = []
    fenced = _FENCE_RE.findall(text)
    candidates.extend(block.strip() for block in fenced)
    candidates.append(text.strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start = candidate.find("{")
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    snippet = candidate[start : i + 1]
                    try:
                        parsed = json.loads(snippet)
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break
    raise JsonCallError("no JSON object found in response")


def call_json(
    llm: Any,
    *,
    system: str,
    user: str,
    schema: type[T],
    meter: CostMeter | None = None,
    label: str = "structured_call",
    max_attempts: int = 2,
    schema_hint: str | None = None,
) -> T:
    """
    Ask the model for JSON matching `schema` and return a validated instance.

    Args:
        schema_hint: Compact field description shown to the model. Defaults to
                     the Pydantic JSON schema (verbose but always accurate).
    """
    hint = schema_hint or json.dumps(schema.model_json_schema(), ensure_ascii=False)
    base_user = (
        f"{user}\n\n"
        f"Respond ONLY with a single JSON object matching this schema "
        f"(no markdown fence, no commentary):\n{hint}"
    )

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        prompt = base_user
        if last_error is not None:
            prompt += (
                f"\n\nYour previous response was rejected: {last_error}. "
                "Return corrected JSON only."
            )
        response = invoke_llm(
            llm,
            [SystemMessage(content=system), HumanMessage(content=prompt)],
            meter=meter,
            label=label if attempt == 1 else f"{label}_retry",
        )
        content = response.content
        if isinstance(content, list):  # Anthropic content blocks
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block) for block in content
            )
        try:
            return schema.model_validate(json_object_from(str(content)))
        except (JsonCallError, ValidationError) as exc:
            last_error = exc
            logger.warning("%s: attempt %d produced invalid JSON (%s)", label, attempt, exc)

    raise JsonCallError(f"{label}: {last_error}")

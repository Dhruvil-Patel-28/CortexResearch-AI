"""Dataclasses for stored entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Item:
    """A single ingested item from any source."""

    id: str
    source: str
    title: str
    url: str = ""
    external_id: str = ""
    author: str = ""
    published_at: str = ""
    raw_text: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    first_seen_at: str = ""


@dataclass(slots=True)
class Score:
    """LLM relevance score for one item against one topic."""

    item_id: str
    relevance: float
    rationale: str = ""
    tags: list[str] = field(default_factory=list)
    topic_id: str = "general"
    model: str = ""
    profile_version: str = ""
    scored_at: str = ""


@dataclass(slots=True)
class Job:
    """A background task (brief generation, digest run, ingest run)."""

    id: str
    kind: str
    status: str = "pending"
    payload: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

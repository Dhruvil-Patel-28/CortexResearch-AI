"""
Interest profile — what "relevant to me" means.

The profile lives in watch/profile.yaml and is editable at any time. Its
content hash doubles as a cache version: re-run scoring only when the
profile actually changed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import Path

import yaml

from utils.config import settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Profile:
    name: str = "there"
    interests: list[str] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    boost: list[str] = field(default_factory=list)
    mute: list[str] = field(default_factory=list)
    arxiv_keywords: list[str] = field(default_factory=list)
    version: str = "default"

    @property
    def keywords(self) -> list[str]:
        """Flattened keyword list used for prefilters and generic matching."""
        out: list[str] = []
        for k in self.arxiv_keywords + self.boost:
            k = k.strip()
            if k and k.lower() not in [o.lower() for o in out]:
                out.append(k)
        return out

    @property
    def arxiv_terms(self) -> list[str]:
        """Terms sent to arXiv: focused keywords when set, otherwise boost terms."""
        terms = [k.strip() for k in self.arxiv_keywords if k.strip()]
        return terms or self.boost

    def is_muted(self, text: str) -> bool:
        haystack = (text or "").lower()
        return any(m.strip().lower() in haystack for m in self.mute if m.strip())

    def prompt_block(self) -> str:
        """Compact profile description injected into scorer prompts."""
        lines = [f"Reader: {self.name}"]
        if self.interests:
            lines.append("Interests: " + "; ".join(self.interests))
        if self.stack:
            lines.append("Builds with: " + "; ".join(self.stack))
        if self.goals:
            lines.append("Current goals: " + "; ".join(self.goals))
        if self.boost:
            lines.append("Always interesting: " + "; ".join(self.boost))
        if self.mute:
            lines.append("Explicitly not interesting: " + "; ".join(self.mute))
        return "\n".join(lines)


def load_profile(path: str | None = None) -> Profile:
    """Load the YAML profile; falls back to a neutral default when missing."""
    p = Path(path or settings.profile_path)
    if not p.exists():
        logger.warning(f"Profile not found at {p} — using neutral defaults")
        return Profile()

    raw = p.read_bytes()
    data = yaml.safe_load(raw.decode("utf-8")) or {}

    return Profile(
        name=str(data.get("name") or "there"),
        interests=list(data.get("interests") or []),
        stack=list(data.get("stack") or []),
        goals=list(data.get("goals") or []),
        boost=list(data.get("boost") or []),
        mute=list(data.get("mute") or []),
        arxiv_keywords=list(data.get("arxiv_keywords") or []),
        version=sha1(raw).hexdigest()[:12],
    )

"""
Supermemory adapter — cross-session memory (optional, flagged).

Supermemory (self-hosted binary or compatible API) stores durable memory
documents beyond the SQLite store: things you've saved, searches you've run,
digests you've received. The app treats it as a nice-to-have: when the flag
is off or the service is unreachable, every method degrades to a no-op and
the internal store remains the source of truth.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from utils.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 5


class SupermemoryMemory:
    """Thin client for a local Supermemory-compatible service."""

    def __init__(self, base_url: str, api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    def remember(self, text: str, metadata: dict[str, Any] | None = None) -> bool:
        """Store a memory document. Returns True on success."""
        try:
            response = requests.post(
                f"{self._base_url}/api/v1/documents",
                json={"content": text, "metadata": metadata or {}},
                headers=self._headers,
                timeout=_TIMEOUT,
            )
            return response.status_code < 300
        except requests.RequestException as e:
            logger.warning("Supermemory remember failed: %s", e)
            return False

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Search memory documents; [] when the service is unreachable."""
        try:
            response = requests.post(
                f"{self._base_url}/api/v1/search",
                json={"q": query, "limit": k},
                headers=self._headers,
                timeout=_TIMEOUT,
            )
            if response.status_code >= 300:
                return []
            data = response.json()
            results = data.get("results") or data.get("documents") or []
            return [
                {
                    "text": r.get("content") or r.get("text") or "",
                    "score": float(r.get("score") or r.get("relevance") or 0.0),
                }
                for r in results[:k]
                if isinstance(r, dict)
            ]
        except (requests.RequestException, ValueError) as e:
            logger.warning("Supermemory search failed: %s", e)
            return []


def get_memory() -> SupermemoryMemory | None:
    """The configured memory client, or None when the flag is off."""
    if not settings.enable_supermemory or not settings.supermemory_url.strip():
        return None
    return SupermemoryMemory(settings.supermemory_url.strip(), settings.supermemory_api_key.strip())

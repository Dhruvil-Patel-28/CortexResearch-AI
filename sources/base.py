"""
Base types and helpers for source adapters.

An adapter is responsible for fetching fresh items from one free source and
mapping them into FeedItem objects. Adapters must never raise on network
failure — they return [] and log a warning so one dead source never breaks
an ingest run.

Each adapter exposes pure parse functions (e.g. parse_hn_item) so parsing
can be unit-tested offline against recorded fixtures.
"""

from __future__ import annotations

import abc
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)

USER_AGENT = "CortexResearch/0.1 (personal research radar)"


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


@dataclass(slots=True)
class FeedItem:
    """A normalized item from any source."""

    source: str
    title: str
    url: str
    external_id: str = ""
    author: str = ""
    published_at: str = ""  # ISO-8601 UTC
    raw_text: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    cluster_key: str = ""  # set during ingest by watch.dedupe

    @property
    def id(self) -> str:
        """Stable dedup key across runs (source + external id, falling back to URL)."""
        return sha1(f"{self.source}:{self.external_id or self.url}")

    @property
    def content_hash(self) -> str:
        """Hash of the textual content — used to invalidate score caches."""
        return sha1(f"{self.title}\n{self.raw_text[:800]}")


class SourceAdapter(abc.ABC):
    """Common interface for all source adapters."""

    name: str = "base"

    @abc.abstractmethod
    def fetch(self, limit: int = 30, keywords: list[str] | None = None) -> list[FeedItem]:
        """Fetch fresh items. Must never raise — return [] on failure."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(1),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    reraise=True,
)
def http_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> httpx.Response:
    """GET with retries (3 attempts, 1s apart) and a sane User-Agent."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    resp = httpx.get(url, params=params, headers=hdrs, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp

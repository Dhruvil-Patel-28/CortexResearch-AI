"""
GitHub trending adapter — Search API (free, unauthenticated).

The trending web page is scrape-only; the Search API gives us the same
signal ("recently created repos gaining stars fast") in a stable form.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sources.base import FeedItem, SourceAdapter, http_get
from utils.config import settings

logger = logging.getLogger(__name__)

API = "https://api.github.com/search/repositories"


def parse_github_search(payload: dict) -> list[FeedItem]:
    """Parse a GitHub repositories search response (pure — unit-testable)."""
    items: list[FeedItem] = []

    for repo in payload.get("items") or []:
        full_name = repo.get("full_name") or ""
        html_url = repo.get("html_url") or ""
        if not full_name or not html_url:
            continue

        items.append(
            FeedItem(
                source="github",
                external_id=full_name,
                title=full_name,
                url=html_url,
                author=(repo.get("owner") or {}).get("login", ""),
                published_at=repo.get("created_at") or "",
                raw_text=(repo.get("description") or "").strip(),
                metrics={
                    "stars": int(repo.get("stargazers_count") or 0),
                    "forks": int(repo.get("forks_count") or 0),
                    "language": repo.get("language") or "",
                    "topics": repo.get("topics") or [],
                },
            )
        )

    return items


class GitHubTrendingAdapter(SourceAdapter):
    name = "github"

    def fetch(self, limit: int = 25, keywords: list[str] | None = None) -> list[FeedItem]:
        since = (datetime.now(UTC) - timedelta(days=settings.github_days)).strftime("%Y-%m-%d")
        query = f"created:>{since} stars:>{settings.github_min_stars}"

        try:
            resp = http_get(
                API,
                params={"q": query, "sort": "stars", "order": "desc", "per_page": min(limit, 30)},
                headers={"Accept": "application/vnd.github+json"},
                timeout=20.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("GitHub search failed: %s", e)
            return []

        items = parse_github_search(resp.json())
        logger.info("GitHub: %s trending repos (%s)", len(items), query)
        return items[:limit]

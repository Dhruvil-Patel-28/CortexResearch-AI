"""
Web search tool using DuckDuckGo.

Two entry points:
- `web_search(query) -> str`      : formatted text, for prompt-based callers
- `web_search_results(query) -> list[dict]` : structured hits with URL, so the
  researcher can register real citations instead of parsing strings.

Both are resilient: rate limits retry once, then degrade to an empty result.
"""

import logging
import time

from ddgs import DDGS

logger = logging.getLogger(__name__)

_MAX_RESULTS = 5


def web_search_results(query: str, max_results: int = _MAX_RESULTS) -> list[dict]:
    """
    Search the web and return structured results.

    Titles and snippets are guardrail-sanitized (PII scrub + injection
    neutralization) before leaving the tool.

    Returns:
        [{"title", "url", "snippet", "source"}] — empty on failure.
    """
    from guardrails import sanitize_content

    for attempt in (1, 2):
        try:
            results: list[dict] = []
            for r in DDGS().text(query, max_results=max_results):
                url = (r.get("href") or "").strip()
                title = (r.get("title") or "").strip()
                if not url and not title:
                    continue
                snippet, _ = sanitize_content((r.get("body") or "").strip())
                title, _ = sanitize_content(title)
                results.append(
                    {
                        "title": title or url,
                        "url": url,
                        "snippet": snippet,
                        "source": _domain(url),
                    }
                )
            if results:
                logger.info("Web search '%s' → %d results", query[:60], len(results))
                return results

            logger.info("Web search '%s' returned nothing", query[:60])
            return []
        except Exception as e:  # noqa: BLE001 — ddgs raises several lib-specific errors
            message = str(e).lower()
            if attempt == 1 and ("rate" in message or "limit" in message or "429" in message):
                logger.warning("Web search rate-limited, retrying once: %s", e)
                time.sleep(1.5)
                continue
            logger.error("Web search failed for '%s': %s", query, e)
            return []
    return []


def _domain(url: str) -> str:
    if not url:
        return ""
    host = url.split("://", 1)[-1].split("/", 1)[0]
    return host[4:] if host.startswith("www.") else host


def web_search(query: str) -> str:
    """
    Search the web for real-time information and return formatted text.

    Kept for prompt-based callers; the researcher uses `web_search_results`.
    """
    results = web_search_results(query)
    if not results:
        return "No results found for this search query."

    blocks = [
        f"[Source: {r['title']}]\nURL: {r['url']}\n{r['snippet']}" for r in results
    ]
    return "\n\n---\n\n".join(blocks)

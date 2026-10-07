"""
Ingestion orchestrator: runs all enabled source adapters in parallel and
stores new items. Adapter failures are isolated — one dead source never
breaks a run.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from sources.base import FeedItem, SourceAdapter
from store import db

logger = logging.getLogger(__name__)


def _get_adapters(names: list[str]) -> list[SourceAdapter]:
    """Instantiate adapters lazily so an unused source costs nothing."""
    from sources.arxiv import ArxivAdapter
    from sources.github_trending import GitHubTrendingAdapter
    from sources.hackernews import HackerNewsAdapter
    from sources.producthunt import ProductHuntAdapter
    from sources.reddit import RedditAdapter
    from sources.rss import RssAdapter

    registry: dict[str, type[SourceAdapter]] = {
        "hackernews": HackerNewsAdapter,
        "arxiv": ArxivAdapter,
        "rss": RssAdapter,
        "reddit": RedditAdapter,
        "github": GitHubTrendingAdapter,
        "producthunt": ProductHuntAdapter,
    }
    return [registry[n]() for n in names if n in registry]


def run_ingest(
    *,
    keywords: list[str] | None = None,
    sources: list[str] | None = None,
    progress=None,
) -> dict:
    """
    Fetch from all enabled sources in parallel and store new items.

    Args:
        keywords: Optional keywords (defaults to the interest profile's).
        sources: Optional source override (defaults to settings.watch_sources).
        progress: Optional callback(stage: str, detail: dict) for streaming.

    Returns:
        Stats dict: new, duplicates, total_fetched, sources, duration_s.
    """
    from utils.config import settings
    from watch.dedupe import assign_clusters

    db.init_db()
    started = datetime.now(timezone.utc)

    names = sources or [s.strip().lower() for s in settings.watch_sources.split(",") if s.strip()]
    adapters = _get_adapters(names)

    if not keywords:
        try:
            from watch.profile import load_profile

            keywords = load_profile().arxiv_terms or None
        except Exception:  # noqa: BLE001
            keywords = None

    stats: dict[str, dict] = {}
    all_items: list[FeedItem] = []

    def _emit(stage: str, detail: dict | None = None):
        if progress:
            try:
                progress(stage, detail or {})
            except Exception:  # noqa: BLE001
                pass

    _emit("ingest_started", {"sources": [a.name for a in adapters]})

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(a.fetch, keywords=keywords): a.name for a in adapters}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                items = fut.result()
                stats[name] = {"fetched": len(items)}
                all_items.extend(items)
                _emit("source_done", {"source": name, "fetched": len(items)})
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Adapter {name} failed: {e}")
                stats[name] = {"fetched": 0, "error": str(e)}
                _emit("source_failed", {"source": name, "error": str(e)})

    # Group the same story coming from multiple sources into one cluster
    cluster_map = assign_clusters(all_items)

    # Guardrails: scrub PII + neutralize injections before anything is stored
    from guardrails import sanitize_content

    guardrail_totals: dict[str, int] = {}
    for item in all_items:
        if item.raw_text:
            item.raw_text, summary = sanitize_content(item.raw_text)
            guardrail_totals["pii"] = guardrail_totals.get("pii", 0) + len(summary["pii_kinds"])
            guardrail_totals["injections"] = guardrail_totals.get("injections", 0) + (
                summary["injection_count"] if summary["injection_action"] == "strip" else 0
            )
    if any(guardrail_totals.values()):
        logger.info("Guardrails at ingest: %s", guardrail_totals)

    for item in all_items:
        item.cluster_key = cluster_map.get(item.id, "")

    new_count, dup_count = db.upsert_items(all_items)
    db.set_meta("last_ingest_at", datetime.now(timezone.utc).isoformat())

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    result = {
        "new": new_count,
        "duplicates": dup_count,
        "total_fetched": len(all_items),
        "clusters": len(set(getattr(i, "cluster_key", "") for i in all_items if getattr(i, "cluster_key", ""))),
        "sources": stats,
        "duration_s": round(duration, 2),
    }
    logger.info(
        f"Ingest done in {duration:.1f}s: {new_count} new, {dup_count} duplicates "
        f"from {len(adapters)} sources"
    )
    _emit("ingest_done", result)
    return result

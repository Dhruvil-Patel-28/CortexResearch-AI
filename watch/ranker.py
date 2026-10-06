"""
Personalized relevance ranker.

Two-stage pipeline designed to keep LLM cost near zero on repeat runs:
1. Prefilter (free): mute-list, cache (profile version), recency cap.
2. LLM scoring (fast tier): batched structured output, only for items that
   were never scored under the current profile version.

The scorer writes a "why this matters to you" rationale — the headline
feature of the Pulse feed.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from store import db
from utils.config import settings
from watch.profile import Profile, load_profile

logger = logging.getLogger(__name__)

BATCH_SIZE = 8


class ScoredItem(BaseModel):
    """One item's score inside a batch response."""

    item_index: int = Field(description="Index of the item in the numbered list (starts at 1)")
    relevance: float = Field(ge=0, le=10, description="0-10 relevance to this specific reader")
    rationale: str = Field(description="One sentence written to the reader ('you') explaining why this matters for their goals or stack")
    tags: list[str] = Field(default_factory=list, description="2-4 short topic tags")


class BatchScores(BaseModel):
    """Structured output for a batch of items."""

    scores: list[ScoredItem]


SCORER_PROMPT = """You score tech-news and research items for how much they matter to ONE specific reader.

{profile}

Scoring guide:
- 9-10: directly advances the reader's goals; they would regret missing it
- 7-8: clearly relevant to their interests or stack
- 5-6: adjacent, mildly useful
- 3-4: general industry news, no personal impact
- 0-2: off-topic or explicitly not interesting

Rules:
- The rationale is written TO the reader ("you ..."), is concrete, and says WHY it matters for their goals or stack.
- Never restate the title. No filler like "this is important".
- Score every item in the list, using its index.
"""


def build_scorer_prompt(profile: Profile) -> str:
    return SCORER_PROMPT.format(profile=profile.prompt_block())


def _item_brief(index: int, item: dict) -> str:
    metrics = item.get("metrics") or {}
    bits = [f"{k}={v}" for k, v in metrics.items() if isinstance(v, (int, float, str)) and v not in ("", None)]
    meta = (" | " + ", ".join(bits[:4])) if bits else ""
    text = (item.get("raw_text") or "").strip().replace("\n", " ")[:400]
    return (
        f"[{index}] ({item.get('source')}{meta})\n"
        f"Title: {item.get('title', '')}\n"
        f"Excerpt: {text or '(no description)'}"
    )


def _batch_prompt(items: list[dict]) -> str:
    return "\n\n".join(_item_brief(i + 1, it) for i, it in enumerate(items))


def score_batch(llm_structured, profile: Profile, items: list[dict]) -> list[dict]:
    """Score one batch of items (<= BATCH_SIZE) and return score dicts."""
    prompt = build_scorer_prompt(profile) + "\n\n---ITEMS---\n\n" + _batch_prompt(items)
    result: BatchScores = llm_structured.invoke(prompt)

    by_index = {s.item_index: s for s in result.scores}
    out: list[dict] = []
    for i, item in enumerate(items, 1):
        s = by_index.get(i)
        if not s:
            continue
        out.append(
            {
                "item_id": item["id"],
                "topic_id": "general",
                "relevance": float(s.relevance),
                "rationale": s.rationale.strip(),
                "tags": s.tags[:4],
                "model": settings.model_fast,
                "profile_version": profile.version,
            }
        )
    return out


def score_unscored(limit: int | None = None, progress=None) -> dict:
    """
    Score all not-yet-scored items (under the current profile version).

    Returns stats: scored, skipped_cached, skipped_muted, batches, errors.
    """
    from utils.llm import get_llm

    db.init_db()
    profile = load_profile()
    cap = limit or settings.llm_score_k

    def _emit(stage: str, detail: dict | None = None):
        if progress:
            try:
                progress(stage, detail or {})
            except Exception:  # noqa: BLE001
                pass

    candidates = db.list_items(limit=settings.prefilter_k, order="newest")
    already = db.scored_item_ids(profile.version)

    fresh: list[dict] = []
    skipped_cached = 0
    skipped_muted = 0

    for item in candidates:
        if item["id"] in already:
            skipped_cached += 1
            continue
        if profile.is_muted(f"{item.get('title', '')} {item.get('raw_text', '')}"):
            skipped_muted += 1
            continue
        fresh.append(item)

    fresh = fresh[:cap]

    _emit("score_started", {"candidates": len(fresh), "cached": skipped_cached})

    if not fresh:
        return {"scored": 0, "skipped_cached": skipped_cached, "skipped_muted": skipped_muted, "batches": 0, "errors": 0}

    llm = get_llm(temperature=0.0, tier="fast")
    structured = llm.with_structured_output(BatchScores)

    scored = 0
    errors = 0
    batches = 0

    for start in range(0, len(fresh), BATCH_SIZE):
        batch = fresh[start : start + BATCH_SIZE]
        batches += 1
        try:
            rows = score_batch(structured, profile, batch)
            db.save_scores(rows)
            scored += len(rows)
            _emit("score_batch_done", {"scored": scored, "of": len(fresh)})
        except Exception as e:  # noqa: BLE001 — one bad batch must not kill the run
            errors += 1
            logger.warning(f"Scoring batch failed: {e}")

    result = {
        "scored": scored,
        "skipped_cached": skipped_cached,
        "skipped_muted": skipped_muted,
        "batches": batches,
        "errors": errors,
        "profile_version": profile.version,
        "model": settings.model_fast,
    }
    logger.info(f"Scoring done: {result}")
    _emit("score_done", result)
    return result

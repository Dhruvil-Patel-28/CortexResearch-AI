"""
Researcher agent — multi-hop evidence gathering.

For each planned sub-question the researcher consults three channels in
parallel:

* **Radar store**  — what the market-pulse pipeline already ingested (your feed)
* **Knowledge base** — the RAG index over your own documents
* **Web search**    — DuckDuckGo, with the top hits fetched in full so the
  writer works from article bodies rather than 140-character snippets

Every hit is registered in a `SourceRegistry` and gets a stable id, so the
writer can cite `s2` and the verifier can check that claim against the exact
snippet stored under `s2`. A gap-check pass then asks the fast model whether
anything critical is missing and runs one more targeted round if so.
"""

from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pydantic import BaseModel, Field, field_validator

from agents.events import emit_event
from agents.sources import SourceRegistry, canonical_url
from agents.state import ResearchState
from tools.fetch_page import fetch_many
from tools.rag_tool import rag_results
from tools.store_search import store_results
from tools.web_search import web_search_results
from utils.cost import CostMeter
from utils.llm import get_llm
from utils.llm_json import JsonCallError, call_json

logger = logging.getLogger(__name__)

MAX_WEB_PER_SUBQ = 2
MAX_PAGE_FETCHES = {"brief": 4, "standard": 9, "deep": 14}
MAX_EXTRA_QUERIES = 3
MAX_EXTRA_SOURCES = 6
MAX_EVIDENCE_CHARS = 26_000

# A deep brief needs the *right* sources, not every hit: each sub-question
# registers only its strongest few so the writer works from signal, not noise.
PER_SUBQ_SOURCES = {"brief": 4, "standard": 5, "deep": 6}
REGISTRY_LIMIT = 40

GAP_SYSTEM = """You are the coverage critic of a research team.

Given the questions the team was asked to answer and the sources gathered so
far, decide whether anything essential is still missing. Be strict but
practical: only ask for more searches when a specific, findable gap exists.
"""

GAP_HINT = """{
  "sufficient": true,
  "missing": "what is still missing, or empty",
  "extra_queries": ["keyword query", "keyword query"]
}"""


class GapCheck(BaseModel):
    sufficient: bool = True
    missing: str = ""
    extra_queries: list[str] = Field(default_factory=list)

    @field_validator("extra_queries", mode="before")
    @classmethod
    def _queries(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [q for q in v if isinstance(q, str) and q.strip()]
        return []


def _run_task(kind: str, query: str) -> list[dict]:
    """Dispatch one retrieval task. Never raises — empty list on failure."""
    try:
        if kind == "store":
            return store_results(query, limit=6)
        if kind == "rag":
            return rag_results(query)
        return web_search_results(query, max_results=5)
    except Exception as e:  # noqa: BLE001
        logger.warning("researcher task %s('%s') failed: %s", kind, query[:50], e)
        return []


# Friendly names for the sources the fan-out touches. Known ones get their own
# pill in the live retrieval graph; everything else folds into "Web".
SOURCE_BUCKETS = {
    "hackernews": "Hacker News",
    "news.ycombinator.com": "Hacker News",
    "arxiv": "arXiv",
    "arxiv.org": "arXiv",
    "reddit": "Reddit",
    "reddit.com": "Reddit",
    "old.reddit.com": "Reddit",
    "github": "GitHub",
    "github.com": "GitHub",
    "producthunt": "Product Hunt",
    "producthunt.com": "Product Hunt",
    "rss": "Blogs",
}
UNKNOWN_BUCKET = "Web"


def _source_bucket(source: str) -> str:
    """Map a hit's `source` to a display bucket; unknowns fold into 'Web'."""
    return SOURCE_BUCKETS.get((source or "").strip().lower(), UNKNOWN_BUCKET)


def researcher_node(state: ResearchState) -> dict:
    """Gather and register evidence for every planned sub-question."""
    query = (state.get("research_query") or "").strip()
    depth = state.get("depth") or "standard"
    plan = state.get("research_plan") or {}
    sub_questions = plan.get("sub_questions") or []
    if not sub_questions:
        sub_questions = [{"question": query, "why": "", "search_queries": [query]}]

    meter: CostMeter | None = state.get("meter")
    logger.info("Researcher starting | %d sub-questions | depth=%s", len(sub_questions), depth)
    emit_event(state, "stage", stage="gathering", label=f"Searching {len(sub_questions)} sub-questions", pct=15)

    # ── Build the task list: store + knowledge base + web per sub-question ──
    tasks: list[tuple[int, str, str]] = []
    for idx, sq in enumerate(sub_questions):
        question = (sq.get("question") or query).strip()
        tasks.append((idx, "store", question))
        tasks.append((idx, "rag", question))
        web_queries = sq.get("search_queries") or [question]
        for web_query in web_queries[:MAX_WEB_PER_SUBQ]:
            if web_query.strip():
                tasks.append((idx, "web", web_query.strip()))

    results: dict[tuple[int, str, str], list[dict]] = {}
    tasks_per_sq: dict[int, int] = {}
    for idx, _, _ in tasks:
        tasks_per_sq[idx] = tasks_per_sq.get(idx, 0) + 1
    done_per_sq: dict[int, int] = {idx: 0 for idx in tasks_per_sq}
    n_sq = len(sub_questions)

    # Seed one lane per sub-question so the live view shows the parallel
    # fan-out immediately, before any task has finished.
    for idx, sq in enumerate(sub_questions):
        emit_event(
            state,
            "subq",
            index=idx,
            total=n_sq,
            question=(sq.get("question") or query)[:80],
            done=0,
            tasks=tasks_per_sq.get(idx, 1),
        )

    # Threads run the sub-questions *in parallel*; every completed task
    # updates its sub-question's lane so users watch the threads race.
    found: Counter[str] = Counter()
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_run_task, kind, q): (idx, kind, q) for idx, kind, q in tasks}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result(timeout=60)
            except Exception as e:  # noqa: BLE001
                logger.warning("task failed/timed out %s: %s", key[1], e)
                results[key] = []
            for hit in results[key]:
                src = (hit.get("source") or "").strip()
                if src:
                    found[_source_bucket(src)] += 1
            done_per_sq[key[0]] = done_per_sq.get(key[0], 0) + 1
            sq_question = (sub_questions[key[0]].get("question") or query)[:80]
            emit_event(
                state,
                "subq",
                index=key[0],
                total=n_sq,
                question=sq_question,
                done=done_per_sq[key[0]],
                tasks=tasks_per_sq.get(key[0], 1),
                kind=key[1],
                found=dict(found),
            )
            if done_per_sq[key[0]] == tasks_per_sq.get(key[0], 1):
                emit_event(
                    state,
                    "stage",
                    stage="gathering",
                    label=f"Sub-question {key[0] + 1}/{n_sq} searched — {sq_question[:60]}",
                    pct=15 + int(14 * sum(done_per_sq.values()) / max(len(tasks), 1)),
                )

    tool_counts = {
        "radar_store": sum(len(v) for k, v in results.items() if k[1] == "store"),
        "knowledge_base": sum(len(v) for k, v in results.items() if k[1] == "rag"),
        "web_search": sum(len(v) for k, v in results.items() if k[1] == "web"),
    }
    emit_event(
        state,
        "tools",
        label=f"Found {tool_counts['radar_store']} radar items, {tool_counts['knowledge_base']} KB chunks, {tool_counts['web_search']} web hits",
        **tool_counts,
        pct=30,
    )

    # ── Pull full article text for the best web hits ──
    web_urls: list[str] = []
    for idx, _ in enumerate(sub_questions):
        for key, hits in results.items():
            if key[0] != idx or key[1] != "web":
                continue
            for hit in hits:
                if hit.get("url"):
                    web_urls.append(hit["url"])
    fetch_budget = MAX_PAGE_FETCHES.get(depth, 9)
    to_fetch = web_urls[:fetch_budget]
    fetched = fetch_many(to_fetch) if to_fetch else {}
    enriched = sum(1 for text in fetched.values() if len(text) > 600)
    emit_event(state, "stage", stage="reading", label=f"Read {enriched}/{len(to_fetch)} pages in full", pct=42)

    # ── Register every source, grouped by sub-question, ids in reading order ──
    registry = SourceRegistry(limit=REGISTRY_LIMIT)
    source_cap = PER_SUBQ_SOURCES.get(depth, 5)
    sub_findings: list[dict[str, Any]] = []
    for idx, sq in enumerate(sub_questions):
        question = (sq.get("question") or query).strip()
        source_ids: list[str] = []

        for kind, hit in _candidates(results, fetched, idx, cap=source_cap):
            if kind == "web":
                snippet = fetched.get(hit.get("url") or "", "") or hit.get("snippet", "")
            else:
                snippet = hit.get("snippet", "")

            source_id = registry.add(
                kind=("knowledge_base" if kind == "rag" else ("web" if kind == "web" else hit.get("source", "web"))),
                title=hit.get("title", ""),
                url=hit.get("url", ""),
                snippet=snippet,
                published_at=hit.get("published_at"),
                sub_question=question[:160],
                score=hit.get("score"),
            )
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)

        sub_findings.append(
            {
                "question": question,
                "why": sq.get("why", ""),
                "source_ids": source_ids,
            }
        )

    # ── Gap check: one extra targeted round when coverage is thin ──
    gap_notes = ""
    if depth in {"standard", "deep"} and len(registry) >= 3:
        gap = _gap_check(query, sub_findings, registry, meter=meter)
        gap_notes = gap.missing
        if not gap.sufficient and gap.extra_queries:
            extra = _run_extra_round(gap.extra_queries[:MAX_EXTRA_QUERIES], fetched, registry)
            if extra:
                sub_findings.append(
                    {
                        "question": "Coverage gap fill",
                        "why": gap.missing or "Filled gaps identified by the coverage critic",
                        "source_ids": extra,
                    }
                )
                emit_event(state, "stage", stage="gap_fill", label=f"Filled a coverage gap with {len(extra)} sources", pct=48)

    research_data = _render_evidence(sub_findings, registry)
    emit_event(
        state,
        "sources",
        sources=registry.as_list(),
        count=len(registry),
        label=f"{len(registry)} sources registered",
        pct=50,
    )
    logger.info("Researcher gathered %d sources across %d sub-questions", len(registry), len(sub_findings))

    step = {
        "agent_name": "Researcher",
        "action": f"Gathered {len(registry)} sources across {len(sub_findings)} research threads",
        "tools_used": ["RadarStore", "RAG/KnowledgeBase", "WebSearch", "PageReader"],
        "source_count": len(registry),
        "tool_counts": tool_counts,
        "gap_notes": gap_notes,
    }
    return {
        "research_data": research_data,
        "source_registry": registry.as_list(),
        "sub_findings": sub_findings,
        "completed_agents": ["Researcher"],
        "agent_steps": [step],
    }


def _candidates(results: dict, fetched: dict[str, str], idx: int, *, cap: int) -> list[tuple[str, dict]]:
    """
    Choose the best sources for one sub-question, in citation order:

    1. radar items — already curated for this reader by the pulse ranker
    2. web pages read in full — the highest-signal evidence available
    3. knowledge-base chunks — your own documents
    4. snippet-only web hits — useful for recency, weakest evidence

    Keeping this order (rather than raw retrieval order) is what makes citation
    ids meaningful in the report: `s1` is always the strongest evidence for the
    first sub-question, not whichever thread happened to finish first.
    """
    buckets: dict[str, list[dict]] = {"store": [], "rag": [], "web_full": [], "web": []}
    for key, hits in results.items():
        if key[0] != idx:
            continue
        kind = key[1]
        for hit in hits:
            if kind == "web":
                target = "web_full" if len(fetched.get(hit.get("url") or "", "")) > 600 else "web"
                buckets[target].append(hit)
            elif kind == "rag":
                buckets["rag"].append(hit)
            else:
                buckets["store"].append(hit)

    order = [
        ("store", buckets["store"][:2]),
        ("web", buckets["web_full"][:2]),
        ("rag", buckets["rag"][:1]),
        ("web", buckets["web"][:2]),
    ]

    picked: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for kind, hits in order:
        for hit in hits:
            key = canonical_url(hit.get("url") or "") or (hit.get("title") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            picked.append((kind, hit))
            if len(picked) >= cap:
                return picked
    return picked


def _gap_check(query: str, sub_findings: list[dict], registry: SourceRegistry, *, meter: CostMeter | None) -> GapCheck:
    """Ask the fast model whether the evidence set can answer the question."""
    covered = "\n".join(
        f"- {f['question']} → {len(f['source_ids'])} sources" for f in sub_findings
    )
    titles = "\n".join(f"[{s['id']}] {s['title']}" for s in registry.as_list()[:30])
    prompt = f"""Main question: {query}

Sub-questions and their coverage:
{covered}

Source titles gathered so far:
{titles}

Is any sub-question unanswered or only covered by a single weak source?
If a specific findable gap remains, propose up to {MAX_EXTRA_QUERIES} short keyword queries to fill it.
Otherwise set sufficient=true and leave extra_queries empty."""

    try:
        return call_json(
            get_llm(temperature=0.0, tier="fast"),
            system=GAP_SYSTEM,
            user=prompt,
            schema=GapCheck,
            meter=meter,
            label="gap_check",
            schema_hint=GAP_HINT,
        )
    except JsonCallError as exc:
        logger.warning("Gap check unavailable: %s", exc)
        return GapCheck(sufficient=True)


def _run_extra_round(queries: list[str], fetched: dict[str, str], registry: SourceRegistry) -> list[str]:
    """Run gap-filling web searches and register the best new sources."""
    new_ids: list[str] = []
    with ThreadPoolExecutor(max_workers=len(queries) or 1) as executor:
        for hits in executor.map(lambda q: web_search_results(q, max_results=4), queries):
            urls = [h.get("url", "") for h in hits if h.get("url")]
            texts = fetch_many(urls[:2]) if urls else {}
            fetched.update(texts)
            for hit in hits:
                if len(new_ids) >= MAX_EXTRA_SOURCES:
                    return new_ids
                source_id = registry.add(
                    kind="web",
                    title=hit.get("title", ""),
                    url=hit.get("url", ""),
                    snippet=texts.get(hit.get("url", ""), "") or hit.get("snippet", ""),
                    sub_question="Coverage gap fill",
                )
                if source_id and source_id not in new_ids:
                    new_ids.append(source_id)
    return new_ids


def _render_evidence(sub_findings: list[dict], registry: SourceRegistry, *, per_source: int = 700) -> str:
    """Group registered evidence under the sub-question it answers."""
    blocks: list[str] = []
    for finding in sub_findings:
        lines = [f"## {finding['question']}"]
        if finding.get("why"):
            lines.append(f"_Why this matters: {finding['why']}_")
        for source_id in finding.get("source_ids", []):
            source = registry.get(source_id)
            if not source:
                continue
            head = f"[{source['id']}] {source['title']}"
            if source["url"]:
                head += f" — {source['url']}"
            date = f" | {source['published_at'][:10]}" if source.get("published_at") else ""
            lines.append(f"\n{head} ({source['kind']}{date})\n{source['snippet'][:per_source]}")
        blocks.append("\n".join(lines))

    text = "\n\n".join(blocks)
    if len(text) > MAX_EVIDENCE_CHARS:
        text = text[:MAX_EVIDENCE_CHARS] + "\n\n[evidence truncated for length]"
        logger.warning("Evidence truncated to %d chars", MAX_EVIDENCE_CHARS)
    return text

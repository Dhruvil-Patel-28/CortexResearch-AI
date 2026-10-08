# CortexResearch — Market Pulse Radar + Deep-Research Engine

A personal, daily-use research workbench: it continuously pulls what's new across the
tech/market landscape, ranks it **against your interests** with a "why this matters to
you" line, and produces **detailed, verified, cited reports** — detailed enough that
you don't need to do manual follow-up research.

Not a chatbot wrapper. A pipeline: free multi-source ingestion → personalized ranking →
multi-hop research → claim-level verification → editorial reporting, with a live-streamed
agent timeline in the browser and a searchable library of everything you've ever saved.

## What it does day to day

1. **Pulse** (`/`) — everything genuinely new since your last visit, pulled from Hacker
   News, arXiv, RSS/blogs, Reddit, GitHub trending and Product Hunt, deduplicated and
   clustered across sources, then ranked by an LLM scorer that writes a personalized
   rationale per story.
2. **Deep brief** — click any story (or ask any question on `/research`) and watch the
   agent run live: planner → multi-hop researcher → writer → verifier → reviser. The
   final report follows a strict schema: TL;DR, executive summary, zero-prior-knowledge
   primer, key developments with per-claim citations and confidence, timeline,
   implications, risks, FAQ, glossary — plus a verification panel showing which claims
   were supported and which the reviser had to flag or remove.
3. **Digests** (`/digests`) — an LLM-free daily briefing assembled from top-scored
   stories (the intelligence was spent at ranking time), a "what changed since last
   digest" delta section computed from data (re-heated clusters = stories that came back
   with new sources or higher relevance), and one-click **delta briefs**: a full research
   run anchored on "what changed in X since [date]".
4. **Library** (`/library`) — hybrid search (BM25 + embeddings + cross-encoder rerank)
   over every ingested source and every published report, with optional GraphRAG for
   multi-hop "how do X and Y connect" questions.

## Architecture

```
Free sources (HN · arXiv · RSS · Reddit · GitHub · Product Hunt)
        │  adapters with timeout/retry/failure isolation
        ▼
Ingest → dedup → cluster → SQLite store (WAL)
        │
        ▼
Ranker: cheap prefilter → LLM score (structured output) → score cache
        │  zero LLM calls on cached reruns
        ▼
┌───────────────────────── Engine (FastAPI + LangGraph) ─────────────────────────┐
│ Planner → Researcher (multi-hop tool loop) → Writer → Verifier → Reviser       │
│ Retrieval: SQLite FTS5 BM25 ⊕ sentence-transformers dense, RRF-fused,          │
│            cross-encoder rerank, content-addressed auto re-index               │
│ Optional (flagged): LightRAG graph queries · Supermemory local                 │
│ SSE job streaming: plan / tools / sources / verification / token events        │
└────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
Next.js 16 UI (App Router, Tailwind v4): Pulse · Research · Live run view ·
Report reader (TOC, citation chips, confidence badges) · Digests · Library
        │
Scheduler worker (APScheduler): ingest+score cycle → daily digest → delivery (file/Slack)
```

**Everywhere, degradation is designed in:** retrieval works if embeddings fail, reports
ship if the reviser fails, digests never depend on an LLM, and GraphRAG/Supermemory are
feature flags the app never hard-depends on.

## Engineering highlights

- **System 1 / System 2 model routing** — every fast decision (item relevance,
  claim support, query classification) is routed through a calibrated S1 model
  (Jev) that returns a score, not prose. Decisions below a confidence threshold
  escalate to the chat tier ("System 2"); a local logistic-regression fallback
  trained on score history keeps the reflex alive when Jev is down, and a
  circuit breaker skips Jev after 3 consecutive failures. Every routed decision
  is visible in the run timeline and the report trace.
- **Guardrails on untrusted content** — every scraped page, search snippet and ingested
  item passes a prompt-injection scanner (six weighted heuristic categories, with
  quote/third-person detection so articles *about* injection aren't flagged) and a
  PII/secret scrubber (emails, phones, SSNs, Luhn-validated cards, API keys, JWTs).
  Scraped evidence is framed in `<untrusted>` delimiters with an explicit
  "data, not instructions" directive, model responses are checked on every LLM call,
  and user queries are screened before a run starts. What was caught is visible live
  in the run view and in the report trace.
- **Eval harness with Langfuse observability** — a threshold-gated guardrail eval
  (precision/recall over a deliberate attack corpus; CI fails on regression), an
  LLM-as-judge suite scoring reports on a 4-dimension rubric (groundedness
  weighted 2×) with deterministic facts computed in code, and a CLI runner
  (`python -m evals.runner`). Every research run traces into Langfuse
  (generations, S1/guardrail events, verification score) when keys are
  configured — and runs identically without it.
- **Claim-level verification** — the verifier checks every claim's citations
  deterministically first (missing/unknown source id → unsupported, no LLM call), then routes
  the remaining claims through S1, grouping low-confidence ones into a single
  fast-model escalation; the reviser is authoritative for the final `verification` block.
- **Report schema v2 with self-healing parsing** — LLM output is remapped through field
  aliases and salvaged per-entry, so one malformed row can't kill a whole report.
- **Hybrid retrieval over your own corpus** — FTS5 BM25 fused with exact cosine search
  over MiniLM vectors (numpy at personal-store scale — no faiss/torch OpenMP conflicts),
  reranked by a cross-encoder; the index is content-addressed and rebuilds itself when
  the store changes.
- **Live agent timeline** — first-class SSE event types with client-side replay dedupe
  and reconnection; no fake progress bars.
- **Cost metering** — per-run token/cost tracking with tiered model routing (fast tier
  for scoring/extraction, frontier tier for synthesis), surfaced on every report.
- **Offline test suite** — 123 tests, all fixture-based: adapters, dedup, ranker caching,
  digest boundaries, scheduler cycles, report schema, API contracts, retrieval legs,
  S1 routing (mocked Jev transport, escalation, circuit breaker).
  No test ever hits a live API or downloads a model.

## Quickstart

Docker (recommended):

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY
docker compose up --build
# Pulse:        http://localhost:3000
# API docs:     http://localhost:8000/docs
```

Local dev:

```bash
python -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env          # set ANTHROPIC_API_KEY
./venv/bin/uvicorn api.main:app --port 8000

cd web && npm install && npm run dev   # http://localhost:3001
```

Optional: run the scheduler worker for automatic ingest cycles and the daily digest:

```bash
./venv/bin/python -m watch.scheduler
```

Configuration is env-driven (models, schedule, digest thresholds, source knobs) — see
`.env.example`. Interests live in a profile (keywords, stack, goals, boosts, mutes),
editable at `/topics`.

## Project structure

```
sources/        feed adapters (HN, arXiv, RSS, Reddit, GitHub, Product Hunt) + base class
store/          SQLite persistence: items, scores, briefs, digests, jobs, settings
watch/          profile, ranker, dedup/clustering, digest builder, scheduler
rag/            hybrid retriever (BM25 + dense + rerank) + optional GraphRAG adapter
memory/         optional Supermemory client (flagged, graceful fallback)
agents/         planner / researcher / writer / verifier / reviser pipeline + jobs
schemas/        report schema v2 (alias remapping + per-entry salvage)
api/            FastAPI routes: /watch, /research (+SSE), /digests, /search, /health
web/            Next.js 16 frontend (App Router, Tailwind v4)
tests/          82 offline tests over fixtures
```

## Status

Actively developed. Roadmap: trends/momentum view, command palette, email delivery,
NotebookLM-style audio briefings.

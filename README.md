<div align="center">

# CortexResearch

**A market-pulse radar and deep-research engine that reads the internet for you.**

Six free sources in, a ranked and personalized radar out. Click anything and a multi-agent
pipeline researches it, verifies every claim against its citations, and writes a report
detailed enough that you don't have to follow up.

[![CI](https://github.com/Dhruvil-Patel-28/CortexResearch-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/Dhruvil-Patel-28/CortexResearch-AI/actions/workflows/ci.yml)
![tests](https://img.shields.io/badge/tests-246%20passing-3fb950)
![python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![engine](https://img.shields.io/badge/FastAPI%20%2B%20LangGraph-engine-009688)
![web](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![lint](https://img.shields.io/badge/lint-ruff%20clean-261230)

[The problem](#the-problem) · [Architecture](#architecture) · [A research run](#a-research-run-end-to-end) ·
[Under the hood](#under-the-hood) · [Quickstart](#quickstart) · [API](#api-surface)

</div>

---

## The problem

Staying current in tech is a manual job. You open ten tabs, skim the same story
three times, forget what mattered last week, and when something *does* matter you
research it by hand — reading blog posts, cross-checking claims, and still ending
up unsure which source said what.

CortexResearch turns that into a pipeline:

| Manual today | Here |
|---|---|
| Open ten sources | One feed, deduplicated **across** sources (the same story from HN + Reddit + two blogs collapses into one card with 4 source links) |
| Guess what matters to *you* | Every item is scored against your interest profile, with a written "why this matters to you" line |
| Research by hand | A multi-agent run: plan → multi-hop research → write → verify claims → revise |
| Trust the output blindly | Each key development cites its sources; unsupported claims get flagged or removed and the verification panel says which |
| Lose the thread | Everything saved is searchable — hybrid retrieval over every item and every report you have ever generated |

## The daily loop

```mermaid
flowchart TD
  START(["You open Cortex"]) --> PULSE["<b>Pulse</b><br/>everything new since your last visit<br/>deduped, clustered, ranked"]
  PULSE --> WHY["Every card answers: why does this matter to <i>you</i>?"]
  WHY --> DECIDE{"Worth the full picture?"}
  DECIDE -->|"yes"| BRIEF["<b>Deep brief</b><br/>planner → researcher → writer → verifier → reviser"]
  DECIDE -->|"not now"| SAVE["Bookmark it"]
  BRIEF --> REPORT["A cited report with TL;DR, primer, timeline,<br/>risks, FAQ and a verification panel"]
  REPORT --> LIB["<b>Library</b><br/>hybrid + graph search over items and reports"]
  SAVE --> LIB
  LIB --> DIGEST["<b>Digest</b><br/>daily briefing + what changed since last time"]
  DIGEST --> START

  classDef you fill:#0b1220,stroke:#1f6feb,color:#c9d1d9
  classDef action fill:#111827,stroke:#6366f1,color:#e5e7eb
  classDef out fill:#0b1f1a,stroke:#10b981,color:#d1fae5
  class START you
  class PULSE,WHY,DECIDE,BRIEF,SAVE,LIB action
  class REPORT,DIGEST out
```

## Architecture

```mermaid
flowchart TB
  subgraph SRC["Free sources · no paid feeds, no X/Twitter"]
    direction LR
    HN["Hacker News"]
    AX["arXiv"]
    RSS["RSS / blogs"]
    RD["Reddit"]
    GH["GitHub trending"]
    PH["Product Hunt"]
  end

  subgraph ENGINE["Python engine · FastAPI + LangGraph"]
    direction TB
    ING["Ingest<br/>per-adapter timeout, retry, failure isolation"]
    DEDUP["Dedup by URL + content hash<br/>cluster the same story across sources"]
    DB[("SQLite · WAL")]
    RANK["Ranker<br/>cheap prefilter → LLM score → cache"]
    RET["Retriever<br/>BM25 + dense → RRF → cross-encoder rerank"]
    AG["Agent graph<br/>planner → researcher → writer → verifier → reviser"]
    JOBS["Job runner<br/>SSE event stream"]

    ING --> DEDUP --> DB
    DB --> RANK --> DB
    DB --> RET --> AG
    AG --> DB
    JOBS --- AG
  end

  subgraph OPT["Feature-flagged, degrades gracefully"]
    direction LR
    MEM["Supermemory<br/>cross-session memory"]
    GR["LightRAG<br/>multi-hop graph"]
    LF["Langfuse<br/>traces + eval scores"]
  end

  subgraph WEB["Next.js 16 · App Router"]
    direction LR
    PULSE["Pulse"]
    LIVE["Live run"]
    REP["Report reader"]
    LIB["Library"]
    DIG["Digests"]
  end

  API["FastAPI HTTP + SSE"]
  SCH["APScheduler worker<br/>ingest cycles · daily digest · email / Slack"]

  SRC --> ING
  DB --> API
  JOBS --> API
  API --> WEB
  SCH --> DB
  DB -.-> MEM
  RET -.-> GR
  AG -.-> LF

  classDef src fill:#0b1220,stroke:#1f6feb,color:#c9d1d9
  classDef core fill:#111827,stroke:#6366f1,color:#e5e7eb
  classDef flag fill:#0b1f1a,stroke:#10b981,color:#d1fae5
  classDef ui fill:#0f0f14,stroke:#8b5cf6,color:#ede9fe
  class HN,AX,RSS,RD,GH,PH src
  class ING,DEDUP,DB,RANK,RET,AG,JOBS,API,SCH core
  class MEM,GR,LF flag
  class WEB ui
```

**Degradation is designed in, not hoped for.** Retrieval still answers if the
embedding model fails to load; a report still ships if the reviser crashes (a
schema-valid fallback is substituted); digests never call an LLM at all; and
GraphRAG, Supermemory and Langfuse are flags the app never hard-depends on.

## A research run, end to end

Nothing about the UI is simulated — the pipeline streams real events as it works.

```mermaid
sequenceDiagram
  autonumber
  actor U as You
  participant W as Next.js
  participant API as FastAPI
  participant J as Job runner
  participant G as Agent graph
  participant T as Tools
  participant S1 as Jev · System 1
  participant DB as SQLite
  participant LF as Langfuse

  U->>W: ask a question (or click "Deep brief" on a story)
  W->>API: POST /research/start
  API->>J: enqueue job, return job id
  API-->>W: job id
  W->>API: GET /research/jobs/:id/stream
  Note over W,API: text/event-stream, replays missed events on reconnect

  J->>G: stage: planner
  G->>S1: classify query + decompose into sub-questions
  S1-->>G: sub-questions with confidence
  G-->>W: plan, subq events

  loop multi-hop, until the evidence converges
    G->>T: search library + web, fetch pages
    T-->>G: evidence (injection-scanned, PII-scrubbed, untrusted-framed)
    T->>DB: read the local corpus
    G-->>W: tools, sources, guardrail events
  end

  G->>G: stage: writer — draft report v2
  G->>S1: claim_support decisions per claim
  S1-->>G: supported / unsupported + confidence
  G->>G: stage: verifier, then reviser only if needed
  G->>DB: persist report + citations + cost
  G-->>W: verification, done

  J->>LF: trace: generations, S1 routes, guardrails, verification score
  W-->>U: report with TOC, citation chips, confidence badges, export
```

Under the hood the graph is a LangGraph state machine with a bounded revision
pass — the verifier is authoritative for the final `verification` block, and a
low-confidence group of claims is escalated to the fast chat tier in **one**
call rather than one call per claim.

## Under the hood

<details open>
<summary><b>System 1 / System 2 routing</b> — calibrated decisions instead of prose</summary>

<br/>

Most "AI features" ask a chat model to answer a yes/no question in a paragraph and
then regex the answer out. Here, every fast decision (item relevance, claim
support, query classification) is a **calibrated decision** with a probability
attached — so "unsure" is a first-class outcome that escalates.

```mermaid
flowchart TD
  Q["Fast decision needed<br/>relevance · claim support · query class"]
  Q --> HAS{"JEV_API_KEY configured?"}
  HAS -->|"no"| LOCAL
  HAS -->|"yes"| BREAKER{"Circuit breaker open?<br/>3 consecutive failures"}
  BREAKER -->|"yes"| LOCAL
  BREAKER -->|"no"| JEV["Jev · POST /v1/systemone<br/>one <i>choice</i> question, no prose"]
  LOCAL["Local calibrated fallback<br/>logistic regression over score history"]
  JEV --> CONF{"confidence ≥ threshold"}
  LOCAL --> CONF
  CONF -->|"yes"| FAST["S1 decision returned<br/>label + probability + confidence"]
  CONF -->|"no"| S2["Escalate to System 2<br/>fast chat tier"]
  S2 --> DONE["Decision, with the route recorded"]
  FAST --> DONE

  classDef s1 fill:#0b1f1a,stroke:#10b981,color:#d1fae5
  classDef s2 fill:#1f1405,stroke:#f59e0b,color:#fef3c7
  classDef q fill:#0b1220,stroke:#1f6feb,color:#c9d1d9
  class JEV,FAST,LOCAL s1
  class S2,BREAKER s2
  class Q,HAS,CONF,DONE q
```

- The client speaks the real `/systemone` contract: one named `choice` question in,
  one answer out. The chosen option's probability is the score, Jev's derived
  confidence drives escalation.
- The fallback is a locally-fitted logistic regression over your own score history,
  so the reflex survives Jev being down or unconfigured.
- Every routed decision lands in the run timeline and the report trace — you can see
  *why* something was judged relevant or flagged unsupported.

</details>

<details>
<summary><b>Guardrails on untrusted content</b> — the internet is an injection vector</summary>

<br/>

Every scraped page, search snippet and feed item is hostile until proven otherwise:
a poisoned blog post can tell the model to ignore its instructions.

```mermaid
flowchart LR
  IN["Untrusted content<br/>pages · snippets · feed items"] --> INJ["Injection scan<br/>6 weighted heuristic categories<br/>quotes and third-person cases don't false-positive"]
  INJ --> PII["PII + secret scrub<br/>emails · phones · SSNs · Luhn cards · API keys · JWTs"]
  PII --> FRAME["Framed as data, never instructions<br/>delimited block + explicit directive"]
  FRAME --> MODEL["Model call"]
  MODEL --> OUT["Output check on every LLM call<br/>monitor · enforce · off"]
  OUT --> TRACE["Run trace<br/>what was caught, live in the UI"]

  classDef bad fill:#1f0a0a,stroke:#ef4444,color:#fee2e2
  classDef safe fill:#0b1f1a,stroke:#10b981,color:#d1fae5
  classDef mid fill:#111827,stroke:#6366f1,color:#e5e7eb
  class IN,INJ bad
  class PII,FRAME,OUT safe
  class MODEL,TRACE mid
```

A deliberate attack corpus and a threshold-gated precision/recall eval keep this
honest: **CI fails if detection regresses**, and the corpus includes near-misses
(articles *about* prompt injection, legitimate PII) so the scanner can't win by
flagging everything.

</details>

<details>
<summary><b>Retrieval</b> — hybrid, reranked, and always local-first</summary>

<br/>

```mermaid
flowchart LR
  Q["Query"] --> FTS["SQLite FTS5 · BM25<br/>exact terms, no training"]
  Q --> DENSE["Dense · MiniLM vectors<br/>exact cosine in numpy"]
  FTS --> RRF["Reciprocal-rank fusion · k=60<br/>no score calibration needed"]
  DENSE --> RRF
  RRF --> RERANK["Cross-encoder rerank<br/>ms-marco-MiniLM-L-6"]
  RERANK --> HITS["Ranked passages over<br/>every ingested item + every report"]
  HITS --> GRAPH{"GraphRAG enabled?"}
  GRAPH -->|"yes"| ANSWER["Plus a graph-synthesized answer<br/>for 'how do X and Y connect'"]
  GRAPH -->|"no"| PLAIN["Ranked hits only"]

  classDef leg fill:#0b1220,stroke:#1f6feb,color:#c9d1d9
  classDef fuse fill:#111827,stroke:#6366f1,color:#e5e7eb
  classDef out fill:#0b1f1a,stroke:#10b981,color:#d1fae5
  class Q,FTS,DENSE leg
  class RRF,RERANK,HITS fuse
  class ANSWER,PLAIN out
```

numpy instead of faiss is deliberate at personal-corpus scale: no OpenMP/torch
conflicts, no prebuilt index to go stale. The index is content-addressed and
rebuilds itself when the store changes, so the old "stale prebuilt `faiss_index/`"
failure mode is gone. Both the embedder and the reranker are injectable, which is
how the retrieval tests run with no model download.

</details>

<details>
<summary><b>Data model</b> — one SQLite file, no services to run</summary>

<br/>

```mermaid
erDiagram
  ITEMS ||--o{ SCORES : "scored once per topic"
  TOPICS ||--o{ SCORES : "profile of interest"
  ITEMS ||--o{ BRIEFS : "researched into"
  TOPICS ||--o{ BRIEFS : "delta briefs"
  ITEMS ||--o| BOOKMARKS : "saved by you"
  DIGESTS }o--o{ ITEMS : "curates top stories"
  JOBS ||--o| BRIEFS : "produces"

  ITEMS {
    text id PK
    text source
    text external_id
    text title
    text url
    text published_at
    text content_hash
    text cluster_key
    text first_seen_at
  }
  SCORES {
    text item_id FK
    text topic_id FK
    real relevance
    text rationale
    text tags_json
    text profile_version
    text scored_at
  }
  BRIEFS {
    text id PK
    text item_id FK
    text topic_id FK
    text query
    text status
    text report_json
    text citations_json
    real cost_usd
  }
  DIGESTS {
    text id PK
    text item_ids_json
    text rendered_md
    text delivered_json
  }
  JOBS {
    text id PK
    text kind
    text status
    text progress_json
  }
  BOOKMARKS {
    text item_id PK
    text note
  }
```

Scores are cached by `(content_hash, profile_version)`: edit your interest profile
and everything is re-scored, re-run the same ingest and the ranker makes **zero LLM
calls** (there is a test that asserts exactly that).

</details>

## Engineering highlights

- **Personalization that is actually personal** — a YAML profile (interests, stack,
  goals, boosts, mutes) drives a cheap prefilter (recency + embedding similarity),
  then an LLM scores only the survivors with structured output. Changing the profile
  invalidates the cache via its version hash.
- **Claim-level verification** — each claim's citations are checked deterministically
  first (missing or unknown source id → unsupported, no LLM call), the rest go through
  S1, and the reviser is authoritative for the final verdict.
- **Report schema v2 with self-healing parsing** — output is remapped through field
  aliases and salvaged per entry, so one malformed row can't destroy a report, and a
  failed pipeline still returns something schema-valid instead of an exception.
- **Cost metering** — tiered models (fast tier for scoring/extraction, frontier for
  synthesis), per-run token and dollar accounting surfaced on every report.
- **MCP server** — the whole app over stdio for MCP clients like Claude Desktop:
  `search_library`, `list_items`, `get_item`, `list_reports`, `get_report`,
  `start_research`, `get_research`. The tool core is SDK-free pure functions, so the
  entire surface is unit-testable without the SDK installed.
- **Eval harness** — a precision/recall gate over the injection corpus, plus an
  LLM-as-judge report suite on a four-dimension rubric (groundedness weighted 2×)
  with deterministic facts computed in code rather than asked of a model.
- **Real observability** — every run traces into Langfuse (generations, S1 routes,
  guardrail catches, verification score) via the v4 OTel SDK, and runs identically
  when Langfuse is absent.
- **Offline test suite** — 246 fixture-based tests: no live API, no model download,
  no network. A developer's real API keys can't leak into a test run (the suite
  clears them by construction).

## Stack

| Layer | Choice | Why |
|---|---|---|
| Engine | FastAPI | Async API + SSE streaming without a second framework |
| Agents | LangGraph | Explicit state machine beats an implicit while-loop |
| Storage | SQLite (WAL) + FTS5 | One file, no services, real BM25 |
| Retrieval | numpy + sentence-transformers + cross-encoder | Hybrid + rerank without faiss/torch conflicts |
| Fast decisions | Jev (TypeSafe System One) + local logistic fallback | Calibrated probabilities, not parsed prose |
| Frontend | Next.js 16 · Tailwind v4 · shadcn-style components | Server-rendered shell, streaming views |
| Scheduling | APScheduler | In-process worker, no queue to operate |
| Optional | LightRAG · Supermemory · Langfuse · MCP | All flagged, all optional |

## Quickstart

**Docker** (recommended):

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY
docker compose up --build
# Pulse:     http://localhost:3000
# API docs:  http://localhost:8000/docs
```

**Local dev**:

```bash
python -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env          # set ANTHROPIC_API_KEY
./venv/bin/uvicorn api.main:app --port 8000

cd web && npm install && npm run dev   # http://localhost:3001
```

Optional extras:

```bash
./venv/bin/python -m watch.scheduler                      # ingest cycles + daily digest
./venv/bin/python -m mcp_server.server                    # expose to MCP clients (stdio)
./venv/bin/python -m evals.runner                         # guardrail + report evals
```

Digest delivery is layered — the Markdown always lands in `data/digests/`, and the
same digest goes out as HTML + plain-text email and/or Slack when configured:

| Channel | Enable with |
|---|---|
| File | Always on |
| Email | `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `DIGEST_EMAIL_TO` |
| Slack | `SLACK_WEBHOOK_URL` |

With Gmail, use a 16-character [App Password](https://myaccount.google.com/apppasswords),
not your login password. Port 587 upgrades with STARTTLS, 465 uses implicit SSL, and a
failed send never blocks the digest.

## API surface

<details>
<summary>Endpoints (all JSON; <code>/research/jobs/&#123;id&#125;/stream</code> is SSE)</summary>

<br/>

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/watch/feed` | Ranked items (window, source, topic, score filters) |
| `GET` | `/watch/items/{id}` | Item detail + cross-source coverage |
| `POST` | `/watch/items/{id}/bookmark` | Save / unsave |
| `GET` | `/watch/profile` · `POST` `/watch/refresh` · `GET` `/watch/jobs/{id}` | Interest profile · manual ingest · job state |
| `GET` | `/watch/stats` | Corpus and score counts for the UI |
| `POST` | `/research/start` | Start a research job |
| `POST` | `/research/items/{id}/brief` | Deep brief for a story |
| `GET` | `/research/jobs/{id}` · `/research/jobs/{id}/stream` | Job state · live SSE events (replays past events to late subscribers) |
| `GET` | `/research/reports` · `/research/reports/{id}` | Report library · full report |
| `DELETE` | `/research/reports/{id}` | Delete a report |
| `GET` | `/research/reports/{id}/export` | Markdown / PDF export |
| `GET` | `/digests/preview` · `/digests/{id}` | Digest preview · stored digest |
| `POST` | `/digests/run` · `/digests/delta` | Build now · delta brief on a topic |
| `GET` | `/search` | Hybrid search over items + reports (+ graph answer) |
| `GET` | `/health` | Health, including which S1 backend is live |

</details>

## Project structure

```
sources/     feed adapters (HN, arXiv, RSS, Reddit, GitHub, Product Hunt) + shared base
store/       SQLite persistence: items, scores, topics, briefs, digests, jobs, bookmarks
watch/       interest profile, ranker + score cache, dedup/clustering, digest, scheduler
rag/         hybrid retriever (BM25 + dense + RRF + rerank) + optional LightRAG adapter
agents/      LangGraph pipeline: planner, researcher, writer, verifier, reviser + jobs
utils/       config, LLM tiers + JSON calls, System 1 routing, tracing, cost meter
guardrails/  injection scanner, PII/secret scrubber, output policy, run trace
evals/       guardrail gate + LLM-as-judge report suite + CLI runner
memory/      optional Supermemory client, write hooks, research recall
mcp_server/  stdio MCP server: 7 tools over the store and job runner
api/         FastAPI routes: /watch, /research (+SSE), /digests, /search, /health
web/         Next.js 16 frontend (App Router, Tailwind v4)
tests/       offline fixture-based test suite (246 tests)
docs/        design specs for each phase
```

## Status

Actively developed. Roadmap: trends/momentum view, command palette, audio briefings,
multi-user accounts.

Every phase has a written design spec in `docs/superpowers/specs/`, and each one landed
with its tests: source intake, personalization, the report engine, streaming jobs,
digests, guardrails, evals, tracing, System 1 routing, memory, GraphRAG and the MCP server.

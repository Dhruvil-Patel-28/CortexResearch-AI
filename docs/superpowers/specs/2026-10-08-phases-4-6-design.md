# Phases 4–6 — Supermemory Enablement, GraphRAG Enablement, MCP Server — Design Spec

Date: 2026-10-08
Status: Draft for review
Project: CortexResearch-AI

## 1. Goal

The adapters for the three remaining roadmap features exist but are inert:
Supermemory and LightRAG have search-route plumbing only (no write path, no
indexing hook, and LightRAG's construction doesn't match its real API), and no
MCP surface exists. These phases make all three real, flagged, and
gracefully-degrading:

- **Phase 4 — Supermemory (cross-session memory)**: the app *remembers* into
  Supermemory (published reports, bookmarks, searches, digests) and *recalls*
  from it (related past work injected into research runs, library search).
  SQLite remains the source of truth; Supermemory is additive.
- **Phase 5 — GraphRAG (LightRAG)**: multi-hop entity-graph retrieval over the
  saved corpus. Indexing is wired into the retriever's auto-reindex path and
  LightRAG is constructed with real LLM + embedding functions (the current
  `embedding_model=` kwarg would fail). Stays off by default; hybrid retrieval
  unaffected when off.
- **Phase 6 — MCP server**: expose the app to any MCP client (Claude Desktop,
  IDEs) over stdio: search the library, list/read reports, browse the pulse
  feed, query the graph, and start/check research runs. Core tool functions
  live in a plain, SDK-free module; the FastMCP wrapper is a thin layer.

Success criteria: every feature works when enabled, is invisible when
disabled, all suites run offline (fakes for the SDK/service boundary), and
existing 215 tests stay green.

## 2. Phase 4 — Supermemory

### Current state
`memory/supermemory.py` has `remember()` / `search()` / `get_memory()` with
correct failure isolation. `api/routes/search.py` calls `search()` when
enabled. **Nothing ever calls `remember()`** — the memory never accumulates.
`SessionManager` (SQLite) handles per-session chat history separately.

### Changes

1. **`memory/remember.py`** (new) — one function per memory-worthy event, all
   best-effort (log + return on failure), all no-op when
   `get_memory()` is None:
   - `remember_report(report)` — published research: title, query, tldr lines,
     report id. (`kind: "report"`)
   - `remember_bookmark(item, note)` — bookmarked pulse items. (`kind: "bookmark"`)
   - `remember_search(query)` — library/research searches, throttled: skip if
     the same query text was remembered (dedupe via a small in-process LRU).
   - `remember_digest(digest)` — weekly digest summaries. (`kind: "digest"`)
   Metadata always carries ids so sources can be linked back.
2. **Write hooks (4 sites, one line each + import)**:
   - research run success → `remember_report` in `_run_pipeline` final block
   - `POST /watch/items/{id}/bookmark` → `remember_bookmark`
   - `/library/search` + `/research/start` → `remember_search`
   - digest generation → `remember_digest`
3. **Recall path** — `memory/remember.py: recall(query, k)` →
   `search()` results formatted as prior-context text. In `run_research`,
   when Supermemory is on: recall before the planner runs; inject as a
   `Related past work` block into the planner's prompt context (behind the
   untrusted framing? No — this is *your own* stored text, trusted framing,
   clearly labelled "from your personal memory store").
4. **Config**: `SUPERMEMORY_URL` documented as e.g. `http://localhost:8080`
   (user's Docker mapping decides); add `.env.example` note. No new flags —
   `ENABLE_SUPERMEMORY` + URL already gate everything.

### Tests (offline)
`test_memory_remember.py` — fake Supermemory client (monkeypatched
`get_memory`): each remember_* builds the expected payload + metadata; no-op
when flag off; search dedupe; recall formatting; hooks fire (bookmark API test
with fake client; report publish test with fake).

## 3. Phase 5 — GraphRAG

### Current state
`rag/graph.py` queries fine in principle but: (a) `LightRAG(embedding_model=…)`
is not the real API — LightRAG needs `llm_model_func` + `embedding_func`;
(b) `index_docs()` is never called; (c) `rag.ainsert` is awaited incorrectly
(ainsert is async — called without await inside sync code).

### Changes

1. **Fix construction** (`rag/graph.py:_get_lightrag`): build LightRAG with
   - `llm_model_func`: async callable calling our `LLMClient(model_fast)`
     (thread-offloaded), returning text;
   - `embedding_func`: LightRAG `EmbeddingFunc` wrapping our MiniLM embedder
     (numpy cosine, same as the dense leg — no new models);
   - `working_dir=settings.graph_working_dir`.
2. **Wire indexing into auto-reindex**: in `Retriever._ensure_index`, after a
   successful rebuild, call `graph.index_docs(docs)` — it's already
   flag-guarded and idempotent (meta-table tracked ids), so this is two lines.
   Fix `index_docs` to run `ainsert` via `asyncio.run`/`loop.run_until_complete`
   safely from sync context (guard for a running loop — fall back to
   `asyncio.run` in a worker thread).
3. **Search route**: already wired (`/library/search` returns `graph`
   field). Add the graph answer as a `kind="graph"` retriever leg? No — keep
   the graph as its own response field (answers, not ranked docs); no change.
4. **Config/docs**: keep `ENABLE_GRAPH_RAG=false` default; `.env.example`
   gains `LIGHT_RAG_LLM_TIER=fast` and a note that `lightrag-hku` is an
   optional install (`pip install lightrag-hku`).
5. **requirements**: comment-only optional dependency (not installed by
   default; the app must import cleanly without it).

### Tests (offline)
`test_graphrag.py` — inject a fake `lightrag` module into `sys.modules`:
construction receives llm_model_func + embedding_func callables and wires
*our* models; `graph_results` happy path + query failure + disabled; 
`index_docs` inserts only new docs and persists meta ids; ainsert sync/async
bridge works; retriever reindex triggers indexing (fake graph module records
the call); all failure paths leave hybrid search untouched.

## 4. Phase 6 — MCP server

### Design

```
mcp_server/
  __init__.py
  tools.py        # pure functions — no SDK import, fully unit-testable
  server.py       # FastMCP wrapper (stdio), guarded import
```

**Tools** (all read-only or fire-and-forget; the app's API contract unchanged):

- `search_library(query, k=8)` — hybrid retrieval over items + reports
  (+ graph answer when enabled).
- `list_reports(limit=20)` / `get_report(report_id)` — from the store.
- `list_items(since_hours=24, limit=50)` — pulse feed window.
- `get_item(item_id)` — one pulse item with its score rationale.
- `start_research(query, depth="brief")` — returns job id immediately.
- `get_research(job_id)` — status + (when done) the report's tldr/sources.

`server.py` = `FastMCP("cortexresearch")` + `@mcp.tool()` wrappers + `main()`
entry (`python -m mcp_server.server`). stdio transport — the standard for
desktop clients. No auth (local single-user, matching the app).

**Config/docs**: none required beyond README — "Add to your MCP client config"
snippet (command: venv python, args: -m mcp_server.server, cwd: project).
`mcp>=1.2.0` added to requirements (small, pure-python, free).

### Tests (offline)
`test_mcp_tools.py` — every tool function against a seeded tmp store:
happy path, empty results, unknown ids, research job lifecycle with stubbed
pipeline. `server.py` import-guard tested with a fake `mcp` module
(tool registration calls observed) when the real SDK is absent.

## 5. Testing & verification (all phases)

- Offline pytest throughout: fakes at the service boundary (Supermemory HTTP,
  LightRAG module, MCP SDK). No new network dependencies in tests.
- Live verification: Supermemory — run the user's service, set URL, verify
  remember+recall end-to-end (user-side assist needed for port). GraphRAG —
  requires `pip install lightrag-hku` + live LLM key: verify one indexing
  cycle + one mix-mode query. MCP — `python -m mcp_server.server` boots, and
  a stdio smoke test drives one tool call.
- Full suite + ruff + tsc/eslint/build (no frontend changes expected; a
  settings-page flag label if trivial).

## 6. Rollout order (milestones → commit each)

| # | Milestone |
|---|---|
| 1 | Phase 4: `memory/remember.py` + write/recall hooks + tests |
| 2 | Phase 5: GraphRAG construction fix + indexing hook + fake-module tests |
| 3 | Phase 6: `mcp_server/tools.py` + tests |
| 4 | Phase 6: `mcp_server/server.py` (FastMCP) + fake-SDK test + README |
| 5 | Config/docs (.env.example, requirements, README) + full verification + live smoke |

## 7. Out of scope

Multi-user auth, cloud deployment, remote MCP transports (SSE/HTTP) — stdio
only for now; GraphRAG eval harness extension (retrieval-quality evals need a
labelled query set — deferred).

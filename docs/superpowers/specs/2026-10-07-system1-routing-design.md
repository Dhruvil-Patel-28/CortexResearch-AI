# Phase 1 — System 1 / System 2 Model Routing (Jev) — Design Spec

Date: 2026-10-07
Status: Draft for review
Project: CortexResearch-AI

## 1. Goal

Route every *fast decision* in the pipeline through a **System 1 model** — Jev
(TypeSafe AI, early access) — which returns calibrated scores/labels instead of
generated text. Low-confidence decisions **escalate to System 2** (chat-tier
deliberation). The expensive chat models are consulted only when the reflex is
unsure, and every decision's "brain" is visible in the run view and report trace.

Success criteria:

- Item ranking decisions run through S1; per-item cost for scoring drops by an
  order of magnitude (measured by the existing cost meter).
- Claim verification runs through S1 with escalation; verification verdicts keep
  their current schema and quality (checked by the Phase 3 eval harness later,
  by calibration smoke tests now).
- The run view shows, live, which brain handled each step (S1 reflex vs S2
  deliberation) and how many escalations happened.
- Nothing hard-depends on Jev being up: local fallback + circuit breaker; all
  tests run offline.

## 2. Background

Current tiers (utils/llm.py): `smart` (claude-sonnet-5-5, synthesis) and `fast`
(claude-haiku-4-5, scoring/extraction/verification). Every decision — "is this
item relevant?", "does this source support this claim?" — is a chat completion:
seconds of latency, hundreds of tokens, for an answer that is fundamentally a
number. A System 1 model inverts this: it *is* a decision function with a
calibrated confidence, at milliseconds latency.

The architectural pattern to demonstrate:

```
decision ──▶ S1 (Jev, ms, calibrated) ──confidence ≥ θ──▶ act
                    │
                    └──confidence < θ──▶ S2 (chat tier, seconds)──▶ act
```

## 3. Architecture

### 3.1 New module: `utils/system1.py`

Core types (Pydantic):

```python
class Decision(BaseModel):
    label: str            # task-specific, e.g. "relevant" / "supported"
    score: float          # 0..1 calibrated
    confidence: float     # 0..1 model's self-reported calibration
    backend: str          # "jev" | "local" | "s2:<model>"
    latency_ms: int

class S1Request(BaseModel):
    task: str             # "relevance" | "claim_support" | "query_class" | ...
    context: str          # item text / claim+evidence / query
    options: list[str]    # candidate labels
    profile_hint: str | None = None
```

Protocol + two backends:

- **`JevBackend`** — thin HTTP adapter (httpx, 5s timeout, 1 retry). Endpoint,
  model name and payload shape come from settings; the adapter is isolated so
  the real early-access contract is a small fix if it differs from the assumed
  `POST {base_url}/decisions` shape. API key from `.env` (`JEV_API_KEY`).
- **`LocalCalibratedBackend`** — logistic regression over the existing MiniLM
  embeddings (numpy only — no new heavy deps), trained at startup on the
  `scores` table history (relevance ≥ 7 → positive, ≤ 4 → negative). Keeps
  working offline and in CI; also the circuit-breaker target.

### 3.2 Router: `S1S2Router`

`decide(request) -> Decision`:

1. If S1 disabled → straight to S2 (current behaviour, bit-compatible).
2. Try S1 backend (Jev; on failure → local backend; recorded in `backend`).
3. If `confidence >= s1_confidence_threshold` (default 0.75) → return decision.
4. Else **escalate**: re-decide via the S2 chat tier (fast tier by default,
   configurable), returning `backend="s2:<model>"`.

Circuit breaker: 3 consecutive Jev failures → Jev skipped for the rest of the
process; health surfaced in `/health` (`s1: {"backend": "...", "healthy": bool}`).

Every decision appends to a per-process `DecisionLog` (ring buffer) consumed by
the run view and cost meter: task, backend, confidence, latency, escalated.

### 3.3 Integration points

**Ranker (`watch/ranker.py`)** — biggest win:
- Relevance scoring goes through the router (`task="relevance"`), keeping the
  existing `(content_hash, profile_version)` cache.
- The "why this matters to you" rationale is **generated lazily**: only for
  items whose S1 score passes the relevance threshold. Below-threshold items
  get no chat call at all. (Behaviour change: today every scored item gets a
  rationale; after this, low-relevance items show a score without one.)

**Verifier (`agents/verifier.py`)**:
- Per-claim `task="claim_support"` through the router; deterministic checks
  unchanged; batches retained for the S2 escalation path (escalated claims are
  grouped into one fast-tier call as today).
- `ClaimVerdict` gains `backend` + `confidence` fields.

**Query classification (new, `agents/planner.py`)**:
- At research start, one S1 decision (`task="query_class"`) classifies the
  question's domain(s) and whether the knowledge base is likely relevant; the
  planner prompt receives it as a hint. Failure is non-fatal (planner proceeds
  unhinted).

**Events (`agents/events.py` / run view)**:
- New SSE event type `route`: `{task, backend, confidence, escalated, latency_ms}`
  emitted as decisions happen during a run (verifier + query-class; ranking is
  off-run so it updates Pulse instead).
- `run-pipeline.tsx`: Verifier step shows an "S1 reflex · N escalations" line;
  a small badge per lane shows the brain used. Reports' `model_trace` gains
  `decisions: [{task, backend, confidence, latency_ms, escalated}]`.

### 3.4 Configuration (all `.env`-driven, matching existing patterns)

```
S1_ENABLED=true
JEV_API_KEY=            # empty → Jev skipped, local backend used
JEV_BASE_URL=https://api.typesafe.ai/v1
JEV_MODEL=jev-1
S1_CONFIDENCE_THRESHOLD=0.75
S1_ESCALATION_TIER=fast   # which chat tier deliberates
```

`.env.example` updated; keys never committed.

## 4. Testing (offline-first, per repo constraint)

- `JevBackend` tested against a scripted httpx `MockTransport` (success, 500,
  timeout, malformed body, rate limit).
- `LocalCalibratedBackend`: trains on synthetic score rows in a temp SQLite;
  asserts sane scores and positive/negative separation.
- Router: escalation on low confidence, circuit breaker after 3 failures,
  disabled-mode passthrough, decision-log contents.
- Ranker: cached rerun still makes zero LLM calls; below-threshold items make
  zero rationale calls (new assertion).
- Verifier: mocked router returning low-confidence forces exactly one grouped
  S2 call; verdict schema extended fields validated.
- All 91 existing tests stay green with `S1_ENABLED=false` default in test env.

## 5. Acceptance (day-1 demo)

1. Ingest with Jev configured → Pulse scores appear; cost meter shows the
   ranking pass costing near-zero vs the previous fast-tier pass.
2. Research run → run view live-shows `route` events: claim checks mostly S1,
   occasional "escalated to S2" highlights; report trace lists every decision.
3. Kill Jev (bad key) mid-session → circuit breaker trips, local backend takes
   over, run completes, `/health` reflects it.
4. `S1_ENABLED=false` → behaviour identical to today.

## 6. Rollout order (implementation milestones → commit each)

1. `utils/system1.py` core (types, backends, router, breaker, log) + tests
2. Ranker integration + lazy rationale + tests
3. Verifier integration + verdict fields + tests
4. Query classification + tests
5. `route` SSE event + run-view badges + report model_trace
6. Config/.env.example/README + live verification with real Jev key

## 7. Out of scope (later phases)

Guardrails (Phase 2), eval harness/calibration reporting (Phase 3), Langfuse
trace export (Phase 4 — decision log is designed to feed it), MCP (Phase 6).

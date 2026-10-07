# System 1/S2 Model Routing (Jev) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route all fast decisions (item ranking, claim verification, query classification) through a calibrated System 1 model (Jev, early-access API) with local fallback and confidence-based escalation to chat-tier System 2, fully visible in the run view.

**Architecture:** New `utils/system1.py` exposes `S1S2Router.decide(S1Request) -> Decision`. Two backends behind one protocol: `JevBackend` (httpx, 5s timeout) and `LocalCalibratedBackend` (logistic regression over the existing MiniLM embeddings, trained on the `scores` table). Low-confidence decisions escalate via a caller-supplied S2 callable. Circuit breaker degrades Jev → local after 3 consecutive failures. New `route` SSE events surface every decision in the UI.

**Tech Stack:** Python 3.14, Pydantic, httpx, numpy, sentence-transformers (existing dep), pytest.

**Spec:** `docs/superpowers/specs/2026-10-07-system1-routing-design.md`

## Global Constraints

- All tests offline: no live Jev/Anthropic calls in pytest; Jev tested via injected `httpx.MockTransport`.
- `S1_ENABLED=false` must reproduce today's behaviour exactly (existing 91 tests stay green, unmodified).
- No new heavy dependencies (numpy + sentence-transformers already present).
- Keys only in `.env` / `.env.example`; never committed. JEV settings follow the existing `Settings` field style in `utils/config.py` (snake_case, `Field(..., description=...)`).
- Every commit: `./venv/bin/python -m pytest tests/` green before committing.

## Review Focus

1. **Jev returns a label outside `options`** — expect: backend raises `JevError`, router falls back to local backend, run continues. Test: Task 1 (`test_jev_unknown_label_raises`).
2. **Jev returns out-of-range/malformed confidence** — expect: response rejected like any failure (never trusted). Test: Task 1 (`test_jev_malformed_body_raises`).
3. **Scores table too small to train on (<5 labeled rows)** — expect: local backend returns a neutral low-confidence decision, not a crash. Test: Task 2 (`test_local_backend_untrained_returns_neutral`).
4. **Router with S1 disabled or no backends** — expect: pure S2 passthrough identical to current behaviour. Test: Task 3 (`test_router_disabled_goes_straight_to_s2`).
5. **Event emission failure mid-verification** — expect: verification continues (telemetry never breaks a run). Test: Task 5 (`test_route_emit_failure_does_not_break_verifier`).

---

### Task 1: Core types + `JevBackend`

**Files:**
- Create: `utils/system1.py`
- Modify: `utils/config.py` (Settings: add `s1_enabled: bool = True`, `jev_api_key: str = ""`, `jev_base_url: str = "https://api.typesafe.ai/v1"`, `jev_model: str = "jev-1"`, `s1_confidence_threshold: float = 0.75`, `s1_escalation_tier: str = "fast"`)
- Test: `tests/test_system1.py`

**Interfaces:**
- Produces:
  - `class S1Request(BaseModel): task: str; context: str; options: list[str]; profile_hint: str | None = None`
  - `class Decision(BaseModel): label: str; score: float; confidence: float; backend: str; latency_ms: int; escalated: bool = False`
  - `class JevError(RuntimeError)`
  - `class JevBackend: def __init__(self, base_url: str, api_key: str, model: str, timeout_s: float = 5.0, transport: httpx.AsyncBaseTransport | None = None) -> None` … `def decide(self, request: S1Request) -> Decision`
  - `class SystemOneBackend(Protocol): def decide(self, request: S1Request) -> Decision`

- [ ] **Step 1: Write failing tests** in `tests/test_system1.py`: happy path (`test_jev_happy_path`) — inject `MockTransport` returning `{"label": "relevant", "score": 0.9, "confidence": 0.82}`, assert Decision fields and `backend == "jev"`; `test_jev_unknown_label_raises` (label `"banana"` not in options → `JevError`); `test_jev_malformed_body_raises` (confidence `"high"`, score 42 → `JevError`); `test_jev_http_500_raises`; `test_jev_timeout_raises` (transport sleeps > timeout).
- [ ] **Step 2: Run** `./venv/bin/python -m pytest tests/test_system1.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** types + `JevBackend.decide`: POST `{base_url}/decisions` with `{"model": ..., "task": ..., "context": ..., "options": [...], "profile_hint": ...}`, header `Authorization: Bearer <key>`; parse/validate label ∈ options, `0.0 <= score, confidence <= 1.0` (else `JevError`); measure latency with `time.monotonic()`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(s1): System 1 core types + Jev backend (mock-transport tested)`.

### Task 2: `LocalCalibratedBackend`

**Files:**
- Modify: `utils/system1.py`
- Test: `tests/test_system1.py`

**Interfaces:**
- Consumes: `S1Request`, `Decision`; sentence-transformer loader — reuse the model instance `rag/retriever.py` already loads if it exposes one; otherwise lazy module-level singleton `SentenceTransformer("all-MiniLM-L6-v2")` in `utils/system1.py`.
- Produces:
  - `class LocalCalibratedBackend: def fit(self, rows: list[tuple[str, float]]) -> None` … `def decide(self, request: S1Request) -> Decision` (raises `NotFittedError`-free: unfitted/undertrained returns neutral `Decision(label=options[0], score=0.5, confidence=0.0, backend="local", latency_ms≈0)`)

- [ ] **Step 1: Failing tests**: `test_local_backend_learns_keyword_split` — fit on rows where texts containing "kubernetes"/"devops" → 9.0 and "recipe"/"celebrity" → 2.0 (8 rows min); assert decide() scores a kubernetes text closer to 1.0 than a recipe text, and confidence of both > 0. `test_local_backend_untrained_returns_neutral` — decide() before fit → neutral decision, confidence 0.0. `test_local_backend_respects_options_order` — label is whichever option matches the side of 0.5.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**: fit() embeds texts, y = 1 if relevance ≥ 7 else 0 if ≤ 4 else dropped; if < 5 usable rows → stay unfitted. Full-batch gradient descent on logistic regression (numpy: 300 iters, lr 0.5, L2 1e-3, seed fixed). decide(): p = sigmoid(w·x+b); label = options[1] if p ≥ 0.5 else options[0]; confidence = abs(p − 0.5) × 2; score = p.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(s1): local calibrated fallback backend (numpy logistic regression)`.

### Task 3: Router, circuit breaker, decision log, `/health`

**Files:**
- Modify: `utils/system1.py`, `api/main.py` (`/health`), `utils/config.py` (nothing new — Task 1 added fields)
- Test: `tests/test_system1.py`

**Interfaces:**
- Consumes: both backends, settings fields from Task 1.
- Produces:
  - `class DecisionLog: def add(self, request: S1Request, decision: Decision) -> None` … `def recent(self, n: int = 50) -> list[dict]` (dicts: task, backend, confidence, latency_ms, escalated)
  - `class CircuitBreaker: def record_success(self) -> None; def record_failure(self) -> None; @property def healthy(self) -> bool; @property def skipped(self) -> bool` (fail_limit=3 consecutive)
  - `class S1S2Router: def __init__(self, backend: SystemOneBackend | None, fallback: SystemOneBackend | None, escalate: Callable[[S1Request], Decision] | None, threshold: float, log: DecisionLog, breaker: CircuitBreaker) -> None` … `def decide(self, request: S1Request) -> Decision`
  - `def build_router(escalate: Callable[[S1Request], Decision] | None = None) -> S1S2Router` — reads settings: no `jev_api_key` → Jev omitted; constructs local backend lazily; module-level `get_router()` singleton.

- [ ] **Step 1: Failing tests**: `test_router_disabled_goes_straight_to_s2` (backend=None → escalate() called once, returned decision `escalated=False`, logged); `test_router_escalates_on_low_confidence` (stub backend returns confidence 0.4 → escalate() called, decision `escalated=True`); `test_router_keeps_high_confidence` (confidence 0.9 → escalate never called); `test_circuit_breaker_trips_after_three_failures` (stub backend raising 3× → 4th call uses fallback, backend not consulted, breaker.skipped); `test_log_ring_buffer` (recent(n) caps and orders).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the three classes + `build_router`/`get_router`; `/health` payload gains `"s1": {"enabled": ..., "backend": "jev"|"local"|"off", "healthy": bool}`.
- [ ] **Step 4: Run** full suite → PASS (91 + new).
- [ ] **Step 5: Commit** `feat(s1): router with S2 escalation, circuit breaker, decision log`.

### Task 4: Ranker integration + lazy rationale

**Files:**
- Modify: `watch/ranker.py`, `utils/system1.py` (nothing)
- Test: `tests/test_ranker_s1.py`

**Interfaces:**
- Consumes: `get_router`, `S1Request(task="relevance", context=item title+summary, options=["low","high"], profile_hint=profile interests joined)`, existing `Profile`, store helpers used by `score_unscored`.
- Produces: `def score_batch_s1(items: list[dict], profile: Profile) -> list[dict]` (same dict shape as `score_batch` output, plus `"backend"` per item) … `def rationale_for(item: dict, profile: Profile, relevance: float) -> str` (fast-tier chat call via `get_llm(tier="fast")` + `call_json`, schema `Rationale(BaseModel): rationale: str`). `score_unscored` uses the S1 path when `settings.s1_enabled`, else `score_batch` unchanged.

- [ ] **Step 1: Failing tests** (stub router via monkeypatch on `watch.ranker.get_router`): `test_s1_scores_map_to_ten_point_scale` (stub Decision score 0.82 → relevance 8.2 rounded to 8, cached row written with backend "stub"); `test_below_threshold_items_skip_rationale` (relevance < 6 → rationale LLM call count 0, item dict has no rationale); `test_at_threshold_items_get_rationale` (relevance ≥ 6 → exactly one rationale call, text attached); `test_cache_still_prevents_llm_calls` (second run over same items → 0 router + 0 rationale calls); `test_s1_disabled_uses_legacy_path` (`settings.s1_enabled=False` → `score_batch` invoked, output identical to today).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Threshold: `RATIONALE_THRESHOLD = 6.0`. Escalation callable for ranking: none — S1 score below rationale threshold is simply not elaborated (cheap by design); router built with `escalate=None` here.
- [ ] **Step 4: Run** full suite → PASS.
- [ ] **Step 5: Commit** `feat(ranker): S1 relevance scoring with lazy rationale generation`.

### Task 5: Verifier integration + `route` events

**Files:**
- Modify: `agents/verifier.py` (`_judge(pending, *, meter)` → `_judge(pending, *, meter, state=None)`; `ClaimVerdict` gains `backend: str | None = None`, `confidence: float | None = None`)
- Test: `tests/test_verifier_s1.py`

**Interfaces:**
- Consumes: `get_router`, `S1Request(task="claim_support", context=claim + evidence + truncated source text (2000 chars), options=["supported","unsupported"])`; `emit_event(state, "route", task=..., backend=..., confidence=..., escalated=..., latency_ms=...)`; existing grouped fast-tier batch call as the escalation path.
- Produces: verdicts with `backend`/`confidence` populated from the winning decision (S2 escalations get `backend=f"s2:{settings.model_fast}"`, `confidence=1.0` — batch path has no per-claim confidence).

- [ ] **Step 1: Failing tests**: `test_high_confidence_s1_verdict_skips_llm` (stub router → confidence 0.9 "supported" → verdict backend "stub", no chat call counted); `test_low_confidence_claims_grouped_into_one_s2_call` (3 low-confidence claims → exactly 1 `call_json` invocation containing all 3 ids); `test_route_events_emitted_per_claim` (collect via stub emit → one `route` event per claim, fields match decision); `test_route_emit_failure_does_not_break_verifier` (emit raises → verdicts still returned); `test_s1_disabled_uses_legacy_judge` (settings off → today's single grouped call path, verdicts have backend None).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (thread `state` through from `verifier_node`; escalation callable groups low-confidence claims into the existing batch call and returns per-claim Decisions).
- [ ] **Step 4: Run** full suite → PASS.
- [ ] **Step 5: Commit** `feat(verifier): S1 claim verification with grouped S2 escalation + route events`.

### Task 6: Query classification in the planner

**Files:**
- Modify: `agents/planner.py`
- Test: `tests/test_planner_s1.py`

**Interfaces:**
- Consumes: `get_router`; two decisions per query: `S1Request(task="query_domain", options=["ai","cloud","devtools","security","hardware","other"])` and `S1Request(task="kb_relevance", options=["relevant","irrelevant"], context=query + top knowledge-base doc titles (500 chars))`.
- Produces: `def classify_query(query: str) -> dict` → `{"domain": str, "kb_relevant": bool}`; `planner_node` calls it inside try/except (any failure → `{}`) and appends `"classification hint: ..." ` to the planner user prompt when non-empty. Emits one `route` event (`task="query_class"`, backend of the domain decision).

- [ ] **Step 1: Failing tests**: `test_classify_query_returns_both_fields` (stub router returning "devtools" then "relevant" → `{"domain": "devtools", "kb_relevant": True}`); `test_planner_prompt_contains_hint` (planner prompt includes the hint line when classification succeeds); `test_classification_failure_is_non_fatal` (router raises → planner proceeds, no hint, no exception).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** full suite → PASS.
- [ ] **Step 5: Commit** `feat(planner): S1 query classification hint`.

### Task 7: Run-view + report trace visibility

**Files:**
- Modify: `web/src/lib/use-run-stream.ts` (add `"route"` to `EVENT_TYPES`), `web/src/lib/types.ts` (route fields: `task?, backend?, confidence?, escalated?, latency_ms?`), `web/src/components/run-pipeline.tsx`, `agents/writer.py` (report `model_trace.decisions`)
- Test: `tests/test_report_trace.py` (backend); frontend via `npx tsc --noEmit` + `npx eslint`

**Interfaces:**
- Consumes: `DecisionLog.recent()` via pipeline state (`state["decision_log"]` set in `agents/pipeline.py` at run start), `route` events.
- Produces: report `model_trace.decisions: [{task, backend, confidence, latency_ms, escalated}]` (≤ 50 entries); Verifier step in `run-pipeline.tsx` shows `S1 reflex · N escalations` (N = count of route events with `escalated: true`), plus a `backend` chip per verifier stage line.

- [ ] **Step 1: Failing backend test** `test_report_model_trace_includes_decisions`: pipeline stub run with a logged decision → `report["model_trace"]["decisions"][0]["task"] == "claim_support"`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** writer change. **Step 4: Run** → PASS.
- [ ] **Step 5: Frontend**: add `"route"` to EVENT_TYPES + types; in `run-pipeline.tsx` compute `escalations = events.filter(e => e.type === "route" && e.escalated).length` and render the Verifier detail suffix; per-step backend chip when a route event names it.
- [ ] **Step 6: `npx tsc --noEmit && npx eslint src`** → clean; **full pytest** → PASS.
- [ ] **Step 7: Commit** `feat(web): S1/S2 visibility — route events, escalation counter, report model_trace`.

### Task 8: Config, docs, live verification

**Files:**
- Modify: `.env.example`, `README.md` (System 1/S2 section), `api/main.py` (nothing beyond Task 3)

- [ ] **Step 1:** Append to `.env.example`: `S1_ENABLED`, `JEV_API_KEY=`, `JEV_BASE_URL=https://api.typesafe.ai/v1`, `JEV_MODEL=jev-1`, `S1_CONFIDENCE_THRESHOLD=0.75`, `S1_ESCALATION_TIER=fast` (with one-line comments). README: short "System 1 / System 2 routing" subsection with the escalation diagram from the spec.
- [ ] **Step 2:** Full suite + `pytest` + frontend build all green.
- [ ] **Step 3: Live verification (needs user's key in `.env`)**: restart API → ingest with S1 on → confirm near-zero ranking cost in logs/Pulse; one research run → observe `route` events and escalation counter; bad-key check → circuit breaker trips, `/health` shows `healthy: false`, run still completes. Record measured cost/latency deltas in the commit message body.
- [ ] **Step 4:** Commit `feat(s1): config + docs; live verification of Jev routing`.

## Self-review notes

- Spec §3.3 ranker/verifier/query-class → Tasks 4/5/6; §3.3 events+UI → Tasks 5/7; §3.4 config → Tasks 1/8; §4 tests → embedded per task; §5 acceptance → Task 8 Step 3. No gaps found.
- Names consistent: `S1S2Router.decide`, `Decision.escalated`, `get_router()` used by all consumers.
- Plan ≈ spec length; no function bodies beyond pinned algorithms (logistic regression hyperparams, escalation grouping).

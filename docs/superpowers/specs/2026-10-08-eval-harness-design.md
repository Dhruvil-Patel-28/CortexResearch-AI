# Phase 3 — Eval Harness: LLM-as-Judge, Guardrail Metrics, Langfuse Tracing — Design Spec

Date: 2026-10-08
Status: Implemented (all 6 milestones; live-verified)
Project: CortexResearch-AI

## 1. Goal

Phases 1–2 added judgement-bearing machinery — S1/S2 routing and guardrails —
but nothing *measures* it. This phase adds an **eval harness** that answers two
questions continuously and quantitatively:

1. **Are the guardrails any good?** Precision/recall over the deliberate attack
   corpus, computed offline and deterministically. Gated in CI.
2. **Are the reports any good?** LLM-as-judge scoring of published reports on a
   structured rubric (groundedness, coverage, coherence, citation hygiene),
   with results persisted locally and pushed to Langfuse.

Alongside this, **Langfuse tracing** (the user's existing Docker deployment)
becomes the observability backend: every LLM call, S1 decision, and guardrail
event from a research run is recorded as a Langfuse trace with scores. The
integration is lazily initialised and fully no-op when keys are absent, so
local development and CI never depend on Langfuse being up.

Success criteria:

- `python -m evals.runner --suite guardrails` prints a confusion matrix and
  precision/recall; a pytest asserts thresholds (≥ 0.9 both) so CI fails when a
  scanner change regresses detection.
- `python -m evals.runner --suite judge` scores a report fixture (or a real
  stored report) on 4 rubric dimensions via the fast-tier model with structured
  JSON output; a pytest with a stubbed judge validates the whole pipeline
  offline.
- With Langfuse keys present, a real run produces a trace in Langfuse with
  generations (model calls), S1 decisions and guardrail events as span
  metadata, and eval results attached as scores. Without keys, everything runs
  silently unaffected.
- All existing 192 tests stay green; no new mandatory runtime dependency for
  the app path (langfuse import is wrapped).

## 2. Background

What exists today:

- The attack corpus (`tests/fixtures/injection_corpus.json`, 12 attacks + 10
  benign) is only exercised as pass/fail per entry — no aggregate metrics, no
  regression gate beyond "all fixtures match".
- Report quality is asserted only structurally (schema validation, citation
  counts in tests). No qualitative measurement.
- No tracing backend. `model_trace` in reports and the SSE events are the only
  visibility, and they are ephemeral (per-run, not queryable).
- The user runs Langfuse in Docker (default port 3000 on localhost) and has
  asked for it explicitly.

## 3. Architecture

### 3.1 New package: `evals/`

```
evals/
  __init__.py
  datasets/
    golden_report.json        # schema-valid report v2 fixture for offline judging
  guardrails_eval.py          # precision/recall/confusion over the corpus
  report_judge.py             # LLM-as-judge rubric + structured scoring
  runner.py                   # CLI entrypoint (`python -m evals.runner`)
  results.py                  # result models + persistence to data/evals/
```

**`evals/guardrails_eval.py`**

`run() -> GuardrailEvalResult` — loads the corpus, runs `guardrails.injection.scan`
on every entry, and computes:

- per-category confusion (attack caught / missed, benign flagged / passed);
- precision, recall, F1 (attack class), plus per-category breakdown;
- action-correctness (entries also assert the expected allow/wrap/strip action,
  so a scanner that "detects but over-strips" still loses points).

The corpus lives where tests already use it; the eval imports the same file so
fixtures and metrics can never drift apart.

**`evals/report_judge.py`**

`judge_report(report: dict) -> JudgeResult` — one structured-output call to the
**fast-tier** model (`utils.llm_json.call_json`) scoring four dimensions, each
0–10 with a one-line rationale:

- `groundedness` — are claims supported by the cited sources (spot-check 3 key
  developments against their citations)?
- `coverage` — does the report fill the schema-v2 sections appropriate for its
  depth (tldr, summary, developments, implications, sources…)?
- `coherence` — reads as one analysis rather than stitched snippets?
- `citation_hygiene` — every key development has ≥ 1 real source; no dangling
  `[S#]` refs.

Plus an overall `weighted_score` (groundedness weighted 2×) and
`verdict` (publishable / needs-review). The judge prompt explicitly instructs
"score only, never rewrite" and caps input size. Deterministic fields
(section presence, citation counts) are computed in Python *first* and handed
to the judge as facts — the LLM judges quality, not arithmetic.

**`evals/runner.py`**

`python -m evals.runner --suite guardrails|judge|all [--report-id ID]`
- guardrails: prints the confusion matrix + metrics, exits 1 below thresholds.
- judge: scores `data/evals`-persisted result; `--report-id` judges a real
  stored report from the DB instead of the golden fixture.
- both suites write JSON results to `data/evals/<timestamp>-<suite>.json` and
  push scores to Langfuse when enabled.

**`evals/results.py`** — Pydantic result models shared by runner/tests/Langfuse
export (`GuardrailEvalResult`, `JudgeResult`, `JudgeDimension`), plus
`save()`/`latest()` persistence helpers (`data/evals/` is gitignored output).

### 3.2 Langfuse integration: `utils/tracing.py`

A thin, failure-isolated wrapper around the `langfuse` SDK:

```
class RunTrace:            # one per research run
    start(query, depth)    # creates trace, run metadata
    generation(model, label, usage, latency_ms)   # per LLM call
    event(name, payload)   # s1 decision, guardrail event, tool call
    score(name, value, comment)                    # eval scores, verification
    finish(status)
```

- Lazy singleton client: built on first use when `LANGFUSE_PUBLIC_KEY` +
  `LANGFUSE_SECRET_KEY` are set; otherwise every method is a no-op. **Any
  Langfuse error is swallowed and logged** — tracing must never fail a run.
- `LLMClient.invoke` records a generation (model, tier label, token usage,
  latency) when a `RunTrace` is active (context-var scoped, defaulting to none,
  so batch/ingest paths stay untraced unless wrapped).
- `run_research` opens a `RunTrace` for the whole run: S1 route events and
  guardrail events are mirrored into it alongside the SSE emissions, and the
  final verification block + report cost are attached as scores/trace metadata.
- Eval runner pushes `guardrail_precision`, `guardrail_recall`, and the four
  judge dimensions as Langfuse scores on a dedicated eval trace.
- New dependency `langfuse>=3.0.0` in requirements.txt — imported inside the
  wrapper only, so tests without the package installed still pass.

### 3.3 Configuration

```
LANGFUSE_PUBLIC_KEY=            # empty = tracing disabled
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_ENABLED=true           # master switch (keys also required)
EVALS_GUARDRAIL_MIN_PRECISION=0.9
EVALS_GUARDRAIL_MIN_RECALL=0.9
EVALS_JUDGE_MODEL=              # empty = model_fast tier
```

### 3.4 CI

The existing pytest job gains the threshold-gated eval tests (offline): the
guardrail metrics test and a stub-judge pipeline test. The real judge suite and
Langfuse export are local commands (`evals.runner`), not CI steps — no secrets
in CI, no network dependency.

## 4. Testing (all offline)

- `test_guardrails_eval.py` — metrics computed on the real corpus match a
  hand-computed confusion matrix; thresholds assert gates CI; per-category
  breakdown is complete.
- `test_report_judge.py` — stubbed `call_json` returns rubric JSON → result
  model validates; deterministic facts (section presence, citation counts) are
  computed correctly for the golden fixture; malformed judge JSON → clean
  `JudgeResult` with `verdict="error"`, never raises.
- `test_evals_runner.py` — CLI runs both suites end-to-end with stubs, writes
  result files, respects thresholds as exit codes.
- `test_tracing.py` — no keys → no-op everywhere (run completes, no crash);
  with a fake Langfuse client (monkeypatched) → generations/events/scores are
  recorded with expected names; Langfuse exception mid-run → run still
  completes.
- Existing suite untouched and green.

## 5. Acceptance (day-1 demo)

1. `python -m evals.runner --suite guardrails` → confusion matrix, P/R ≥ 0.9,
   JSON written to `data/evals/`.
2. `python -m evals.runner --suite judge` → 4-dimension scores + weighted
   overall for the golden report; visible in Langfuse when keys configured.
3. A live research run with Langfuse keys → trace in the Langfuse UI with
   generations, S1/guardrail events, and verification score; run with keys
   absent behaves exactly as Phase 2.
4. CI stays green with the new threshold-gated tests.

## 6. Rollout order (milestones → commit each)

1. `evals/guardrails_eval.py` + threshold tests (CI gate lands first — it
   protects the Phase 2 scanner from here on)
2. `evals/results.py` + golden report fixture
3. `evals/report_judge.py` + stub tests
4. `evals/runner.py` CLI + persistence + tests
5. `utils/tracing.py` (Langfuse wrapper) + LLMClient/run instrumentation + tests
6. Eval → Langfuse score export, config/docs, live verification

## 7. Out of scope (later phases)

GraphRAG enablement (Phase 5), MCP server (Phase 6), retrieval-quality evals
(needs a labelled query/relevance set — deferred until Phase 5 lands so graph
and hybrid retrieval can be compared on the same set), drift monitoring
dashboards.

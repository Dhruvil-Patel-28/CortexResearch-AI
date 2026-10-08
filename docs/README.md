# Design docs

Written before the code, kept as the record of *why* the system looks the way it
does. Each spec names the modules it covers and the verification that proves it
landed; the tests reference these decisions by name.

## Specs

| Document | Covers |
|---|---|
| [Guardrails](specs/2026-10-07-guardrails-design.md) | Untrusted-content pipeline: injection scanning, PII/secret scrubbing, instruction framing, output policy, run trace |
| [System 1 routing](specs/2026-10-07-system1-routing-design.md) | Calibrated fast decisions over Jev, the circuit breaker, the local logistic fallback, escalation to System 2 |
| [Eval harness](specs/2026-10-08-eval-harness-design.md) | Injection-corpus precision/recall gate and the LLM-as-judge report rubric |
| [Memory, GraphRAG, MCP](specs/2026-10-08-phases-4-6-design.md) | Supermemory-backed recall, the LightRAG graph layer, and the stdio MCP server |

## Plans

| Document | Covers |
|---|---|
| [System 1 routing plan](plans/2026-10-07-system1-routing.md) | Task breakdown for the routing work above |

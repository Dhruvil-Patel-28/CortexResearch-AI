"""System 1 routing core — offline tests via mocked Jev transport."""

import json
import time

import httpx
import pytest

from utils.system1 import JevBackend, JevError, S1Request


def _client(handler: httpx.MockTransport, timeout_s: float = 5.0) -> JevBackend:
    return JevBackend(
        base_url="https://jev.test/v1",
        api_key="test-key",
        model="jev-1",
        timeout_s=timeout_s,
        transport=handler,
    )


def _request() -> S1Request:
    return S1Request(
        task="relevance",
        context="some item text",
        options=["low", "high"],
        profile_hint="interests: AI agents",
    )


def _choice_response(label: str = "high", confidence: float = 0.82) -> dict:
    """A real /systemone response body (choice answer)."""
    other = {"low": 0.1, "high": 0.9} if label == "high" else {"low": 0.9, "high": 0.1}
    return {
        "model": "jev-1.13.0",
        "answers": {
            "decision": {
                "type": "choice",
                "choice": label,
                "probabilities": other,
                "confidence": confidence,
            }
        },
        "usage": {"input_tokens": 296, "output_tokens": 20},
    }


def test_jev_sends_the_real_systemone_contract() -> None:
    """The pinned wire format: POST /systemone with state + typed choice question."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["json"] = json.loads(request.read())
        return httpx.Response(200, json=_choice_response())

    _client(httpx.MockTransport(handler)).decide(_request())

    assert seen["url"].endswith("/v1/systemone"), "the endpoint is /systemone, not /decisions"
    assert seen["auth"] == "Bearer test-key"

    body = seen["json"]
    assert body["model"] == "jev-1"
    assert body["state"] == "some item text"
    question = body["questions"]["decision"]
    assert question["type"] == "choice"
    assert set(question["criteria"]) == {"low", "high"}, "options become the choice criteria keys"
    assert question["instructions"]["task"] == "relevance"
    assert question["instructions"]["profile"] == "interests: AI agents"


def test_jev_happy_path_maps_choice_to_decision() -> None:
    decision = _client(httpx.MockTransport(lambda r: httpx.Response(200, json=_choice_response()))).decide(
        _request()
    )
    assert decision.label == "high"
    assert decision.score == pytest.approx(0.9), "score is the chosen option's probability"
    assert decision.confidence == pytest.approx(0.82)
    assert decision.backend == "jev"
    assert decision.latency_ms >= 0
    assert decision.escalated is False


def test_jev_unknown_label_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_choice_response(label="banana"))

    with pytest.raises(JevError):
        _client(httpx.MockTransport(handler)).decide(_request())


def test_jev_wrong_answer_type_raises() -> None:
    """A score answer under a choice question is a contract violation."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {"decision": {"type": "noul", "noul": 0.9}},
                "usage": {},
            },
        )

    with pytest.raises(JevError):
        _client(httpx.MockTransport(handler)).decide(_request())


def test_jev_malformed_body_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _choice_response()
        body["answers"]["decision"]["confidence"] = "very"
        return httpx.Response(200, json=body)

    with pytest.raises(JevError):
        _client(httpx.MockTransport(handler)).decide(_request())


def test_jev_http_500_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(JevError):
        _client(httpx.MockTransport(handler)).decide(_request())


def test_jev_timeout_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        time.sleep(0.2)
        return httpx.Response(200, json=_choice_response())

    with pytest.raises(JevError):
        _client(httpx.MockTransport(handler), timeout_s=0.05).decide(_request())


# ── LocalCalibratedBackend ────────────────────────────────────────────

from utils.system1 import LocalCalibratedBackend

TECH = ["kubernetes cluster autoscaling devops pipeline", "devops observability kubernetes rollout",
        "kubernetes operator devops incident", "terraform kubernetes devops deploy"]
NOT_TECH = ["celebrity recipe pasta dinner", "recipe for celebrity bake off",
            "celebrity chef recipe show", "pasta recipe celebrity kitchen"]


def _fitted_backend(options: list[str]) -> LocalCalibratedBackend:
    backend = LocalCalibratedBackend()
    rows = [(t, 9.0) for t in TECH] + [(t, 2.0) for t in NOT_TECH]
    backend.fit(rows)
    assert options  # keep options in scope for readability
    return backend


def test_local_backend_untrained_returns_neutral() -> None:
    backend = LocalCalibratedBackend()
    decision = backend.decide(_request())
    assert decision.label == "low"
    assert decision.score == pytest.approx(0.5)
    assert decision.confidence == 0.0
    assert decision.backend == "local"


def test_local_backend_learns_keyword_split() -> None:
    backend = _fitted_backend(["low", "high"])
    tech = backend.decide(S1Request(task="relevance", context=TECH[0], options=["low", "high"]))
    not_tech = backend.decide(S1Request(task="relevance", context=NOT_TECH[0], options=["low", "high"]))
    assert tech.score > not_tech.score
    assert tech.score > 0.7
    assert not_tech.score < 0.3
    assert tech.confidence > 0 and not_tech.confidence > 0


def test_local_backend_respects_options_order() -> None:
    backend = _fitted_backend(["low", "high"])
    assert backend.decide(S1Request(task="t", context=TECH[0], options=["low", "high"])).label == "high"
    assert backend.decide(S1Request(task="t", context=NOT_TECH[0], options=["low", "high"])).label == "low"


def test_local_backend_undertrained_stays_neutral() -> None:
    backend = LocalCalibratedBackend()
    backend.fit([("kubernetes devops", 9.0), ("celebrity recipe", 2.0)])  # 2 rows < 5
    decision = backend.decide(S1Request(task="t", context="kubernetes", options=["low", "high"]))
    assert decision.confidence == 0.0


# ── Router / breaker / log ────────────────────────────────────────────

from utils.system1 import (
    CircuitBreaker,
    Decision,
    DecisionLog,
    S1S2Router,
)


def _stub_backend(label: str = "high", confidence: float = 0.9) -> LocalCalibratedBackend:
    class Stub:
        def __init__(self) -> None:
            self.calls = 0

        def decide(self, request: S1Request) -> Decision:
            self.calls += 1
            return Decision(label=label, score=0.9, confidence=confidence, backend="stub", latency_ms=1)

    return Stub()  # type: ignore[return-value]


def test_router_disabled_goes_straight_to_s2() -> None:
    calls: list[S1Request] = []

    def escalate(request: S1Request) -> Decision:
        calls.append(request)
        return Decision(label="high", score=0.8, confidence=1.0, backend="s2:fast", latency_ms=5)

    router = S1S2Router(backend=None, fallback=None, escalate=escalate, threshold=0.75, log=DecisionLog(), breaker=CircuitBreaker())
    decision = router.decide(_request())
    assert decision.backend == "s2:fast"
    assert decision.escalated is False
    assert len(calls) == 1


def test_router_escalates_on_low_confidence() -> None:
    def escalate(request: S1Request) -> Decision:
        return Decision(label="high", score=0.8, confidence=1.0, backend="s2:fast", latency_ms=5)

    backend = _stub_backend(confidence=0.4)
    router = S1S2Router(backend=backend, fallback=None, escalate=escalate, threshold=0.75, log=DecisionLog(), breaker=CircuitBreaker())
    decision = router.decide(_request())
    assert decision.escalated is True
    assert decision.backend == "s2:fast"


def test_router_keeps_high_confidence() -> None:
    def escalate(request: S1Request) -> Decision:  # pragma: no cover — must not run
        raise AssertionError("should not escalate")

    backend = _stub_backend(confidence=0.9)
    router = S1S2Router(backend=backend, fallback=None, escalate=escalate, threshold=0.75, log=DecisionLog(), breaker=CircuitBreaker())
    decision = router.decide(_request())
    assert decision.escalated is False
    assert decision.backend == "stub"


def test_circuit_breaker_trips_after_three_failures() -> None:
    class Failing:
        def __init__(self) -> None:
            self.calls = 0

        def decide(self, request: S1Request) -> Decision:
            self.calls += 1
            raise JevError("down")

    failing = Failing()
    fallback = _stub_backend(label="low", confidence=0.6)
    router = S1S2Router(backend=failing, fallback=fallback, escalate=None, threshold=0.75, log=DecisionLog(), breaker=CircuitBreaker())
    for _ in range(3):
        decision = router.decide(_request())
        assert decision.backend == "stub"
    assert failing.calls == 3
    decision = router.decide(_request())  # 4th call: breaker open, Jev skipped
    assert failing.calls == 3
    assert decision.backend == "stub"


def test_log_ring_buffer() -> None:
    log = DecisionLog()
    for i in range(7):
        log.add(_request(), Decision(label="x", score=0.5, confidence=0.5, backend="stub", latency_ms=i))
    recent = log.recent(5)
    assert len(recent) == 5
    assert [r["latency_ms"] for r in recent] == [2, 3, 4, 5, 6]
    assert recent[0]["task"] == "relevance"


def test_fetch_score_history_joins_items(tmp_path) -> None:
    from sources.base import FeedItem
    from store import db as store_db

    path = str(tmp_path / "t.db")
    store_db.init_db(path)
    i1 = FeedItem(source="hackernews", title="Kubernetes devops", url="https://x/1", raw_text="cluster text")
    i2 = FeedItem(source="hackernews", title="Celebrity recipe", url="https://x/2", raw_text="pasta")
    store_db.upsert_items([i1, i2], path=path)
    store_db.save_scores([
        {"item_id": i1.id, "relevance": 9.0, "profile_version": "v1"},
        {"item_id": i2.id, "relevance": 2.0, "profile_version": "v1"},
    ], path=path)
    rows = store_db.fetch_score_history(path=path)
    texts = dict(rows)
    assert texts["Kubernetes devops cluster text"] == 9.0
    assert texts["Celebrity recipe pasta"] == 2.0

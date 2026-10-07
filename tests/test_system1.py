"""System 1 routing core — offline tests via mocked Jev transport."""

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
    return S1Request(task="relevance", context="some item text", options=["low", "high"])


def test_jev_happy_path() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = request.read()
        return httpx.Response(200, json={"label": "high", "score": 0.9, "confidence": 0.82})

    decision = _client(httpx.MockTransport(handler)).decide(_request())
    assert decision.label == "high"
    assert decision.score == pytest.approx(0.9)
    assert decision.confidence == pytest.approx(0.82)
    assert decision.backend == "jev"
    assert decision.latency_ms >= 0
    assert decision.escalated is False
    assert seen["url"].endswith("/v1/decisions")
    assert seen["auth"] == "Bearer test-key"
    body = seen["body"].decode()
    assert '"task"' in body and '"relevance"' in body
    assert '"options"' in body and '"low"' in body and '"high"' in body


def test_jev_unknown_label_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"label": "banana", "score": 0.9, "confidence": 0.9})

    with pytest.raises(JevError):
        _client(httpx.MockTransport(handler)).decide(_request())


def test_jev_malformed_body_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"label": "high", "score": 42, "confidence": "high"})

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
        return httpx.Response(200, json={"label": "high", "score": 0.9, "confidence": 0.9})

    with pytest.raises(JevError):
        _client(httpx.MockTransport(handler), timeout_s=0.05).decide(_request())


# ── LocalCalibratedBackend ────────────────────────────────────────────

from utils.system1 import LocalCalibratedBackend  # noqa: E402

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

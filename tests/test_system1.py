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

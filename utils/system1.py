"""
System 1 / System 2 model routing.

System 1 = fast, calibrated *decisions* (Jev, or the local fallback) instead of
generated text. System 2 = chat-tier deliberation, consulted only when the
reflex is unsure. See docs/superpowers/specs/2026-10-07-system1-routing-design.md.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

import httpx
import numpy as np
from pydantic import BaseModel, Field

from utils.config import settings

logger = logging.getLogger(__name__)


class S1Request(BaseModel):
    """One fast decision to make."""

    task: str
    context: str
    options: list[str] = Field(min_length=2)
    profile_hint: str | None = None


class Decision(BaseModel):
    """The outcome of one routed decision."""

    label: str
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    backend: str
    latency_ms: int = 0
    escalated: bool = False


class JevError(RuntimeError):
    """Any Jev backend failure: HTTP, timeout, or contract violation."""


class SystemOneBackend(Protocol):
    def decide(self, request: S1Request) -> Decision: ...


class JevBackend:
    """Thin HTTP adapter for the Jev decision API.

    Isolated on purpose: the early-access contract is pinned here and nowhere
    else, so a real-world mismatch is a one-file fix. Callers inject `transport`
    (httpx.MockTransport) in tests.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout_s,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def decide(self, request: S1Request) -> Decision:
        payload = {
            "model": self._model,
            "task": request.task,
            "context": request.context,
            "options": request.options,
            "profile_hint": request.profile_hint,
        }
        started = time.monotonic()
        try:
            response = self._client.post("/decisions", json=payload)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:  # noqa: BLE001 — any transport/HTTP failure is a JevError
            raise JevError(f"Jev request failed: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        # Deadline enforcement lives here (not only in the transport) so slow
        # responses can never masquerade as fast decisions.
        if latency_ms > self._timeout_s * 1000:
            raise JevError(f"Jev deadline exceeded: {latency_ms}ms > {self._timeout_s}s")

        label = body.get("label")
        score = body.get("score")
        confidence = body.get("confidence")
        if (
            not isinstance(label, str)
            or label not in request.options
            or not isinstance(score, (int, float))
            or not isinstance(confidence, (int, float))
            or not (0.0 <= float(score) <= 1.0)
            or not (0.0 <= float(confidence) <= 1.0)
        ):
            raise JevError(f"Jev contract violation: {body!r}")

        return Decision(
            label=label,
            score=float(score),
            confidence=float(confidence),
            backend="jev",
            latency_ms=latency_ms,
        )


# ── Local calibrated fallback ──────────────────────────────────────────

_ST_MODEL: object | None = None


def _embed(texts: list[str]) -> np.ndarray:
    """Embed texts with the same MiniLM model the RAG dense leg uses."""
    global _ST_MODEL
    if _ST_MODEL is None:
        from sentence_transformers import SentenceTransformer

        _ST_MODEL = SentenceTransformer(settings.embedding_model)
    return _ST_MODEL.encode(  # type: ignore[attr-defined]
        texts, normalize_embeddings=True, show_progress_bar=False
    )


class LocalCalibratedBackend:
    """Logistic regression over MiniLM embeddings, trained on score history.

    Offline System 1: no API, no heavy deps. Undertrained → neutral decisions
    (confidence 0.0) so the router escalates instead of trusting a guess.
    """

    def __init__(self) -> None:
        self._w: np.ndarray | None = None
        self._b = 0.0

    def fit(self, rows: list[tuple[str, float]]) -> None:
        """rows = (text, relevance 0-10). ≥7 → positive, ≤4 → negative."""
        labeled = [(t, 1.0) for t, r in rows if r >= 7.0] + [(t, 0.0) for t, r in rows if r <= 4.0]
        if len(labeled) < 5:
            logger.info("S1 local backend undertrained (%d labeled rows) — staying neutral", len(labeled))
            self._w = None
            return
        texts = np.array([t for t, _ in labeled])
        y = np.array([v for _, v in labeled])
        x = _embed(list(texts))
        w = np.zeros(x.shape[1], dtype=np.float64)
        b = 0.0
        for _ in range(300):
            p = 1.0 / (1.0 + np.exp(-(x @ w + b)))
            w -= 0.5 * (x.T @ (p - y) / len(y) + 1e-3 * w)
            b -= 0.5 * float(np.mean(p - y))
        self._w, self._b = w, b

    def decide(self, request: S1Request) -> Decision:
        started = time.monotonic()
        if self._w is None:
            return Decision(
                label=request.options[0], score=0.5, confidence=0.0, backend="local", latency_ms=0
            )
        (vec,) = _embed([request.context])
        p = float(1.0 / (1.0 + np.exp(-(vec @ self._w + self._b))))
        label = request.options[1] if p >= 0.5 else request.options[0]
        return Decision(
            label=label,
            score=p,
            confidence=abs(p - 0.5) * 2,
            backend="local",
            latency_ms=int((time.monotonic() - started) * 1000),
        )

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


# ── Router / breaker / decision log ────────────────────────────────────

from collections import deque  # noqa: E402
from collections.abc import Callable  # noqa: E402

from pydantic import ValidationError  # noqa: E402


class DecisionLog:
    """Ring buffer of routed decisions, for the run view and report trace."""

    def __init__(self, maxlen: int = 500) -> None:
        self._entries: deque[dict] = deque(maxlen=maxlen)

    def add(self, request: S1Request, decision: Decision) -> None:
        self._entries.append(
            {
                "task": request.task,
                "backend": decision.backend,
                "confidence": round(decision.confidence, 3),
                "latency_ms": decision.latency_ms,
                "escalated": decision.escalated,
            }
        )

    def recent(self, n: int = 50) -> list[dict]:
        return list(self._entries)[-n:]


class CircuitBreaker:
    """After `fail_limit` consecutive backend failures, skip it for the process."""

    def __init__(self, fail_limit: int = 3) -> None:
        self._fail_limit = fail_limit
        self._consecutive_failures = 0

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        self._consecutive_failures += 1

    @property
    def healthy(self) -> bool:
        return self._consecutive_failures < self._fail_limit

    @property
    def skipped(self) -> bool:
        return not self.healthy


def _as_decision(result: object, default_backend: str) -> Decision:
    try:
        return Decision.model_validate(result)
    except ValidationError as exc:
        raise JevError(f"invalid decision from {default_backend}: {exc}") from exc


class S1S2Router:
    """S1 reflex first; escalate to a caller-supplied S2 path when unsure."""

    def __init__(
        self,
        backend: SystemOneBackend | None,
        fallback: SystemOneBackend | None,
        escalate: Callable[[S1Request], Decision] | None,
        threshold: float,
        log: DecisionLog,
        breaker: CircuitBreaker,
    ) -> None:
        self._backend = backend
        self._fallback = fallback
        self._escalate = escalate
        self._threshold = threshold
        self._log = log
        self._breaker = breaker

    @property
    def has_jev(self) -> bool:
        return self._backend is not None

    @property
    def has_fallback(self) -> bool:
        return self._fallback is not None

    @property
    def breaker(self) -> CircuitBreaker:
        return self._breaker

    def decide(self, request: S1Request) -> Decision:
        reflex_consulted = False
        last_reflex: Decision | None = None
        # Reflex 1: Jev (subject to its own circuit breaker).
        if self._backend is not None and self._breaker.healthy:
            reflex_consulted = True
            try:
                decision = self._backend.decide(request)
                self._breaker.record_success()
                last_reflex = decision
                if decision.confidence >= self._threshold:
                    self._log.add(request, decision)
                    return decision
            except Exception as exc:  # noqa: BLE001 — S1 failure must never break a run
                logger.warning("S1 backend failed (%s) — trying fallback", exc)
                self._breaker.record_failure()
        # Reflex 2: local classifier (never breaker-gated — it runs in-process).
        if self._fallback is not None:
            reflex_consulted = True
            try:
                decision = self._fallback.decide(request)
                last_reflex = decision
                if decision.confidence >= self._threshold:
                    self._log.add(request, decision)
                    return decision
            except Exception as exc:  # noqa: BLE001
                logger.warning("S1 fallback failed (%s) — escalating", exc)
        # System 2: deliberate. Escalation = a reflex ran and was unsure; with
        # S1 fully disabled, S2 is the primary path, not an escalation.
        if self._escalate is not None:
            decision = _as_decision(self._escalate(request), "s2").model_copy(
                update={"escalated": reflex_consulted}
            )
            self._log.add(request, decision)
            return decision
        # No S2 path: return the best reflex judgment we have (keeps runs alive
        # when the breaker trips), or a neutral decision if nothing ran.
        decision = last_reflex or Decision(
            label=request.options[0], score=0.5, confidence=0.0, backend="none"
        )
        self._log.add(request, decision)
        return decision


_router: S1S2Router | None = None


def build_router(escalate: Callable[[S1Request], Decision] | None = None) -> S1S2Router:
    """Build a router from settings. No JEV_API_KEY → local-only reflex."""
    backend: JevBackend | None = None
    if settings.s1_enabled and settings.jev_api_key:
        backend = JevBackend(
            base_url=settings.jev_base_url,
            api_key=settings.jev_api_key,
            model=settings.jev_model,
        )
    fallback: LocalCalibratedBackend | None = None
    if settings.s1_enabled:
        fallback = LocalCalibratedBackend()
        try:
            from store import db as store_db  # local import avoids a cycle in tests

            fallback.fit(store_db.fetch_score_history())
        except Exception as exc:  # noqa: BLE001 — training data is optional
            logger.info("S1 local backend untrained (%s) — neutral until history exists", exc)
    return S1S2Router(
        backend=backend,
        fallback=fallback,
        escalate=escalate,
        threshold=settings.s1_confidence_threshold,
        log=DecisionLog(),
        breaker=CircuitBreaker(),
    )


def get_router() -> S1S2Router:
    global _router
    if _router is None:
        _router = build_router()
    return _router

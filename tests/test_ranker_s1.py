"""Ranker S1 integration tests — offline, everything stubbed."""

from __future__ import annotations

import pytest

from sources.base import FeedItem
from store import db
from utils.system1 import CircuitBreaker, Decision, DecisionLog, S1Request, S1S2Router
from watch import ranker


class StubRouter(S1S2Router):
    """Router whose decide() returns canned decisions and counts calls."""

    def __init__(self, score: float, confidence: float = 0.9) -> None:
        super().__init__(
            backend=None,
            fallback=None,
            escalate=None,
            threshold=0.75,
            log=DecisionLog(),
            breaker=CircuitBreaker(),
        )
        self.score = score
        self.confidence = confidence
        self.calls = 0

    def decide(self, request: S1Request) -> Decision:
        self.calls += 1
        return Decision(
            label="high" if self.score >= 0.5 else "low",
            score=self.score,
            confidence=self.confidence,
            backend="stub",
            latency_ms=1,
        )


@pytest.fixture()
def seeded_db(tmp_path, monkeypatch):
    from utils.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "r.db"))
    monkeypatch.setattr(settings, "profile_path", str(tmp_path / "profile.yaml"))
    db.init_db()
    db.upsert_items(
        [
            FeedItem(
                source="hackernews",
                title="Agent evals framework",
                url="https://x/1",
                external_id="1",
                raw_text="eval harness for agents",
            ),
            FeedItem(
                source="hackernews",
                title="Another item",
                url="https://x/2",
                external_id="2",
                raw_text="something else",
            ),
        ]
    )
    yield


def _items() -> list[dict]:
    return [
        {
            "id": db.list_items(limit=1, order="newest")[0]["id"],
            "source": "hackernews",
            "title": "Agent evals framework",
            "raw_text": "eval harness",
            "metrics": {},
        },
    ]


def test_s1_scores_map_to_ten_point_scale(seeded_db, monkeypatch):
    from utils.config import settings

    monkeypatch.setattr(settings, "profile_path", str(seeded_db))  # unused, keep path sane
    stub = StubRouter(score=0.82)
    monkeypatch.setattr(ranker, "get_router", lambda: stub)
    profile = ranker.load_profile()
    rows = ranker.score_batch_s1(_items(), profile)
    assert rows[0]["relevance"] == pytest.approx(8.2)
    assert rows[0]["model"] == "s1:stub"
    assert stub.calls == 1
    db.save_scores(rows)
    cached = db.list_items(limit=1, order="newest")[0]
    assert cached.get("relevance") is not None, "score row must round-trip through the store"


def test_below_threshold_items_skip_rationale(seeded_db, monkeypatch):
    stub = StubRouter(score=0.4)
    monkeypatch.setattr(ranker, "get_router", lambda: stub)
    calls = []

    class FakeRunnable:
        def invoke(self, prompt):
            return ranker.Rationale(rationale="you should care")

    class FakeLLM:
        def with_structured_output(self, schema):
            calls.append(schema)
            return FakeRunnable()

    monkeypatch.setattr(ranker, "get_llm", lambda **kw: FakeLLM())
    profile = ranker.load_profile()
    rows = ranker.score_batch_s1(_items(), profile)
    assert rows[0]["relevance"] == pytest.approx(4.0)
    assert rows[0]["rationale"] == ""
    assert calls == []  # no chat model consulted below the threshold


def test_at_threshold_items_get_rationale(seeded_db, monkeypatch):
    stub = StubRouter(score=0.82)
    monkeypatch.setattr(ranker, "get_router", lambda: stub)
    calls = []

    class FakeRunnable:
        def invoke(self, prompt):
            return ranker.Rationale(rationale="you build evals, so this matters")

    class FakeLLM:
        def with_structured_output(self, schema):
            calls.append(schema)
            return FakeRunnable()

    monkeypatch.setattr(ranker, "get_llm", lambda **kw: FakeLLM())
    profile = ranker.load_profile()
    rows = ranker.score_batch_s1(_items(), profile)
    assert rows[0]["rationale"] == "you build evals, so this matters"
    assert len(calls) == 1


def test_cache_still_prevents_llm_calls(seeded_db, monkeypatch):
    stub = StubRouter(score=0.82)
    monkeypatch.setattr(ranker, "get_router", lambda: stub)

    class FakeRunnable:
        def invoke(self, prompt):
            return ranker.Rationale(rationale="matters to you")

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeRunnable()

    monkeypatch.setattr(ranker, "get_llm", lambda **kw: FakeLLM())
    first = ranker.score_unscored()
    assert first["scored"] == 2
    assert stub.calls == 2
    second = ranker.score_unscored()
    assert second["scored"] == 0
    assert second["skipped_cached"] == 2
    assert stub.calls == 2  # zero router calls on the cached rerun


def test_s1_disabled_uses_legacy_path(seeded_db, monkeypatch):
    from utils.config import settings

    monkeypatch.setattr(settings, "s1_enabled", False)
    legacy_calls = []
    monkeypatch.setattr(ranker, "score_batch", lambda *a, **kw: legacy_calls.append(1) or [])
    result = ranker.score_unscored()
    assert legacy_calls == [1]  # one batch of two items, legacy path
    assert "model" in result

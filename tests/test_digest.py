"""
Offline tests for digests, delta computation and the scheduler plumbing.

No network, no LLM: items and scores are seeded into a temporary store and the
digest is built from them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import ClassVar, Self

import pytest

from store import db as store
from utils.config import settings


@pytest.fixture()
def store_db(tmp_path, monkeypatch):
    """Point the whole app at a temporary database."""
    path = str(tmp_path / "digest-test.db")
    monkeypatch.setattr(settings, "db_path", path)
    monkeypatch.setattr(settings, "digest_dir", str(tmp_path / "digests"))
    store.init_db(path)
    return path


def _seed_item(item_id: str, *, title: str, source: str, score: float | None,
               hours_ago: float = 2, url: str | None = None,
               cluster_key: str | None = None, rationale: str = "you should care",
               path: str | None = None, published_at: str | None = None) -> str:
    """Seed one item (+ optional score). Returns the stored item id."""
    from sources.base import FeedItem

    now = datetime.now(timezone.utc)
    stamp = published_at or (now - timedelta(hours=hours_ago)).isoformat()
    item = FeedItem(
        source=source,
        title=title,
        url=url or f"https://example.com/{item_id}",
        external_id=item_id,
        published_at=stamp,
        raw_text=f"Body text of {title}.",
        metrics={"points": 100},
        cluster_key=cluster_key or "",
    )
    store.upsert_items([item], path=path)
    if score is not None:
        store.save_scores(
            [{
                "item_id": item.id,
                "relevance": score,
                "rationale": rationale,
                "tags": ["ai"],
                "model": "test",
                "profile_version": "test",
                "scored_at": stamp,
            }],
            path=path,
        )
    return item.id


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api.main import app
    from utils.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "digest-api.db"))
    monkeypatch.setattr(settings, "digest_dir", str(tmp_path / "digests"))
    store.init_db()
    return TestClient(app)


def test_digest_collects_only_scored_items_above_threshold(store_db):
    id_hi = _seed_item("hi", title="Hot AI release", source="hackernews", score=8.5)
    id_mid = _seed_item("mid", title="Mildly interesting", source="rss", score=6.2)
    _seed_item("low", title="Below the bar", source="reddit", score=4.0)
    _seed_item("unscored", title="Never scored", source="rss", score=None)

    from watch.digest import collect_digest_items

    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    items = collect_digest_items(since=since, min_score=6.0, limit=10)

    assert [i["id"] for i in items] == [id_hi, id_mid], "unscored and low-score items must not appear"


def test_digest_persists_and_anchors_next_digest_on_it(store_db, monkeypatch):
    id_a1 = _seed_item("a1", title="First story", source="hackernews", score=9.0)
    id_a2 = _seed_item("a2", title="Second story", source="rss", score=7.0)

    from watch.digest import build_digest

    first = build_digest(persist=True)
    assert first["id"]
    assert "First story" in first["markdown"]
    assert first["delta"]["new_clusters"] == 2
    assert first["delivered"] == ["file"], "no slack webhook configured in tests"

    stored = store.get_digest(first["id"])
    assert stored["rendered_md"] == first["markdown"]
    assert sorted(stored["item_ids"]) == sorted([id_a1, id_a2])

    # A second digest immediately after must find nothing new: the boundary is
    # the previous digest, not a fixed window — no repeated stories.
    second = build_digest(persist=True)
    assert second["items"] == []
    assert "Nothing new cleared the bar" in second["markdown"]


def test_delta_detects_reheated_clusters(store_db):
    from watch.digest import build_digest, collect_digest_items, compute_delta

    _seed_item("c1", title="Mistral ships a model", source="hackernews",
               score=8.0, cluster_key="cluster-mistral")
    first = build_digest(persist=True)
    assert first["delta"]["reheated"] == []

    # The same story comes back with a second source and a higher score, after
    # the first digest was created (so it clears the digest-time boundary).
    boundary = store.last_digest()["created_at"]
    later = (datetime.fromisoformat(boundary) + timedelta(seconds=5)).isoformat()
    _seed_item("c2", title="Mistral ships a model (TechCrunch)", source="rss",
               score=9.0, cluster_key="cluster-mistral", published_at=later)
    _seed_item("c3", title="Brand new story", source="reddit", score=8.8, published_at=later)

    previous = store.last_digest()
    since = previous["created_at"]

    items = collect_digest_items(since=since, min_score=6.0, limit=10)
    delta = compute_delta(items, previous)

    assert delta["new_clusters"] >= 1, "the brand-new story counts as new"
    reheated_titles = [r["title"] for r in delta["reheated"]]
    assert any("Mistral" in t for t in reheated_titles), "re-sighted cluster with new evidence is re-heated"


def test_preview_digest_persists_nothing(store_db):
    _seed_item("p1", title="Preview story", source="hackernews", score=7.5)

    from watch.digest import build_digest

    result = build_digest(persist=False)
    assert result["id"] == ""
    assert "Preview story" in result["markdown"]
    assert store.list_digests() == []


def test_delta_query_anchors_on_last_digest(store_db):
    from watch.digest import build_delta_query

    query_no_history = build_delta_query("vector databases")
    assert "vector databases" in query_no_history

    _seed_item("seed", title="x", source="rss", score=7.0)
    from watch.digest import build_digest

    build_digest(persist=True)
    query = build_delta_query("vector databases")
    assert "since " in query and "Focus only on developments after" in query


def test_scheduler_cycle_runs_ingest_score_digest(store_db, monkeypatch):
    """The full scheduled cycle, with ingest stubbed to seeded rows."""
    from watch import scheduler

    def fake_ingest(*, keywords=None, sources=None, progress=None):
        _seed_item("s1", title="Cycle story", source="hackernews", score=None)
        return {"new": 1, "duplicates": 0, "total_fetched": 1, "sources": {}, "duration_s": 0.1}

    def fake_score(limit=None, progress=None):
        _seed_item("s1", title="Cycle story", source="hackernews", score=8.2, hours_ago=0.001)
        return {"scored": 1, "skipped": 0}

    monkeypatch.setattr("watch.ingest.run_ingest", fake_ingest)
    monkeypatch.setattr("watch.ranker.score_unscored", fake_score)

    scheduler._safe_cycle(include_digest=True)

    digest = store.last_digest()
    assert digest and "Cycle story" in digest["rendered_md"]

    jobs = store.list_jobs(limit=5)
    assert any(j["kind"] == "scheduled_cycle" for j in jobs), "cycles are recorded as job rows"
    assert all(j["kind"] != "scheduled_cycle" or j["status"] == "pending" or j["status"] for j in jobs)


def test_digest_api_contract(client):
    """The digests API against the same temp store the client fixture configures."""
    from watch.digest import build_digest

    _seed_item("api1", title="API digest story", source="rss", score=8.4)
    built = build_digest(persist=True)

    listed = client.get("/digests").json()
    assert [d["id"] for d in listed] == [built["id"]]
    assert listed[0]["story_count"] == 1

    detail = client.get(f"/digests/{built['id']}").json()
    assert "API digest story" in detail["markdown"]
    assert client.get("/digests/nope").status_code == 404

    preview = client.get("/digests/preview?window_hours=24").json()
    assert preview["story_count"] == 1
    assert "API digest story" in preview["markdown"]

    again = client.post("/digests/run").json()
    assert again["story_count"] == 0, "immediately re-running must not repeat stories"


# ── Email delivery ────────────────────────────────────────────────────


class _FakeSMTP:
    """Records what would have been sent, instead of opening a socket."""

    sent: ClassVar[dict] = {}

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        _FakeSMTP.sent.update(host=host, port=port, timeout=timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def starttls(self, context: object | None = None) -> None:
        _FakeSMTP.sent["tls"] = True

    def login(self, user: str, password: str) -> None:
        _FakeSMTP.sent["login"] = (user, password)

    def send_message(self, message) -> None:
        _FakeSMTP.sent["message"] = message


@pytest.fixture()
def smtp_env(monkeypatch):
    """Configure SMTP settings + a fake SMTP class for one test."""
    from watch import digest as digest_mod

    _FakeSMTP.sent = {}
    monkeypatch.setattr(digest_mod.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_user", "me@gmail.com")
    monkeypatch.setattr(settings, "smtp_password", "app-password")
    monkeypatch.setattr(settings, "digest_email_to", "me@gmail.com")
    return _FakeSMTP.sent


def test_digest_emails_both_html_and_plain_text(store_db, smtp_env):
    _seed_item("e1", title="Emailed story", source="hackernews", score=8.5)

    from watch.digest import build_digest

    built = build_digest(persist=True)

    assert "email" in built["delivered"], "a configured SMTP must add the email channel"
    assert smtp_env["host"] == "smtp.gmail.com"
    assert smtp_env["port"] == 587
    assert smtp_env.get("tls") is True, "587 must upgrade with STARTTLS"
    assert smtp_env["login"] == ("me@gmail.com", "app-password")

    message = smtp_env["message"]
    assert message["To"] == "me@gmail.com"
    assert message["From"] == "me@gmail.com"
    assert "digest" in message["Subject"].lower()

    plain = message.get_body(preferencelist=("plain",)).get_content()
    assert "Emailed story" in plain, "a no-HTML client still gets the markdown"

    html = message.get_body(preferencelist=("html",)).get_content()
    assert "Emailed story" in html
    assert "<!doctype html>" in html.lower()
    assert "https://example.com/e1" in html, "story links survive into the email"

    stored = store.get_digest(built["id"])
    assert "email" in stored["delivered"], "the channel is recorded for the UI"


def test_email_escapes_html_and_splits_recipients(store_db, smtp_env, monkeypatch):
    monkeypatch.setattr(settings, "digest_email_to", "me@gmail.com, other@example.com")
    _seed_item("e2", title="RAG <script>alert(1)</script> & friends", source="rss", score=7.9)

    from watch.digest import build_digest

    built = build_digest(persist=True)

    assert smtp_env["message"]["To"] == "me@gmail.com, other@example.com"
    html = smtp_env["message"].get_body(preferencelist=("html",)).get_content()
    assert "<script>alert(1)</script>" not in html, "titles are escaped, not injected"
    assert "&lt;script&gt;" in html
    assert "RAG <script>alert(1)</script> & friends" in built["markdown"], "markdown keeps the raw title"


def test_email_failure_never_breaks_the_digest(store_db, monkeypatch):
    from watch import digest as digest_mod

    class BoomSMTP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise OSError("no route to host")

    monkeypatch.setattr(digest_mod.smtplib, "SMTP", BoomSMTP)
    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "smtp_user", "me@gmail.com")
    monkeypatch.setattr(settings, "smtp_password", "app-password")
    monkeypatch.setattr(settings, "digest_email_to", "me@gmail.com")

    _seed_item("e3", title="Survives a dead SMTP", source="hackernews", score=8.0)

    from watch.digest import build_digest

    built = build_digest(persist=True)

    assert built["delivered"] == ["file"], "delivery failure must not claim success"
    assert "Survives a dead SMTP" in built["markdown"]
    assert store.get_digest(built["id"]) is not None, "the digest is still persisted"

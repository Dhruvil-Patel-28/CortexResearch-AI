"""
API contract tests for the deep-research routes.

The pipeline itself is stubbed (its own tests live in test_research_engine.py);
what is verified here is the HTTP contract: starting runs, polling, SSE
streaming, the report library and exports.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from schemas.report import Source, coerce_report


def _stub_report(query: str, depth: str):
    report = coerce_report(
        {
            "title": "Stubbed deep brief",
            "tldr": ["A takeaway", "Another pass"],
            "executive_summary": "It happened.",
            "key_developments": [
                {"claim": "Claim", "evidence": "Because.", "sources": ["s1"], "confidence": "high"}
            ],
            "what_to_watch_next": ["Watch the pricing page"],
        },
        query=query,
        depth=depth,
    )
    report.sources = [
        Source(
            id="s1", title="Primary post", url="https://example.com/post", kind="web", quote="quote"
        ),
    ]
    report.verification.checked = 1
    report.verification.supported = 1
    report.cost_usd = 0.0123
    return report


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from utils.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "research.db"))

    from api.main import app
    from store import db

    db.init_db()
    return TestClient(app)


@pytest.fixture()
def stub_pipeline(monkeypatch):
    """Replace the real pipeline with a fast, deterministic stand-in."""
    calls: list[str] = []

    def fake_run_research(query, session_id=None, *, depth="standard", item_id=None, emit=None):
        calls.append(query)
        if emit:
            emit("stage", {"label": "Planning research", "pct": 5, "stage": "planning"})
            emit("plan", {"plan": {"sub_questions": []}, "pct": 10})
            emit("sources", {"sources": [{"id": "s1"}], "count": 1, "pct": 50})
            emit("verification", {"verification": {"checked": 1, "supported": 1}, "pct": 80})
        report = _stub_report(query, depth)
        return {
            "session_id": session_id or "test-session",
            "report": report.model_dump(),
            "citations": [
                {
                    "source_name": "Primary post",
                    "page_number": None,
                    "content_snippet": "quote",
                    "relevance_score": None,
                }
            ],
            "agent_steps": [
                {"agent_name": "Planner", "action": "Planned", "tools_used": []},
                {"agent_name": "Writer", "action": "Wrote", "tools_used": []},
            ],
            "verification": report.verification.model_dump(),
            "cost_usd": 0.0123,
            "model_trace": [{"model": "stub", "label": "planner", "cost_usd": 0.0123}],
            "duration_s": 0.5,
        }

    monkeypatch.setattr("agents.jobs.run_research", fake_run_research)
    return calls


def _wait_for(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/research/jobs/{job_id}").json()
        if body["status"] in {"done", "error"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish in time")


def test_run_lifecycle_from_start_to_export(client, stub_pipeline):
    started = client.post(
        "/research/start", json={"query": "What changed in GPU supply?", "depth": "brief"}
    )
    assert started.status_code == 200
    payload = started.json()
    assert payload["job_id"] and payload["brief_id"]

    snapshot = _wait_for(client, payload["job_id"])
    assert snapshot["status"] == "done"
    assert snapshot["pct"] == 100
    assert {"stage", "plan", "sources", "verification"} <= {e["type"] for e in snapshot["events"]}

    library = client.get("/research/reports").json()
    assert len(library) == 1
    summary = library[0]
    assert summary["id"] == payload["brief_id"]
    assert summary["title"] == "Stubbed deep brief"
    assert summary["source_count"] == 1
    assert summary["verification"]["supported"] == 1

    detail = client.get(f"/research/reports/{payload['brief_id']}").json()
    assert detail["report"]["title"] == "Stubbed deep brief"
    assert "[[s1]](https://example.com/post)" in detail["markdown"]
    assert stub_pipeline[0].startswith("What changed")

    md = client.get(f"/research/reports/{payload['brief_id']}/export?format=md")
    assert md.status_code == 200
    assert "Stubbed deep brief" in md.text
    assert "attachment" in md.headers["content-disposition"]

    raw = client.get(f"/research/reports/{payload['brief_id']}/export?format=json")
    assert json.loads(raw.text)["sources"][0]["id"] == "s1"

    assert client.delete(f"/research/reports/{payload['brief_id']}").status_code == 200
    assert client.get(f"/research/reports/{payload['brief_id']}").status_code == 404


def test_stream_delivers_events_then_closes(client, stub_pipeline):
    job_id = client.post("/research/start", json={"query": "Stream me"}).json()["job_id"]

    with client.stream("GET", f"/research/jobs/{job_id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(chunk for chunk in response.iter_text())

    assert "event: stage" in body
    assert "event: done" in body
    assert '"pct": 100' in body


def test_stream_replays_a_finished_run(client, stub_pipeline):
    job_id = client.post("/research/start", json={"query": "Replay me", "depth": "deep"}).json()[
        "job_id"
    ]
    _wait_for(client, job_id)

    body = client.get(f"/research/jobs/{job_id}/stream").text
    assert "event: queued" in body
    assert "event: done" in body
    assert body.count("data: ") >= 5


def test_item_brief_requires_a_known_item(client):
    assert client.post("/research/items/nope/brief").status_code == 404


def test_unknown_job_and_report_are_404(client):
    assert client.get("/research/jobs/nope").status_code == 404
    assert client.get("/research/reports/nope").status_code == 404
    assert client.get("/research/reports/nope/export").status_code == 404


def test_empty_query_is_rejected(client):
    assert client.post("/research/start", json={"query": "   "}).status_code == 400

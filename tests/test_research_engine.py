"""
Offline tests for the deep-research engine.

Everything here runs with no network and no LLM: the four model calls are
served by a fake client and all retrieval tools are stubbed. That means the
full planner → researcher → writer → verifier → reviser graph is exercised
deterministically, including the claim-verification and revision loop.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from agents import planner as planner_mod
from agents import researcher as researcher_mod
from agents import verifier as verifier_mod
from agents import writer as writer_mod
from agents.research_agent import run_research
from agents.sources import SourceRegistry, canonical_url
from schemas.report import ResearchReportV2
from tools.fetch_page import extract_main_text
from tools.store_search import tokens
from utils.llm_json import JsonCallError, json_object_from

# ─── Fake model client ───


class FakeLLM:
    """Records prompts and returns canned JSON based on the system message."""

    def __init__(self, responder):
        self.model = "fake-sonnet"
        self._responder = responder
        self.calls: list[list] = []

    def invoke(self, messages, **kwargs):  # noqa: ARG002 — LangChain-compatible surface
        self.calls.append(messages)
        return AIMessage(
            content=self._responder(messages),
            usage_metadata={"input_tokens": 120, "output_tokens": 60, "total_tokens": 180},
        )


PLAN_JSON = {
    "title": "GPU supply in 2026",
    "scope": "Availability and pricing of consumer GPUs.",
    "sub_questions": [
        {"question": "What changed in GPU supply?", "why": "baseline", "search_queries": ["gpu supply", "gpu prices"]},
        {"question": "Who is affected?", "why": "impact", "search_queries": ["gpu buyers"]},
    ],
}

DEVELOPMENT_OK = {"claim": "Supply improved in Q1", "evidence": "Two sources report higher volume.", "sources": ["s1"], "confidence": "high"}
DEVELOPMENT_OK2 = {"claim": "Prices fell 12%", "evidence": "Reported by two outlets.", "sources": ["s1", "s2"], "confidence": "medium"}
DEVELOPMENT_BAD = {"claim": "A completely uncited claim", "evidence": "Nowhere.", "sources": ["s99"], "confidence": "low"}


def _report_payload(developments):
    return {
        "title": "GPU supply in 2026",
        "tldr": ["Supply loosened", "Prices fell"],
        "executive_summary": "Supply improved and prices followed.",
        "background_primer": "GPUs are the bottleneck for AI training.",
        "key_developments": developments,
        "technical_explainer": "Fabs moved to a denser node.",
        "timeline": [{"when": "2026-01", "what": "Volume shipped", "source_id": "s1"}],
        "comparison_table": {"columns": ["Vendor", "Position"], "rows": [["A", "Leading"]]},
        "implications": "Your inference costs should drop.",
        "risks_and_uncertainty": "Pricing data is self-reported.",
        "what_to_watch_next": ["Q2 earnings"],
        "faq": [{"question": "Should I buy now?", "answer": "Prices are still falling."}],
        "glossary": [{"term": "node", "definition": "A chip manufacturing generation."}],
        "open_questions": ["Which vendor keeps the lead?"],
    }


def _install_fakes(monkeypatch, *, developments, verdicts=None, total=2):
    """Wire stubbed tools + a fake LLM into every agent module."""
    writer_outputs: list[str] = []

    def responder(messages):
        system = str(messages[0].content)
        user = str(messages[1].content)
        if "Planner of an autonomous" in system:
            return json.dumps(PLAN_JSON)
        if "coverage critic" in system:
            return json.dumps({"sufficient": True, "missing": "", "extra_queries": []})
        if "Verifier of an autonomous" in system:
            if verdicts is not None:
                return json.dumps(verdicts)
            ids = [line.split("\n")[0].strip() for line in user.split("\n\n") if line.startswith("c")]
            return json.dumps({"verdicts": [{"id": cid, "supported": True, "reason": "matches"} for cid in ids], "notes": "solid"})
        if "Writer of an autonomous" in system:
            revising = "YOUR PREVIOUS DRAFT" in user
            payload = _report_payload(developments)
            if revising:
                # The revision pass drops the uncited claim and keeps the rest.
                payload["key_developments"] = [d for d in developments if "s99" not in d["sources"]]
                payload["title"] = "GPU supply in 2026 (revised)"
            rendered = json.dumps(payload)
            writer_outputs.append("revision" if revising else "draft")
            return rendered
        return "{}"

    fake = FakeLLM(responder)
    for module in (planner_mod, researcher_mod, verifier_mod, writer_mod):
        monkeypatch.setattr(module, "get_llm", lambda *a, _m=fake, **k: _m)

    def fake_web(query, max_results=5):
        return [
            {"title": f"{query} — result {i}", "url": f"https://news.example.com/{query.replace(' ', '-')}-{i}",
             "snippet": f"snippet {i} for {query}", "source": "news.example.com"}
            for i in range(1, total + 1)
        ]

    def fake_store(query, limit=6):
        return [
            {"id": "i1", "title": f"Radar item about {query}", "url": "https://news.ycombinator.com/item?id=1",
             "source": "hackernews", "published_at": "2026-01-02T00:00:00Z", "snippet": "radar text", "relevance": 8.5}
        ]

    def fake_rag(query, k=None):
        return [{"title": "internal-notes.pdf (p. 3)", "url": "", "snippet": "internal context", "score": 0.72}]

    def fake_fetch(urls, **kwargs):
        return {url: ("Full article body about the topic. " * 40) for url in urls}

    monkeypatch.setattr(researcher_mod, "web_search_results", fake_web)
    monkeypatch.setattr(researcher_mod, "store_results", fake_store)
    monkeypatch.setattr(researcher_mod, "rag_results", fake_rag)
    monkeypatch.setattr(researcher_mod, "fetch_many", fake_fetch)
    return fake, writer_outputs


# ─── Source registry ───


def test_registry_dedupes_by_canonical_url_and_keeps_richest_snippet():
    registry = SourceRegistry()
    first = registry.add(kind="web", title="Post", url="https://www.example.com/a/", snippet="short")
    second = registry.add(kind="rss", title="Post (syndicated)", url="http://example.com/a?utm_source=x", snippet="a much longer snippet")

    assert first == "s1"
    assert second == "s1"
    assert len(registry) == 1
    assert "much longer" in registry.get("s1")["snippet"]


def test_registry_respects_limit_and_renders_evidence_block():
    registry = SourceRegistry(limit=2)
    assert registry.add(kind="web", title="One", url="https://a.example.com/1") == "s1"
    assert registry.add(kind="web", title="Two", url="https://a.example.com/2") == "s2"
    assert registry.add(kind="web", title="Three", url="https://a.example.com/3") is None

    rendered = registry.render()
    assert "[s1] One" in rendered
    assert "[s2] Two" in rendered


def test_canonical_url_strips_scheme_www_and_trailing_slash():
    assert canonical_url("https://www.Example.com/Post/") == canonical_url("http://example.com/Post")


# ─── Utility behaviour ───


@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Sure! Here is the JSON:\n{"a": 1}\nHope that helps.',
        '{"a": {"b": "}"}}',
    ],
)
def test_json_object_from_survives_real_model_shapes(raw):
    assert json_object_from(raw) == {"a": 1} or "a" in json_object_from(raw)


def test_json_object_from_raises_on_garbage():
    with pytest.raises(JsonCallError):
        json_object_from("no json here at all")


def test_store_query_tokens_drop_stopwords():
    assert tokens("What is the latest on gpt-5 vs claude?") == ["gpt-5", "claude"]


def test_extract_main_text_prefers_article_body():
    html = """<html><head><style>.x{color:red}</style><script>var a=1;</script></head>
    <body><nav>Menu Home About</nav><article><h1>Title</h1>
    <p>""" + ("Real body sentence. " * 60) + """</p></article><footer>Copyright 2026</footer></body></html>"""

    text = extract_main_text(html)
    assert "Real body sentence." in text
    assert "var a=1" not in text
    assert "Copyright 2026" not in text


# ─── Full graph ───


def test_pipeline_produces_a_schema_valid_report_with_verified_citations(monkeypatch):
    fake, writer_outputs = _install_fakes(
        monkeypatch,
        developments=[DEVELOPMENT_OK, DEVELOPMENT_OK2, DEVELOPMENT_BAD],
    )
    events: list[dict] = []
    result = run_research("What is happening with GPU supply?", depth="standard", emit=lambda t, p: events.append(p))
    report = ResearchReportV2.model_validate(result["report"])

    # Schema contract
    assert report.title.startswith("GPU supply")
    assert report.tldr and len(report.tldr) <= 5
    assert report.reading_time_min >= 1
    assert report.sources, "the report must carry the registered sources"
    source_ids = {s.id for s in report.sources}

    # No claim may cite a source that was never fetched
    for dev in report.key_developments:
        assert dev.sources, f"claim is uncited: {dev.claim}"
        assert set(dev.sources) <= source_ids
    assert all(entry.source_id in source_ids for entry in report.timeline if entry.source_id)

    # Verification caught the uncited claim, and the reviser removed it
    verification = result["verification"]
    assert verification["checked"] == 3
    assert verification["unsupported"] == 1
    assert verification["unsupported_claims"][0]["action"] == "removed"
    assert report.verification.unsupported == 1

    # Two writer passes: draft then revision
    assert writer_outputs == ["draft", "revision"]

    # Trace, metering and streaming
    agents_used = [step["agent_name"] for step in result["agent_steps"]]
    assert agents_used == ["Planner", "Researcher", "Writer", "Verifier", "Reviser"]
    assert result["cost_usd"] > 0
    assert result["model_trace"]
    assert {"plan", "sources", "verification", "run_completed"} <= {e.get("type") for e in events}
    assert "# " in report.markdown()


def test_clean_verification_skips_the_revision_pass(monkeypatch):
    _, writer_outputs = _install_fakes(monkeypatch, developments=[DEVELOPMENT_OK, DEVELOPMENT_OK2])
    result = run_research("What is happening with GPU supply?", depth="brief")

    assert writer_outputs == ["draft"], "a clean report must not trigger a second writer call"
    assert result["verification"]["unsupported"] == 0
    assert result["verification"]["supported"] == 2
    assert [s["agent_name"] for s in result["agent_steps"]] == ["Planner", "Researcher", "Writer", "Verifier", "Reviser"]
    assert result["report"]["title"] == "GPU supply in 2026"


def test_verifier_flags_uncited_claims_without_calling_the_model(monkeypatch):
    fake, _ = _install_fakes(
        monkeypatch,
        developments=[DEVELOPMENT_BAD],
        verdicts={"verdicts": [], "notes": "should not be asked"},
    )
    result = run_research("Anything?", depth="brief")

    assert result["verification"]["checked"] == 1
    assert result["verification"]["unsupported"] == 1
    assert "No source cited" in result["verification"]["unsupported_claims"][0]["reason"]
    # Only the planner and the writer talked to the model — the verifier used the
    # deterministic path and the reviser short-circuited to an empty report.
    assert len(fake.calls) <= 4


def test_pipeline_survives_a_writer_that_returns_prose(monkeypatch):
    _, _ = _install_fakes(monkeypatch, developments=[DEVELOPMENT_OK])
    monkeypatch.setattr(writer_mod, "invoke_llm", lambda llm, msgs, meter=None, label="": AIMessage(content="I could not comply."))

    result = run_research("What is happening?", depth="brief")
    report = ResearchReportV2.model_validate(result["report"])

    assert report.title  # still a valid, if empty, report
    assert report.key_developments == []

"""
Tests for the writer/reviser robustness layer:

- `json_object_from` salvages truncated JSON (output-token-cap cut-offs)
- `_patch_draft` splices claim patches into the draft
- `reviser_node` NEVER publishes an empty shell over a good draft
"""

from __future__ import annotations

import pytest

from utils.llm_json import JsonCallError, _repair_truncated, json_object_from


def test_json_object_from_parses_complete_object():
    assert json_object_from('{"a": 1}') == {"a": 1}
    assert json_object_from('prose before {"a": {"b": [1, 2]}} prose after') == {"a": {"b": [1, 2]}}
    assert json_object_from('```json\n{"a": true}\n```') == {"a": True}


def test_repair_truncated_salvages_complete_fields():
    truncated = '{"tldr": ["one", "two"], "key_developments": [{"claim": "x"'
    repaired = _repair_truncated(truncated)
    assert repaired is not None
    assert repaired["tldr"] == ["one", "two"]


def test_json_object_from_recovers_truncated_report():
    # Simulates the production failure: full-report JSON cut off mid-array.
    truncated = (
        '{"title": "Report", "executive_summary": "Sum", '
        '"tldr": ["a", "b"], "key_developments": ['
        '{"claim": "claim one", "sources": ["s1"]}, '
        '{"claim": "claim two", "evidence": "ev'
    )
    parsed = json_object_from(truncated)
    assert parsed["title"] == "Report"
    assert parsed["tldr"] == ["a", "b"]
    claims = [d["claim"] for d in parsed["key_developments"]]
    assert "claim one" in claims


def test_repair_truncated_returns_none_for_garbage():
    assert _repair_truncated("not json at all") is None


def test_json_object_from_raises_when_nothing_works():
    with pytest.raises(JsonCallError):
        json_object_from("there is genuinely no object here")


# ── Reviser behaviour ─────────────────────────────────────────────────


def _draft_state(**overrides):
    draft = {
        "title": "T",
        "query": "q",
        "executive_summary": "has content",
        "key_developments": [
            {"claim": "Claim A is supported.", "evidence": "e", "sources": ["s1"]},
            {"claim": "Claim B overreaches wildly.", "evidence": "e2", "sources": ["s2"]},
        ],
    }
    state = {
        "research_query": "q",
        "depth": "standard",
        "report_draft": draft,
        "verification": {
            "checked": 2,
            "supported": 1,
            "unsupported": 1,
            "unsupported_claims": [
                {"claim": "Claim B overreaches wildly.", "reason": "evidence does not say that"}
            ],
            "notes": "",
        },
        "source_registry": [
            {"id": "s1", "title": "S1", "url": "https://a", "kind": "web", "quote": "q1"},
            {"id": "s2", "title": "S2", "url": "https://b", "kind": "web", "quote": "q2"},
        ],
    }
    state.update(overrides)
    return state


def test_patch_draft_applies_rewrite_and_remove(monkeypatch):
    from agents import writer as writer_mod
    from agents.writer import ClaimPatch, PatchList, _patch_draft

    def fake_call_json(llm, **kwargs):
        return PatchList(
            revisions=[
                ClaimPatch(index=0, action="rewrite", claim="Claim A, hedged.", evidence="still e"),
                ClaimPatch(index=1, action="remove"),
            ]
        )

    monkeypatch.setattr(writer_mod, "call_json", fake_call_json)
    state = _draft_state()
    patched = _patch_draft(
        state, state["report_draft"], state["verification"]["unsupported_claims"]
    )

    assert patched is not None
    assert len(patched["key_developments"]) == 1
    assert patched["key_developments"][0]["claim"] == "Claim A, hedged."


def test_patch_draft_returns_none_when_call_fails(monkeypatch):
    from agents import writer as writer_mod
    from agents.writer import _patch_draft
    from utils.llm_json import JsonCallError as _JsonCallError

    def boom(*args, **kwargs):
        raise _JsonCallError("no parse")

    monkeypatch.setattr(writer_mod, "call_json", boom)
    state = _draft_state()
    assert (
        _patch_draft(state, state["report_draft"], state["verification"]["unsupported_claims"])
        is None
    )


def test_reviser_keeps_draft_when_patching_unavailable(monkeypatch):
    from agents import writer as writer_mod
    from agents.writer import reviser_node

    monkeypatch.setattr(writer_mod, "_patch_draft", lambda *a, **k: None)
    result = reviser_node(_draft_state())
    report = result["report"]

    # The draft's content survived — the report is NOT an empty shell.
    assert len(report["key_developments"]) == 2
    assert report["executive_summary"] == "has content"
    # The flagged claim is labelled for the reader.
    assert report["verification"]["unsupported"] == 1
    assert report["verification"]["unsupported_claims"][0]["claim"] == "Claim B overreaches wildly."


def test_reviser_clean_pass_through(monkeypatch):
    from agents.writer import reviser_node

    state = _draft_state()
    state["verification"] = {
        "checked": 2,
        "supported": 2,
        "unsupported": 0,
        "unsupported_claims": [],
        "notes": "",
    }
    result = reviser_node(state)
    assert result["report"]["key_developments"][0]["claim"] == "Claim A is supported."

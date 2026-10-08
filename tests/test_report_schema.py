"""Tests for the Report Schema v2 contract and the Markdown exporter."""

from __future__ import annotations

from schemas.report import ResearchReportV2, coerce_report, estimate_reading_time


def test_coerce_report_accepts_loosely_shaped_llm_json():
    report = coerce_report(
        {
            "title": "Model release roundup",
            "tldr": "One big takeaway",
            "key_developments": {
                "claim": "Something shipped",
                "sources": "s1",
                "confidence": "HIGH",
            },
            "what_to_watch_next": ["Pricing changes"],
            "sources": [{"id": "s1", "title": "Post", "url": "https://example.com/p"}],
            "verification": {"checked": 99},  # must be ignored: the pipeline computes it
        },
        query="what shipped?",
        depth="standard",
    )

    assert isinstance(report, ResearchReportV2)
    assert report.tldr == ["One big takeaway"]
    assert report.key_developments[0].sources == ["s1"]
    assert report.key_developments[0].confidence == "high"
    assert report.verification.checked == 0
    assert report.query == "what shipped?"


def test_coerce_report_fills_a_usable_report_from_nothing():
    report = coerce_report({}, query="anything")

    assert report.title.startswith("Research Report")
    assert report.reading_time_min >= 1
    assert report.sources == []
    assert report.verification.checked == 0


def test_tldr_is_capped_and_sources_are_typed():
    report = coerce_report(
        {
            "tldr": [f"point {i}" for i in range(9)],
            "sources": [
                {"id": "s1", "title": "A paper", "url": "https://arxiv.org/abs/1", "kind": "arxiv"},
                {"id": "s2", "title": "A repo", "url": "https://github.com/x/y", "kind": "github"},
                {"id": "s3", "title": "Weird", "kind": "unknown-kind"},
            ],
        },
        query="q",
    )

    assert len(report.tldr) == 5
    assert [s.kind for s in report.sources] == ["paper", "repo", "other"]


def test_comparison_table_accepts_dict_rows():
    report = coerce_report(
        {
            "comparison_table": {
                "columns": ["Option", "Best for"],
                "rows": [{"Option": "A", "Best for": "speed"}, ["B", "cost"]],
            }
        },
        query="q",
    )

    assert report.comparison_table is not None
    assert report.comparison_table.columns == ["Option", "Best for"]
    assert len(report.comparison_table.rows) == 2


def test_markdown_export_links_citations_and_lists_sources():
    report = coerce_report(
        {
            "title": "Test report",
            "tldr": ["First takeaway"],
            "executive_summary": "It happened.",
            "key_developments": [
                {
                    "claim": "Claim A",
                    "evidence": "Because.",
                    "sources": ["s1"],
                    "confidence": "high",
                }
            ],
            "timeline": [{"when": "2026-01", "what": "Released", "source_id": "s1"}],
            "sources": [
                {
                    "id": "s1",
                    "title": "Primary post",
                    "url": "https://example.com/post",
                    "kind": "web",
                }
            ],
            "open_questions": ["Will it last?"],
        },
        query="what happened?",
    )
    report.verification.checked = 1
    report.verification.supported = 1
    md = report.markdown()

    assert "# Test report" in md
    assert "[[s1]](https://example.com/post)" in md
    assert "## Timeline" in md
    assert "1/1 load-bearing claims" in md
    assert "Primary post" in md


def test_reading_time_scales_with_length():
    assert estimate_reading_time(0) == 1
    assert estimate_reading_time(2200) == 10


def test_field_name_drift_is_remapped_not_rejected():
    """Models often rename the fields we ask for; the report must survive."""
    report = coerce_report(
        {
            "title": "Drifted",
            "summary": "A summary under the wrong key.",
            "takeaways": ["First", "Second"],
            "why_it_matters": "Because it is your stack.",
            "findings": [
                {
                    "headline": "A headline instead of a claim",
                    "details": "Supporting detail",
                    "citations": ["s4"],
                },
                {
                    "finding": "Another phrasing",
                    "support": "More detail",
                    "references": "s5",
                    "certainty": "HIGH",
                },
            ],
            "next_steps": ["Watch the changelog"],
            "open_questions": ["Does it scale?"],
        },
        query="drift?",
    )

    assert report.executive_summary == "A summary under the wrong key."
    assert report.tldr == ["First", "Second"]
    assert report.implications == "Because it is your stack."
    assert [d.claim for d in report.key_developments] == [
        "A headline instead of a claim",
        "Another phrasing",
    ]
    assert report.key_developments[0].sources == ["s4"]
    assert report.key_developments[1].confidence == "high"
    assert report.what_to_watch_next == ["Watch the changelog"]


def test_unusable_sections_are_dropped_without_losing_the_report():
    """One malformed entry must never cost the reader the whole brief."""
    report = coerce_report(
        {
            "title": "Partly broken",
            "executive_summary": "Still readable.",
            "key_developments": [
                {"claim": "Good claim", "sources": ["s1"]},
                "this entry is not an object at all",
                {"claim": "Also good", "sources": ["s2"]},
            ],
            "faq": [{"question": "Q?", "answer": "A."}, 42],
            "comparison_table": "not a table",
        },
        query="broken?",
    )

    assert report.title == "Partly broken"
    assert report.executive_summary == "Still readable."
    assert [d.claim for d in report.key_developments] == ["Good claim", "Also good"]
    assert [f.question for f in report.faq] == ["Q?"]
    assert report.comparison_table is None

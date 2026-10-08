"""
Markdown rendering for a Report Schema v2 object.

Used for the "Copy as Markdown" action, `/reports/{id}/export?format=md` and as
the source HTML/PDF exporters build on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from schemas.report import ResearchReportV2


def render_markdown(report: ResearchReportV2) -> str:
    """Render the full report as Markdown with linked inline citations."""
    sources = report.source_map()

    def cite(source_ids: list[str]) -> str:
        parts = []
        for sid in source_ids:
            source = sources.get(sid)
            if source and source.url:
                parts.append(f"[[{sid}]]({source.url})")
            else:
                parts.append(f"[{sid}]")
        return " ".join(parts)

    lines: list[str] = [f"# {report.title}", ""]

    meta = [
        f"**Depth:** {report.depth}",
        f"**Reading time:** {report.reading_time_min} min",
        f"**Sources:** {len(report.sources)}",
        f"**Claims verified:** {report.verification.supported}/{report.verification.checked}",
    ]
    if report.created_at:
        meta.append(f"**Generated:** {report.created_at[:19].replace('T', ' ')} UTC")
    lines += [" · ".join(meta), ""]

    if report.query:
        lines += [f"> {report.query}", ""]

    if report.tldr:
        lines += ["## TL;DR", ""]
        lines += [f"- {item}" for item in report.tldr]
        lines.append("")

    def section(title: str, body: str) -> None:
        if body and body.strip():
            lines.extend([f"## {title}", "", body.strip(), ""])

    section("Executive summary", report.executive_summary)
    section("Background primer", report.background_primer)

    if report.key_developments:
        lines += ["## Key developments", ""]
        for index, dev in enumerate(report.key_developments, 1):
            badge = {
                "high": "High confidence",
                "medium": "Medium confidence",
                "low": "Low confidence",
            }[dev.confidence]
            lines.append(f"### {index}. {dev.claim}")
            lines.append("")
            lines.append(f"*{badge}{' · ' + cite(dev.sources) if dev.sources else ' · uncited'}*")
            lines.append("")
            if dev.evidence:
                lines += [dev.evidence.strip(), ""]

    section("How it works", report.technical_explainer)

    if report.timeline:
        lines += ["## Timeline", "", "| When | What | Source |", "| --- | --- | --- |"]
        for entry in report.timeline:
            when = (entry.when or "").replace("|", "/")
            what = (entry.what or "").replace("|", "/")
            lines.append(
                f"| {when} | {what} | {cite([entry.source_id]) if entry.source_id else ''} |"
            )
        lines.append("")

    if report.comparison_table and report.comparison_table.columns:
        table = report.comparison_table
        lines += ["## Comparison", "", "| " + " | ".join(table.columns) + " |"]
        lines.append("| " + " | ".join("---" for _ in table.columns) + " |")
        for row in table.rows:
            cells = [str(cell).replace("|", "/") for cell in row]
            cells += [""] * (len(table.columns) - len(cells))
            lines.append("| " + " | ".join(cells[: len(table.columns)]) + " |")
        lines.append("")

    section("Why this matters", report.implications)
    section("Risks and uncertainty", report.risks_and_uncertainty)

    if report.what_to_watch_next:
        lines += ["## What to watch next", ""]
        lines += [f"- {item}" for item in report.what_to_watch_next]
        lines.append("")

    if report.faq:
        lines += ["## FAQ", ""]
        for item in report.faq:
            lines += [f"**{item.question}**", "", item.answer.strip(), ""]

    if report.glossary:
        lines += ["## Glossary", ""]
        lines += [f"- **{term.term}** — {term.definition}" for term in report.glossary]
        lines.append("")

    if report.open_questions:
        lines += ["## Open questions", ""]
        lines += [f"- {item}" for item in report.open_questions]
        lines.append("")

    if report.sources:
        lines += ["## Sources", ""]
        for source in report.sources:
            title = source.title or source.url or source.id
            if source.url:
                lines.append(f"- `{source.id}` [{title}]({source.url}) — *{source.kind}*")
            else:
                lines.append(f"- `{source.id}` {title} — *{source.kind}*")
        lines.append("")

    verification = report.verification
    if verification.checked:
        lines += ["## Verification", ""]
        supported = verification.supported
        checked = verification.checked
        lines.append(
            f"{supported}/{checked} load-bearing claims were checked against their cited sources."
        )
        if verification.notes:
            lines.append("")
            lines.append(f"_{verification.notes}_")
        if verification.unsupported_claims:
            lines += ["", "Flagged claims:", ""]
            for claim in verification.unsupported_claims:
                label = {"flagged": "flagged", "softened": "softened", "removed": "removed"}[
                    claim.action
                ]
                lines.append(f"- **{label}** — {claim.claim}  ")
                lines.append(f"  _{claim.reason}_")
        lines.append("")

    lines += ["---", ""]
    footer = f"Generated by CortexResearch · {report.cost_usd:.4f} USD"
    trace = report.model_trace
    calls = trace.get("calls", []) if isinstance(trace, dict) else trace
    if calls:
        models = sorted({call.get("model", "?") for call in calls if isinstance(call, dict)})
        if models:
            footer += f" · models: {', '.join(models)}"
    lines.append(f"_{footer}_")

    return "\n".join(lines).strip() + "\n"


def render_filename(report: ResearchReportV2) -> str:
    """Filesystem-safe filename stem for exports."""
    slug = "".join(ch if ch.isalnum() or ch in " -_" else "" for ch in (report.title or "report"))
    slug = "-".join(slug.split())[:70] or "report"
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"{slug}-{stamp}"

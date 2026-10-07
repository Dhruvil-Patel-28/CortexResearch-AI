"""Public guardrails API: one call to sanitize untrusted scraped content."""

from __future__ import annotations

from guardrails.injection import scan
from guardrails.pii import scrub

_REDACTION_MARK = "[redacted: suspected injection]"


def sanitize_content(text: str) -> tuple[str, dict]:
    """
    Scrub PII and neutralize embedded instructions in untrusted text.

    Returns:
        (clean_text, summary) where summary is
        {"pii_kinds": [...], "injection_action": "allow"|"wrap"|"strip",
         "injection_count": int} — empty summary when guardrails are disabled.
    """
    from utils.config import settings

    summary: dict = {"pii_kinds": [], "injection_action": "allow", "injection_count": 0}
    if not settings.guardrails_enabled or not text:
        return text, summary

    clean = text
    if settings.guardrails_pii_enabled:
        clean, redactions = scrub(clean)
        if redactions:
            summary["pii_kinds"] = [r["kind"] for r in redactions]

    if settings.guardrails_injection_enabled:
        report = scan(clean)
        summary["injection_action"] = report.action
        summary["injection_count"] = len(report.findings)
        if report.action == "strip":
            clean = _neutralize(clean)

    from guardrails import trace

    trace.record_content(summary)
    return clean, summary


def _neutralize(text: str) -> str:
    """Remove zero-width obfuscation, then cut out matched directive spans."""
    from guardrails.injection import _ZERO_WIDTH_RE

    text = _ZERO_WIDTH_RE.sub("", text)
    report = scan(text)
    spans = sorted(
        (f["start"], f["start"] + len(f["excerpt"]))
        for f in report.findings
        if f.get("start") is not None
    )
    # Merge overlaps, then replace from the end so offsets stay valid.
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    for start, end in reversed(merged):
        text = text[:start] + _REDACTION_MARK + text[end:]
    return text

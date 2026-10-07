"""
PII / secret scrubbing.

One entry point: `scrub(text)` returns cleaned text plus a per-kind tally of
redactions. Redactions are shape-preserving placeholders ([EMAIL], [PHONE],
[SSN], [CARD], [SECRET]) so reports and prompts stay readable.

Detection order matters: emails first, then secrets (longest, most specific),
then SSN, then Luhn-validated card numbers, then phone numbers. Plain runs of
digits are never touched — a number must look like a phone (separators) or pass
the Luhn check (card) to be redacted.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
]

_API_KEY_ASSIGN_RE = re.compile(
    r"(api[_-]?key|secret|token|password)(\s*[:=]\s*['\"]?)([A-Za-z0-9_\-]{8,})", re.IGNORECASE
)
_BEARER_RE = re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]{16,})")

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# 13–16 digit runs with optional spaces/dashes inside; Luhn-validated after.
_CARD_RE = re.compile(r"\b(?:\d[ -]?){12,15}\d\b")

# Requires separators (or a + prefix) so bare digit runs are never phone-redacted.
_PHONE_RE = re.compile(r"(?:\+\d{1,3}[-.\s])?(?:\(?\d{3}\)?[-.\s]\d{3}[-.\s]?\d{4})\b")


def _luhn_valid(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scrub(text: str) -> tuple[str, list[dict]]:
    """
    Redact PII and secret-shaped strings.

    Returns:
        (clean_text, redactions) where redactions is [{"kind", "count"}] for
        every kind found, ordered by first appearance. Empty list for clean text.
    """
    if not text:
        return text, []

    counts: dict[str, int] = {"email": 0, "secret": 0, "ssn": 0, "card": 0, "phone": 0}

    def _sub(kind: str):
        def _replace(_match: re.Match) -> str:
            counts[kind] += 1
            return "[SECRET]" if kind == "secret" else f"[{kind.upper()}]"

        return _replace

    def _sub_assignment(match: re.Match) -> str:
        counts["secret"] += 1
        return f"{match.group(1)}{match.group(2)}[SECRET]"

    def _sub_bearer(match: re.Match) -> str:
        counts["secret"] += 1
        return f"{match.group(1)}[SECRET]"

    text = _EMAIL_RE.sub(_sub("email"), text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_sub("secret"), text)
    text = _API_KEY_ASSIGN_RE.sub(_sub_assignment, text)
    text = _BEARER_RE.sub(_sub_bearer, text)
    text = _SSN_RE.sub(_sub("ssn"), text)

    def _sub_card(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if not _luhn_valid(digits):
            return match.group(0)
        counts["card"] += 1
        return "[CARD]"

    text = _CARD_RE.sub(_sub_card, text)
    text = _PHONE_RE.sub(_sub("phone"), text)

    redactions = [{"kind": kind, "count": count} for kind, count in counts.items() if count]
    return text, redactions

"""
Prompt-injection scanner for untrusted scraped content.

`scan(text)` returns an InjectionReport: aggregated risk, per-finding details
(category, excerpt, offset) and a policy action —
allow (risk < 0.3) / wrap (0.3–0.7) / strip (>= 0.7).

Detection is heuristic and weighted across six categories: instruction
override, goal hijack, exfiltration, fake authority, source fabrication and
obfuscation (zero-width Unicode hiding an override phrase).

False-positive control: a match that sits inside quotes or follows a
third-person cue ("showed that", "such as", "asked the model to", …) is treated
as *discussion about* attacks, not an attack — articles about prompt injection
must pass clean.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

STRIP_THRESHOLD = 0.7
WRAP_THRESHOLD = 0.3

_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")

# (category, pattern, weight). Strong markers need no directive context.
_STRONG_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    ("fake_authority", re.compile(r"\bSYSTEM\s*:", re.IGNORECASE), 0.85),
    ("fake_authority", re.compile(r"<\|im_start\|>|<\|im_end\|>|\[INST\]|###\s*Assistant", re.IGNORECASE), 0.85),
    ("fake_authority", re.compile(r"\[\s*NOTE\s+FROM\s+YOUR\s+(?:DEVELOPERS?|CREATORS?|ADMIN)\s*\]", re.IGNORECASE), 0.85),
    ("fake_authority", re.compile(r"your\s+(?:developer|creator|admin)s?\s+(?:says?|said|instructed)", re.IGNORECASE), 0.75),
]

# Directive-context patterns: must also pass the quote / third-person guard.
_DIRECTIVE_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    # Instruction override
    ("instruction_override", re.compile(
        r"ignore\s+(?:all\s+|any\s+|the\s+|everything\s+|each\s+)?(?:previous\s+|prior\s+|earlier\s+|above\s+|given\s+|that\s+)?instructions?", re.IGNORECASE), 0.8),
    ("instruction_override", re.compile(
        r"ignore\s+(?:all\s+|any\s+|everything\s+|the\s+)?(?:that\s+was\s+)?(?:said\s+)?above", re.IGNORECASE), 0.8),
    ("instruction_override", re.compile(
        r"disregard\s+(?:all\s+|any\s+|the\s+|your\s+|previous\s+|prior\s+)?(?:instructions|system\s+prompt|guidelines)", re.IGNORECASE), 0.8),
    ("instruction_override", re.compile(
        r"you\s+are\s+now\s+(?:a|an|no\s+longer|unrestricted|free)", re.IGNORECASE), 0.8),
    # Goal hijack
    ("goal_hijack", re.compile(
        r"\b(?:print|output|reveal|echo)\s+(?:your|the)\b[^.\n]{0,40}(?:system\s+prompt|instructions?|secrets?|configuration)", re.IGNORECASE), 0.8),
    ("goal_hijack", re.compile(
        r"respond\s+only\s+with\s+(?:your|the)\s+(?:hidden\s+|system\s+|new\s+)?(?:configuration|instructions|prompt)", re.IGNORECASE), 0.8),
    # Exfiltration
    ("exfiltration", re.compile(
        r"\b(?:email|send|post|exfiltrate)\s+(?:me\s+|out\s+)?(?:your|the|all)\s+(?:system\s+prompt|api\s+keys?|secrets?|credentials?|conversation(?:\s+history)?|hidden\s+instructions?|configuration)", re.IGNORECASE), 0.85),
    ("exfiltration", re.compile(
        r"base64[- ]?(?:encode|encodes|encoded)\s+your", re.IGNORECASE), 0.8),
    # Source fabrication
    ("source_fabrication", re.compile(
        r"treat\s+(?:this|the|that)\s+(?:document|page|source|article|site)\s+as\s+(?:a\s+)?trusted", re.IGNORECASE), 0.8),
    ("source_fabrication", re.compile(
        r"mark\s+(?:all\s+|its\s+|these\s+|the\s+)?(?:claims?\s+)?as\s+verified", re.IGNORECASE), 0.75),
    ("source_fabrication", re.compile(
        r"skip(?:ping)?\s+(?:the\s+)?(?:citation|verification)\s+checks?", re.IGNORECASE), 0.75),
    ("source_fabrication", re.compile(
        r"cite\s+https?://\S+\s+as\s+(?:a\s+)?verified\s+source", re.IGNORECASE), 0.8),
]

# Preceding-window cues that mark a match as third-person discussion / quoted.
_THIRD_PERSON_CUE_RE = re.compile(
    r"(?:\b(?:such as|like|examples?|asked|told|showed|demonstrated|catalogu\w*|"
    r"analys\w*|phrase|jailbreak|attacks?|attempts?|including|discuss\w*|reports?\b)|"
    r"['\"\u201c\u2018])\s*$",
    re.IGNORECASE,
)
_CUE_WINDOW = 60


class InjectionReport(BaseModel):
    risk: float = 0.0
    action: str = "allow"  # allow | wrap | strip
    findings: list[dict] = Field(default_factory=list)


def _is_discussion_context(text: str, start: int) -> bool:
    """True when the match is inside quotes or follows a third-person cue."""
    window = text[max(0, start - _CUE_WINDOW):start]
    if _THIRD_PERSON_CUE_RE.search(window):
        return True
    line_start = text.rfind("\n", 0, start) + 1
    quotes_before = text[line_start:start].count('"') + text[line_start:start].count("'")
    return quotes_before % 2 == 1


def _find(text: str, findings: list[dict]) -> float:
    risk = 0.0
    for category, pattern, weight in _STRONG_PATTERNS:
        for m in pattern.finditer(text):
            findings.append({
                "category": category,
                "excerpt": m.group(0)[:120],
                "start": m.start(),
                "weight": weight,
            })
            risk += weight
    for category, pattern, weight in _DIRECTIVE_PATTERNS:
        for m in pattern.finditer(text):
            if _is_discussion_context(text, m.start()):
                continue
            findings.append({
                "category": category,
                "excerpt": m.group(0)[:120],
                "start": m.start(),
                "weight": weight,
            })
            risk += weight
    return risk


def scan(text: str) -> InjectionReport:
    """Scan untrusted text for embedded instructions. Never raises."""
    if not text or len(text.strip()) < 8:
        return InjectionReport()

    findings: list[dict] = []
    risk = _find(text, findings)

    # Obfuscation: several zero-width chars present AND a directive hides underneath.
    if len(_ZERO_WIDTH_RE.findall(text)) >= 3:
        stripped = _ZERO_WIDTH_RE.sub("", text)
        hidden: list[dict] = []
        hidden_risk = _find(stripped, hidden)
        if hidden_risk > 0:
            risk += 0.25  # obfuscation is itself a signal
            findings.append({
                "category": "obfuscation",
                "excerpt": "[zero-width unicode hiding directives]",
                "start": None,
                "weight": 0.25,
            })
            for f in hidden:
                f["start"] = None  # offsets refer to de-obfuscated text
                findings.append({**f, "excerpt": f"[zero-width-obfuscated] {f['excerpt']}"})

    if not findings:
        return InjectionReport()

    risk = min(1.0, risk)
    action = "strip" if risk >= STRIP_THRESHOLD else ("wrap" if risk >= WRAP_THRESHOLD else "allow")
    return InjectionReport(risk=round(risk, 3), action=action, findings=findings)

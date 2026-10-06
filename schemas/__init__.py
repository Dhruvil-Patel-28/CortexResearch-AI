"""Shared, dependency-free data contracts (Pydantic) used across the app."""

from schemas.report import (
    ComparisonTable,
    FAQItem,
    GlossaryTerm,
    KeyDevelopment,
    ResearchReportV2,
    Source,
    TimelineEntry,
    Verification,
    coerce_report,
)

__all__ = [
    "ComparisonTable",
    "FAQItem",
    "GlossaryTerm",
    "KeyDevelopment",
    "ResearchReportV2",
    "Source",
    "TimelineEntry",
    "Verification",
    "coerce_report",
]

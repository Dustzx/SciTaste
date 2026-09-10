"""Dependency-neutral reviewer concern vocabulary."""

from enum import StrEnum


class ConcernCategory(StrEnum):
    CLARITY = "clarity"
    MISSING_EVIDENCE = "missing_evidence"
    MISSING_BASELINE = "missing_baseline"
    ANALYSIS = "analysis"
    METHOD = "method"
    OVERCLAIM = "overclaim"
    ERROR = "error"
    LIMITATION = "limitation"
    VALIDITY = "validity"


class ConcernSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


__all__ = ["ConcernCategory", "ConcernSeverity"]

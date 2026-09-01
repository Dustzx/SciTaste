"""Structured literature-landscape construction."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from scitaste.state.research_state import LiteratureLandscape


class LandscapeCategory(StrEnum):
    SOLVED_PROBLEM = "solved_problem"
    ACTIVE_PROBLEM = "active_problem"
    EMERGING_DIRECTION = "emerging_direction"
    SATURATED_DIRECTION = "saturated_direction"
    METHODOLOGICAL_BOTTLENECK = "methodological_bottleneck"
    EVALUATION_GAP = "evaluation_gap"
    CONTROVERSIAL_FINDING = "controversial_finding"
    UNEXPLAINED_FAILURE = "unexplained_failure"


class LandscapeFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: LandscapeCategory
    statement: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)


_CATEGORY_FIELD = {
    LandscapeCategory.SOLVED_PROBLEM: "solved_problems",
    LandscapeCategory.ACTIVE_PROBLEM: "active_problems",
    LandscapeCategory.EMERGING_DIRECTION: "emerging_directions",
    LandscapeCategory.SATURATED_DIRECTION: "saturated_directions",
    LandscapeCategory.METHODOLOGICAL_BOTTLENECK: "methodological_bottlenecks",
    LandscapeCategory.EVALUATION_GAP: "evaluation_gaps",
    LandscapeCategory.CONTROVERSIAL_FINDING: "controversial_findings",
    LandscapeCategory.UNEXPLAINED_FAILURE: "unexplained_failures",
}


class LiteratureLandscapeAgent:
    """Aggregate traceable findings into the required non-summary structure."""

    def build(self, findings: list[LandscapeFinding]) -> LiteratureLandscape:
        if not findings:
            raise ValueError("at least one literature finding is required")
        grouped: dict[str, list[str]] = {field: [] for field in _CATEGORY_FIELD.values()}
        for finding in findings:
            field = _CATEGORY_FIELD[finding.category]
            rendered_sources = ", ".join(finding.source_ids)
            grouped[field].append(f"{finding.statement} [sources: {rendered_sources}]")
        return LiteratureLandscape.model_validate(grouped)

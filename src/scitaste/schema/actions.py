"""Research actions considered by the Scientific Taste Controller."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MetaAction(StrEnum):
    """Complete cross-stage action vocabulary used by the v1 architecture."""

    SEARCH = "SEARCH"
    FORM_INTUITION = "FORM_INTUITION"
    FORM_WORKING_HYPOTHESIS = "FORM_WORKING_HYPOTHESIS"
    PROBE = "PROBE"
    VALIDATE_HYPOTHESIS = "VALIDATE_HYPOTHESIS"
    REFORMULATE_HYPOTHESIS = "REFORMULATE_HYPOTHESIS"
    SPLIT_HYPOTHESIS = "SPLIT_HYPOTHESIS"
    DISCARD_HYPOTHESIS = "DISCARD_HYPOTHESIS"
    FORMULATE_PROBLEM = "FORMULATE_PROBLEM"
    IDEATE = "IDEATE"
    SELECT_IDEA = "SELECT_IDEA"
    PILOT = "PILOT"
    ADVANCE = "ADVANCE"
    EXPERIMENT = "EXPERIMENT"
    ANALYZE = "ANALYZE"
    COLLECT_EVIDENCE = "COLLECT_EVIDENCE"
    REFINE = "REFINE"
    RE_PROBE = "RE_PROBE"
    REPRODUCE = "REPRODUCE"
    PIVOT = "PIVOT"
    DROP = "DROP"
    BUILD_STORY = "BUILD_STORY"
    WRITE = "WRITE"
    DESIGN_FIGURE = "DESIGN_FIGURE"
    REVIEW = "REVIEW"
    RESPOND = "RESPOND"
    ADD_EXPERIMENT = "ADD_EXPERIMENT"
    ADD_BASELINE = "ADD_BASELINE"
    ADD_ANALYSIS = "ADD_ANALYSIS"
    REVISE_METHOD = "REVISE_METHOD"
    NARROW_CLAIM = "NARROW_CLAIM"
    STOP = "STOP"


class ResearchAction(BaseModel):
    """One candidate high-level action, independent of any executor backend."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(default_factory=lambda: f"act-{uuid4().hex}")
    type: MetaAction
    description: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_cost: dict[str, float] = Field(default_factory=dict)
    expected_value: dict[str, float] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("expected_cost", "expected_value")
    @classmethod
    def values_are_finite(cls, values: dict[str, float]) -> dict[str, float]:
        for key, value in values.items():
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError(f"{key} must be finite")
        return values

    @field_validator("expected_cost")
    @classmethod
    def costs_are_nonnegative(cls, values: dict[str, float]) -> dict[str, float]:
        for key, value in values.items():
            if value < 0:
                raise ValueError(f"{key} cost must be nonnegative")
        return values

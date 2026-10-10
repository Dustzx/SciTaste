"""Contextual, outcome-grounded Scientific Taste policy.

The first Scientific Situation prototype transferred utilities with a fixed
categorical similarity kernel.  That is useful as an interpretable baseline,
but it cannot learn which *interaction* between a scientific state and an
action predicts downstream progress.  This module defines the claim-bearing
alternative: an outcome-hidden continuous decision geometry, a registered
action-affordance vector, and a content-bound contextual action-contrast
model.  The model is a residual policy.  It changes the base controller's
action only when the predicted advantage remains positive under a
task-cluster jackknife.

Training is intentionally kept out of the runtime module.  Study code may fit
the small regularized model with the optional ``study`` dependencies, then
serialize the resulting coefficients here.  Inference itself is pure Python
and remains available in the base installation.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import content_sha256, validate_entry_id

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"


class DecisionGeometryDimension(StrEnum):
    EVIDENCE_STRENGTH = "evidence_strength"
    RESIDUAL_UNCERTAINTY = "residual_uncertainty"
    EXPECTED_INFORMATION_GAIN = "expected_information_gain"
    CONTRADICTION_PRESSURE = "contradiction_pressure"
    HYPOTHESIS_CONCENTRATION = "hypothesis_concentration"
    REPAIRABILITY = "repairability"
    TERMINAL_READINESS = "terminal_readiness"
    BUDGET_PRESSURE = "budget_pressure"


DECISION_GEOMETRY_FEATURES = tuple(item.value for item in DecisionGeometryDimension)
ACTION_AFFORDANCE_FEATURES = (
    "evidence_acquisition",
    "hypothesis_revision",
    "evidence_synthesis",
    "candidate_refinement",
    "termination",
    "intervention_scope",
)


class DecisionGeometryAnchor(BaseModel):
    """One exact selector-visible span grounding geometry dimensions."""

    model_config = _CONFIG

    field_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=2, max_length=500)
    supports_dimensions: tuple[DecisionGeometryDimension, ...] = Field(
        min_length=1,
        max_length=8,
    )

    @model_validator(mode="after")
    def dimensions_are_unique(self) -> DecisionGeometryAnchor:
        if len(self.supports_dimensions) != len(set(self.supports_dimensions)):
            raise ValueError("decision-geometry anchor dimensions must be unique")
        return self


class ScientificDecisionGeometryProposal(BaseModel):
    """Outcome-hidden model proposal before runtime provenance is attached."""

    model_config = _CONFIG

    evidence_strength: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    residual_uncertainty: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    expected_information_gain: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    contradiction_pressure: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    hypothesis_concentration: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    repairability: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    terminal_readiness: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    budget_pressure: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    anchors: tuple[DecisionGeometryAnchor, ...] = Field(min_length=2, max_length=8)
    decision_basis: str = Field(min_length=1, max_length=3_000)
    abstraction_confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def anchors_are_unique(self) -> ScientificDecisionGeometryProposal:
        identities = [(item.field_id, item.quote) for item in self.anchors]
        if len(identities) != len(set(identities)):
            raise ValueError("decision-geometry anchors must be unique")
        return self


class ScientificDecisionGeometry(BaseModel):
    """Content-bound continuous state available before target outcomes."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_id: Literal["outcome-hidden-decision-geometry-v1"] = (
        "outcome-hidden-decision-geometry-v1"
    )
    study_id: str
    task_cluster_id: str = Field(min_length=1)
    prefix_sha256: str = Field(pattern=_SHA256)
    evidence_strength: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    residual_uncertainty: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    expected_information_gain: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    contradiction_pressure: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    hypothesis_concentration: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    repairability: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    terminal_readiness: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    budget_pressure: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    anchors: tuple[DecisionGeometryAnchor, ...] = Field(min_length=2, max_length=8)
    decision_basis: str = Field(min_length=1, max_length=3_000)
    abstraction_confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    extractor_provider: str = Field(min_length=1)
    extractor_model: str = Field(min_length=1)
    request_fingerprint: str = Field(pattern=_SHA256)
    response_sha256: str = Field(pattern=_SHA256)
    target_outcomes_visible_to_extractor: Literal[False] = False
    geometry_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def geometry_is_closed(self) -> ScientificDecisionGeometry:
        validate_entry_id(self.study_id, field_name="decision-geometry study_id")
        expected = content_sha256(self.model_dump(mode="json", exclude={"geometry_sha256"}))
        if self.geometry_sha256 != expected:
            raise ValueError("decision-geometry hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ScientificDecisionGeometry:
        payload = {
            "schema_version": "1.0",
            "contract_id": "outcome-hidden-decision-geometry-v1",
            "target_outcomes_visible_to_extractor": False,
            **values,
        }
        payload.pop("geometry_sha256", None)
        payload["anchors"] = tuple(
            DecisionGeometryAnchor.model_validate(item)
            for item in payload["anchors"]  # type: ignore[union-attr]
        )
        unsigned = cls.model_construct(geometry_sha256="0" * 64, **payload)
        return cls(
            **payload,
            geometry_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"geometry_sha256"})
            ),
        )

    def feature_vector(self) -> tuple[float, ...]:
        return tuple(float(getattr(self, name)) for name in DECISION_GEOMETRY_FEATURES)


def validate_decision_geometry_grounding(
    geometry: ScientificDecisionGeometry,
    *,
    visible_fields: dict[str, str],
) -> tuple[str, ...]:
    """Require exact spans and coverage of every continuous dimension."""

    findings: list[str] = []
    supported: set[DecisionGeometryDimension] = set()
    for anchor in geometry.anchors:
        source = visible_fields.get(anchor.field_id)
        if source is None:
            findings.append(f"unknown-anchor-field:{anchor.field_id}")
        elif anchor.quote not in source:
            findings.append(f"non-exact-anchor:{anchor.field_id}")
        supported.update(anchor.supports_dimensions)
    missing = set(DecisionGeometryDimension) - supported
    findings.extend(f"ungrounded-dimension:{item.value}" for item in sorted(missing))
    return tuple(sorted(set(findings)))


class ActionAffordanceProfile(BaseModel):
    """Outcome-blind semantic coordinates for a registered target action."""

    model_config = _CONFIG

    action_id: str = Field(min_length=1)
    action_definition_sha256: str = Field(pattern=_SHA256)
    evidence_acquisition: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    hypothesis_revision: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    evidence_synthesis: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    candidate_refinement: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    termination: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    intervention_scope: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    construction_rationale: str = Field(min_length=1, max_length=1_000)
    target_outcomes_visible_during_construction: Literal[False] = False
    profile_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def profile_is_closed(self) -> ActionAffordanceProfile:
        expected = content_sha256(self.model_dump(mode="json", exclude={"profile_sha256"}))
        if self.profile_sha256 != expected:
            raise ValueError("action-affordance profile hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ActionAffordanceProfile:
        payload = {"target_outcomes_visible_during_construction": False, **values}
        payload.pop("profile_sha256", None)
        unsigned = cls.model_construct(profile_sha256="0" * 64, **payload)
        return cls(
            **payload,
            profile_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"profile_sha256"})
            ),
        )

    def feature_vector(self) -> tuple[float, ...]:
        return tuple(float(getattr(self, name)) for name in ACTION_AFFORDANCE_FEATURES)


class ContextualTasteModel(BaseModel):
    """A fitted bilinear state--action advantage model."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    model_family: Literal["ridge-action-contrast-v1"] = "ridge-action-contrast-v1"
    state_feature_names: tuple[str, ...] = DECISION_GEOMETRY_FEATURES
    action_feature_names: tuple[str, ...] = ACTION_AFFORDANCE_FEATURES
    state_means: tuple[float, ...] = Field(min_length=8, max_length=8)
    state_scales: tuple[float, ...] = Field(min_length=8, max_length=8)
    coefficients: tuple[float, ...] = Field(min_length=54, max_length=54)
    ridge_alpha: float = Field(gt=0.0, allow_inf_nan=False)
    source_case_ids: tuple[str, ...] = Field(min_length=1)
    source_task_cluster_ids: tuple[str, ...] = Field(min_length=2)
    training_target: Literal["within-fork-action-advantage"] = "within-fork-action-advantage"
    target_outcomes_used_for_training: Literal[True] = True
    model_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def fitted_model_is_closed(self) -> ContextualTasteModel:
        if self.state_feature_names != DECISION_GEOMETRY_FEATURES:
            raise ValueError("contextual Taste state feature contract drifted")
        if self.action_feature_names != ACTION_AFFORDANCE_FEATURES:
            raise ValueError("contextual Taste action feature contract drifted")
        if any(not math.isfinite(item) for item in (*self.state_means, *self.coefficients)):
            raise ValueError("contextual Taste parameters must be finite")
        if any(not math.isfinite(item) or item <= 0.0 for item in self.state_scales):
            raise ValueError("contextual Taste state scales must be finite and positive")
        if self.source_case_ids != tuple(sorted(set(self.source_case_ids))):
            raise ValueError("contextual Taste source cases must be sorted and unique")
        if self.source_task_cluster_ids != tuple(sorted(set(self.source_task_cluster_ids))):
            raise ValueError("contextual Taste source clusters must be sorted and unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"model_sha256"}))
        if self.model_sha256 != expected:
            raise ValueError("contextual Taste model hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ContextualTasteModel:
        payload = {
            "schema_version": "1.0",
            "model_family": "ridge-action-contrast-v1",
            "state_feature_names": DECISION_GEOMETRY_FEATURES,
            "action_feature_names": ACTION_AFFORDANCE_FEATURES,
            "training_target": "within-fork-action-advantage",
            "target_outcomes_used_for_training": True,
            **values,
        }
        payload.pop("model_sha256", None)
        unsigned = cls.model_construct(model_sha256="0" * 64, **payload)
        return cls(
            **payload,
            model_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"model_sha256"})),
        )

    def score(
        self,
        geometry: ScientificDecisionGeometry,
        profile: ActionAffordanceProfile,
    ) -> float:
        state = (
            1.0,
            *(
                (value - mean) / scale
                for value, mean, scale in zip(
                    geometry.feature_vector(),
                    self.state_means,
                    self.state_scales,
                    strict=True,
                )
            ),
        )
        action = profile.feature_vector()
        design = tuple(a * s for a in action for s in state)
        return sum(
            coefficient * value
            for coefficient, value in zip(self.coefficients, design, strict=True)
        )


class ContextualTasteActionScore(BaseModel):
    model_config = _CONFIG

    action_id: str = Field(min_length=1)
    mean_advantage_score: float = Field(allow_inf_nan=False)
    jackknife_standard_error: float = Field(ge=0.0, allow_inf_nan=False)


class ContextualTasteDecision(BaseModel):
    """Selective residual intervention relative to the base-controller action."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    target_study_id: str
    target_geometry_sha256: str = Field(pattern=_SHA256)
    base_action_id: str = Field(min_length=1)
    action_scores: tuple[ContextualTasteActionScore, ...] = Field(min_length=2)
    proposed_action_id: str = Field(min_length=1)
    selected_action_id: str | None = Field(default=None, min_length=1)
    abstained: bool
    abstention_reasons: tuple[str, ...] = ()
    predicted_advantage_over_base: float = Field(allow_inf_nan=False)
    advantage_standard_error: float = Field(ge=0.0, allow_inf_nan=False)
    advantage_lower_confidence_bound: float = Field(allow_inf_nan=False)
    confidence_level: float = Field(gt=0.5, lt=1.0, allow_inf_nan=False)
    fitted_model_sha256: str = Field(pattern=_SHA256)
    jackknife_model_sha256s: tuple[str, ...] = Field(min_length=2)
    target_outcomes_used_for_selection: Literal[False] = False
    decision_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def decision_is_closed(self) -> ContextualTasteDecision:
        validate_entry_id(self.target_study_id, field_name="contextual Taste target study_id")
        if self.abstained == (self.selected_action_id is not None):
            raise ValueError("contextual Taste must select one action xor abstain")
        if self.abstained != bool(self.abstention_reasons):
            raise ValueError("contextual Taste abstention reasons are inconsistent")
        ids = tuple(item.action_id for item in self.action_scores)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("contextual Taste action scores must be sorted and unique")
        if self.proposed_action_id not in ids or self.base_action_id not in ids:
            raise ValueError("contextual Taste decision references an unknown action")
        if (
            self.selected_action_id is not None
            and self.selected_action_id != self.proposed_action_id
        ):
            raise ValueError("contextual Taste selected action differs from proposal")
        if self.jackknife_model_sha256s != tuple(sorted(set(self.jackknife_model_sha256s))):
            raise ValueError("contextual Taste jackknife models must be sorted and unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
        if self.decision_sha256 != expected:
            raise ValueError("contextual Taste decision hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ContextualTasteDecision:
        payload = {
            "schema_version": "1.0",
            "target_outcomes_used_for_selection": False,
            **values,
        }
        payload.pop("decision_sha256", None)
        payload["action_scores"] = tuple(
            ContextualTasteActionScore.model_validate(item)
            for item in payload["action_scores"]  # type: ignore[union-attr]
        )
        unsigned = cls.model_construct(decision_sha256="0" * 64, **payload)
        return cls(
            **payload,
            decision_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"decision_sha256"})
            ),
        )


__all__ = [
    "ACTION_AFFORDANCE_FEATURES",
    "DECISION_GEOMETRY_FEATURES",
    "ActionAffordanceProfile",
    "ContextualTasteActionScore",
    "ContextualTasteDecision",
    "ContextualTasteModel",
    "DecisionGeometryAnchor",
    "DecisionGeometryDimension",
    "ScientificDecisionGeometry",
    "ScientificDecisionGeometryProposal",
    "validate_decision_geometry_grounding",
]

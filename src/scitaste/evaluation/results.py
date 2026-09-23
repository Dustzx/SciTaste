"""Integrity-aware result admission for generic API and GPU evaluation cells."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.benchmark.study_models import StudyOutcome
from scitaste.evaluation.cell_plan import EvaluationCellPlan, PlannedEvaluationCell
from scitaste.evaluation.prelaunch import (
    ClaimAdmissionContract,
    ConfirmatoryContrastSpec,
    ConfirmatoryEstimandKind,
    ContrastInferenceRole,
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    ScientificLaneRole,
    SystemRole,
    TaskFreezeSemantics,
)
from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_relative_locator,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_CELL_ID = r"^cell-[0-9a-f]{24}$"
_BLIND_ID = r"^blind-[0-9a-f]{24}$"
_H4_SYSTEM_IDS = {
    "full-scitaste-learned-policy",
    "native-base-without-learned-taste",
}


class EvaluationResultArtifact(BaseModel):
    """One project-owned immutable result artifact."""

    model_config = _CONFIG

    locator: str
    sha256: str = Field(pattern=_SHA256)
    size_bytes: int = Field(gt=0, le=4 * 1024 * 1024 * 1024)

    @field_validator("locator")
    @classmethod
    def locator_is_project_relative(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="evaluation result artifact")


class EvaluationCellUsage(BaseModel):
    """Telemetry required to enforce the resource ceiling of one planned cell."""

    model_config = _CONFIG

    request_count: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    max_input_tokens_observed: int | None = Field(default=None, ge=0)
    max_output_tokens_observed: int | None = Field(default=None, ge=0)
    api_cost: float | None = Field(default=None, ge=0)
    gpu_hours: float | None = Field(default=None, ge=0)
    wall_time_hours: float = Field(ge=0)
    experiment_count: int = Field(ge=0)


class EvaluationCellResult(BaseModel):
    """One exact planned cell result; prose cannot change its identity or status."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    cell_id: str = Field(pattern=_CELL_ID)
    proposal_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    cell_sha256: str = Field(pattern=_SHA256)
    resource_sha256: str = Field(pattern=_SHA256)
    status: Literal["succeeded", "failed"]
    evidence_class: Literal["real", "synthetic"]
    usage: EvaluationCellUsage
    outcome: StudyOutcome | None = None
    artifacts: tuple[EvaluationResultArtifact, ...] = Field(default=(), max_length=200)
    error_code: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
    record_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_is_closed_and_self_hashed(self) -> EvaluationCellResult:
        locators = [item.locator for item in self.artifacts]
        if len(locators) != len(set(locators)):
            raise ValueError("evaluation result artifact locators must be unique")
        if self.status == "succeeded":
            if self.outcome is None or not self.artifacts or self.error_code is not None:
                raise ValueError("a successful cell requires outcome and artifacts only")
        elif self.error_code is None or self.outcome is not None:
            raise ValueError("a failed cell requires an error code and no outcome")
        if self.schema_version == "1.0" and any(
            value is not None
            for value in (
                self.usage.max_input_tokens_observed,
                self.usage.max_output_tokens_observed,
            )
        ):
            raise ValueError("cell result v1.1 is required for per-call token telemetry")
        expected = content_sha256(_cell_result_hash_payload(self))
        if self.record_sha256 != expected:
            raise ValueError("evaluation cell result hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> EvaluationCellResult:
        payload = {"schema_version": "1.0", **values}
        payload.pop("record_sha256", None)
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(_cell_result_hash_payload(unsigned)),
        )


class EvaluationBlindReview(BaseModel):
    """Condition-blinded panel review with a separate external attestation file."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    blind_id: str = Field(pattern=_BLIND_ID)
    source: Literal["external", "internal", "synthetic"]
    reviewer_identity_hashes: tuple[str, ...] = Field(min_length=2, max_length=20)
    rubric_id: str = Field(min_length=1, max_length=200)
    rubric_sha256: str = Field(pattern=_SHA256)
    criterion_scores: dict[str, float] = Field(min_length=1, max_length=50)
    final_preference_score: float = Field(ge=0, le=1)
    conflict: bool = False
    adjudicated: bool = False
    attestation: EvaluationResultArtifact
    review_sha256: str = Field(pattern=_SHA256)

    @field_validator("reviewer_identity_hashes")
    @classmethod
    def reviewer_hashes_are_unique_and_valid(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in values
        ):
            raise ValueError("reviewer identity hashes must be unique SHA-256 values")
        return values

    @field_validator("criterion_scores")
    @classmethod
    def scores_are_bounded(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not key.strip() or score < 0 or score > 1 for key, score in values.items()):
            raise ValueError("review criterion scores must be named values in [0, 1]")
        return values

    @model_validator(mode="after")
    def review_is_closed_and_self_hashed(self) -> EvaluationBlindReview:
        if self.conflict and not self.adjudicated:
            raise ValueError("a conflicted panel review requires adjudication")
        expected = content_sha256(self.model_dump(mode="json", exclude={"review_sha256"}))
        if self.review_sha256 != expected:
            raise ValueError("evaluation blind review hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> EvaluationBlindReview:
        payload = {"schema_version": "1.0", **values}
        payload.pop("review_sha256", None)
        unsigned = cls.model_construct(review_sha256="0" * 64, **payload)
        return cls(
            **payload,
            review_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"review_sha256"})
            ),
        )


class EvaluationPrimaryComparison(BaseModel):
    """One preregistered primary contrast with a mechanically checked conclusion."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    comparison_id: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
    analysis_contract_sha256: str = Field(pattern=_SHA256)
    analysis_input_sha256: str | None = Field(default=None, pattern=_SHA256)
    failure_handling: Literal["include-as-outcome"] | None = None
    objective_outcome_contract_sha256: str | None = Field(default=None, pattern=_SHA256)
    objective_measurement_set_artifact: EvaluationResultArtifact | None = None
    independent_unit_kind: Literal["held-out-task"] | None = None
    observed_block_count: int | None = Field(default=None, gt=0)
    inference_role: ContrastInferenceRole | None = None
    raw_p_value: float | None = Field(default=None, ge=0, le=1)
    adjusted_p_value: float | None = Field(default=None, ge=0, le=1)
    alpha: float | None = Field(default=None, gt=0, lt=1)
    multiplicity_family_sha256: str | None = Field(default=None, pattern=_SHA256)
    candidate_system_id: str
    comparator_system_id: str
    analysis_unit_count: int = Field(gt=0)
    favorable_direction: Literal["higher", "lower"]
    minimum_effect: float = Field(ge=0)
    effect_estimate: float
    interval_lower: float
    interval_upper: float
    conclusion: Literal["supports_claim", "inconclusive", "contradicts_claim"]
    analysis_artifact: EvaluationResultArtifact
    comparison_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def conclusion_is_derived_and_self_hashed(self) -> EvaluationPrimaryComparison:
        extensions = (self.analysis_input_sha256, self.failure_handling)
        executable_extensions = (
            self.objective_outcome_contract_sha256,
            self.objective_measurement_set_artifact,
            self.independent_unit_kind,
            self.observed_block_count,
            self.inference_role,
            self.raw_p_value,
            self.alpha,
        )
        if self.schema_version == "1.0" and any(value is not None for value in extensions):
            raise ValueError("primary comparison v1.1 is required for claim-analysis inputs")
        if self.schema_version in {"1.1", "1.2"} and any(value is None for value in extensions):
            raise ValueError("primary comparison v1.1 requires claim-analysis inputs")
        if self.schema_version != "1.2" and any(
            value is not None
            for value in (
                *executable_extensions,
                self.adjusted_p_value,
                self.multiplicity_family_sha256,
            )
        ):
            raise ValueError("primary comparison v1.2 is required for executable inference")
        if self.schema_version == "1.2":
            if any(value is None for value in executable_extensions):
                raise ValueError("primary comparison v1.2 requires executable inference fields")
            if self.inference_role is ContrastInferenceRole.CONFIRMATORY:
                if self.adjusted_p_value is None or self.multiplicity_family_sha256 is None:
                    raise ValueError(
                        "confirmatory comparison v1.2 requires multiplicity-adjusted inference"
                    )
            elif self.adjusted_p_value is not None or self.multiplicity_family_sha256 is not None:
                raise ValueError(
                    "diagnostic comparison v1.2 cannot enter the confirmatory multiplicity family"
                )
        if self.candidate_system_id == self.comparator_system_id:
            raise ValueError("primary comparison requires distinct systems")
        if not self.interval_lower <= self.effect_estimate <= self.interval_upper:
            raise ValueError("primary comparison estimate must lie inside its interval")
        if self.favorable_direction == "higher":
            supports_interval = self.interval_lower > self.minimum_effect
            contradicts = self.interval_upper < -self.minimum_effect
        else:
            supports_interval = self.interval_upper < -self.minimum_effect
            contradicts = self.interval_lower > self.minimum_effect
        if self.schema_version == "1.2":
            significance = (
                self.adjusted_p_value
                if self.inference_role is ContrastInferenceRole.CONFIRMATORY
                else self.raw_p_value
            )
            assert significance is not None and self.alpha is not None
            supports = supports_interval and significance < self.alpha
        else:
            supports = supports_interval
        expected_conclusion = (
            "supports_claim" if supports else "contradicts_claim" if contradicts else "inconclusive"
        )
        if self.conclusion != expected_conclusion:
            raise ValueError("primary comparison conclusion differs from its interval rule")
        expected = content_sha256(_comparison_hash_payload(self))
        if self.comparison_sha256 != expected:
            raise ValueError("evaluation primary comparison hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> EvaluationPrimaryComparison:
        payload = {"schema_version": "1.0", **values}
        payload.pop("comparison_sha256", None)
        unsigned = cls.model_construct(comparison_sha256="0" * 64, **payload)
        return cls(
            **payload,
            comparison_sha256=content_sha256(_comparison_hash_payload(unsigned)),
        )


class EvaluationResultSet(BaseModel):
    """Raw registered execution, panel, and primary-analysis records."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    project_id: str
    evaluation_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    run_id: str | None = None
    campaign_manifest_sha256: str | None = Field(default=None, pattern=_SHA256)
    launch_config_sha256: str | None = Field(default=None, pattern=_SHA256)
    formal_preparation_sha256: str | None = Field(default=None, pattern=_SHA256)
    cell_results: tuple[EvaluationCellResult, ...] = Field(default=(), max_length=10_000)
    blind_reviews: tuple[EvaluationBlindReview, ...] = Field(default=(), max_length=10_000)
    primary_comparisons: tuple[EvaluationPrimaryComparison, ...] = Field(default=(), max_length=100)
    result_set_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_set_is_unique_and_self_hashed(self) -> EvaluationResultSet:
        identities = (
            [item.cell_id for item in self.cell_results],
            [item.blind_id for item in self.blind_reviews],
            [item.comparison_id for item in self.primary_comparisons],
        )
        if any(len(values) != len(set(values)) for values in identities):
            raise ValueError("evaluation result identities must be unique")
        if any(
            item.proposal_sha256 != self.proposal_sha256 or item.plan_sha256 != self.plan_sha256
            for item in self.cell_results
        ):
            raise ValueError("cell results must bind the result-set proposal and plan")
        provenance = (
            self.run_id,
            self.campaign_manifest_sha256,
            self.launch_config_sha256,
            self.formal_preparation_sha256,
        )
        if self.schema_version == "1.0" and any(item is not None for item in provenance):
            raise ValueError("result set v1.0 cannot carry campaign provenance")
        if self.schema_version == "1.1":
            if any(item is None for item in provenance):
                raise ValueError("result set v1.1 requires complete campaign provenance")
            assert self.run_id is not None
            validate_entry_id(self.run_id, field_name="result-set run_id")
        expected = content_sha256(_result_set_hash_payload(self))
        if self.result_set_sha256 != expected:
            raise ValueError("evaluation result-set hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> EvaluationResultSet:
        payload = {"schema_version": "1.0", **values}
        payload.pop("result_set_sha256", None)
        unsigned = cls.model_construct(result_set_sha256="0" * 64, **payload)
        return cls(
            **payload,
            result_set_sha256=content_sha256(_result_set_hash_payload(unsigned)),
        )


def _comparison_hash_payload(comparison: EvaluationPrimaryComparison) -> dict[str, object]:
    payload = comparison.model_dump(mode="json", exclude={"comparison_sha256"})
    executable_fields = (
        "objective_outcome_contract_sha256",
        "objective_measurement_set_artifact",
        "independent_unit_kind",
        "observed_block_count",
        "inference_role",
        "raw_p_value",
        "adjusted_p_value",
        "alpha",
        "multiplicity_family_sha256",
    )
    if comparison.schema_version == "1.0":
        payload.pop("analysis_input_sha256", None)
        payload.pop("failure_handling", None)
    if comparison.schema_version in {"1.0", "1.1"}:
        for field in executable_fields:
            payload.pop(field, None)
    return payload


def _cell_result_hash_payload(record: EvaluationCellResult) -> dict[str, object]:
    payload = record.model_dump(mode="json", exclude={"record_sha256"})
    if record.schema_version == "1.0":
        payload["usage"].pop("max_input_tokens_observed", None)
        payload["usage"].pop("max_output_tokens_observed", None)
    return payload


def _result_set_hash_payload(result_set: EvaluationResultSet) -> dict[str, object]:
    payload = result_set.model_dump(mode="json", exclude={"result_set_sha256"})
    if result_set.schema_version == "1.0":
        for field in (
            "run_id",
            "campaign_manifest_sha256",
            "launch_config_sha256",
            "formal_preparation_sha256",
        ):
            payload.pop(field, None)
    for record in payload["cell_results"]:
        if record["schema_version"] == "1.0":
            record["usage"].pop("max_input_tokens_observed", None)
            record["usage"].pop("max_output_tokens_observed", None)
    for comparison in payload["primary_comparisons"]:
        if comparison["schema_version"] == "1.0":
            comparison.pop("analysis_input_sha256", None)
            comparison.pop("failure_handling", None)
        if comparison["schema_version"] in {"1.0", "1.1"}:
            for field in (
                "objective_outcome_contract_sha256",
                "objective_measurement_set_artifact",
                "independent_unit_kind",
                "observed_block_count",
                "inference_role",
                "raw_p_value",
                "adjusted_p_value",
                "alpha",
                "multiplicity_family_sha256",
            ):
                comparison.pop(field, None)
    return payload


def claim_analysis_input_sha256(
    claim: ClaimAdmissionContract,
    contrast: ConfirmatoryContrastSpec,
    cells: list[PlannedEvaluationCell] | tuple[PlannedEvaluationCell, ...],
    records: dict[str, EvaluationCellResult],
) -> str:
    """Bind one claim analysis to every exact candidate/comparator outcome record."""

    if contrast not in claim.contrasts:
        raise ValueError("claim analysis contrast is outside the admission contract")
    system_ids = {contrast.candidate_system_id, contrast.comparator_system_id}
    selected = [cell for cell in cells if cell.system_id in system_ids]
    expected_units = {
        (cell.task_id, cell.seed, cell.repetition)
        for cell in selected
        if cell.system_id == contrast.candidate_system_id
    }
    if not expected_units or len(selected) != 2 * len(expected_units):
        raise ValueError("claim analysis cells do not form a complete paired population")
    if {
        (cell.task_id, cell.seed, cell.repetition)
        for cell in selected
        if cell.system_id == contrast.comparator_system_id
    } != expected_units:
        raise ValueError("claim analysis candidate and comparator units differ")
    if any(cell.cell_id not in records for cell in selected):
        raise ValueError("claim analysis is missing a planned result record")
    ordered = sorted(
        selected,
        key=lambda item: (
            item.task_id,
            item.seed,
            item.repetition,
            item.system_id,
            item.cell_id,
        ),
    )
    return content_sha256(
        {
            "claim_contract_sha256": content_sha256(claim),
            "contrast_id": contrast.contrast_id,
            "failure_handling": claim.failure_handling,
            "records": [
                {
                    "cell_id": cell.cell_id,
                    "record_sha256": records[cell.cell_id].record_sha256,
                    "status": records[cell.cell_id].status,
                }
                for cell in ordered
            ],
        }
    )


class EvaluationCellResultAudit(BaseModel):
    model_config = _CONFIG

    cell_id: str = Field(pattern=_CELL_ID)
    lane_id: str
    system_id: str
    task_id: str
    status: Literal["missing", "failed", "succeeded", "invalid"]
    real_evidence: bool
    budget_compliant: bool
    external_review_valid: bool
    issue_codes: tuple[str, ...]


class EvaluationOutcomeAssessment(BaseModel):
    """Deterministic admission verdict; completeness and positive effect stay separate."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    project_id: str
    evaluation_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    result_set_sha256: str = Field(pattern=_SHA256)
    status: Literal["incomplete", "complete"]
    planned_cells: int = Field(ge=0)
    verified_records: int = Field(ge=0)
    succeeded_cells: int = Field(ge=0)
    failed_cells: int = Field(ge=0)
    missing_cells: int = Field(ge=0)
    invalid_cells: int = Field(ge=0)
    matched_backbone_cells: int = Field(ge=0)
    valid_external_reviews: int = Field(ge=0)
    required_primary_comparisons: int = Field(ge=0)
    valid_primary_comparisons: int = Field(ge=0)
    scientific_evidence_complete: bool
    headline_eligible: bool
    scientific_effectiveness_established: bool
    confirmatory_estimand_kind: ConfirmatoryEstimandKind | None = None
    confirmatory_evidence_complete: bool | None = None
    confirmatory_conclusion_supported: bool | None = None
    required_confirmatory_comparisons: int | None = Field(default=None, ge=0)
    valid_confirmatory_comparisons: int | None = Field(default=None, ge=0)
    supported_confirmatory_comparisons: int | None = Field(default=None, ge=0)
    required_diagnostic_comparisons: int | None = Field(default=None, ge=0)
    valid_diagnostic_comparisons: int | None = Field(default=None, ge=0)
    title_claim_eligible: bool | None = None
    external_superiority_eligible: bool | None = None
    descriptive_external_complete: bool | None = None
    blocker_codes: tuple[str, ...]
    cells: tuple[EvaluationCellResultAudit, ...]
    assessment_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def assessment_is_consistent_and_self_hashed(self) -> EvaluationOutcomeAssessment:
        if self.planned_cells != len(self.cells):
            raise ValueError("assessment must audit every planned cell")
        if self.verified_records + self.missing_cells + self.invalid_cells != self.planned_cells:
            raise ValueError("assessment cell counts do not cover the plan")
        if self.succeeded_cells + self.failed_cells != self.verified_records:
            raise ValueError("verified result counts do not close")
        if self.status == "complete" and (self.missing_cells or self.invalid_cells):
            raise ValueError("a complete result set cannot have missing or invalid cells")
        extensions = (
            self.confirmatory_estimand_kind,
            self.confirmatory_evidence_complete,
            self.confirmatory_conclusion_supported,
            self.title_claim_eligible,
            self.external_superiority_eligible,
            self.descriptive_external_complete,
        )
        inference_counts = (
            self.required_confirmatory_comparisons,
            self.valid_confirmatory_comparisons,
            self.supported_confirmatory_comparisons,
            self.required_diagnostic_comparisons,
            self.valid_diagnostic_comparisons,
        )
        if self.schema_version == "1.0":
            if any(value is not None for value in extensions):
                raise ValueError("outcome assessment v1.1 is required for claim semantics")
            if self.headline_eligible != self.scientific_evidence_complete:
                raise ValueError("headline eligibility must match complete scientific evidence")
        else:
            if any(value is None for value in extensions):
                raise ValueError("outcome assessment v1.1 requires complete claim semantics")
            assert self.confirmatory_estimand_kind is not None
            assert self.confirmatory_evidence_complete is not None
            assert self.confirmatory_conclusion_supported is not None
            assert self.title_claim_eligible is not None
            assert self.external_superiority_eligible is not None
            assert self.descriptive_external_complete is not None
            causal_complete = self.confirmatory_evidence_complete and (
                self.confirmatory_estimand_kind is not ConfirmatoryEstimandKind.EXTERNAL_BEST_NATIVE
            )
            if self.scientific_evidence_complete != causal_complete:
                raise ValueError(
                    "scientific evidence must exclude descriptive best-native evidence"
                )
            if self.headline_eligible != causal_complete:
                raise ValueError("headline eligibility must match complete causal evidence")
            expected_title = (
                self.confirmatory_estimand_kind
                in {
                    ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL,
                    ConfirmatoryEstimandKind.NATIVE_TASTE_MECHANISMS,
                    ConfirmatoryEstimandKind.COMPLETE_SYSTEM_BUNDLE_EFFECT,
                }
                and self.confirmatory_evidence_complete
                and self.confirmatory_conclusion_supported
            )
            if self.title_claim_eligible != expected_title:
                raise ValueError("title eligibility differs from native causal evidence")
            expected_external = (
                self.confirmatory_estimand_kind
                is ConfirmatoryEstimandKind.EXTERNAL_MATCHED_SUPERIORITY
                and self.confirmatory_evidence_complete
                and self.confirmatory_conclusion_supported
            )
            if self.external_superiority_eligible != expected_external:
                raise ValueError("external superiority differs from matched external evidence")
            expected_descriptive = (
                self.confirmatory_estimand_kind is ConfirmatoryEstimandKind.EXTERNAL_BEST_NATIVE
                and self.confirmatory_evidence_complete
            )
            if self.descriptive_external_complete != expected_descriptive:
                raise ValueError("descriptive completion differs from best-native evidence")
        if self.schema_version in {"1.0", "1.1"}:
            if any(value is not None for value in inference_counts):
                raise ValueError("outcome assessment v1.2 is required for inference counts")
        else:
            if any(value is None for value in inference_counts):
                raise ValueError("outcome assessment v1.2 requires complete inference counts")
            assert self.required_confirmatory_comparisons is not None
            assert self.valid_confirmatory_comparisons is not None
            assert self.supported_confirmatory_comparisons is not None
            assert self.required_diagnostic_comparisons is not None
            assert self.valid_diagnostic_comparisons is not None
            if self.required_confirmatory_comparisons < 1:
                raise ValueError("claim admission requires at least one confirmatory comparison")
            if (
                self.required_confirmatory_comparisons + self.required_diagnostic_comparisons
                != self.required_primary_comparisons
                or self.valid_confirmatory_comparisons + self.valid_diagnostic_comparisons
                != self.valid_primary_comparisons
            ):
                raise ValueError("inference comparison counts do not partition all analyses")
            if (
                not (
                    self.supported_confirmatory_comparisons
                    <= self.valid_confirmatory_comparisons
                    <= self.required_confirmatory_comparisons
                )
                or self.valid_diagnostic_comparisons > self.required_diagnostic_comparisons
            ):
                raise ValueError("inference comparison counts exceed their declared populations")
            expected_supported = bool(
                self.confirmatory_evidence_complete
                and self.supported_confirmatory_comparisons
                == self.required_confirmatory_comparisons
            )
            if self.confirmatory_conclusion_supported != expected_supported:
                raise ValueError(
                    "confirmatory conclusion differs from explicit confirmatory comparisons"
                )
        if self.scientific_effectiveness_established and not self.headline_eligible:
            raise ValueError("effectiveness requires headline-eligible evidence")
        if self.schema_version in {
            "1.1",
            "1.2",
        } and self.scientific_effectiveness_established != bool(
            self.confirmatory_conclusion_supported and self.headline_eligible
        ):
            raise ValueError("effectiveness differs from complete supported causal evidence")
        expected = content_sha256(_outcome_hash_payload(self))
        if self.assessment_sha256 != expected:
            raise ValueError("evaluation outcome assessment hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> EvaluationOutcomeAssessment:
        payload = {"schema_version": "1.0", **values}
        payload.pop("assessment_sha256", None)
        unsigned = cls.model_construct(assessment_sha256="0" * 64, **payload)
        return cls(
            **payload,
            assessment_sha256=content_sha256(_outcome_hash_payload(unsigned)),
        )


def _outcome_hash_payload(assessment: EvaluationOutcomeAssessment) -> dict[str, object]:
    payload = assessment.model_dump(mode="json", exclude={"assessment_sha256"})
    if assessment.schema_version == "1.0":
        for field in (
            "confirmatory_estimand_kind",
            "confirmatory_evidence_complete",
            "confirmatory_conclusion_supported",
            "title_claim_eligible",
            "external_superiority_eligible",
            "descriptive_external_complete",
        ):
            payload.pop(field, None)
    if assessment.schema_version in {"1.0", "1.1"}:
        for field in (
            "required_confirmatory_comparisons",
            "valid_confirmatory_comparisons",
            "supported_confirmatory_comparisons",
            "required_diagnostic_comparisons",
            "valid_diagnostic_comparisons",
        ):
            payload.pop(field, None)
    return payload


def inspect_evaluation_results(
    manifest: ExperimentPrelaunchManifest,
    plan: EvaluationCellPlan,
    results: EvaluationResultSet,
    *,
    project_root: str | Path,
    project_id: str,
    evaluation_id: str,
    execution_authorized: bool,
) -> EvaluationOutcomeAssessment:
    """Recompute result, budget, review, and analysis admission from exact bytes."""

    root = Path(project_root).resolve(strict=True)
    expected = (
        project_id,
        evaluation_id,
        manifest.proposal_sha256,
        plan.plan_sha256,
    )
    observed = (
        results.project_id,
        results.evaluation_id,
        results.proposal_sha256,
        results.plan_sha256,
    )
    if observed != expected or plan.proposal_sha256 != manifest.proposal_sha256:
        raise ValueError("evaluation result set differs from its project proposal or plan")

    claim = manifest.analysis.claim_admission if manifest.analysis is not None else None
    if claim is not None:
        expected_claim_binding = (
            claim.estimand_kind,
            claim.lane_id,
            content_sha256(claim),
        )
        observed_claim_binding = (
            plan.claim_estimand_kind,
            plan.claim_lane_id,
            plan.claim_contract_sha256,
        )
        if plan.schema_version not in {"1.2", "1.3"} or (
            observed_claim_binding != expected_claim_binding
        ):
            raise ValueError("evaluation plan differs from its claim-admission contract")
    if (
        manifest.integrity is not None
        and manifest.integrity.task_freeze_semantics
        is TaskFreezeSemantics.BENCHMARK_METADATA_ALLOCATION
    ):
        expected_task_binding = (
            manifest.integrity.formal_task_set_sha256,
            manifest.integrity.task_freeze_sha256,
        )
        observed_task_binding = (
            plan.formal_task_set_sha256,
            plan.task_freeze_file_sha256,
        )
        if plan.schema_version != "1.3" or observed_task_binding != expected_task_binding:
            raise ValueError("evaluation plan differs from its formal task-set allocation")
    claim_cell_ids = {
        cell.cell_id for cell in plan.cells if claim is not None and cell.lane_id == claim.lane_id
    }

    records = {item.cell_id: item for item in results.cell_results}
    reviews = {item.blind_id: item for item in results.blind_reviews}
    audits: list[EvaluationCellResultAudit] = []
    valid_records: dict[str, EvaluationCellResult] = {}
    valid_reviews: set[str] = set()
    for cell in plan.cells:
        record = records.get(cell.cell_id)
        issues: list[str] = []
        if record is None:
            status = "missing"
            issues.append(f"cell:{cell.cell_id}:result-missing")
        else:
            issues.extend(_record_issues(root, cell, plan, record))
            status = "invalid" if issues else record.status
            if not issues:
                valid_records[cell.cell_id] = record
        review = reviews.get(cell.review_blind_id)
        review_valid = False
        if review is not None:
            review_issues = _review_issues(root, cell, manifest, review)
            issues.extend(review_issues)
            review_valid = not review_issues
            if review_valid:
                valid_reviews.add(cell.review_blind_id)
        elif manifest.human_review.required and (
            (claim is None and cell.scientific_role is ScientificLaneRole.MATCHED_BACKBONE)
            or cell.cell_id in claim_cell_ids
        ):
            issues.append(f"review:{cell.review_blind_id}:missing")
        audits.append(
            EvaluationCellResultAudit(
                cell_id=cell.cell_id,
                lane_id=cell.lane_id,
                system_id=cell.system_id,
                task_id=cell.task_id,
                status=status,
                real_evidence=bool(record and record.evidence_class == "real" and not issues),
                budget_compliant=bool(record and not _budget_issues(cell, record)),
                external_review_valid=review_valid,
                issue_codes=tuple(sorted(set(issues))),
            )
        )

    unplanned_results = sorted(set(records) - {item.cell_id for item in plan.cells})
    unplanned_reviews = sorted(set(reviews) - {item.review_blind_id for item in plan.cells})
    blockers = {code for audit in audits for code in audit.issue_codes}
    blockers.update(f"result:{identity}:unplanned" for identity in unplanned_results)
    blockers.update(f"review:{identity}:unplanned" for identity in unplanned_reviews)

    matched = [
        item for item in plan.cells if item.scientific_role is ScientificLaneRole.MATCHED_BACKBONE
    ]
    analysis_contract_sha256 = (
        content_sha256(manifest.analysis) if manifest.analysis is not None else None
    )
    objective_outcome_contract_sha256 = (
        manifest.analysis.objective_outcome_contract_sha256
        if manifest.analysis is not None
        else None
    )
    if claim is None:
        for cell in matched:
            record = valid_records.get(cell.cell_id)
            if record is not None and record.status == "failed":
                blockers.add(f"headline:cell:{cell.cell_id}:execution-failed:{record.error_code}")
            if record is not None and record.evidence_class != "real":
                blockers.add(f"headline:cell:{cell.cell_id}:real-evidence-required")
        comparison_issues, required_pairs, valid_pairs, supported_pairs = _comparison_status(
            root,
            matched,
            results.primary_comparisons,
            analysis_contract_sha256=analysis_contract_sha256,
        )
        blockers.update(comparison_issues)
        if manifest.study_scope != "formal":
            blockers.add("headline:formal-scope-required")
        if not execution_authorized:
            blockers.add("headline:exact-proposal-authorization-unverified")
        if not plan.ready_for_launch_preparation or not plan.proposal_author_approved:
            blockers.add("headline:launch-plan-was-not-ready-and-approved")
        if not matched:
            blockers.add("headline:matched-backbone-lane-missing")

        matched_ready = bool(matched) and all(
            (record := valid_records.get(cell.cell_id)) is not None
            and record.status == "succeeded"
            and record.evidence_class == "real"
            and (not manifest.human_review.required or cell.review_blind_id in valid_reviews)
            for cell in matched
        )
        scientific_complete = (
            manifest.study_scope == "formal"
            and execution_authorized
            and plan.ready_for_launch_preparation
            and plan.proposal_author_approved
            and matched_ready
            and bool(required_pairs)
            and required_pairs == valid_pairs
            and not comparison_issues
            and not unplanned_results
            and not unplanned_reviews
        )
        effectiveness = scientific_complete and supported_pairs == required_pairs
        assessment_version = "1.0"
        claim_fields: dict[str, object] = {}
    else:
        claim_cells = [cell for cell in plan.cells if cell.lane_id == claim.lane_id]
        for cell in claim_cells:
            record = valid_records.get(cell.cell_id)
            if record is not None and record.evidence_class != "real":
                blockers.add(f"claim:cell:{cell.cell_id}:real-evidence-required")
        comparison_issues, required_specs, valid_specs, supported_specs = _claim_comparison_status(
            root,
            claim,
            claim_cells,
            valid_records,
            results.primary_comparisons,
            analysis_contract_sha256=analysis_contract_sha256,
            objective_outcome_contract_sha256=objective_outcome_contract_sha256,
            manifest=manifest,
            plan=plan,
            result_set=results,
        )
        blockers.update(comparison_issues)
        if manifest.study_scope != "formal":
            blockers.add("claim:formal-scope-required")
        if not execution_authorized:
            blockers.add("claim:exact-proposal-authorization-unverified")
        if not plan.ready_for_launch_preparation or not plan.proposal_author_approved:
            blockers.add("claim:launch-plan-was-not-ready-and-approved")
        distinct_tasks = {cell.task_id for cell in claim_cells}
        if len(distinct_tasks) < claim.minimum_distinct_tasks:
            blockers.add("claim:minimum-distinct-tasks-not-met")
        if not claim_cells:
            blockers.add("claim:lane-cells-missing")

        claim_cells_ready = bool(claim_cells) and all(
            (record := valid_records.get(cell.cell_id)) is not None
            and record.evidence_class == "real"
            and (not manifest.human_review.required or cell.review_blind_id in valid_reviews)
            for cell in claim_cells
        )
        confirmatory_complete = (
            manifest.study_scope == "formal"
            and execution_authorized
            and plan.ready_for_launch_preparation
            and plan.proposal_author_approved
            and claim_cells_ready
            and bool(required_specs)
            and required_specs == valid_specs
            and not comparison_issues
            and not unplanned_results
            and not unplanned_reviews
            and len(distinct_tasks) >= claim.minimum_distinct_tasks
        )
        confirmatory_specs = {
            item.contrast_id
            for item in claim.contrasts
            if item.inference_role in {None, ContrastInferenceRole.CONFIRMATORY}
        }
        diagnostic_specs = required_specs - confirmatory_specs
        conclusion_supported = (
            confirmatory_complete and (supported_specs & confirmatory_specs) == confirmatory_specs
        )
        causal = claim.estimand_kind is not ConfirmatoryEstimandKind.EXTERNAL_BEST_NATIVE
        scientific_complete = confirmatory_complete and causal
        effectiveness = scientific_complete and conclusion_supported
        assessment_version = "1.2" if manifest.schema_version == "1.4" else "1.1"
        claim_fields = {
            "confirmatory_estimand_kind": claim.estimand_kind,
            "confirmatory_evidence_complete": confirmatory_complete,
            "confirmatory_conclusion_supported": conclusion_supported,
            "title_claim_eligible": (
                claim.estimand_kind
                in {
                    ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL,
                    ConfirmatoryEstimandKind.NATIVE_TASTE_MECHANISMS,
                    ConfirmatoryEstimandKind.COMPLETE_SYSTEM_BUNDLE_EFFECT,
                }
                and conclusion_supported
            ),
            "external_superiority_eligible": (
                claim.estimand_kind is ConfirmatoryEstimandKind.EXTERNAL_MATCHED_SUPERIORITY
                and conclusion_supported
            ),
            "descriptive_external_complete": (
                claim.estimand_kind is ConfirmatoryEstimandKind.EXTERNAL_BEST_NATIVE
                and confirmatory_complete
            ),
        }
        if assessment_version == "1.2":
            claim_fields.update(
                {
                    "required_confirmatory_comparisons": len(confirmatory_specs),
                    "valid_confirmatory_comparisons": len(valid_specs & confirmatory_specs),
                    "supported_confirmatory_comparisons": len(supported_specs & confirmatory_specs),
                    "required_diagnostic_comparisons": len(diagnostic_specs),
                    "valid_diagnostic_comparisons": len(valid_specs & diagnostic_specs),
                }
            )
    missing = sum(item.status == "missing" for item in audits)
    invalid = sum(item.status == "invalid" for item in audits)
    verified = len(audits) - missing - invalid
    return EvaluationOutcomeAssessment.create(
        schema_version=assessment_version,
        project_id=project_id,
        evaluation_id=evaluation_id,
        proposal_sha256=manifest.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        result_set_sha256=results.result_set_sha256,
        status="complete" if not missing and not invalid else "incomplete",
        planned_cells=len(plan.cells),
        verified_records=verified,
        succeeded_cells=sum(item.status == "succeeded" for item in audits),
        failed_cells=sum(item.status == "failed" for item in audits),
        missing_cells=missing,
        invalid_cells=invalid,
        matched_backbone_cells=len(matched),
        valid_external_reviews=len(valid_reviews),
        required_primary_comparisons=(
            len(required_pairs) if claim is None else len(required_specs)
        ),
        valid_primary_comparisons=len(valid_pairs) if claim is None else len(valid_specs),
        scientific_evidence_complete=scientific_complete,
        headline_eligible=scientific_complete,
        scientific_effectiveness_established=effectiveness,
        **claim_fields,
        blocker_codes=tuple(sorted(blockers)),
        cells=tuple(audits),
    )


def _record_issues(
    root: Path,
    cell: PlannedEvaluationCell,
    plan: EvaluationCellPlan,
    record: EvaluationCellResult,
) -> list[str]:
    issues: list[str] = []
    if record.cell_sha256 != content_sha256(cell):
        issues.append(f"cell:{cell.cell_id}:identity-mismatch")
    if record.resource_sha256 != cell.resource.resource_sha256:
        issues.append(f"cell:{cell.cell_id}:resource-mismatch")
    if record.proposal_sha256 != plan.proposal_sha256 or record.plan_sha256 != plan.plan_sha256:
        issues.append(f"cell:{cell.cell_id}:protocol-mismatch")
    issues.extend(_budget_issues(cell, record))
    for artifact in record.artifacts:
        if not _artifact_matches(root, artifact):
            issues.append(f"cell:{cell.cell_id}:artifact-invalid:{artifact.locator}")
    return issues


def _budget_issues(cell: PlannedEvaluationCell, record: EvaluationCellResult) -> list[str]:
    usage = record.usage
    resource = cell.resource
    issues: list[str] = []
    has_api = cell.lane_kind in {ExecutionLaneKind.API_ONLY, ExecutionLaneKind.HYBRID}
    has_gpu = cell.lane_kind in {ExecutionLaneKind.GPU, ExecutionLaneKind.HYBRID}
    if has_api:
        required = (
            usage.request_count,
            usage.input_tokens,
            usage.output_tokens,
            usage.max_input_tokens_observed,
            usage.max_output_tokens_observed,
            usage.api_cost,
        )
        if record.schema_version == "1.1" and any(value is None for value in required):
            issues.append(f"cell:{cell.cell_id}:api-telemetry-incomplete")
        else:
            assert usage.request_count is not None
            assert usage.input_tokens is not None
            assert usage.output_tokens is not None
            assert usage.api_cost is not None
            if usage.request_count > (resource.max_requests or 0):
                issues.append(f"cell:{cell.cell_id}:request-budget-exceeded")
            if usage.input_tokens + usage.output_tokens > (resource.max_total_tokens or 0):
                issues.append(f"cell:{cell.cell_id}:token-budget-exceeded")
            if usage.max_input_tokens_observed is not None and usage.max_input_tokens_observed > (
                resource.max_input_tokens_per_call or 0
            ):
                issues.append(f"cell:{cell.cell_id}:input-token-call-budget-exceeded")
            if usage.max_output_tokens_observed is not None and usage.max_output_tokens_observed > (
                resource.max_output_tokens_per_call or 0
            ):
                issues.append(f"cell:{cell.cell_id}:output-token-call-budget-exceeded")
            if usage.api_cost > (resource.max_cost or 0):
                issues.append(f"cell:{cell.cell_id}:cost-budget-exceeded")
    if has_gpu:
        if usage.gpu_hours is None or (
            cell.lane_kind is ExecutionLaneKind.GPU and usage.api_cost is not None
        ):
            issues.append(f"cell:{cell.cell_id}:gpu-telemetry-incomplete")
        elif usage.gpu_hours > (resource.max_gpu_hours or 0):
            issues.append(f"cell:{cell.cell_id}:gpu-budget-exceeded")
        local_model_telemetry = (
            usage.request_count,
            usage.input_tokens,
            usage.output_tokens,
            usage.max_input_tokens_observed,
            usage.max_output_tokens_observed,
        )
        if (
            record.schema_version == "1.1"
            and any(value is not None for value in local_model_telemetry)
            and any(value is None for value in local_model_telemetry)
        ):
            issues.append(f"cell:{cell.cell_id}:local-model-telemetry-incomplete")
        if sum(item.size_bytes for item in record.artifacts) > (resource.max_storage_bytes or 0):
            issues.append(f"cell:{cell.cell_id}:storage-budget-exceeded")
    return issues


def _review_issues(
    root: Path,
    cell: PlannedEvaluationCell,
    manifest: ExperimentPrelaunchManifest,
    review: EvaluationBlindReview,
) -> list[str]:
    issues: list[str] = []
    if review.blind_id != cell.review_blind_id:
        issues.append(f"review:{cell.review_blind_id}:identity-mismatch")
    if manifest.human_review.required and review.source != "external":
        issues.append(f"review:{cell.review_blind_id}:not-external")
    expected_rubric_sha256 = (
        manifest.integrity.judge_protocol_sha256 if manifest.integrity is not None else None
    )
    if manifest.human_review.required and expected_rubric_sha256 is None:
        issues.append(f"review:{cell.review_blind_id}:rubric-unbound")
    elif expected_rubric_sha256 is not None and review.rubric_sha256 != expected_rubric_sha256:
        issues.append(f"review:{cell.review_blind_id}:rubric-mismatch")
    if len(review.reviewer_identity_hashes) < manifest.human_review.minimum_reviewers_per_artifact:
        issues.append(f"review:{cell.review_blind_id}:reviewer-count-insufficient")
    if not _artifact_matches(root, review.attestation):
        issues.append(f"review:{cell.review_blind_id}:attestation-invalid")
    return issues


def _comparison_status(
    root: Path,
    matched: list[PlannedEvaluationCell],
    comparisons: tuple[EvaluationPrimaryComparison, ...],
    *,
    analysis_contract_sha256: str | None,
) -> tuple[set[str], set[tuple[str, str]], set[tuple[str, str]], set[tuple[str, str]]]:
    candidate_ids = sorted(
        {item.system_id for item in matched if item.system_role is SystemRole.SCITASTE}
    )
    comparator_ids = sorted(
        {item.system_id for item in matched if item.system_role is SystemRole.METHOD_COMPARATOR}
    )
    issues: set[str] = set()
    if len(candidate_ids) != 1:
        issues.add("analysis:exactly-one-scitaste-candidate-required")
    if len(comparator_ids) < 2:
        issues.add("analysis:two-independent-method-comparators-required")
    required = (
        {(candidate_ids[0], comparator) for comparator in comparator_ids}
        if len(candidate_ids) == 1 and len(comparator_ids) >= 2
        else set()
    )
    valid: set[tuple[str, str]] = set()
    supported: set[tuple[str, str]] = set()
    for comparison in comparisons:
        pair = (comparison.candidate_system_id, comparison.comparator_system_id)
        if pair not in required:
            issues.add(f"analysis:{comparison.comparison_id}:unplanned-contrast")
            continue
        if comparison.analysis_contract_sha256 != analysis_contract_sha256:
            issues.add(f"analysis:{comparison.comparison_id}:contract-mismatch")
            continue
        if not _artifact_matches(root, comparison.analysis_artifact):
            issues.add(f"analysis:{comparison.comparison_id}:artifact-invalid")
            continue
        if pair in valid:
            issues.add(f"analysis:{comparison.comparison_id}:duplicate-contrast")
            continue
        valid.add(pair)
        if comparison.conclusion == "supports_claim":
            supported.add(pair)
    for candidate, comparator in sorted(required - valid):
        issues.add(f"analysis:{candidate}-vs-{comparator}:missing")
    return issues, required, valid, supported


def _claim_comparison_status(
    root: Path,
    claim: ClaimAdmissionContract,
    cells: list[PlannedEvaluationCell],
    records: dict[str, EvaluationCellResult],
    comparisons: tuple[EvaluationPrimaryComparison, ...],
    *,
    analysis_contract_sha256: str | None,
    objective_outcome_contract_sha256: str | None,
    manifest: ExperimentPrelaunchManifest,
    plan: EvaluationCellPlan,
    result_set: EvaluationResultSet,
) -> tuple[set[str], set[str], set[str], set[str]]:
    """Check exact preregistered contrasts without treating failures as exclusions."""

    specs = {item.contrast_id: item for item in claim.contrasts}
    required = set(specs)
    valid: set[str] = set()
    supported: set[str] = set()
    issues: set[str] = set()
    units_by_system: dict[str, set[tuple[str, int, int]]] = {}
    for cell in cells:
        units_by_system.setdefault(cell.system_id, set()).add(
            (cell.task_id, cell.seed, cell.repetition)
        )

    for spec in claim.contrasts:
        candidate_units = units_by_system.get(spec.candidate_system_id, set())
        comparator_units = units_by_system.get(spec.comparator_system_id, set())
        if not candidate_units or candidate_units != comparator_units:
            issues.add(f"analysis:{spec.contrast_id}:planned-units-not-paired")

    h4_claim = (
        claim.estimand_kind is ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL
        and any(cell.system_id in _H4_SYSTEM_IDS for cell in cells)
    )
    if h4_claim:
        provenance = (
            result_set.run_id,
            result_set.campaign_manifest_sha256,
            result_set.launch_config_sha256,
            result_set.formal_preparation_sha256,
        )
        if result_set.schema_version != "1.1" or any(item is None for item in provenance):
            issues.add("analysis:h4-formal-campaign-provenance-required")
        issues.update(
            f"analysis:{item.comparison_id}:h4-requires-executable-schema-1.2"
            for item in comparisons
            if item.schema_version != "1.2"
        )
    executable_comparisons = [item for item in comparisons if item.schema_version == "1.2"]
    expected_executable: dict[str, EvaluationPrimaryComparison] = {}
    if executable_comparisons:
        try:
            expected_executable = _recompute_objective_comparisons(
                root,
                manifest,
                plan,
                result_set,
                executable_comparisons,
            )
        except (OSError, ValueError):
            issues.update(
                f"analysis:{item.comparison_id}:executable-recomputation-failed"
                for item in executable_comparisons
            )

    for comparison in comparisons:
        spec = specs.get(comparison.comparison_id)
        if spec is None:
            issues.add(f"analysis:{comparison.comparison_id}:unplanned-contrast")
            continue
        if h4_claim and comparison.schema_version != "1.2":
            continue
        if (
            comparison.candidate_system_id != spec.candidate_system_id
            or comparison.comparator_system_id != spec.comparator_system_id
        ):
            issues.add(f"analysis:{comparison.comparison_id}:pair-mismatch")
            continue
        if (
            comparison.favorable_direction != spec.favorable_direction
            or comparison.minimum_effect != spec.minimum_effect
        ):
            issues.add(f"analysis:{comparison.comparison_id}:decision-rule-mismatch")
            continue
        expected_blocks = len(units_by_system.get(spec.candidate_system_id, set()))
        expected_tasks = len(
            {
                task_id
                for task_id, _seed, _repetition in units_by_system.get(
                    spec.candidate_system_id, set()
                )
            }
        )
        expected_units = expected_tasks if comparison.schema_version == "1.2" else expected_blocks
        if comparison.analysis_unit_count != expected_units:
            issues.add(f"analysis:{comparison.comparison_id}:analysis-unit-count-mismatch")
            continue
        if comparison.schema_version == "1.2" and (
            comparison.independent_unit_kind != "held-out-task"
            or comparison.observed_block_count != expected_blocks
            or comparison.inference_role
            != (spec.inference_role or ContrastInferenceRole.CONFIRMATORY)
            or comparison.objective_outcome_contract_sha256 != objective_outcome_contract_sha256
        ):
            issues.add(f"analysis:{comparison.comparison_id}:executable-inference-mismatch")
            continue
        if comparison.schema_version == "1.2" and (
            expected_executable.get(comparison.comparison_id) != comparison
        ):
            issues.add(f"analysis:{comparison.comparison_id}:executable-analysis-mismatch")
            continue
        try:
            expected_input = claim_analysis_input_sha256(claim, spec, cells, records)
        except ValueError:
            issues.add(f"analysis:{comparison.comparison_id}:analysis-input-incomplete")
            continue
        if (
            comparison.schema_version not in {"1.1", "1.2"}
            or comparison.failure_handling != claim.failure_handling
            or comparison.analysis_input_sha256 != expected_input
        ):
            issues.add(f"analysis:{comparison.comparison_id}:analysis-input-mismatch")
            continue
        if comparison.analysis_contract_sha256 != analysis_contract_sha256:
            issues.add(f"analysis:{comparison.comparison_id}:contract-mismatch")
            continue
        if not _artifact_matches(root, comparison.analysis_artifact):
            issues.add(f"analysis:{comparison.comparison_id}:artifact-invalid")
            continue
        valid.add(comparison.comparison_id)
        if comparison.conclusion == "supports_claim":
            supported.add(comparison.comparison_id)

    for contrast_id in sorted(required - valid):
        issues.add(f"analysis:{contrast_id}:missing")
    return issues, required, valid, supported


def _recompute_objective_comparisons(
    root: Path,
    manifest: ExperimentPrelaunchManifest,
    plan: EvaluationCellPlan,
    result_set: EvaluationResultSet,
    comparisons: list[EvaluationPrimaryComparison],
) -> dict[str, EvaluationPrimaryComparison]:
    """Re-run v1.2 inference from its bound measurements before claim admission."""

    from scitaste.evaluation.objective_analysis import (  # avoid an import cycle
        ObjectiveAnalysisReport,
        analyze_objective_outcomes,
        load_objective_measurement_set,
        load_objective_outcome_contract,
        primary_comparisons_from_objective_report,
    )

    analysis_artifacts = {item.analysis_artifact for item in comparisons}
    measurement_artifacts = {
        item.objective_measurement_set_artifact
        for item in comparisons
        if item.objective_measurement_set_artifact is not None
    }
    if len(analysis_artifacts) != 1 or len(measurement_artifacts) != 1:
        raise ValueError("executable comparisons must share analysis and measurement artifacts")
    analysis_artifact = next(iter(analysis_artifacts))
    measurement_artifact = next(iter(measurement_artifacts))
    if not _artifact_matches(root, analysis_artifact) or not _artifact_matches(
        root, measurement_artifact
    ):
        raise ValueError("executable objective artifact is missing or changed")
    if manifest.analysis is None or manifest.analysis.objective_outcome_contract_ref is None:
        raise ValueError("objective outcome contract is not bound")
    contract = load_objective_outcome_contract(
        root / PurePosixPath(manifest.analysis.objective_outcome_contract_ref)
    )
    measurements = load_objective_measurement_set(
        root / PurePosixPath(measurement_artifact.locator)
    )
    raw_results = EvaluationResultSet.create(
        schema_version=result_set.schema_version,
        project_id=result_set.project_id,
        evaluation_id=result_set.evaluation_id,
        proposal_sha256=result_set.proposal_sha256,
        plan_sha256=result_set.plan_sha256,
        run_id=result_set.run_id,
        campaign_manifest_sha256=result_set.campaign_manifest_sha256,
        launch_config_sha256=result_set.launch_config_sha256,
        formal_preparation_sha256=result_set.formal_preparation_sha256,
        cell_results=result_set.cell_results,
        blind_reviews=result_set.blind_reviews,
        primary_comparisons=(),
    )
    recomputed_report = analyze_objective_outcomes(
        manifest,
        plan,
        raw_results,
        contract,
        measurements,
        project_root=root,
        project_id=result_set.project_id,
        evaluation_id=result_set.evaluation_id,
    )
    report_path = root / PurePosixPath(analysis_artifact.locator)
    reported = ObjectiveAnalysisReport.model_validate_json(report_path.read_bytes())
    if reported != recomputed_report:
        raise ValueError("objective analysis report differs from recomputation")
    expected = primary_comparisons_from_objective_report(
        recomputed_report,
        contract.contract,
        analysis_artifact=analysis_artifact,
        measurement_set_artifact=measurement_artifact,
    )
    return {item.comparison_id: item for item in expected}


def _artifact_matches(root: Path, artifact: EvaluationResultArtifact) -> bool:
    try:
        candidate = root / PurePosixPath(artifact.locator)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        current = root
        for part in PurePosixPath(artifact.locator).parts:
            current /= part
            if current.is_symlink():
                return False
        if not resolved.is_file() or resolved.stat().st_size != artifact.size_bytes:
            return False
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == artifact.sha256
    except (OSError, ValueError):
        return False


__all__ = [
    "EvaluationBlindReview",
    "EvaluationCellResult",
    "EvaluationCellResultAudit",
    "EvaluationCellUsage",
    "EvaluationOutcomeAssessment",
    "EvaluationPrimaryComparison",
    "EvaluationResultArtifact",
    "EvaluationResultSet",
    "claim_analysis_input_sha256",
    "inspect_evaluation_results",
]

"""Executable, task-clustered analysis for preregistered objective outcomes.

This module closes the boundary between raw evaluation-cell records and an
``EvaluationPrimaryComparison``.  Seeds and repetitions are paired blocks, not
independent samples: inference first averages them within each held-out task and
then gives every task equal weight.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from itertools import product
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.cell_plan import EvaluationCellPlan, PlannedEvaluationCell
from scitaste.evaluation.prelaunch import (
    ContrastInferenceRole,
    ExperimentPrelaunchManifest,
)
from scitaste.evaluation.results import (
    EvaluationPrimaryComparison,
    EvaluationResultArtifact,
    EvaluationResultSet,
    claim_analysis_input_sha256,
)
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_MAX_JSON_BYTES = 64 * 1024 * 1024
_IMPLEMENTATION_ID = "scitaste.objective-analysis.task-clustered-v1"


class ObjectiveDirection(StrEnum):
    HIGHER = "higher"
    LOWER = "lower"


class ObjectiveTaskScoreContract(BaseModel):
    """Preregistered normalization and failure floor for one held-out task."""

    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    metric_id: str = Field(pattern=_ID)
    metric_version: str = Field(min_length=1, max_length=100)
    direction: ObjectiveDirection
    raw_minimum: float
    raw_maximum: float
    starting_score: float
    target_score: float
    failure_normalized_score: float
    scorer_artifact: EvaluationResultArtifact

    @model_validator(mode="after")
    def anchors_and_failure_floor_are_preregistered(self) -> ObjectiveTaskScoreContract:
        values = (
            self.raw_minimum,
            self.raw_maximum,
            self.starting_score,
            self.target_score,
            self.failure_normalized_score,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("objective score constants must be finite")
        if not self.raw_minimum < self.raw_maximum:
            raise ValueError("objective raw score range must be non-degenerate")
        if not self.raw_minimum <= self.starting_score <= self.raw_maximum:
            raise ValueError("objective starting score lies outside the raw range")
        if not self.raw_minimum <= self.target_score <= self.raw_maximum:
            raise ValueError("objective target score lies outside the raw range")
        if self.direction is ObjectiveDirection.HIGHER:
            if self.target_score <= self.starting_score:
                raise ValueError("a higher-is-better target must exceed the starting score")
        elif self.target_score >= self.starting_score:
            raise ValueError("a lower-is-better target must be below the starting score")
        possible_floor = min(
            self.normalize(self.raw_minimum),
            self.normalize(self.raw_maximum),
        )
        if not math.isclose(
            self.failure_normalized_score,
            possible_floor,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "failure score must equal the preregistered worst attainable normalized score"
            )
        return self

    def normalize(self, raw_score: float) -> float:
        if self.direction is ObjectiveDirection.HIGHER:
            return (raw_score - self.starting_score) / (self.target_score - self.starting_score)
        return (self.starting_score - raw_score) / (self.starting_score - self.target_score)


class ObjectiveOutcomeContract(BaseModel):
    """Frozen estimator, uncertainty, multiplicity, and task-score contract."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_id: str = Field(pattern=_ID)
    protocol_id: str = Field(pattern=_ID)
    endpoint_id: str = Field(pattern=_ID)
    task_scores: tuple[ObjectiveTaskScoreContract, ...] = Field(min_length=2, max_length=500)
    independent_unit: Literal["held-out-task"] = "held-out-task"
    within_task_aggregation: Literal["arithmetic-mean"] = "arithmetic-mean"
    task_weighting: Literal["equal"] = "equal"
    failure_handling: Literal["preregistered-task-floor"] = "preregistered-task-floor"
    interval_method: Literal["task-clustered-percentile-bootstrap"] = (
        "task-clustered-percentile-bootstrap"
    )
    confidence_level: float = Field(default=0.95, gt=0.5, lt=1)
    bootstrap_resamples: int = Field(default=10_000, ge=1_000, le=1_000_000)
    bootstrap_seed: int = Field(default=202709, ge=0, le=2**63 - 1)
    hypothesis_test: Literal["paired-task-sign-flip"] = "paired-task-sign-flip"
    maximum_exact_sign_flip_tasks: int = Field(default=20, ge=2, le=24)
    monte_carlo_sign_flips: int = Field(default=100_000, ge=10_000, le=10_000_000)
    multiplicity_method: Literal["holm-confirmatory-only"] = "holm-confirmatory-only"
    alpha: float = Field(default=0.05, gt=0, lt=0.5)
    contract_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def tasks_are_independent_and_self_hashed(self) -> ObjectiveOutcomeContract:
        task_ids = [item.task_id for item in self.task_scores]
        source_groups = [item.source_group_id for item in self.task_scores]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("objective outcome task IDs must be unique")
        if len(source_groups) != len(set(source_groups)):
            raise ValueError("each held-out task must use a distinct source group")
        expected = content_sha256(self.model_dump(mode="json", exclude={"contract_sha256"}))
        if self.contract_sha256 != expected:
            raise ValueError("objective outcome contract hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ObjectiveOutcomeContract:
        payload = {"schema_version": "1.0", **values}
        payload.pop("contract_sha256", None)
        unsigned = cls.model_construct(contract_sha256="0" * 64, **payload)
        return cls(
            **payload,
            contract_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"contract_sha256"})
            ),
        )


class ObjectiveOutcomeContractInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    contract: ObjectiveOutcomeContract


class ObjectiveCellMeasurement(BaseModel):
    """One successful cell's externally scored objective measurement."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    cell_id: str = Field(pattern=r"^cell-[0-9a-f]{24}$")
    result_record_sha256: str = Field(pattern=_SHA256)
    metric_id: str = Field(pattern=_ID)
    metric_version: str = Field(min_length=1, max_length=100)
    raw_score: float
    score_artifact: EvaluationResultArtifact
    measurement_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def measurement_is_finite_and_self_hashed(self) -> ObjectiveCellMeasurement:
        if not math.isfinite(self.raw_score):
            raise ValueError("objective cell score must be finite")
        expected = content_sha256(self.model_dump(mode="json", exclude={"measurement_sha256"}))
        if self.measurement_sha256 != expected:
            raise ValueError("objective cell measurement hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ObjectiveCellMeasurement:
        payload = {"schema_version": "1.0", **values}
        payload.pop("measurement_sha256", None)
        unsigned = cls.model_construct(measurement_sha256="0" * 64, **payload)
        return cls(
            **payload,
            measurement_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"measurement_sha256"})
            ),
        )


class ObjectiveMeasurementSet(BaseModel):
    """Closed measurement population; failed cells deliberately have no measurement."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(pattern=_ID)
    evaluation_id: str = Field(pattern=_ID)
    proposal_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    cell_result_population_sha256: str = Field(pattern=_SHA256)
    objective_outcome_contract_sha256: str = Field(pattern=_SHA256)
    measurements: tuple[ObjectiveCellMeasurement, ...] = Field(max_length=10_000)
    measurement_set_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def set_is_unique_and_self_hashed(self) -> ObjectiveMeasurementSet:
        cell_ids = [item.cell_id for item in self.measurements]
        if len(cell_ids) != len(set(cell_ids)):
            raise ValueError("objective cell measurements must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"measurement_set_sha256"}))
        if self.measurement_set_sha256 != expected:
            raise ValueError("objective measurement-set hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ObjectiveMeasurementSet:
        payload = {"schema_version": "1.0", **values}
        payload.pop("measurement_set_sha256", None)
        unsigned = cls.model_construct(measurement_set_sha256="0" * 64, **payload)
        return cls(
            **payload,
            measurement_set_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"measurement_set_sha256"})
            ),
        )


class ObjectiveTaskContrast(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    paired_block_count: int = Field(gt=0)
    candidate_normalized_mean: float
    comparator_normalized_mean: float
    signed_effect: float


class ObjectiveContrastAnalysis(BaseModel):
    model_config = _CONFIG

    contrast_id: str = Field(pattern=_ID)
    candidate_system_id: str = Field(pattern=_ID)
    comparator_system_id: str = Field(pattern=_ID)
    inference_role: ContrastInferenceRole
    favorable_direction: Literal["higher", "lower"]
    minimum_effect: float = Field(ge=0)
    independent_task_count: int = Field(ge=2)
    observed_block_count: int = Field(gt=0)
    task_effects: tuple[ObjectiveTaskContrast, ...] = Field(min_length=2, max_length=500)
    effect_estimate: float
    interval_lower: float
    interval_upper: float
    raw_p_value: float = Field(ge=0, le=1)
    adjusted_p_value: float | None = Field(default=None, ge=0, le=1)
    conclusion: Literal["supports_claim", "inconclusive", "contradicts_claim"]
    analysis_input_sha256: str = Field(pattern=_SHA256)


class ObjectiveAnalysisReport(BaseModel):
    """Deterministic analysis report suitable for result-set evidence binding."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    implementation_id: Literal[_IMPLEMENTATION_ID] = _IMPLEMENTATION_ID
    project_id: str = Field(pattern=_ID)
    evaluation_id: str = Field(pattern=_ID)
    study_scope: Literal["pilot", "formal", "robustness"]
    proposal_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    cell_result_population_sha256: str = Field(pattern=_SHA256)
    analysis_contract_sha256: str = Field(pattern=_SHA256)
    objective_outcome_contract_sha256: str = Field(pattern=_SHA256)
    objective_outcome_contract_semantic_sha256: str = Field(pattern=_SHA256)
    measurement_set_sha256: str = Field(pattern=_SHA256)
    multiplicity_family_sha256: str = Field(pattern=_SHA256)
    comparisons: tuple[ObjectiveContrastAnalysis, ...] = Field(min_length=1, max_length=20)
    confirmatory_comparisons: int = Field(gt=0)
    supported_confirmatory_comparisons: int = Field(ge=0)
    formal_effectiveness_established: bool
    no_model_calls_performed: Literal[True] = True
    no_api_spend_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_closed_and_self_hashed(self) -> ObjectiveAnalysisReport:
        confirmatory = [
            item
            for item in self.comparisons
            if item.inference_role is ContrastInferenceRole.CONFIRMATORY
        ]
        supported = [item for item in confirmatory if item.conclusion == "supports_claim"]
        if self.confirmatory_comparisons != len(confirmatory):
            raise ValueError("objective analysis confirmatory count differs")
        if self.supported_confirmatory_comparisons != len(supported):
            raise ValueError("objective analysis supported count differs")
        expected_effectiveness = (
            self.study_scope == "formal"
            and bool(confirmatory)
            and len(supported) == len(confirmatory)
        )
        if self.formal_effectiveness_established != expected_effectiveness:
            raise ValueError("objective analysis effectiveness decision differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("objective analysis report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ObjectiveAnalysisReport:
        payload = {"schema_version": "1.0", "implementation_id": _IMPLEMENTATION_ID, **values}
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


@dataclass(frozen=True)
class ObjectiveAnalysisMaterialization:
    report: ObjectiveAnalysisReport
    analysis_artifact: EvaluationResultArtifact
    primary_comparisons: tuple[EvaluationPrimaryComparison, ...]
    output_path: Path


def complete_objective_result_set(
    results: EvaluationResultSet,
    materialization: ObjectiveAnalysisMaterialization,
) -> EvaluationResultSet:
    """Attach derived comparisons without changing the analyzed cell population."""

    if results.primary_comparisons:
        raise ValueError("objective analysis refuses to replace existing primary comparisons")
    if (
        objective_cell_population_sha256(results)
        != materialization.report.cell_result_population_sha256
    ):
        raise ValueError("objective analysis cell population changed before completion")
    return EvaluationResultSet.create(
        project_id=results.project_id,
        evaluation_id=results.evaluation_id,
        proposal_sha256=results.proposal_sha256,
        plan_sha256=results.plan_sha256,
        cell_results=results.cell_results,
        blind_reviews=results.blind_reviews,
        primary_comparisons=materialization.primary_comparisons,
    )


def save_completed_objective_result_set(
    results: EvaluationResultSet,
    path: str | Path,
    *,
    project_root: str | Path,
) -> Path:
    """Freeze a completed result set beneath the owning project."""

    root = Path(project_root).resolve(strict=True)
    output = _project_output_path(root, path)
    return _atomic_json(output, results.model_dump(mode="json"), require_absent=True)


def load_objective_outcome_contract(path: str | Path) -> ObjectiveOutcomeContractInspection:
    resolved, raw, payload = _load_json_mapping(path, "objective outcome contract")
    return ObjectiveOutcomeContractInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        contract=ObjectiveOutcomeContract.model_validate(payload),
    )


def load_objective_measurement_set(path: str | Path) -> ObjectiveMeasurementSet:
    _resolved, _raw, payload = _load_json_mapping(path, "objective measurement set")
    return ObjectiveMeasurementSet.model_validate(payload)


def bind_objective_measurement_set(
    path: str | Path,
    *,
    project_root: str | Path,
) -> EvaluationResultArtifact:
    """Validate and content-bind one project-owned measurement-set file."""

    root = Path(project_root).resolve(strict=True)
    requested = Path(path)
    candidate = requested if requested.is_absolute() else root / requested
    resolved = candidate.resolve(strict=True)
    try:
        locator = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("objective measurement set escapes the project root") from exc
    _project_regular_file(root, locator)
    load_objective_measurement_set(resolved)
    return EvaluationResultArtifact(
        locator=locator,
        sha256=_sha256_file(resolved),
        size_bytes=resolved.stat().st_size,
    )


def save_objective_outcome_contract(contract: ObjectiveOutcomeContract, path: str | Path) -> Path:
    return _atomic_json(path, contract.model_dump(mode="json"), require_absent=True)


def save_objective_measurement_set(measurements: ObjectiveMeasurementSet, path: str | Path) -> Path:
    return _atomic_json(path, measurements.model_dump(mode="json"), require_absent=True)


def analyze_objective_outcomes(
    manifest: ExperimentPrelaunchManifest,
    plan: EvaluationCellPlan,
    results: EvaluationResultSet,
    contract_inspection: ObjectiveOutcomeContractInspection,
    measurements: ObjectiveMeasurementSet,
    *,
    project_root: str | Path,
    evidence_root: str | Path | None = None,
    project_id: str,
    evaluation_id: str,
) -> ObjectiveAnalysisReport:
    """Compute task-level paired estimates without launching any external resource."""

    root = Path(project_root).resolve(strict=True)
    protocol_root = (
        Path(evidence_root).resolve(strict=True) if evidence_root is not None else root
    )
    contract = contract_inspection.contract
    if manifest.analysis is None or manifest.analysis.claim_admission is None:
        raise ValueError("objective analysis requires a preregistered claim-admission contract")
    analysis = manifest.analysis
    claim = analysis.claim_admission
    if analysis.objective_outcome_contract_ref is None:
        raise ValueError("prelaunch analysis does not bind an objective-outcome contract")
    expected_contract_path = _project_regular_file(
        protocol_root, analysis.objective_outcome_contract_ref
    )
    if contract_inspection.path.resolve(strict=True) != expected_contract_path:
        raise ValueError("objective outcome contract path differs from the prelaunch binding")
    if analysis.objective_outcome_contract_sha256 != contract_inspection.file_sha256:
        raise ValueError("objective outcome contract bytes differ from the prelaunch binding")
    if contract.protocol_id != manifest.protocol_id:
        raise ValueError("objective outcome contract protocol differs from prelaunch")
    if manifest.study_scope == "formal":
        if analysis.power_analysis_ref is None or analysis.power_analysis_sha256 is None:
            raise ValueError("formal objective analysis requires a content-bound power analysis")
        power_path = _project_regular_file(protocol_root, analysis.power_analysis_ref)
        if _sha256_file(power_path) != analysis.power_analysis_sha256:
            raise ValueError("formal power-analysis bytes differ from prelaunch")

    if plan.proposal_sha256 != manifest.proposal_sha256 or plan.plan_sha256 != results.plan_sha256:
        raise ValueError("objective analysis proposal or plan binding differs")
    if results.proposal_sha256 != plan.proposal_sha256:
        raise ValueError("objective result-set proposal differs")
    if results.project_id != project_id or results.evaluation_id != evaluation_id:
        raise ValueError("objective result set identity differs")
    if (
        measurements.project_id != project_id
        or measurements.evaluation_id != evaluation_id
        or measurements.proposal_sha256 != plan.proposal_sha256
        or measurements.plan_sha256 != plan.plan_sha256
        or measurements.cell_result_population_sha256 != objective_cell_population_sha256(results)
        or measurements.objective_outcome_contract_sha256 != contract_inspection.file_sha256
    ):
        raise ValueError("objective measurement-set binding differs")

    task_specs = {item.task_id: item for item in contract.task_scores}
    claim_cells = [item for item in plan.cells if item.lane_id == claim.lane_id]
    claim_tasks = {item.task_id for item in claim_cells}
    if claim_tasks != set(task_specs):
        raise ValueError("objective score contract must cover exactly the claim-lane tasks")
    if len(claim_tasks) < claim.minimum_distinct_tasks:
        raise ValueError("objective analysis has too few independent held-out tasks")
    for spec in task_specs.values():
        if not _artifact_matches(protocol_root, spec.scorer_artifact):
            raise ValueError(f"objective scorer artifact is missing or changed: {spec.task_id}")

    record_by_cell = {item.cell_id: item for item in results.cell_results}
    if any(cell.cell_id not in record_by_cell for cell in claim_cells):
        raise ValueError("objective analysis is missing a claim-lane result record")
    claim_cell_ids = {item.cell_id for item in claim_cells}
    successful_ids = {
        cell.cell_id for cell in claim_cells if record_by_cell[cell.cell_id].status == "succeeded"
    }
    measurement_by_cell = {item.cell_id: item for item in measurements.measurements}
    if set(measurement_by_cell) != successful_ids:
        raise ValueError(
            "objective measurements must cover every successful claim cell and no failed cell"
        )
    if set(measurement_by_cell) - claim_cell_ids:
        raise ValueError("objective measurement set contains a non-claim cell")
    if manifest.study_scope == "formal" and any(
        record_by_cell[cell.cell_id].evidence_class != "real" for cell in claim_cells
    ):
        raise ValueError("formal objective analysis requires real evidence for every claim cell")

    normalized_scores: dict[str, float] = {}
    for cell in claim_cells:
        record = record_by_cell[cell.cell_id]
        task_spec = task_specs[cell.task_id]
        if record.status == "failed":
            normalized_scores[cell.cell_id] = task_spec.failure_normalized_score
            continue
        measurement = measurement_by_cell[cell.cell_id]
        if measurement.result_record_sha256 != record.record_sha256:
            raise ValueError(f"objective measurement record binding differs: {cell.cell_id}")
        if (
            measurement.metric_id != task_spec.metric_id
            or measurement.metric_version != task_spec.metric_version
        ):
            raise ValueError(f"objective measurement metric differs: {cell.cell_id}")
        if not task_spec.raw_minimum <= measurement.raw_score <= task_spec.raw_maximum:
            raise ValueError(f"objective measurement lies outside frozen bounds: {cell.cell_id}")
        if not _artifact_matches(root, measurement.score_artifact):
            raise ValueError(f"objective score artifact is missing or changed: {cell.cell_id}")
        normalized_scores[cell.cell_id] = task_spec.normalize(measurement.raw_score)

    analysis_sha = content_sha256(analysis)
    provisional: list[dict[str, object]] = []
    for contrast_index, contrast in enumerate(claim.contrasts):
        task_effects = _task_effects(
            claim_cells,
            normalized_scores,
            task_specs,
            candidate_system_id=contrast.candidate_system_id,
            comparator_system_id=contrast.comparator_system_id,
        )
        signed_values = [item.signed_effect for item in task_effects]
        estimate = _mean(signed_values)
        lower, upper = _bootstrap_interval(
            signed_values,
            confidence_level=contract.confidence_level,
            resamples=contract.bootstrap_resamples,
            seed=contract.bootstrap_seed + contrast_index,
        )
        favorable_values = (
            signed_values
            if contrast.favorable_direction == "higher"
            else [-value for value in signed_values]
        )
        p_value = _sign_flip_p_value(
            [value - contrast.minimum_effect for value in favorable_values],
            exact_limit=contract.maximum_exact_sign_flip_tasks,
            monte_carlo_samples=contract.monte_carlo_sign_flips,
            seed=contract.bootstrap_seed + 10_000 + contrast_index,
        )
        provisional.append(
            {
                "contrast": contrast,
                "task_effects": task_effects,
                "effect_estimate": estimate,
                "interval_lower": lower,
                "interval_upper": upper,
                "raw_p_value": p_value,
                "analysis_input_sha256": claim_analysis_input_sha256(
                    claim, contrast, claim_cells, record_by_cell
                ),
            }
        )

    confirmatory = [
        item
        for item in provisional
        if (item["contrast"].inference_role or ContrastInferenceRole.CONFIRMATORY)
        is ContrastInferenceRole.CONFIRMATORY
    ]
    family_sha256 = content_sha256(
        {
            "method": contract.multiplicity_method,
            "alpha": contract.alpha,
            "contract_sha256": contract.contract_sha256,
            "members": sorted(
                [
                    {
                        "contrast_id": item["contrast"].contrast_id,
                        "analysis_input_sha256": item["analysis_input_sha256"],
                    }
                    for item in confirmatory
                ],
                key=lambda member: member["contrast_id"],
            ),
        }
    )
    adjusted = _holm_adjust(
        {item["contrast"].contrast_id: item["raw_p_value"] for item in confirmatory}
    )

    comparison_results: list[ObjectiveContrastAnalysis] = []
    for item in provisional:
        contrast = item["contrast"]
        role = contrast.inference_role or ContrastInferenceRole.CONFIRMATORY
        adjusted_p = adjusted.get(contrast.contrast_id)
        significance = adjusted_p if adjusted_p is not None else item["raw_p_value"]
        conclusion = _conclusion(
            favorable_direction=contrast.favorable_direction,
            minimum_effect=contrast.minimum_effect,
            interval_lower=item["interval_lower"],
            interval_upper=item["interval_upper"],
            p_value=significance,
            alpha=contract.alpha,
        )
        task_effects = item["task_effects"]
        comparison_results.append(
            ObjectiveContrastAnalysis(
                contrast_id=contrast.contrast_id,
                candidate_system_id=contrast.candidate_system_id,
                comparator_system_id=contrast.comparator_system_id,
                inference_role=role,
                favorable_direction=contrast.favorable_direction,
                minimum_effect=contrast.minimum_effect,
                independent_task_count=len(task_effects),
                observed_block_count=sum(value.paired_block_count for value in task_effects),
                task_effects=task_effects,
                effect_estimate=item["effect_estimate"],
                interval_lower=item["interval_lower"],
                interval_upper=item["interval_upper"],
                raw_p_value=item["raw_p_value"],
                adjusted_p_value=adjusted_p,
                conclusion=conclusion,
                analysis_input_sha256=item["analysis_input_sha256"],
            )
        )

    supported = sum(
        item.conclusion == "supports_claim"
        for item in comparison_results
        if item.inference_role is ContrastInferenceRole.CONFIRMATORY
    )
    return ObjectiveAnalysisReport.create(
        project_id=project_id,
        evaluation_id=evaluation_id,
        study_scope=manifest.study_scope,
        proposal_sha256=plan.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        cell_result_population_sha256=objective_cell_population_sha256(results),
        analysis_contract_sha256=analysis_sha,
        objective_outcome_contract_sha256=contract_inspection.file_sha256,
        objective_outcome_contract_semantic_sha256=contract.contract_sha256,
        measurement_set_sha256=measurements.measurement_set_sha256,
        multiplicity_family_sha256=family_sha256,
        comparisons=tuple(comparison_results),
        confirmatory_comparisons=len(confirmatory),
        supported_confirmatory_comparisons=supported,
        formal_effectiveness_established=(
            manifest.study_scope == "formal"
            and bool(confirmatory)
            and supported == len(confirmatory)
        ),
    )


def materialize_objective_analysis(
    manifest: ExperimentPrelaunchManifest,
    plan: EvaluationCellPlan,
    results: EvaluationResultSet,
    contract_inspection: ObjectiveOutcomeContractInspection,
    measurements: ObjectiveMeasurementSet,
    measurement_set_artifact: EvaluationResultArtifact,
    *,
    project_root: str | Path,
    evidence_root: str | Path | None = None,
    project_id: str,
    evaluation_id: str,
    output_path: str | Path,
) -> ObjectiveAnalysisMaterialization:
    """Analyze, atomically freeze the report, and derive admissible comparisons."""

    report = analyze_objective_outcomes(
        manifest,
        plan,
        results,
        contract_inspection,
        measurements,
        project_root=project_root,
        evidence_root=evidence_root,
        project_id=project_id,
        evaluation_id=evaluation_id,
    )
    root = Path(project_root).resolve(strict=True)
    if not _artifact_matches(root, measurement_set_artifact):
        raise ValueError("objective measurement-set artifact is missing or changed")
    loaded_measurements = load_objective_measurement_set(
        root / PurePosixPath(measurement_set_artifact.locator)
    )
    if loaded_measurements != measurements:
        raise ValueError("objective measurement-set artifact differs from analyzed measurements")
    output = _project_output_path(root, output_path)
    _atomic_json(output, report.model_dump(mode="json"), require_absent=True)
    artifact = EvaluationResultArtifact(
        locator=output.relative_to(root).as_posix(),
        sha256=_sha256_file(output),
        size_bytes=output.stat().st_size,
    )
    contract = contract_inspection.contract
    comparisons = primary_comparisons_from_objective_report(
        report,
        contract,
        analysis_artifact=artifact,
        measurement_set_artifact=measurement_set_artifact,
    )
    return ObjectiveAnalysisMaterialization(
        report=report,
        analysis_artifact=artifact,
        primary_comparisons=comparisons,
        output_path=output,
    )


def primary_comparisons_from_objective_report(
    report: ObjectiveAnalysisReport,
    contract: ObjectiveOutcomeContract,
    *,
    analysis_artifact: EvaluationResultArtifact,
    measurement_set_artifact: EvaluationResultArtifact,
) -> tuple[EvaluationPrimaryComparison, ...]:
    """Derive the exact v1.2 comparison records represented by one report."""

    if report.objective_outcome_contract_semantic_sha256 != contract.contract_sha256:
        raise ValueError("objective report and contract differ")
    return tuple(
        EvaluationPrimaryComparison.create(
            schema_version="1.2",
            comparison_id=item.contrast_id,
            analysis_contract_sha256=report.analysis_contract_sha256,
            analysis_input_sha256=item.analysis_input_sha256,
            failure_handling="include-as-outcome",
            objective_outcome_contract_sha256=report.objective_outcome_contract_sha256,
            objective_measurement_set_artifact=measurement_set_artifact,
            independent_unit_kind="held-out-task",
            observed_block_count=item.observed_block_count,
            inference_role=item.inference_role,
            raw_p_value=item.raw_p_value,
            adjusted_p_value=item.adjusted_p_value,
            alpha=contract.alpha,
            multiplicity_family_sha256=(
                report.multiplicity_family_sha256
                if item.inference_role is ContrastInferenceRole.CONFIRMATORY
                else None
            ),
            candidate_system_id=item.candidate_system_id,
            comparator_system_id=item.comparator_system_id,
            analysis_unit_count=item.independent_task_count,
            favorable_direction=item.favorable_direction,
            minimum_effect=item.minimum_effect,
            effect_estimate=item.effect_estimate,
            interval_lower=item.interval_lower,
            interval_upper=item.interval_upper,
            conclusion=item.conclusion,
            analysis_artifact=analysis_artifact,
        )
        for item in report.comparisons
    )


def _task_effects(
    cells: list[PlannedEvaluationCell],
    scores: dict[str, float],
    task_specs: dict[str, ObjectiveTaskScoreContract],
    *,
    candidate_system_id: str,
    comparator_system_id: str,
) -> tuple[ObjectiveTaskContrast, ...]:
    selected = [
        item for item in cells if item.system_id in {candidate_system_id, comparator_system_id}
    ]
    by_identity = {
        (item.system_id, item.task_id, item.seed, item.repetition): item for item in selected
    }
    tasks = sorted({item.task_id for item in selected})
    output: list[ObjectiveTaskContrast] = []
    for task_id in tasks:
        candidate_blocks = {
            (item.seed, item.repetition)
            for item in selected
            if item.system_id == candidate_system_id and item.task_id == task_id
        }
        comparator_blocks = {
            (item.seed, item.repetition)
            for item in selected
            if item.system_id == comparator_system_id and item.task_id == task_id
        }
        if not candidate_blocks or candidate_blocks != comparator_blocks:
            raise ValueError(f"objective contrast is not paired within task: {task_id}")
        candidate_values = [
            scores[by_identity[(candidate_system_id, task_id, seed, repetition)].cell_id]
            for seed, repetition in sorted(candidate_blocks)
        ]
        comparator_values = [
            scores[by_identity[(comparator_system_id, task_id, seed, repetition)].cell_id]
            for seed, repetition in sorted(comparator_blocks)
        ]
        candidate_mean = _mean(candidate_values)
        comparator_mean = _mean(comparator_values)
        output.append(
            ObjectiveTaskContrast(
                task_id=task_id,
                source_group_id=task_specs[task_id].source_group_id,
                paired_block_count=len(candidate_blocks),
                candidate_normalized_mean=candidate_mean,
                comparator_normalized_mean=comparator_mean,
                signed_effect=candidate_mean - comparator_mean,
            )
        )
    return tuple(output)


def objective_cell_population_sha256(results: EvaluationResultSet) -> str:
    """Hash execution records without creating a cycle through derived comparisons."""

    return content_sha256(
        {
            "project_id": results.project_id,
            "evaluation_id": results.evaluation_id,
            "proposal_sha256": results.proposal_sha256,
            "plan_sha256": results.plan_sha256,
            "cell_results": [
                {
                    "cell_id": item.cell_id,
                    "record_sha256": item.record_sha256,
                    "status": item.status,
                    "evidence_class": item.evidence_class,
                }
                for item in sorted(results.cell_results, key=lambda value: value.cell_id)
            ],
        }
    )


def _bootstrap_interval(
    values: list[float], *, confidence_level: float, resamples: int, seed: int
) -> tuple[float, float]:
    if len(values) < 2:
        raise ValueError("task-clustered bootstrap requires at least two tasks")
    generator = random.Random(seed)
    draws = sorted(
        _mean([values[generator.randrange(len(values))] for _ in values]) for _ in range(resamples)
    )
    tail = (1 - confidence_level) / 2
    return _quantile(draws, tail), _quantile(draws, 1 - tail)


def _sign_flip_p_value(
    centered_favorable_values: list[float],
    *,
    exact_limit: int,
    monte_carlo_samples: int,
    seed: int,
) -> float:
    if len(centered_favorable_values) < 2:
        raise ValueError("paired sign-flip inference requires at least two tasks")
    observed = _mean(centered_favorable_values)
    tolerance = 1e-15
    if len(centered_favorable_values) <= exact_limit:
        exceed = 0
        total = 0
        for signs in product((-1.0, 1.0), repeat=len(centered_favorable_values)):
            statistic = _mean(
                [sign * value for sign, value in zip(signs, centered_favorable_values, strict=True)]
            )
            exceed += statistic >= observed - tolerance
            total += 1
        return exceed / total
    generator = random.Random(seed)
    exceed = 0
    for _ in range(monte_carlo_samples):
        statistic = _mean(
            [value if generator.getrandbits(1) else -value for value in centered_favorable_values]
        )
        exceed += statistic >= observed - tolerance
    return (exceed + 1) / (monte_carlo_samples + 1)


def _holm_adjust(raw: dict[str, float]) -> dict[str, float]:
    ordered = sorted(raw.items(), key=lambda item: (item[1], item[0]))
    total = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (identity, p_value) in enumerate(ordered):
        running = max(running, min(1.0, (total - index) * p_value))
        adjusted[identity] = running
    return adjusted


def _conclusion(
    *,
    favorable_direction: Literal["higher", "lower"],
    minimum_effect: float,
    interval_lower: float,
    interval_upper: float,
    p_value: float,
    alpha: float,
) -> Literal["supports_claim", "inconclusive", "contradicts_claim"]:
    if favorable_direction == "higher":
        supports = interval_lower > minimum_effect
        contradicts = interval_upper < -minimum_effect
    else:
        supports = interval_upper < -minimum_effect
        contradicts = interval_lower > minimum_effect
    if supports and p_value < alpha:
        return "supports_claim"
    if contradicts:
        return "contradicts_claim"
    return "inconclusive"


def _mean(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def _quantile(sorted_values: list[float], probability: float) -> float:
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def _load_json_mapping(path: str | Path, label: str) -> tuple[Path, bytes, dict[str, object]]:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError(f"{label} cannot be a symbolic link")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return resolved, raw, payload


def _project_regular_file(root: Path, locator: str) -> Path:
    candidate = root / PurePosixPath(locator)
    resolved = candidate.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("objective-analysis input escapes the project root") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("objective-analysis input cannot traverse a symbolic link")
    if not resolved.is_file():
        raise ValueError("objective-analysis input must be a regular file")
    return resolved


def _project_output_path(root: Path, value: str | Path) -> Path:
    requested = Path(value)
    candidate = requested if requested.is_absolute() else root / requested
    resolved_parent = candidate.parent.resolve(strict=True)
    try:
        resolved_parent.relative_to(root)
    except ValueError as exc:
        raise ValueError("objective-analysis output escapes the project root") from exc
    relative_parent = resolved_parent.relative_to(root)
    current = root
    for part in relative_parent.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("objective-analysis output cannot traverse a symbolic link")
    if candidate.exists() and candidate.is_symlink():
        raise ValueError("objective-analysis output cannot be a symbolic link")
    return resolved_parent / candidate.name


def _artifact_matches(root: Path, artifact: EvaluationResultArtifact) -> bool:
    try:
        path = _project_regular_file(root, artifact.locator)
        return path.stat().st_size == artifact.size_bytes and _sha256_file(path) == artifact.sha256
    except (OSError, ValueError):
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: str | Path, payload: object, *, require_absent: bool) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if require_absent and target.exists():
        raise FileExistsError(f"refusing to replace immutable objective artifact: {target}")
    data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target.resolve(strict=True)


__all__ = [
    "ObjectiveAnalysisMaterialization",
    "ObjectiveAnalysisReport",
    "ObjectiveCellMeasurement",
    "ObjectiveContrastAnalysis",
    "ObjectiveDirection",
    "ObjectiveMeasurementSet",
    "ObjectiveOutcomeContract",
    "ObjectiveOutcomeContractInspection",
    "ObjectiveTaskContrast",
    "ObjectiveTaskScoreContract",
    "analyze_objective_outcomes",
    "bind_objective_measurement_set",
    "complete_objective_result_set",
    "load_objective_measurement_set",
    "load_objective_outcome_contract",
    "materialize_objective_analysis",
    "objective_cell_population_sha256",
    "primary_comparisons_from_objective_report",
    "save_completed_objective_result_set",
    "save_objective_measurement_set",
    "save_objective_outcome_contract",
]

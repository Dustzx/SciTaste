"""Pilot-bound power planning for clustered H1/H2 and H3 evidence.

Power is assigned to held-out source groups or tasks.  Seeds, repetitions,
reviewers, and candidate-order repeats affect cost and measurement reliability;
they never manufacture additional independent units.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from enum import StrEnum
from pathlib import Path, PurePosixPath
from statistics import NormalDist
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.human_preference_analysis import HumanPreferenceAnalysisReport
from scitaste.evaluation.objective_analysis import ObjectiveAnalysisReport
from scitaste.evaluation.prelaunch import ContrastInferenceRole
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_CONTRAST_ID = r"^[A-Za-z0-9]+(?:[A-Za-z0-9._-]*[A-Za-z0-9])?$"
_MAX_INPUT_BYTES = 64 * 1024 * 1024
_IMPLEMENTATION_ID = "scitaste.clustered-power.conservative-normal-v1"


class PowerAnalysisFamily(StrEnum):
    HUMAN_H1_H2 = "human-h1-h2"
    OBJECTIVE_H3 = "objective-h3"


class PowerIndependentUnit(StrEnum):
    HELD_OUT_SOURCE_GROUP = "held-out-source-group"
    HELD_OUT_TASK = "held-out-task"


class PilotAnalysisBinding(BaseModel):
    """Exact pilot report used only to estimate independent-unit dispersion."""

    model_config = _CONFIG

    report_kind: PowerAnalysisFamily
    path: str = Field(min_length=1, max_length=1_000)
    file_sha256: str = Field(pattern=_SHA256)
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_relative(self) -> PilotAnalysisBinding:
        _validate_relative_path(self.path)
        return self


class PowerContrastSpecification(BaseModel):
    """Outcome-independent effect target plus a conservative dispersion floor."""

    model_config = _CONFIG

    contrast_id: str = Field(pattern=_CONTRAST_ID)
    minimum_effect: float = Field(ge=0)
    smallest_effect_of_interest: float = Field(gt=0)
    dispersion_floor: float = Field(gt=0)
    effect_justification: str = Field(min_length=20, max_length=2_000)
    dispersion_floor_justification: str = Field(min_length=20, max_length=2_000)

    @model_validator(mode="after")
    def planning_effect_exceeds_the_claim_boundary(self) -> PowerContrastSpecification:
        values = (
            self.minimum_effect,
            self.smallest_effect_of_interest,
            self.dispersion_floor,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("power-planning constants must be finite")
        if self.smallest_effect_of_interest <= self.minimum_effect:
            raise ValueError("smallest effect of interest must exceed the claim minimum")
        return self


class PowerResourceGeometry(BaseModel):
    """Cost geometry kept deliberately separate from statistical sample size."""

    model_config = _CONFIG

    generation_conditions_per_independent_unit: int = Field(ge=2, le=30)
    generation_blocks_per_condition_unit: int = Field(ge=1, le=100)
    human_comparisons_per_independent_unit: int = Field(default=0, ge=0, le=1_000)
    reviewers_per_human_comparison: int = Field(default=0, ge=0, le=20)

    @model_validator(mode="after")
    def human_geometry_is_complete_or_absent(self) -> PowerResourceGeometry:
        fields = (
            self.human_comparisons_per_independent_unit,
            self.reviewers_per_human_comparison,
        )
        if any(fields) and not all(fields):
            raise ValueError("human comparison and reviewer geometry must be supplied together")
        return self


class ClusteredPowerRequest(BaseModel):
    """Post-pilot, pre-formal design contract with no execution authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    formal_study_id: str = Field(pattern=_ID)
    family: PowerAnalysisFamily
    independent_unit: PowerIndependentUnit
    pilot_report: PilotAnalysisBinding
    contrasts: tuple[PowerContrastSpecification, ...] = Field(min_length=1, max_length=20)
    alpha: float = Field(default=0.05, gt=0, lt=0.5)
    target_joint_power: float = Field(default=0.8, gt=0.5, lt=1)
    dispersion_confidence: float = Field(default=0.9, gt=0.5, lt=1)
    dispersion_bootstrap_resamples: int = Field(default=10_000, ge=1_000, le=1_000_000)
    bootstrap_seed: int = Field(default=202711, ge=0, le=2**63 - 1)
    minimum_pilot_independent_units: int = Field(default=6, ge=6, le=500)
    minimum_formal_independent_units: int = Field(default=8, ge=6, le=10_000)
    maximum_formal_independent_units: int = Field(default=500, ge=6, le=10_000)
    resource_geometry: PowerResourceGeometry
    multiplicity_planning: Literal["bonferroni-bound-for-holm-family"] = (
        "bonferroni-bound-for-holm-family"
    )
    sample_size_method: Literal["normal-approximation-with-bootstrap-dispersion-upper-bound"] = (
        "normal-approximation-with-bootstrap-dispersion-upper-bound"
    )
    formal_sample_size_rule: Literal["fixed-before-formal-outcomes"] = (
        "fixed-before-formal-outcomes"
    )
    effect_target_derived_from_pilot: Literal[False] = False
    pilot_data_excluded_from_formal_test: Literal[True] = True
    repetitions_are_not_independent_units: Literal[True] = True
    authorizes_experiment_execution: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    request_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def family_and_bounds_are_closed(self) -> ClusteredPowerRequest:
        expected_unit = {
            PowerAnalysisFamily.HUMAN_H1_H2: PowerIndependentUnit.HELD_OUT_SOURCE_GROUP,
            PowerAnalysisFamily.OBJECTIVE_H3: PowerIndependentUnit.HELD_OUT_TASK,
        }[self.family]
        if self.independent_unit is not expected_unit:
            raise ValueError("power family uses the wrong independent unit")
        if self.pilot_report.report_kind is not self.family:
            raise ValueError("pilot-report kind differs from the power family")
        contrast_ids = [item.contrast_id for item in self.contrasts]
        if len(contrast_ids) != len(set(contrast_ids)):
            raise ValueError("power contrast IDs must be unique")
        if self.family is PowerAnalysisFamily.HUMAN_H1_H2 and len(self.contrasts) != 2:
            raise ValueError("H1/H2 power planning requires exactly two contrasts")
        if self.minimum_formal_independent_units > self.maximum_formal_independent_units:
            raise ValueError("minimum formal units exceed the declared ceiling")
        human_geometry = self.resource_geometry.human_comparisons_per_independent_unit > 0
        if human_geometry != (self.family is PowerAnalysisFamily.HUMAN_H1_H2):
            raise ValueError("human-review geometry must occur only for H1/H2")
        expected = content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("clustered power request hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ClusteredPowerRequest:
        payload = {"schema_version": "1.0", **values}
        payload.pop("request_sha256", None)
        unsigned = cls.model_construct(request_sha256="0" * 64, **payload)
        return cls(
            **payload,
            request_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"request_sha256"})
            ),
        )


class ClusteredPowerRequestInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    request: ClusteredPowerRequest


class ContrastPowerResult(BaseModel):
    model_config = _CONFIG

    contrast_id: str = Field(pattern=_CONTRAST_ID)
    minimum_effect: float = Field(ge=0)
    smallest_effect_of_interest: float = Field(gt=0)
    planning_margin: float = Field(gt=0)
    pilot_independent_unit_count: int = Field(ge=6)
    pilot_effect_estimate: float
    pilot_sample_dispersion: float = Field(ge=0)
    bootstrap_dispersion_upper_bound: float = Field(ge=0)
    dispersion_floor: float = Field(gt=0)
    planning_dispersion: float = Field(gt=0)
    per_contrast_alpha: float = Field(gt=0, lt=0.5)
    marginal_power_required_for_joint_target: float = Field(gt=0.5, lt=1)
    normal_approximation_units: int = Field(gt=0)
    sign_flip_resolution_units: int = Field(gt=0)
    required_independent_units: int = Field(gt=0)
    within_declared_ceiling: bool

    @model_validator(mode="after")
    def derived_values_are_consistent(self) -> ContrastPowerResult:
        if not math.isclose(
            self.planning_margin,
            self.smallest_effect_of_interest - self.minimum_effect,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("power planning margin differs from the registered effects")
        expected_dispersion = max(
            self.pilot_sample_dispersion,
            self.bootstrap_dispersion_upper_bound,
            self.dispersion_floor,
        )
        if not math.isclose(
            self.planning_dispersion, expected_dispersion, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError("power planning dispersion is not conservative")
        expected_units = max(
            self.normal_approximation_units,
            self.sign_flip_resolution_units,
        )
        if self.required_independent_units < expected_units:
            raise ValueError("required units omit an inferential lower bound")
        return self


class ClusteredPowerReport(BaseModel):
    """Self-hashed formal sample-size recommendation derived from a frozen pilot."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    implementation_id: Literal[_IMPLEMENTATION_ID] = _IMPLEMENTATION_ID
    request_id: str = Field(pattern=_ID)
    formal_study_id: str = Field(pattern=_ID)
    family: PowerAnalysisFamily
    independent_unit: PowerIndependentUnit
    request_sha256: str = Field(pattern=_SHA256)
    request_file_sha256: str = Field(pattern=_SHA256)
    alpha: float = Field(gt=0, lt=0.5)
    target_joint_power: float = Field(gt=0.5, lt=1)
    dispersion_confidence: float = Field(gt=0.5, lt=1)
    dispersion_bootstrap_resamples: int = Field(ge=1_000)
    bootstrap_seed: int = Field(ge=0)
    minimum_formal_independent_units: int = Field(ge=6)
    pilot_report_file_sha256: str = Field(pattern=_SHA256)
    pilot_report_semantic_sha256: str = Field(pattern=_SHA256)
    resource_geometry: PowerResourceGeometry
    contrast_results: tuple[ContrastPowerResult, ...] = Field(min_length=1, max_length=20)
    recommended_independent_units: int = Field(gt=0)
    maximum_formal_independent_units: int = Field(gt=0)
    generation_trajectory_count: int = Field(gt=0)
    human_judgment_count: int = Field(ge=0)
    ready_for_formal_sample_size_freeze: bool
    fixed_sample_size_before_formal_outcomes: Literal[True] = True
    pilot_data_excluded_from_formal_test: Literal[True] = True
    pilot_estimate_used_as_effect_target: Literal[False] = False
    repetitions_change_cost_not_power: Literal[True] = True
    no_sequential_outcome_peeking: Literal[True] = True
    no_model_calls_performed: Literal[True] = True
    no_api_spend_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    no_human_recruitment_performed: Literal[True] = True
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def summary_and_hash_are_consistent(self) -> ClusteredPowerReport:
        contrast_ids = [item.contrast_id for item in self.contrast_results]
        if len(contrast_ids) != len(set(contrast_ids)):
            raise ValueError("power report contrast IDs must be unique")
        family_size = len(self.contrast_results)
        expected_alpha = self.alpha / family_size
        expected_marginal_power = 1 - (1 - self.target_joint_power) / family_size
        if any(
            not math.isclose(item.per_contrast_alpha, expected_alpha, rel_tol=1e-12, abs_tol=1e-12)
            or not math.isclose(
                item.marginal_power_required_for_joint_target,
                expected_marginal_power,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            for item in self.contrast_results
        ):
            raise ValueError("power report multiplicity allocation is inconsistent")
        recommended = max(item.required_independent_units for item in self.contrast_results)
        if self.recommended_independent_units != recommended:
            raise ValueError("recommended power units differ from the contrast family")
        expected_ready = all(item.within_declared_ceiling for item in self.contrast_results)
        if self.ready_for_formal_sample_size_freeze != expected_ready:
            raise ValueError("power readiness differs from contrast ceilings")
        if self.maximum_formal_independent_units < 1:
            raise ValueError("power report has no formal-unit ceiling")
        if any(
            item.within_declared_ceiling
            != (item.required_independent_units <= self.maximum_formal_independent_units)
            for item in self.contrast_results
        ):
            raise ValueError("power contrast ceiling decision is inconsistent")
        if any(
            item.required_independent_units < self.minimum_formal_independent_units
            for item in self.contrast_results
        ):
            raise ValueError("power contrast falls below the formal independent-unit floor")
        expected_trajectories = (
            recommended
            * self.resource_geometry.generation_conditions_per_independent_unit
            * self.resource_geometry.generation_blocks_per_condition_unit
        )
        expected_judgments = (
            recommended
            * self.resource_geometry.human_comparisons_per_independent_unit
            * self.resource_geometry.reviewers_per_human_comparison
        )
        if self.generation_trajectory_count != expected_trajectories:
            raise ValueError("power report generation cost is inconsistent")
        if self.human_judgment_count != expected_judgments:
            raise ValueError("power report review cost is inconsistent")
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("clustered power report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ClusteredPowerReport:
        payload = {
            "schema_version": "1.0",
            "implementation_id": _IMPLEMENTATION_ID,
            **values,
        }
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


class ClusteredPowerReportInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    report: ClusteredPowerReport


def load_clustered_power_request(path: str | Path) -> ClusteredPowerRequestInspection:
    resolved, raw, payload = _load_mapping(path, "clustered power request")
    return ClusteredPowerRequestInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        request=ClusteredPowerRequest.model_validate(payload),
    )


def load_clustered_power_report(path: str | Path) -> ClusteredPowerReportInspection:
    resolved, raw, payload = _load_mapping(path, "clustered power report")
    return ClusteredPowerReportInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        report=ClusteredPowerReport.model_validate(payload),
    )


def plan_clustered_power(
    inspection: ClusteredPowerRequestInspection,
    *,
    evidence_root: str | Path,
) -> ClusteredPowerReport:
    """Derive one fixed formal-unit recommendation from exact pilot report bytes."""

    request = inspection.request
    root = Path(evidence_root).resolve(strict=True)
    pilot_path = _bound_file(root, request.pilot_report.path)
    raw = pilot_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != request.pilot_report.file_sha256:
        raise ValueError("pilot analysis file SHA-256 differs from the power request")
    payload = _decode_json_mapping(raw, "pilot analysis report")
    effects, semantic_sha = _pilot_effects(request, payload)
    if semantic_sha != request.pilot_report.report_sha256:
        raise ValueError("pilot analysis semantic SHA-256 differs from the power request")

    family_size = len(request.contrasts)
    per_alpha = request.alpha / family_size
    marginal_power = 1 - (1 - request.target_joint_power) / family_size
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1 - per_alpha)
    z_power = normal.inv_cdf(marginal_power)
    results: list[ContrastPowerResult] = []
    for index, specification in enumerate(request.contrasts):
        values = effects[specification.contrast_id]
        if len(values) < request.minimum_pilot_independent_units:
            raise ValueError(
                f"pilot contrast has too few independent units: {specification.contrast_id}"
            )
        estimate = _mean(values)
        observed_dispersion = _sample_standard_deviation(values)
        bootstrap_upper = _bootstrap_dispersion_upper(
            values,
            confidence=request.dispersion_confidence,
            resamples=request.dispersion_bootstrap_resamples,
            seed=request.bootstrap_seed + index,
        )
        planning_dispersion = max(
            observed_dispersion,
            bootstrap_upper,
            specification.dispersion_floor,
        )
        margin = specification.smallest_effect_of_interest - specification.minimum_effect
        normal_units = max(
            2,
            math.ceil(((z_alpha + z_power) * planning_dispersion / margin) ** 2),
        )
        sign_flip_units = _sign_flip_resolution_floor(
            alpha=request.alpha,
            family_size=family_size,
        )
        required = max(
            request.minimum_formal_independent_units,
            normal_units,
            sign_flip_units,
        )
        results.append(
            ContrastPowerResult(
                contrast_id=specification.contrast_id,
                minimum_effect=specification.minimum_effect,
                smallest_effect_of_interest=specification.smallest_effect_of_interest,
                planning_margin=margin,
                pilot_independent_unit_count=len(values),
                pilot_effect_estimate=estimate,
                pilot_sample_dispersion=observed_dispersion,
                bootstrap_dispersion_upper_bound=bootstrap_upper,
                dispersion_floor=specification.dispersion_floor,
                planning_dispersion=planning_dispersion,
                per_contrast_alpha=per_alpha,
                marginal_power_required_for_joint_target=marginal_power,
                normal_approximation_units=normal_units,
                sign_flip_resolution_units=sign_flip_units,
                required_independent_units=required,
                within_declared_ceiling=required <= request.maximum_formal_independent_units,
            )
        )

    recommended = max(item.required_independent_units for item in results)
    geometry = request.resource_geometry
    trajectories = (
        recommended
        * geometry.generation_conditions_per_independent_unit
        * geometry.generation_blocks_per_condition_unit
    )
    judgments = (
        recommended
        * geometry.human_comparisons_per_independent_unit
        * geometry.reviewers_per_human_comparison
    )
    return ClusteredPowerReport.create(
        request_id=request.request_id,
        formal_study_id=request.formal_study_id,
        family=request.family,
        independent_unit=request.independent_unit,
        request_sha256=request.request_sha256,
        request_file_sha256=inspection.file_sha256,
        alpha=request.alpha,
        target_joint_power=request.target_joint_power,
        dispersion_confidence=request.dispersion_confidence,
        dispersion_bootstrap_resamples=request.dispersion_bootstrap_resamples,
        bootstrap_seed=request.bootstrap_seed,
        minimum_formal_independent_units=request.minimum_formal_independent_units,
        pilot_report_file_sha256=request.pilot_report.file_sha256,
        pilot_report_semantic_sha256=semantic_sha,
        resource_geometry=geometry,
        contrast_results=tuple(results),
        recommended_independent_units=recommended,
        maximum_formal_independent_units=request.maximum_formal_independent_units,
        generation_trajectory_count=trajectories,
        human_judgment_count=judgments,
        ready_for_formal_sample_size_freeze=all(item.within_declared_ceiling for item in results),
    )


def save_clustered_power_report(report: ClusteredPowerReport, path: str | Path) -> Path:
    return _atomic_json(path, report.model_dump(mode="json"), require_absent=True)


def _pilot_effects(
    request: ClusteredPowerRequest,
    payload: dict[str, object],
) -> tuple[dict[str, list[float]], str]:
    specifications = {item.contrast_id: item for item in request.contrasts}
    if request.family is PowerAnalysisFamily.HUMAN_H1_H2:
        report = HumanPreferenceAnalysisReport.model_validate(payload)
        if report.study_scope != "pilot" or report.formal_joint_title_gate_passed:
            raise ValueError("power planning requires an excluded H1/H2 pilot report")
        observed = {item.hypothesis.value: item for item in report.hypotheses}
        if set(observed) != set(specifications):
            raise ValueError("power request differs from the H1/H2 pilot family")
        effects: dict[str, list[float]] = {}
        for identity, result in observed.items():
            specification = specifications[identity]
            if not math.isclose(
                result.minimum_effect,
                specification.minimum_effect,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("power minimum effect differs from the H1/H2 pilot")
            groups = [item.source_group for item in result.source_groups]
            if len(groups) != len(set(groups)):
                raise ValueError("H1/H2 pilot reuses an independent source group")
            values = [item.effect_over_tie for item in result.source_groups]
            if not math.isclose(
                _mean(values), result.effect_estimate, rel_tol=1e-12, abs_tol=1e-12
            ):
                raise ValueError("H1/H2 pilot effect does not match its source groups")
            effects[identity] = values
        return effects, report.report_sha256

    report = ObjectiveAnalysisReport.model_validate(payload)
    if report.study_scope != "pilot" or report.formal_effectiveness_established:
        raise ValueError("power planning requires an excluded objective pilot report")
    confirmatory = {
        item.contrast_id: item
        for item in report.comparisons
        if item.inference_role is ContrastInferenceRole.CONFIRMATORY
    }
    if set(confirmatory) != set(specifications):
        raise ValueError("power request differs from the objective pilot family")
    effects = {}
    for identity, result in confirmatory.items():
        specification = specifications[identity]
        if not math.isclose(
            result.minimum_effect,
            specification.minimum_effect,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("power minimum effect differs from the objective pilot")
        task_ids = [item.task_id for item in result.task_effects]
        source_groups = [item.source_group_id for item in result.task_effects]
        if len(task_ids) != len(set(task_ids)) or len(source_groups) != len(set(source_groups)):
            raise ValueError("objective pilot reuses a held-out task or source group")
        signed = [item.signed_effect for item in result.task_effects]
        if not math.isclose(_mean(signed), result.effect_estimate, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("objective pilot effect does not match its task effects")
        effects[identity] = (
            signed if result.favorable_direction == "higher" else [-x for x in signed]
        )
    return effects, report.report_sha256


def _bootstrap_dispersion_upper(
    values: list[float], *, confidence: float, resamples: int, seed: int
) -> float:
    generator = random.Random(seed)
    draws = sorted(
        _sample_standard_deviation(
            [values[generator.randrange(len(values))] for _ in range(len(values))]
        )
        for _ in range(resamples)
    )
    return _quantile(draws, confidence)


def _sample_standard_deviation(values: list[float]) -> float:
    if len(values) < 2:
        raise ValueError("dispersion requires at least two independent units")
    mean = _mean(values)
    return math.sqrt(math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _sign_flip_resolution_floor(*, alpha: float, family_size: int) -> int:
    units = 1
    while family_size * (2.0**-units) >= alpha:
        units += 1
    return units


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("power planning requires independent-unit effects")
    return math.fsum(values) / len(values)


def _quantile(values: list[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def _bound_file(root: Path, locator: str) -> Path:
    current = root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("power input cannot traverse a symbolic link")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("power input escapes the evidence root") from exc
    if not resolved.is_file() or resolved.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("power input must be a bounded regular file")
    return resolved


def _validate_relative_path(path: str) -> None:
    pure = PurePosixPath(path)
    if (
        "\\" in path
        or pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("power input paths must be normalized relative POSIX paths")


def _load_mapping(path: str | Path, label: str) -> tuple[Path, bytes, dict[str, object]]:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError(f"{label} cannot be a symbolic link")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} must be UTF-8 YAML or JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a mapping")
    return resolved, raw, payload


def _decode_json_mapping(raw: bytes, label: str) -> dict[str, object]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _atomic_json(path: str | Path, payload: object, *, require_absent: bool) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("clustered power output cannot be a symbolic link")
    if require_absent and target.exists():
        raise FileExistsError(f"refusing to replace immutable power report: {target}")
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
        temporary.unlink(missing_ok=True)
    return target


__all__ = [
    "ClusteredPowerReport",
    "ClusteredPowerReportInspection",
    "ClusteredPowerRequest",
    "ClusteredPowerRequestInspection",
    "ContrastPowerResult",
    "PilotAnalysisBinding",
    "PowerAnalysisFamily",
    "PowerContrastSpecification",
    "PowerIndependentUnit",
    "PowerResourceGeometry",
    "load_clustered_power_report",
    "load_clustered_power_request",
    "plan_clustered_power",
    "save_clustered_power_report",
]

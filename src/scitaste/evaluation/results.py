"""Integrity-aware result admission for generic API and GPU evaluation cells."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.benchmark.study_models import StudyOutcome
from scitaste.evaluation.cell_plan import EvaluationCellPlan, PlannedEvaluationCell
from scitaste.evaluation.prelaunch import (
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    ScientificLaneRole,
    SystemRole,
)
from scitaste.project.models import content_sha256, validate_relative_locator

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_CELL_ID = r"^cell-[0-9a-f]{24}$"
_BLIND_ID = r"^blind-[0-9a-f]{24}$"


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
    api_cost: float | None = Field(default=None, ge=0)
    gpu_hours: float | None = Field(default=None, ge=0)
    wall_time_hours: float = Field(ge=0)
    experiment_count: int = Field(ge=0)


class EvaluationCellResult(BaseModel):
    """One exact planned cell result; prose cannot change its identity or status."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
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
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
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
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
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

    schema_version: Literal["1.0"] = "1.0"
    comparison_id: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
    analysis_contract_sha256: str = Field(pattern=_SHA256)
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
        if self.candidate_system_id == self.comparator_system_id:
            raise ValueError("primary comparison requires distinct systems")
        if not self.interval_lower <= self.effect_estimate <= self.interval_upper:
            raise ValueError("primary comparison estimate must lie inside its interval")
        if self.favorable_direction == "higher":
            supports = self.interval_lower > self.minimum_effect
            contradicts = self.interval_upper < -self.minimum_effect
        else:
            supports = self.interval_upper < -self.minimum_effect
            contradicts = self.interval_lower > self.minimum_effect
        expected_conclusion = (
            "supports_claim" if supports else "contradicts_claim" if contradicts else "inconclusive"
        )
        if self.conclusion != expected_conclusion:
            raise ValueError("primary comparison conclusion differs from its interval rule")
        expected = content_sha256(self.model_dump(mode="json", exclude={"comparison_sha256"}))
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
            comparison_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"comparison_sha256"})
            ),
        )


class EvaluationResultSet(BaseModel):
    """Raw registered execution, panel, and primary-analysis records."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    evaluation_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
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
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_set_sha256"}))
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
            result_set_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"result_set_sha256"})
            ),
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

    schema_version: Literal["1.0"] = "1.0"
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
        if self.headline_eligible != self.scientific_evidence_complete:
            raise ValueError("headline eligibility must match complete scientific evidence")
        if self.scientific_effectiveness_established and not self.headline_eligible:
            raise ValueError("effectiveness requires headline-eligible evidence")
        expected = content_sha256(self.model_dump(mode="json", exclude={"assessment_sha256"}))
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
            assessment_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"assessment_sha256"})
            ),
        )


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
        elif (
            manifest.human_review.required
            and cell.scientific_role is ScientificLaneRole.MATCHED_BACKBONE
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
    for cell in matched:
        record = valid_records.get(cell.cell_id)
        if record is not None and record.status == "failed":
            blockers.add(f"headline:cell:{cell.cell_id}:execution-failed:{record.error_code}")
        if record is not None and record.evidence_class != "real":
            blockers.add(f"headline:cell:{cell.cell_id}:real-evidence-required")
    analysis_contract_sha256 = (
        content_sha256(manifest.analysis) if manifest.analysis is not None else None
    )
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
    missing = sum(item.status == "missing" for item in audits)
    invalid = sum(item.status == "invalid" for item in audits)
    verified = len(audits) - missing - invalid
    return EvaluationOutcomeAssessment.create(
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
        required_primary_comparisons=len(required_pairs),
        valid_primary_comparisons=len(valid_pairs),
        scientific_evidence_complete=scientific_complete,
        headline_eligible=scientific_complete,
        scientific_effectiveness_established=effectiveness,
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
    if cell.lane_kind is ExecutionLaneKind.API_ONLY:
        required = (
            usage.request_count,
            usage.input_tokens,
            usage.output_tokens,
            usage.api_cost,
        )
        if any(value is None for value in required) or usage.gpu_hours is not None:
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
            if usage.api_cost > (resource.max_cost or 0):
                issues.append(f"cell:{cell.cell_id}:cost-budget-exceeded")
    else:
        if usage.gpu_hours is None or usage.api_cost is not None:
            issues.append(f"cell:{cell.cell_id}:gpu-telemetry-incomplete")
        elif usage.gpu_hours > (resource.max_gpu_hours or 0):
            issues.append(f"cell:{cell.cell_id}:gpu-budget-exceeded")
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
    "inspect_evaluation_results",
]

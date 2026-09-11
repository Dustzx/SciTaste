"""Versioned schemas for project-owned runs, papers, and snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_PROJECT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ENTRY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_project_id(value: str) -> str:
    if not _PROJECT_ID.fullmatch(value):
        raise ValueError("project_id must be a lowercase kebab-case identifier")
    return value


def validate_entry_id(value: str, *, field_name: str) -> str:
    if not _ENTRY_ID.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"{field_name} must be one safe path segment")
    return value


def validate_relative_locator(value: str, *, field_name: str) -> str:
    if "\\" in value:
        raise ValueError(f"{field_name} must use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field_name} must be a normalized project-relative path")
    if "//" in value:
        raise ValueError(f"{field_name} must not contain repeated separators")
    return value


class ProjectRun(BaseModel):
    """One registered execution or auditable project iteration."""

    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    run_id: str
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    seed: int = Field(ge=0)
    status: str = Field(min_length=1)
    evidence_scope: str = Field(min_length=1)
    stage_path: str | None = None
    artifact: str | None = None
    superseded_by: str | None = None

    @field_validator("run_id")
    @classmethod
    def run_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="run_id")

    @field_validator("stage_path", "artifact")
    @classmethod
    def paths_are_project_relative(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_relative_locator(value, field_name="run locator")

    @field_validator("superseded_by")
    @classmethod
    def superseding_run_id_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_entry_id(value, field_name="superseded_by")

    @model_validator(mode="after")
    def run_does_not_supersede_itself(self) -> ProjectRun:
        if self.superseded_by == self.run_id:
            raise ValueError("a run cannot supersede itself")
        return self


class ProjectReview(BaseModel):
    """Content-bound pointer to one project-owned paper review round."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    review_id: str
    paper_directory: str
    venue_id: str = Field(min_length=1)
    round_number: int = Field(ge=1)
    status: str = Field(min_length=1)
    round_locator: str
    round_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("review_id", "paper_directory")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: Any) -> str:
        return validate_entry_id(value, field_name=str(info.field_name))

    @field_validator("round_locator")
    @classmethod
    def round_locator_is_owned(cls, value: str, info: Any) -> str:
        locator = validate_relative_locator(value, field_name=str(info.field_name))
        parts = PurePosixPath(locator).parts
        if len(parts) != 3 or parts[0] != "reviews" or parts[2] != "ROUND.json":
            raise ValueError("round_locator must be reviews/<review-id>/ROUND.json")
        validate_entry_id(parts[1], field_name="review directory")
        return locator

    @model_validator(mode="after")
    def locator_matches_review_id(self) -> ProjectReview:
        if PurePosixPath(self.round_locator).parts[1] != self.review_id:
            raise ValueError("round_locator review directory must match review_id")
        return self


class ProjectEvaluationArtifact(BaseModel):
    """One immutable file inside a project-owned evaluation proposal bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    locator: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=16 * 1024 * 1024)

    @field_validator("locator")
    @classmethod
    def locator_is_bundle_relative(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="evaluation artifact locator")


class ProjectEvaluationBundle(BaseModel):
    """Self-hashed no-run projection of one exact experiment proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    evaluation_id: str
    manifest_id: str
    protocol_id: str
    study_scope: Literal["pilot", "formal", "robustness"]
    status: Literal["blocked", "awaiting_author_approval", "execution_authorized"]
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    planned_cells: int = Field(gt=0)
    system_ids: tuple[str, ...] = Field(min_length=2, max_length=30)
    task_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    lane_ids: tuple[str, ...] = Field(min_length=1, max_length=10)
    api_resources: tuple[str, ...] = Field(default=(), max_length=10)
    gpu_resources: tuple[str, ...] = Field(default=(), max_length=10)
    ready_for_author_review: bool
    execution_authorized: bool
    observed_source_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    source_tree_clean: bool | None = None
    readiness_blocker_codes: tuple[str, ...] = Field(default=(), max_length=2_000)
    authorization_blocker_codes: tuple[str, ...] = Field(default=(), max_length=100)
    critic_blocking_codes: tuple[str, ...] = Field(default=(), max_length=100)
    cell_plan_blockers: tuple[str, ...] = Field(default=(), max_length=2_000)
    files: dict[str, ProjectEvaluationArtifact] = Field(min_length=5, max_length=20)
    no_execution_performed: Literal[True] = True
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("evaluation_id", "manifest_id", "protocol_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: Any) -> str:
        return validate_entry_id(value, field_name=str(info.field_name))

    @field_validator("system_ids", "task_ids", "lane_ids")
    @classmethod
    def referenced_ids_are_unique(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        for value in values:
            validate_entry_id(value, field_name=str(info.field_name))
        if len(values) != len(set(values)):
            raise ValueError(f"{info.field_name} must be unique")
        return values

    @field_validator(
        "readiness_blocker_codes",
        "authorization_blocker_codes",
        "critic_blocking_codes",
        "cell_plan_blockers",
    )
    @classmethod
    def blocker_codes_are_unique(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError(f"{info.field_name} must be unique")
        return values

    @model_validator(mode="after")
    def bundle_is_closed_and_self_hashed(self) -> ProjectEvaluationBundle:
        required_files = {
            "prelaunch_manifest",
            "resource_corpus",
            "gate_report",
            "critic_report",
            "cell_plan",
        }
        if set(self.files) != required_files:
            raise ValueError("evaluation bundle must bind the five canonical artifacts")
        locators = [item.locator for item in self.files.values()]
        if len(locators) != len(set(locators)) or "EVALUATION.json" in locators:
            raise ValueError("evaluation artifact locators must be unique and non-recursive")
        if not self.api_resources and not self.gpu_resources:
            raise ValueError("evaluation bundle must identify at least one API or GPU resource")
        if self.execution_authorized and not self.ready_for_author_review:
            raise ValueError("execution authorization requires completed author-review readiness")
        expected_status = (
            "execution_authorized"
            if self.execution_authorized
            else "awaiting_author_approval"
            if self.ready_for_author_review
            else "blocked"
        )
        if self.status != expected_status:
            raise ValueError("evaluation status does not match its readiness and authority")
        expected = content_sha256(self.model_dump(mode="json", exclude={"bundle_sha256"}))
        if self.bundle_sha256 != expected:
            raise ValueError("evaluation bundle hash mismatch")
        return self


class ProjectEvaluation(BaseModel):
    """Content-bound pointer to one registered project evaluation proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    evaluation_id: str
    manifest_id: str
    protocol_id: str
    study_scope: Literal["pilot", "formal", "robustness"]
    status: Literal["blocked", "awaiting_author_approval", "execution_authorized"]
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    planned_cells: int = Field(gt=0)
    api_resources: tuple[str, ...] = Field(default=(), max_length=10)
    gpu_resources: tuple[str, ...] = Field(default=(), max_length=10)
    ready_for_author_review: bool
    execution_authorized: bool
    blocker_count: int = Field(ge=0)
    record_locator: str
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    no_execution_performed: Literal[True] = True

    @field_validator("evaluation_id", "manifest_id", "protocol_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: Any) -> str:
        return validate_entry_id(value, field_name=str(info.field_name))

    @field_validator("record_locator")
    @classmethod
    def record_locator_is_owned(cls, value: str) -> str:
        locator = validate_relative_locator(value, field_name="evaluation record locator")
        parts = PurePosixPath(locator).parts
        if len(parts) != 3 or parts[0] != "evaluations" or parts[2] != "EVALUATION.json":
            raise ValueError(
                "evaluation record_locator must be evaluations/<evaluation-id>/EVALUATION.json"
            )
        validate_entry_id(parts[1], field_name="evaluation directory")
        return locator

    @model_validator(mode="after")
    def entry_is_consistent(self) -> ProjectEvaluation:
        if PurePosixPath(self.record_locator).parts[1] != self.evaluation_id:
            raise ValueError("evaluation record directory must match evaluation_id")
        if self.execution_authorized and not self.ready_for_author_review:
            raise ValueError("execution authorization requires author-review readiness")
        expected_status = (
            "execution_authorized"
            if self.execution_authorized
            else "awaiting_author_approval"
            if self.ready_for_author_review
            else "blocked"
        )
        if self.status != expected_status:
            raise ValueError("evaluation entry status is inconsistent")
        return self


class ProjectEvaluationResultEvidence(BaseModel):
    """One immutable project-owned byte sequence used by an evaluation result."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    locator: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0, le=4 * 1024 * 1024 * 1024)

    @field_validator("locator")
    @classmethod
    def locator_is_project_relative(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="evaluation-result evidence")


class ProjectEvaluationResultBundle(BaseModel):
    """Self-hashed result admission bound to one immutable evaluation proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    result_id: str
    evaluation_id: str
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["incomplete", "complete"]
    planned_cells: int = Field(ge=0)
    verified_records: int = Field(ge=0)
    succeeded_cells: int = Field(ge=0)
    failed_cells: int = Field(ge=0)
    missing_cells: int = Field(ge=0)
    invalid_cells: int = Field(ge=0)
    valid_external_reviews: int = Field(ge=0)
    scientific_evidence_complete: bool
    headline_eligible: bool
    scientific_effectiveness_established: bool
    blocker_codes: tuple[str, ...] = Field(max_length=20_000)
    files: dict[str, ProjectEvaluationArtifact] = Field(min_length=2, max_length=2)
    evidence: tuple[ProjectEvaluationResultEvidence, ...] = Field(max_length=20_000)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("result_id", "evaluation_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: Any) -> str:
        return validate_entry_id(value, field_name=str(info.field_name))

    @model_validator(mode="after")
    def result_bundle_is_closed_and_self_hashed(self) -> ProjectEvaluationResultBundle:
        if set(self.files) != {"result_set", "assessment"}:
            raise ValueError("evaluation result bundle must bind result_set and assessment")
        locators = [item.locator for item in self.files.values()]
        if len(locators) != len(set(locators)) or "RESULT.json" in locators:
            raise ValueError("evaluation result bundle file locators must be unique")
        evidence_locators = [item.locator for item in self.evidence]
        if len(evidence_locators) != len(set(evidence_locators)):
            raise ValueError("evaluation result evidence locators must be unique")
        if self.verified_records + self.missing_cells + self.invalid_cells != self.planned_cells:
            raise ValueError("evaluation result counts must cover every planned cell")
        if self.succeeded_cells + self.failed_cells != self.verified_records:
            raise ValueError("evaluation verified-result counts must close")
        if self.headline_eligible != self.scientific_evidence_complete:
            raise ValueError("result headline eligibility must match scientific completeness")
        if self.scientific_effectiveness_established and not self.headline_eligible:
            raise ValueError("scientific effectiveness requires headline-eligible evidence")
        expected = content_sha256(self.model_dump(mode="json", exclude={"bundle_sha256"}))
        if self.bundle_sha256 != expected:
            raise ValueError("evaluation result bundle hash mismatch")
        return self


class ProjectEvaluationResult(BaseModel):
    """Content-bound project-manifest pointer to one admitted result bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    result_id: str
    evaluation_id: str
    status: Literal["incomplete", "complete"]
    planned_cells: int = Field(ge=0)
    verified_records: int = Field(ge=0)
    succeeded_cells: int = Field(ge=0)
    failed_cells: int = Field(ge=0)
    missing_cells: int = Field(ge=0)
    invalid_cells: int = Field(ge=0)
    scientific_evidence_complete: bool
    headline_eligible: bool
    scientific_effectiveness_established: bool
    record_locator: str
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("result_id", "evaluation_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: Any) -> str:
        return validate_entry_id(value, field_name=str(info.field_name))

    @field_validator("record_locator")
    @classmethod
    def record_locator_is_owned(cls, value: str) -> str:
        locator = validate_relative_locator(value, field_name="evaluation-result record")
        parts = PurePosixPath(locator).parts
        if len(parts) != 3 or parts[0] != "evaluation-results" or parts[2] != "RESULT.json":
            raise ValueError(
                "evaluation-result record_locator must be "
                "evaluation-results/<result-id>/RESULT.json"
            )
        validate_entry_id(parts[1], field_name="evaluation-result directory")
        return locator

    @model_validator(mode="after")
    def result_entry_is_consistent(self) -> ProjectEvaluationResult:
        if PurePosixPath(self.record_locator).parts[1] != self.result_id:
            raise ValueError("evaluation-result directory must match result_id")
        if self.verified_records + self.missing_cells + self.invalid_cells != self.planned_cells:
            raise ValueError("evaluation-result entry counts must cover the plan")
        if self.succeeded_cells + self.failed_cells != self.verified_records:
            raise ValueError("evaluation-result entry verified counts must close")
        if self.headline_eligible != self.scientific_evidence_complete:
            raise ValueError("evaluation-result headline status is inconsistent")
        if self.scientific_effectiveness_established and not self.headline_eligible:
            raise ValueError("evaluation-result effectiveness requires headline evidence")
        return self


class ProjectManifest(BaseModel):
    """Primary ownership record; extension fields preserve historical manifests."""

    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    schema_version: str = "1.0"
    revision: int = Field(default=0, ge=0)
    project_id: str
    title: str = Field(min_length=1)
    research_direction: str = Field(min_length=1)
    target_domain: str | None = None
    target_venue: str | None = None
    status: str = Field(min_length=1)
    publication_ready: bool = False
    current_run: str | None = None
    completed_stages: list[int] = Field(default_factory=list)
    current_paper: str | None = None
    current_review: str | None = None
    current_evaluation: str | None = None
    current_evaluation_result: str | None = None
    stage_semantics: str = "autoresearchclaw-stages"
    retrieval_eligible: bool = True
    runs: list[ProjectRun] = Field(default_factory=list)
    reviews: list[ProjectReview] = Field(default_factory=list)
    evaluations: list[ProjectEvaluation] = Field(default_factory=list)
    evaluation_results: list[ProjectEvaluationResult] = Field(default_factory=list)

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("current_run")
    @classmethod
    def current_run_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_entry_id(value, field_name="current_run")

    @field_validator("current_paper")
    @classmethod
    def current_paper_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        locator = validate_relative_locator(value, field_name="current_paper")
        parts = PurePosixPath(locator).parts
        if len(parts) != 2 or parts[0] != "papers":
            raise ValueError("current_paper must be papers/<paper-directory>")
        validate_entry_id(parts[1], field_name="paper directory")
        return locator

    @field_validator("current_review")
    @classmethod
    def current_review_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_entry_id(value, field_name="current_review")

    @field_validator("current_evaluation")
    @classmethod
    def current_evaluation_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_entry_id(value, field_name="current_evaluation")

    @field_validator("current_evaluation_result")
    @classmethod
    def current_evaluation_result_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_entry_id(value, field_name="current_evaluation_result")

    @field_validator("completed_stages")
    @classmethod
    def completed_stages_are_canonical(cls, values: list[int]) -> list[int]:
        if any(stage < 1 or stage > 23 for stage in values):
            raise ValueError("completed stages must be between 1 and 23")
        if values != sorted(set(values)):
            raise ValueError("completed stages must be sorted and unique")
        return values

    @model_validator(mode="after")
    def run_references_are_closed(self) -> ProjectManifest:
        run_ids = [run.run_id for run in self.runs]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("project run IDs must be unique")
        known = set(run_ids)
        if self.current_run is not None and self.current_run not in known:
            raise ValueError("current_run must reference a registered run")
        unknown_superseding = {
            run.superseded_by for run in self.runs if run.superseded_by not in {None, *known}
        }
        if unknown_superseding:
            raise ValueError(
                f"superseded_by references unknown runs: {sorted(unknown_superseding)}"
            )
        if self.stage_semantics != "autoresearchclaw-stages" and self.completed_stages:
            raise ValueError("alternate stage semantics cannot claim AutoResearchClaw stages")
        review_ids = [review.review_id for review in self.reviews]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("project review IDs must be unique")
        if self.current_review is not None and self.current_review not in set(review_ids):
            raise ValueError("current_review must reference a registered review")
        evaluation_ids = [item.evaluation_id for item in self.evaluations]
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise ValueError("project evaluation IDs must be unique")
        if self.current_evaluation is not None and self.current_evaluation not in set(
            evaluation_ids
        ):
            raise ValueError("current_evaluation must reference a registered evaluation")
        result_ids = [item.result_id for item in self.evaluation_results]
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("project evaluation-result IDs must be unique")
        known_evaluations = set(evaluation_ids)
        if any(item.evaluation_id not in known_evaluations for item in self.evaluation_results):
            raise ValueError("evaluation results must reference registered evaluations")
        if self.current_evaluation_result is not None and self.current_evaluation_result not in set(
            result_ids
        ):
            raise ValueError(
                "current_evaluation_result must reference a registered evaluation result"
            )
        if self.current_evaluation_result is not None:
            selected_result = next(
                item
                for item in self.evaluation_results
                if item.result_id == self.current_evaluation_result
            )
            if self.current_evaluation != selected_result.evaluation_id:
                raise ValueError("current evaluation result must belong to the current evaluation")
        return self


class PaperScientificEvidenceBinding(BaseModel):
    """Self-hashed proof that one paper bundle incorporates one admitted result."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    paper_id: str
    evaluation_id: str
    result_id: str
    result_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scientific_evidence_complete: Literal[True] = True
    headline_eligible: Literal[True] = True
    scientific_effectiveness_established: bool
    bound_artifact_sha256: dict[str, str] = Field(min_length=1, max_length=500)
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("paper_id", "evaluation_id", "result_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: Any) -> str:
        return validate_entry_id(value, field_name=str(info.field_name))

    @field_validator("bound_artifact_sha256")
    @classmethod
    def artifact_bindings_are_closed(cls, values: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for locator, digest in values.items():
            normalized_locator = validate_relative_locator(
                locator,
                field_name="paper scientific-evidence artifact",
            )
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError("paper scientific-evidence artifact hashes must be SHA-256")
            normalized[normalized_locator] = digest
        if len(normalized) != len(values):
            raise ValueError("paper scientific-evidence artifact locators must be unique")
        return dict(sorted(normalized.items()))

    @model_validator(mode="after")
    def binding_is_self_hashed(self) -> PaperScientificEvidenceBinding:
        expected = content_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("paper scientific-evidence binding hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> PaperScientificEvidenceBinding:
        payload = {"schema_version": "1.0", **values}
        payload.pop("binding_sha256", None)
        unsigned = cls.model_construct(binding_sha256="0" * 64, **payload)
        return cls(
            **payload,
            binding_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"binding_sha256"})
            ),
        )


class PaperManifest(BaseModel):
    """Reader-facing paper bundle registered beneath exactly one project."""

    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    schema_version: str = "1.0"
    paper_id: str
    project_id: str
    title: str = Field(min_length=1)
    date: date
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    task: str = Field(min_length=1)
    seed: int = Field(ge=0)
    stage: int = Field(ge=1, le=23)
    status: str = Field(min_length=1)
    evidence_scope: str = Field(min_length=1)
    publication_ready: bool = False
    source_run: str | None = None
    files: dict[str, str] = Field(default_factory=dict)
    scientific_evidence: PaperScientificEvidenceBinding | None = None

    @field_validator("paper_id")
    @classmethod
    def paper_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="paper_id")

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("source_run")
    @classmethod
    def source_run_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_entry_id(value, field_name="source_run")

    @field_validator("files")
    @classmethod
    def files_are_relative(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not label.strip() for label in values):
            raise ValueError("paper file labels must not be blank")
        normalized: dict[str, str] = {}
        for label, locator in values.items():
            normalized[label] = validate_relative_locator(locator, field_name="paper file")
        if len(set(normalized.values())) != len(normalized):
            raise ValueError("paper file locators must be unique")
        return normalized

    @model_validator(mode="after")
    def scientific_evidence_matches_manifest(self) -> PaperManifest:
        binding = self.scientific_evidence
        locator = self.files.get("scientific-evidence-binding")
        if binding is None:
            if locator is not None:
                raise ValueError("paper evidence-binding file requires a typed binding")
            return self
        if locator is None:
            raise ValueError("paper scientific evidence requires its binding file")
        if binding.project_id != self.project_id or binding.paper_id != self.paper_id:
            raise ValueError("paper scientific-evidence identity differs from its manifest")
        expected_artifacts = set(self.files.values()) - {locator}
        if set(binding.bound_artifact_sha256) != expected_artifacts:
            raise ValueError("paper scientific-evidence binding must cover every other paper file")
        return self


class ProjectPaperEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    directory_name: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: PaperManifest

    @field_validator("directory_name")
    @classmethod
    def directory_name_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="paper directory")


class ProjectSnapshot(BaseModel):
    """Immutable serialized view consumed by catalogs and future generated surfaces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    project_id: str
    revision: int = Field(ge=0)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_locator: str
    manifest: ProjectManifest
    run_locators: dict[str, str]
    review_locators: dict[str, str] = Field(default_factory=dict)
    evaluation_locators: dict[str, str] = Field(default_factory=dict)
    evaluation_result_locators: dict[str, str] = Field(default_factory=dict)
    papers: list[ProjectPaperEntry]
    current_run_locator: str | None = None
    current_stage_locator: str | None = None
    current_paper_locator: str | None = None
    current_review_locator: str | None = None
    current_evaluation_locator: str | None = None
    current_evaluation_result_locator: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator(
        "project_locator",
        "current_run_locator",
        "current_stage_locator",
        "current_paper_locator",
        "current_review_locator",
        "current_evaluation_locator",
        "current_evaluation_result_locator",
    )
    @classmethod
    def snapshot_locators_are_relative(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_relative_locator(value, field_name="snapshot locator")

    @model_validator(mode="after")
    def identity_matches_manifest(self) -> ProjectSnapshot:
        if self.project_id != self.manifest.project_id:
            raise ValueError("snapshot project_id must match its manifest")
        if self.revision != self.manifest.revision:
            raise ValueError("snapshot revision must match its manifest")
        if set(self.run_locators) != {run.run_id for run in self.manifest.runs}:
            raise ValueError("snapshot run locators must cover registered runs")
        if set(self.review_locators) != {review.review_id for review in self.manifest.reviews}:
            raise ValueError("snapshot review locators must cover registered reviews")
        if set(self.evaluation_locators) != {
            evaluation.evaluation_id for evaluation in self.manifest.evaluations
        }:
            raise ValueError("snapshot evaluation locators must cover registered evaluations")
        if set(self.evaluation_result_locators) != {
            result.result_id for result in self.manifest.evaluation_results
        }:
            raise ValueError("snapshot evaluation-result locators must cover registered results")
        return self


def content_sha256(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()

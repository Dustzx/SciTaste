"""Bind reviewer concerns to the registered scientific evidence program.

Review routing determines *what kind* of work a concern needs.  This module
closes the next, scientific gap: it records which already-registered study,
contrast, task population, endpoint, and external method can answer that
concern.  Compilation and publication are deterministic and perform no
download, model call, GPU work, experiment, or human review.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.evaluation.evidence_program import (
    EvidenceHypothesis,
    EvidenceLayer,
    EvidenceProgramInspection,
    FormalSourceRole,
    InferenceRole,
    ReadinessStatus,
    TaskSourceRole,
    load_evidence_program,
)
from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.review.iteration_plan import (
    ProjectReviewIterationPlan,
    ReviewIterationWorkKind,
    inspect_project_review_iteration,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MAPPING_BYTES = 262_144


class ReviewFollowupObjective(StrEnum):
    """Scientific purpose of one concern-to-program mapping."""

    TITLE_EFFECTIVENESS = "title_effectiveness"
    EXTERNAL_ECOLOGICAL_COMPARISON = "external_ecological_comparison"
    CROSS_TASK_GENERALIZATION = "cross_task_generalization"
    TITLE_CLAIM_DISPOSITION = "title_claim_disposition"


class ReviewFollowupTreatmentKind(StrEnum):
    """Whether a concern needs evidence or an evidence-conditional claim action."""

    REGISTERED_STUDY_BUNDLE = "registered_study_bundle"
    CONDITIONAL_CLAIM_DISPOSITION = "conditional_claim_disposition"


class ReviewConcernEvidenceMapping(BaseModel):
    """Human-inspectable scientific judgment supplied to the deterministic compiler."""

    model_config = _CONFIG

    concern_id: str = Field(max_length=255)
    objective: ReviewFollowupObjective
    treatment_kind: ReviewFollowupTreatmentKind
    study_ids: tuple[str, ...] = Field(min_length=1, max_length=30)
    rationale: str = Field(min_length=1, max_length=4_000)
    claim_action: (
        Literal["retain_target_title_pending_evidence_or_narrow_before_submission"] | None
    ) = None
    title_change_authorized: Literal[False] = False

    @field_validator("concern_id")
    @classmethod
    def concern_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="review follow-up concern_id")

    @field_validator("study_ids")
    @classmethod
    def studies_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not value or len(value) > 255:
                raise ValueError("review follow-up study IDs must be bounded")
        if len(values) != len(set(values)):
            raise ValueError("review follow-up study IDs must be unique")
        return values

    @model_validator(mode="after")
    def treatment_matches_objective(self) -> ReviewConcernEvidenceMapping:
        is_claim = self.objective is ReviewFollowupObjective.TITLE_CLAIM_DISPOSITION
        expected = (
            ReviewFollowupTreatmentKind.CONDITIONAL_CLAIM_DISPOSITION
            if is_claim
            else ReviewFollowupTreatmentKind.REGISTERED_STUDY_BUNDLE
        )
        if self.treatment_kind is not expected:
            raise ValueError("review follow-up objective and treatment kind differ")
        if (self.claim_action is not None) != is_claim:
            raise ValueError("only a title claim disposition may carry a claim action")
        return self


class ReviewFollowupMappingManifest(BaseModel):
    """Explicit concern mapping reviewed before a package is project-registered."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    mapping_id: str = Field(pattern=_ID)
    project_id: str
    review_id: str = Field(max_length=255)
    review_iteration_run_id: str = Field(max_length=255)
    paper_title: str = Field(min_length=1, max_length=500)
    mappings: tuple[ReviewConcernEvidenceMapping, ...] = Field(min_length=1, max_length=320)
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @field_validator("project_id")
    @classmethod
    def project_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("review_id", "review_iteration_run_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "identifier")))

    @model_validator(mode="after")
    def concerns_are_unique(self) -> ReviewFollowupMappingManifest:
        concern_ids = [item.concern_id for item in self.mappings]
        if len(concern_ids) != len(set(concern_ids)):
            raise ValueError("review follow-up mapping must contain each concern once")
        return self


class ReviewFollowupMappingInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: ReviewFollowupMappingManifest


class ReviewFollowupTaskRequirement(BaseModel):
    model_config = _CONFIG

    source_id: str
    role: TaskSourceRole
    formal_role: FormalSourceRole
    resource_id: str | None = None
    accepted_venue: str | None = None
    selected_for_acquisition_proposal: bool
    rationale: str


class ReviewFollowupSystemRequirement(BaseModel):
    model_config = _CONFIG

    system_id: str
    resource_id: str | None = None
    accepted_venue: str
    selected_for_adapter_proposal: bool
    rationale: str


class ReviewFollowupStudyBinding(BaseModel):
    """One unique study reused across every concern that it answers."""

    model_config = _CONFIG

    study_id: str
    hypothesis: EvidenceHypothesis
    layer: EvidenceLayer
    inference_role: InferenceRole
    reused_by_concern_ids: tuple[str, ...] = Field(min_length=1, max_length=320)
    claim_ids: tuple[str, ...] = ()
    condition_ids: tuple[str, ...] = Field(min_length=1)
    task_source_ids: tuple[str, ...] = Field(min_length=1)
    system_candidate_ids: tuple[str, ...] = ()
    primary_endpoint: str
    estimand: str
    experimental_unit: str
    matched_backbone: bool
    matched_starting_information: bool
    matched_tool_permissions: bool
    matched_repair_policy: bool
    final_paper_required: bool
    title_critical: bool


class ReviewConcernFollowupTreatment(BaseModel):
    model_config = _CONFIG

    concern_id: str
    iteration_step_id: str
    objective: ReviewFollowupObjective
    treatment_kind: ReviewFollowupTreatmentKind
    study_ids: tuple[str, ...] = Field(min_length=1)
    hypothesis_ids: tuple[EvidenceHypothesis, ...] = Field(min_length=1)
    claim_ids: tuple[str, ...] = ()
    rationale: str
    claim_action: (
        Literal["retain_target_title_pending_evidence_or_narrow_before_submission"] | None
    ) = None
    title_change_authorized: Literal[False] = False
    creates_additional_execution: Literal[False] = False


class ProjectReviewFollowupDesign(BaseModel):
    """Self-hashed, resource-unselected evidence response to one review iteration."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    review_id: str
    review_iteration_run_id: str
    review_iteration_plan_sha256: str = Field(pattern=_SHA256)
    source_commit: str = Field(pattern=_COMMIT)
    mapping_id: str = Field(pattern=_ID)
    mapping_file_sha256: str = Field(pattern=_SHA256)
    evidence_program_id: str
    evidence_program_file_sha256: str = Field(pattern=_SHA256)
    evidence_program_sha256: str = Field(pattern=_SHA256)
    paper_title: str
    target_venue: Literal["ICLR 2027"]
    treatments: tuple[ReviewConcernFollowupTreatment, ...] = Field(min_length=1, max_length=320)
    studies: tuple[ReviewFollowupStudyBinding, ...] = Field(min_length=1, max_length=30)
    task_requirements: tuple[ReviewFollowupTaskRequirement, ...] = Field(
        min_length=1, max_length=30
    )
    system_requirements: tuple[ReviewFollowupSystemRequirement, ...] = Field(max_length=30)
    excluded_process_study_ids: tuple[str, ...]
    inventory_can_select_scientific_design: Literal[False] = False
    primary_model_id: None = None
    primary_model_selection_stage: Literal["after_conformance_pilot"]
    primary_model_selection_criteria: tuple[str, ...] = Field(min_length=3, max_length=30)
    matched_model_within_confirmatory_study: Literal[True] = True
    robustness_provider_non_pooled: Literal[True] = True
    task_subset_freeze: ReadinessStatus
    task_data_acquisition: ReadinessStatus
    adapter_preflight: ReadinessStatus
    model_conformance_pilot: ReadinessStatus
    power_analysis: ReadinessStatus
    reviewer_recruitment: ReadinessStatus
    judge_validation: ReadinessStatus
    sample_size_basis: Literal["pilot_then_power_analysis"]
    fixed_formal_sample_size: None = None
    fixed_repetitions: None = None
    source_group_split_required: Literal[True] = True
    failures_are_outcomes: Literal[True] = True
    pilot_data_excluded_from_formal_test: Literal[True] = True
    minimum_independent_reviewers: int = Field(ge=2)
    condition_blinded: Literal[True] = True
    conflict_screening: Literal[True] = True
    adjudication: Literal[True] = True
    automated_judge_role: Literal["secondary_calibrated_measure"]
    judge_validation_required: Literal[True] = True
    title_claim_status: Literal["submission_blocked_pending_title_critical_evidence"]
    title_change_authorized: Literal[False] = False
    compute_allocated: Literal[False] = False
    shared_studies_deduplicated: Literal[True] = True
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_execution: Literal[False] = False
    no_execution_performed: Literal[True] = True
    scientific_evidence_established: Literal[False] = False
    design_sha256: str = Field(pattern=_SHA256)

    @field_validator("project_id")
    @classmethod
    def project_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id", "review_id", "review_iteration_run_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "identifier")))

    @model_validator(mode="after")
    def bindings_are_closed_and_self_hashed(self) -> ProjectReviewFollowupDesign:
        treatment_concerns = [item.concern_id for item in self.treatments]
        if len(treatment_concerns) != len(set(treatment_concerns)):
            raise ValueError("review follow-up treatments must cover concerns once")
        study_ids = [item.study_id for item in self.studies]
        if len(study_ids) != len(set(study_ids)):
            raise ValueError("review follow-up studies must be deduplicated")
        known_studies = set(study_ids)
        if any(set(item.study_ids) - known_studies for item in self.treatments):
            raise ValueError("review follow-up treatment references an unknown study")
        expected_use = {
            study_id: tuple(
                item.concern_id for item in self.treatments if study_id in item.study_ids
            )
            for study_id in study_ids
        }
        if any(item.reused_by_concern_ids != expected_use[item.study_id] for item in self.studies):
            raise ValueError("review follow-up study reuse differs from concern treatments")
        expected = content_sha256(self.model_dump(mode="json", exclude={"design_sha256"}))
        if self.design_sha256 != expected:
            raise ValueError("review follow-up design hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectReviewFollowupDesign:
        payload = {"schema_version": "1.0", **values}
        payload.pop("design_sha256", None)
        unsigned = cls.model_construct(design_sha256="0" * 64, **payload)
        return cls(
            **payload,
            design_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"design_sha256"})
            ),
        )


@dataclass(frozen=True)
class PreparedProjectReviewFollowupDesign:
    design: ProjectReviewFollowupDesign
    mapping_bytes: bytes
    evidence_program_bytes: bytes


def load_review_followup_mapping(path: str | Path) -> ReviewFollowupMappingInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("review follow-up mapping must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MAPPING_BYTES:
        raise ValueError("review follow-up mapping must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("review follow-up mapping must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("review follow-up mapping must contain a YAML mapping")
    return ReviewFollowupMappingInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=ReviewFollowupMappingManifest.model_validate(payload),
    )


def compile_review_followup_design(
    *,
    project_id: str,
    run_id: str,
    source_commit: str,
    review_iteration: ProjectReviewIterationPlan,
    mapping: ReviewFollowupMappingInspection,
    evidence_program: EvidenceProgramInspection,
) -> ProjectReviewFollowupDesign:
    """Compile exact review treatments while deduplicating shared studies."""

    validate_project_id(project_id)
    validate_entry_id(run_id, field_name="run_id")
    manifest = mapping.manifest
    program = evidence_program.program
    if review_iteration.project_id != project_id or manifest.project_id != project_id:
        raise ValueError("review follow-up inputs belong to another project")
    if manifest.review_id != review_iteration.review_id:
        raise ValueError("review follow-up mapping identifies another review")
    if manifest.review_iteration_run_id != review_iteration.run_id:
        raise ValueError("review follow-up mapping identifies another iteration plan")
    if manifest.paper_title != program.paper_title:
        raise ValueError("review follow-up paper title differs from the evidence program")
    if set(item.concern_id for item in manifest.mappings) != set(review_iteration.concern_ids):
        raise ValueError("review follow-up mapping must cover every iteration concern exactly")
    if program.model_policy.primary_model_id is not None:
        raise ValueError("no-run review design requires the primary model to remain unselected")
    if any(
        (
            program.authorizes_download,
            program.authorizes_api_calls,
            program.authorizes_gpu_work,
            program.authorizes_execution,
        )
    ):
        raise ValueError("review follow-up design requires a no-run evidence program")

    studies_by_id = {item.study_id: item for item in program.study_layers}
    claims_by_id = {item.claim_id: item for item in program.claims}
    conditions_by_id = {item.condition_id: item for item in program.conditions}
    sources_by_id = {item.source_id: item for item in program.task_sources}
    systems_by_id = {item.system_id: item for item in program.system_candidates}
    title_claim_ids = tuple(item.claim_id for item in program.claims if item.title_critical)
    title_study_ids = tuple(
        item.study_id
        for item in program.study_layers
        if any(claim_id in title_claim_ids for claim_id in item.claim_ids)
    )
    ecological_study_ids = tuple(
        item.study_id
        for item in program.study_layers
        if item.hypothesis is EvidenceHypothesis.ECOLOGICAL_COMPARISON
    )
    non_process_study_ids = tuple(
        item.study_id
        for item in program.study_layers
        if item.inference_role is not InferenceRole.PROCESS_ONLY
    )
    expected_by_objective = {
        ReviewFollowupObjective.TITLE_EFFECTIVENESS: title_study_ids,
        ReviewFollowupObjective.EXTERNAL_ECOLOGICAL_COMPARISON: ecological_study_ids,
        ReviewFollowupObjective.CROSS_TASK_GENERALIZATION: non_process_study_ids,
        ReviewFollowupObjective.TITLE_CLAIM_DISPOSITION: title_study_ids,
    }

    treatments: list[ReviewConcernFollowupTreatment] = []
    for item in manifest.mappings:
        expected_studies = expected_by_objective[item.objective]
        if item.study_ids != expected_studies:
            raise ValueError(
                f"{item.concern_id} does not use the exact registered studies for "
                f"{item.objective.value}"
            )
        if any(study_id not in studies_by_id for study_id in item.study_ids):
            raise ValueError("review follow-up mapping references an unknown study")
        expected_kind = (
            ReviewIterationWorkKind.CLAIM_REVISION
            if item.treatment_kind is ReviewFollowupTreatmentKind.CONDITIONAL_CLAIM_DISPOSITION
            else ReviewIterationWorkKind.EXPERIMENT_DESIGN
        )
        matching_steps = [
            step
            for step in review_iteration.steps
            if item.concern_id in step.concern_ids and step.kind is expected_kind
        ]
        if len(matching_steps) != 1:
            raise ValueError(
                f"{item.concern_id} lacks one matching {expected_kind.value} iteration step"
            )
        selected_studies = tuple(studies_by_id[study_id] for study_id in item.study_ids)
        selected_claim_ids = tuple(
            claim.claim_id
            for claim in program.claims
            if any(claim.claim_id in study.claim_ids for study in selected_studies)
        )
        if item.objective is ReviewFollowupObjective.TITLE_CLAIM_DISPOSITION and (
            selected_claim_ids != title_claim_ids
        ):
            raise ValueError("title disposition must bind every title-critical claim")
        treatments.append(
            ReviewConcernFollowupTreatment(
                concern_id=item.concern_id,
                iteration_step_id=matching_steps[0].step_id,
                objective=item.objective,
                treatment_kind=item.treatment_kind,
                study_ids=item.study_ids,
                hypothesis_ids=tuple(study.hypothesis for study in selected_studies),
                claim_ids=selected_claim_ids,
                rationale=item.rationale,
                claim_action=item.claim_action,
            )
        )

    used_study_ids = {study_id for treatment in treatments for study_id in treatment.study_ids}
    studies = tuple(
        ReviewFollowupStudyBinding(
            study_id=study.study_id,
            hypothesis=study.hypothesis,
            layer=study.layer,
            inference_role=study.inference_role,
            reused_by_concern_ids=tuple(
                item.concern_id for item in treatments if study.study_id in item.study_ids
            ),
            claim_ids=study.claim_ids,
            condition_ids=study.condition_ids,
            task_source_ids=study.task_source_ids,
            system_candidate_ids=study.system_candidate_ids,
            primary_endpoint=study.primary_endpoint,
            estimand=study.estimand,
            experimental_unit=study.experimental_unit,
            matched_backbone=study.matched_backbone,
            matched_starting_information=study.matched_starting_information,
            matched_tool_permissions=study.matched_tool_permissions,
            matched_repair_policy=study.matched_repair_policy,
            final_paper_required=study.final_paper_required,
            title_critical=any(claims_by_id[item].title_critical for item in study.claim_ids),
        )
        for study in program.study_layers
        if study.study_id in used_study_ids
    )
    used_source_ids = {source_id for study in studies for source_id in study.task_source_ids}
    task_requirements = tuple(
        ReviewFollowupTaskRequirement(
            source_id=source.source_id,
            role=source.role,
            formal_role=source.formal_role,
            resource_id=source.resource_id,
            accepted_venue=source.accepted_venue,
            selected_for_acquisition_proposal=source.selected_for_acquisition_proposal,
            rationale=source.rationale,
        )
        for source in program.task_sources
        if source.source_id in used_source_ids
    )
    used_system_ids = {system_id for study in studies for system_id in study.system_candidate_ids}
    system_requirements = tuple(
        ReviewFollowupSystemRequirement(
            system_id=system.system_id,
            resource_id=system.resource_id,
            accepted_venue=system.accepted_venue,
            selected_for_adapter_proposal=system.selected_for_adapter_proposal,
            rationale=system.rationale,
        )
        for system in program.system_candidates
        if system.system_id in used_system_ids
    )
    # Force full reference resolution before hashing the package.
    for study in studies:
        _ = tuple(conditions_by_id[item] for item in study.condition_ids)
        _ = tuple(sources_by_id[item] for item in study.task_source_ids)
        _ = tuple(systems_by_id[item] for item in study.system_candidate_ids)

    readiness = program.operational_readiness
    return ProjectReviewFollowupDesign.create(
        project_id=project_id,
        run_id=run_id,
        review_id=review_iteration.review_id,
        review_iteration_run_id=review_iteration.run_id,
        review_iteration_plan_sha256=review_iteration.plan_sha256,
        source_commit=source_commit,
        mapping_id=manifest.mapping_id,
        mapping_file_sha256=mapping.file_sha256,
        evidence_program_id=program.program_id,
        evidence_program_file_sha256=evidence_program.file_sha256,
        evidence_program_sha256=program.proposal_sha256,
        paper_title=program.paper_title,
        target_venue=program.target_venue,
        treatments=tuple(treatments),
        studies=studies,
        task_requirements=task_requirements,
        system_requirements=system_requirements,
        excluded_process_study_ids=tuple(
            item.study_id
            for item in program.study_layers
            if item.inference_role is InferenceRole.PROCESS_ONLY
        ),
        primary_model_selection_stage=program.model_policy.primary_selection_stage,
        primary_model_selection_criteria=program.model_policy.selection_criteria,
        task_subset_freeze=readiness.task_subset_freeze,
        task_data_acquisition=readiness.task_data_acquisition,
        adapter_preflight=readiness.adapter_preflight,
        model_conformance_pilot=readiness.model_conformance_pilot,
        power_analysis=readiness.power_analysis,
        reviewer_recruitment=readiness.reviewer_recruitment,
        judge_validation=readiness.judge_validation,
        sample_size_basis=program.sampling_policy.sample_size_basis,
        minimum_independent_reviewers=program.human_review.minimum_independent_reviewers,
        automated_judge_role=program.human_review.automated_judge_role,
        title_claim_status="submission_blocked_pending_title_critical_evidence",
    )


def prepare_project_review_followup_design(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    review_iteration_run_id: str,
    mapping_path: str | Path,
    evidence_program_path: str | Path,
    run_id: str,
    source_commit: str,
    expected_revision: int,
) -> PreparedProjectReviewFollowupDesign:
    """Prepare a project-owned design without mutating the project."""

    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        raise ValueError(
            f"stale project revision {expected_revision}; current is {snapshot.revision}"
        )
    if run_id in {item.run_id for item in snapshot.manifest.runs}:
        raise ValueError("review follow-up design run is already registered")
    iteration = inspect_project_review_iteration(runtime, project_id, review_iteration_run_id)
    mapping = load_review_followup_mapping(mapping_path)
    program = load_evidence_program(evidence_program_path)
    _require_git_bound_inputs(
        source_commit=source_commit,
        evidence_program=program,
    )
    design = compile_review_followup_design(
        project_id=project_id,
        run_id=run_id,
        source_commit=source_commit,
        review_iteration=iteration,
        mapping=mapping,
        evidence_program=program,
    )
    return PreparedProjectReviewFollowupDesign(
        design=design,
        mapping_bytes=mapping.path.read_bytes(),
        evidence_program_bytes=program.path.read_bytes(),
    )


def publish_project_review_followup_design(
    runtime: ProjectRuntime,
    *,
    prepared: PreparedProjectReviewFollowupDesign,
    expected_revision: int,
) -> tuple[ProjectSnapshot, ProjectReviewFollowupDesign]:
    """Atomically publish an immutable, self-contained no-run design package."""

    design = prepared.design
    if runtime.open(design.project_id).revision != expected_revision:
        raise ValueError("project changed after review follow-up design")
    run = ProjectRun(
        run_id=design.run_id,
        provider="scitaste-native",
        model="deterministic-review-evidence-designer",
        condition="review-followup-evidence-design",
        seed=0,
        status="preparing-review-followup-design",
        evidence_scope="review-followup-design-only-no-effectiveness-claim",
        review_id=design.review_id,
        review_iteration_run_id=design.review_iteration_run_id,
        repository_commit=design.source_commit,
        design_sha256=design.design_sha256,
        evidence_program_sha256=design.evidence_program_sha256,
        authorizes_execution=False,
        no_execution_performed=True,
        scientific_evidence_established=False,
        model_calls=0,
    )
    snapshot = runtime.begin_run(design.project_id, run, expected_revision=expected_revision)
    run_root = runtime.projects_root / design.project_id / "runs" / design.run_id
    target = run_root / "review_followup_design"
    temporary = Path(tempfile.mkdtemp(prefix=".review-followup-", dir=run_root))
    try:
        _write_exclusive(temporary / "DESIGN.json", _json_bytes(design))
        _write_exclusive(temporary / "MAPPING.yaml", prepared.mapping_bytes)
        _write_exclusive(temporary / "PROGRAM.yaml", prepared.evidence_program_bytes)
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    snapshot = runtime.update_run(
        design.project_id,
        design.run_id,
        expected_revision=snapshot.revision,
        status="complete-review-followup-designed",
        stage_path="review_followup_design",
        artifact=f"runs/{design.run_id}/review_followup_design/DESIGN.json",
        study_ids=[item.study_id for item in design.studies],
        concern_ids=[item.concern_id for item in design.treatments],
    )
    observed = inspect_project_review_followup_design(runtime, design.project_id, design.run_id)
    if observed.design_sha256 != design.design_sha256:
        raise ValueError("published review follow-up design differs from prepared bytes")
    return snapshot, observed


def inspect_project_review_followup_design(
    runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
) -> ProjectReviewFollowupDesign:
    """Rehash and deterministically recompile one project-owned design package."""

    snapshot = runtime.open(project_id)
    run = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    if run is None:
        raise ValueError("unknown project review follow-up design run")
    root = f"runs/{run_id}/review_followup_design"
    if run.artifact != f"{root}/DESIGN.json" or run.stage_path != "review_followup_design":
        raise ValueError("project run does not identify a complete review follow-up design")
    design_path = _contained_regular_file(runtime.projects_root / project_id, f"{root}/DESIGN.json")
    design = ProjectReviewFollowupDesign.model_validate_json(design_path.read_bytes())
    if design.project_id != project_id or design.run_id != run_id:
        raise ValueError("review follow-up design identity differs from the project run")
    if getattr(run, "design_sha256", None) != design.design_sha256:
        raise ValueError("project run review follow-up design hash differs")
    mapping = load_review_followup_mapping(
        _contained_regular_file(runtime.projects_root / project_id, f"{root}/MAPPING.yaml")
    )
    program = load_evidence_program(
        _contained_regular_file(runtime.projects_root / project_id, f"{root}/PROGRAM.yaml")
    )
    if mapping.file_sha256 != design.mapping_file_sha256:
        raise ValueError("review follow-up mapping bytes changed")
    if program.file_sha256 != design.evidence_program_file_sha256:
        raise ValueError("review follow-up evidence-program bytes changed")
    iteration = inspect_project_review_iteration(
        runtime, project_id, design.review_iteration_run_id
    )
    if iteration.plan_sha256 != design.review_iteration_plan_sha256:
        raise ValueError("review iteration plan changed after follow-up design")
    rebuilt = compile_review_followup_design(
        project_id=project_id,
        run_id=run_id,
        source_commit=design.source_commit,
        review_iteration=iteration,
        mapping=mapping,
        evidence_program=program,
    )
    if rebuilt != design:
        raise ValueError("review follow-up design differs from deterministic recompilation")
    return design


def _json_bytes(value: BaseModel) -> bytes:
    return (value.model_dump_json(indent=2) + "\n").encode("utf-8")


def _require_git_bound_inputs(
    *,
    source_commit: str,
    evidence_program: EvidenceProgramInspection,
) -> None:
    """Require the named commit to contain the exact two scientific inputs."""

    try:
        root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=evidence_program.path.parent,
            check=True,
            capture_output=True,
            timeout=10,
        )
        root = Path(root_result.stdout.decode("utf-8").strip()).resolve(strict=True)
    except (OSError, UnicodeDecodeError, subprocess.SubprocessError) as exc:
        raise ValueError("review follow-up inputs must belong to a Git repository") from exc
    try:
        program_locator = evidence_program.path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("review follow-up evidence program must belong to the repository") from exc
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("review follow-up source commit is unavailable") from exc
    for locator, expected in (
        (program_locator, evidence_program.path.read_bytes()),
        ("src/scitaste/review/followup_design.py", None),
    ):
        try:
            result = subprocess.run(
                ["git", "show", f"{source_commit}:{locator}"],
                cwd=root,
                check=True,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError(f"review follow-up source commit does not contain {locator}") from exc
        if expected is not None and result.stdout != expected:
            raise ValueError(f"review follow-up source commit has different bytes for {locator}")


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _contained_regular_file(root: Path, locator: str) -> Path:
    root = root.resolve(strict=True)
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("project review follow-up paths must not contain symlinks")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("project review follow-up path escapes its root") from exc
    if not resolved.is_file():
        raise ValueError("project review follow-up path must be a regular file")
    return resolved


__all__ = [
    "PreparedProjectReviewFollowupDesign",
    "ProjectReviewFollowupDesign",
    "ReviewConcernEvidenceMapping",
    "ReviewConcernFollowupTreatment",
    "ReviewFollowupMappingInspection",
    "ReviewFollowupMappingManifest",
    "ReviewFollowupObjective",
    "ReviewFollowupStudyBinding",
    "ReviewFollowupSystemRequirement",
    "ReviewFollowupTaskRequirement",
    "ReviewFollowupTreatmentKind",
    "compile_review_followup_design",
    "inspect_project_review_followup_design",
    "load_review_followup_mapping",
    "prepare_project_review_followup_design",
    "publish_project_review_followup_design",
]

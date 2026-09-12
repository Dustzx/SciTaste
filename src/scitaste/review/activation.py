"""Compile review evidence designs into bounded, no-run activation decisions.

The review follow-up design says which studies can answer reviewer concerns.
This module joins that design to exact data, adapter, compute, and project-
resource proposals.  It reports the next owner decision and every remaining
launch blocker, but cannot approve or perform an external action.
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

from scitaste.evaluation.evidence_review import (
    MethodProposalStatus,
    SourceProposalKind,
    SourceProposalStatus,
    inspect_evidence_review_package,
    load_evidence_review_package,
)
from scitaste.evaluation.model_identity import (
    ApiIdentityCandidateQualification,
    ApiIdentityMode,
    load_api_identity_protocol,
    qualify_api_identity_candidate,
)
from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.resources import (
    ApiModelDefinition,
    ModelCheckpointDefinition,
    ObservationStatus,
    ResourceKind,
    inspect_compute_resource_catalog,
    inspect_project_resource_binding,
    load_compute_resource_catalog,
    load_project_resource_binding,
)
from scitaste.resources.registry import ComputeResourceDefinition, ProjectResourceBindingEntry
from scitaste.review.followup_design import (
    ProjectReviewFollowupDesign,
    ReviewFollowupStudyBinding,
    ReviewFollowupTaskRequirement,
    inspect_project_review_followup_design,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MANIFEST_BYTES = 1_048_576


class ActivationReadiness(StrEnum):
    READY_FOR_OWNER_DECISION = "ready_for_owner_decision"
    PROTOCOL_ONLY = "protocol_only"
    BLOCKED = "blocked"


class ActivationFileBinding(BaseModel):
    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=1_000)
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_safe(self) -> ActivationFileBinding:
        pure = PurePosixPath(self.path)
        if (
            pure.is_absolute()
            or not pure.parts
            or any(item in {"", ".", ".."} for item in pure.parts)
        ):
            raise ValueError("activation paths must be normalized relative POSIX paths")
        return self


class ReviewFollowupActivationManifest(BaseModel):
    """Human-authored resource candidates; none is an experimental selection."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    manifest_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    evidence_review_package: ActivationFileBinding
    compute_catalog: ActivationFileBinding
    project_resource_binding: ActivationFileBinding
    model_identity_protocol: ActivationFileBinding | None = None
    primary_api_candidate_ids: tuple[str, ...] = Field(min_length=2, max_length=10)
    diagnostic_checkpoint_ids: tuple[str, ...] = Field(default=(), max_length=10)
    primary_selection_stage: Literal["after_task_excluded_conformance_pilot"]
    stable_model_revision_required: Literal[True] | None = None
    stable_model_identity_required: Literal[True] | None = None
    pilot_excluded_from_formal_test: Literal[True] = True
    automated_judge_is_secondary: Literal[True] = True
    authorizes_download: Literal[False] = False
    authorizes_repository_checkout: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @field_validator("primary_api_candidate_ids", "diagnostic_checkpoint_ids")
    @classmethod
    def candidate_ids_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("activation resource candidate IDs must be unique")
        return values

    @model_validator(mode="after")
    def version_selects_one_identity_contract(self) -> ReviewFollowupActivationManifest:
        if self.schema_version == "1.0":
            if self.stable_model_revision_required is not True:
                raise ValueError("activation v1.0 requires stable model revisions")
            if self.model_identity_protocol is not None or self.stable_model_identity_required:
                raise ValueError("activation v1.0 cannot use a temporal identity protocol")
        else:
            if self.stable_model_identity_required is not True:
                raise ValueError("activation v1.1 requires stable model identity")
            if self.model_identity_protocol is None:
                raise ValueError("activation v1.1 requires an API identity protocol")
            if self.stable_model_revision_required is not None:
                raise ValueError("activation v1.1 replaces immutable-revision-only policy")
        return self


class ReviewFollowupActivationManifestInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: ReviewFollowupActivationManifest


class ActivationTaskStatus(BaseModel):
    model_config = _CONFIG

    source_id: str
    formal_role: str
    proposal_kind: SourceProposalKind | None = None
    requested_item_count: int = Field(ge=0)
    maximum_requested_bytes: int = Field(ge=0)
    ready_for_owner_scope_review: bool
    experiment_ready: Literal[False] = False
    blocker_codes: tuple[str, ...] = Field(min_length=1)


class ActivationSystemStatus(BaseModel):
    model_config = _CONFIG

    system_id: str
    proposal_viable: bool
    adapter_implementation_ready: bool
    upstream_preflight_ready: bool
    experiment_ready: Literal[False] = False
    blocker_codes: tuple[str, ...] = Field(min_length=1)


class ActivationModelCandidateStatus(BaseModel):
    model_config = _CONFIG

    resource_id: str
    role: str
    provider_id: str
    model_id: str
    declared_revision: str
    availability: ObservationStatus
    rolling_alias: bool
    pricing_verified: bool
    identity_mode: ApiIdentityMode | None = None
    temporal_identity_protocol_defined: bool | None = None
    authenticated_identity_attested: bool | None = None
    pilot_proposal_ready: bool | None = None
    formal_identity_window_open: Literal[False] | None = None
    selected: Literal[False] = False
    ready_for_conformance_pilot: bool
    blocker_codes: tuple[str, ...]

    @model_validator(mode="after")
    def readiness_matches_blockers(self) -> ActivationModelCandidateStatus:
        if self.identity_mode is None:
            additions = (
                self.temporal_identity_protocol_defined,
                self.authenticated_identity_attested,
                self.pilot_proposal_ready,
                self.formal_identity_window_open,
            )
            if any(item is not None for item in additions):
                raise ValueError("legacy model candidates cannot carry temporal identity state")
            if self.ready_for_conformance_pilot != (not self.blocker_codes):
                raise ValueError("model-candidate readiness must match its blockers")
            return self
        if (
            self.temporal_identity_protocol_defined is not True
            or self.authenticated_identity_attested is None
            or self.pilot_proposal_ready is None
            or self.formal_identity_window_open is not False
        ):
            raise ValueError("temporal model candidates require complete identity state")
        expected_pilot = self.authenticated_identity_attested and self.pricing_verified
        if self.ready_for_conformance_pilot != expected_pilot:
            raise ValueError("model conformance readiness differs from identity evidence")
        return self


class ActivationDiagnosticCheckpoint(BaseModel):
    model_config = _CONFIG

    resource_id: str
    model_id: str
    declared_revision: str
    availability: ObservationStatus
    role: str
    paper_backbone_selected: Literal[False] = False


class ActivationStudyStatus(BaseModel):
    model_config = _CONFIG

    study_id: str
    hypothesis: str
    task_source_ids: tuple[str, ...] = Field(min_length=1)
    system_candidate_ids: tuple[str, ...] = ()
    title_critical: bool
    readiness: Literal[ActivationReadiness.BLOCKED] = ActivationReadiness.BLOCKED
    blocker_codes: tuple[str, ...] = Field(min_length=1)


class ActivationOwnerDecision(BaseModel):
    model_config = _CONFIG

    decision_id: Literal["review-exact-metadata-acquisition"]
    readiness: Literal[ActivationReadiness.READY_FOR_OWNER_DECISION]
    source_ids: tuple[str, ...] = Field(min_length=1)
    requested_item_count: int = Field(gt=0)
    maximum_requested_bytes: int = Field(gt=0)
    requested_external_action: Literal["download_metadata"]
    approved: Literal[False] = False
    approval_recorded: Literal[False] = False
    action_performed: Literal[False] = False


class ProjectReviewFollowupActivation(BaseModel):
    """Self-hashed project record joining scientific design and launch resources."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    project_id: str
    run_id: str
    source_commit: str = Field(pattern=_COMMIT)
    review_id: str
    review_iteration_run_id: str
    followup_design_run_id: str
    followup_design_sha256: str = Field(pattern=_SHA256)
    evidence_program_sha256: str = Field(pattern=_SHA256)
    activation_manifest_id: str
    activation_manifest_file_sha256: str = Field(pattern=_SHA256)
    evidence_review_package_sha256: str = Field(pattern=_SHA256)
    evidence_review_report_sha256: str = Field(pattern=_SHA256)
    compute_catalog_semantic_sha256: str = Field(pattern=_SHA256)
    project_resource_binding_semantic_sha256: str = Field(pattern=_SHA256)
    model_identity_protocol_id: str | None = Field(default=None, pattern=_ID)
    model_identity_protocol_file_sha256: str | None = Field(default=None, pattern=_SHA256)
    model_identity_protocol_semantic_sha256: str | None = Field(default=None, pattern=_SHA256)
    paper_title: str
    target_venue: Literal["ICLR 2027"]
    studies: tuple[ActivationStudyStatus, ...] = Field(min_length=1, max_length=30)
    task_sources: tuple[ActivationTaskStatus, ...] = Field(min_length=1, max_length=30)
    external_systems: tuple[ActivationSystemStatus, ...] = Field(max_length=30)
    primary_model_candidates: tuple[ActivationModelCandidateStatus, ...] = Field(
        min_length=2, max_length=10
    )
    diagnostic_checkpoints: tuple[ActivationDiagnosticCheckpoint, ...] = Field(max_length=10)
    primary_model_id: None = None
    primary_selection_stage: Literal["after_task_excluded_conformance_pilot"]
    task_excluded_pilot_required: Literal[True] = True
    pilot_excluded_from_formal_test: Literal[True] = True
    minimum_independent_reviewers: int = Field(ge=2)
    condition_blinded: Literal[True] = True
    conflict_screening: Literal[True] = True
    adjudication: Literal[True] = True
    automated_judge_role: Literal["secondary_calibrated_measure"]
    reviewer_recruitment_state: Literal[ActivationReadiness.PROTOCOL_ONLY]
    reviewer_count: Literal[0] = 0
    fixed_formal_sample_size: None = None
    fixed_repetitions: None = None
    compute_allocated: Literal[False] = False
    ready_for_metadata_owner_decision: Literal[True] = True
    ready_for_model_pilot_proposal: bool | None = None
    ready_for_model_conformance_pilot: bool
    ready_for_adapter_preflight: bool
    ready_for_human_recruitment: Literal[False] = False
    ready_for_experiment: Literal[False] = False
    next_owner_decision: ActivationOwnerDecision
    blocker_codes: tuple[str, ...] = Field(min_length=1, max_length=500)
    historical_campaign_superseded_for_launch: Literal[True] = True
    authorizes_download: Literal[False] = False
    authorizes_repository_checkout: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_execution: Literal[False] = False
    no_external_action_performed: Literal[True] = True
    scientific_evidence_established: Literal[False] = False
    activation_sha256: str = Field(pattern=_SHA256)

    @field_validator("project_id")
    @classmethod
    def project_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id", "review_id", "review_iteration_run_id", "followup_design_run_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "identifier")))

    @model_validator(mode="after")
    def activation_is_closed_and_self_hashed(self) -> ProjectReviewFollowupActivation:
        for values, label in (
            ([item.study_id for item in self.studies], "study"),
            ([item.source_id for item in self.task_sources], "task source"),
            ([item.system_id for item in self.external_systems], "system"),
            ([item.resource_id for item in self.primary_model_candidates], "model candidate"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"activation {label} IDs must be unique")
        if self.ready_for_model_conformance_pilot != all(
            item.ready_for_conformance_pilot for item in self.primary_model_candidates
        ):
            raise ValueError("model pilot readiness differs from candidate states")
        identity_values = (
            self.model_identity_protocol_id,
            self.model_identity_protocol_file_sha256,
            self.model_identity_protocol_semantic_sha256,
            self.ready_for_model_pilot_proposal,
        )
        if self.schema_version == "1.0":
            if any(item is not None for item in identity_values):
                raise ValueError("activation v1.0 cannot carry temporal identity state")
        else:
            if any(item is None for item in identity_values):
                raise ValueError("activation v1.1 requires temporal identity provenance")
            expected_owner_ready = all(
                item.pilot_proposal_ready is True for item in self.primary_model_candidates
            )
            if self.ready_for_model_pilot_proposal != expected_owner_ready:
                raise ValueError("model pilot-proposal readiness differs from candidates")
        if self.ready_for_adapter_preflight != all(
            item.adapter_implementation_ready for item in self.external_systems
        ):
            raise ValueError("adapter readiness differs from system states")
        expected = content_sha256(_activation_hash_payload(self))
        if self.activation_sha256 != expected:
            raise ValueError("review activation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectReviewFollowupActivation:
        payload = {"schema_version": "1.0", **values}
        payload.pop("activation_sha256", None)
        unsigned = cls.model_construct(activation_sha256="0" * 64, **payload)
        return cls(
            **payload,
            activation_sha256=content_sha256(_activation_hash_payload(unsigned)),
        )


@dataclass(frozen=True)
class PreparedProjectReviewFollowupActivation:
    activation: ProjectReviewFollowupActivation
    manifest_bytes: bytes


def load_review_followup_activation_manifest(
    path: str | Path,
) -> ReviewFollowupActivationManifestInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("review activation manifest must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("review activation manifest must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("review activation manifest must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("review activation manifest must contain a YAML mapping")
    return ReviewFollowupActivationManifestInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=ReviewFollowupActivationManifest.model_validate(payload),
    )


def compile_review_followup_activation(
    *,
    design: ProjectReviewFollowupDesign,
    manifest_inspection: ReviewFollowupActivationManifestInspection,
    workspace_root: str | Path,
    run_id: str,
    source_commit: str,
) -> ProjectReviewFollowupActivation:
    """Cross-check one design against exact proposals without performing actions."""

    manifest = manifest_inspection.manifest
    root = Path(workspace_root).resolve(strict=True)
    validate_entry_id(run_id, field_name="run_id")
    if manifest.project_id != design.project_id:
        raise ValueError("review activation manifest belongs to another project")

    review_path = _verify_binding(root, manifest.evidence_review_package)
    catalog_path = _verify_binding(root, manifest.compute_catalog)
    binding_path = _verify_binding(root, manifest.project_resource_binding)
    review_inspection = load_evidence_review_package(review_path)
    review = inspect_evidence_review_package(review_inspection, workspace_root=root)
    if review_inspection.package.package_sha256 != manifest.evidence_review_package.semantic_sha256:
        raise ValueError("review activation evidence package semantic hash differs")
    if not review.ready_for_owner_review:
        raise ValueError("review activation requires an exact owner-review-ready package")
    if review.evidence_program_sha256 != design.evidence_program_sha256:
        raise ValueError("review activation evidence program differs from follow-up design")

    catalog_inspection = inspect_compute_resource_catalog(catalog_path, evidence_root=root)
    loaded_catalog = load_compute_resource_catalog(catalog_path)
    if loaded_catalog.semantic_sha256 != manifest.compute_catalog.semantic_sha256:
        raise ValueError("review activation compute-catalog semantic hash differs")
    if not catalog_inspection.evidence_verified:
        raise ValueError("review activation compute evidence is not exact")
    binding_inspection = inspect_project_resource_binding(catalog_path, binding_path)
    resource_binding = load_project_resource_binding(binding_path)
    if (
        binding_inspection.binding_semantic_sha256
        != manifest.project_resource_binding.semantic_sha256
    ):
        raise ValueError("review activation project-resource semantic hash differs")
    if not binding_inspection.valid or resource_binding.project_id != design.project_id:
        raise ValueError("review activation project-resource binding is invalid")

    identity_inspection = None
    if manifest.model_identity_protocol is not None:
        identity_path = _verify_binding(root, manifest.model_identity_protocol)
        identity_inspection = load_api_identity_protocol(identity_path)
        if identity_inspection.semantic_sha256 != manifest.model_identity_protocol.semantic_sha256:
            raise ValueError("review activation API identity semantic hash differs")
        if identity_inspection.protocol.project_id != design.project_id:
            raise ValueError("review activation API identity protocol belongs to another project")
        identity_resource_ids = {
            item.resource_id for item in identity_inspection.protocol.candidate_policies
        }
        if identity_resource_ids != set(manifest.primary_api_candidate_ids):
            raise ValueError("review activation API identity candidates differ")

    selected_source_ids = {
        item.source_id
        for item in design.task_requirements
        if item.selected_for_acquisition_proposal
    }
    reviewed_source_ids = {item.source_id for item in review.source_statuses}
    if selected_source_ids != reviewed_source_ids:
        raise ValueError("review activation source proposals do not cover the design")
    selected_system_ids = {item.system_id for item in design.system_requirements}
    reviewed_system_ids = {item.system_id for item in review.method_statuses}
    if selected_system_ids != reviewed_system_ids:
        raise ValueError("review activation method proposals do not cover the design")

    entries_by_resource: dict[str, list[ProjectResourceBindingEntry]] = {}
    for item in resource_binding.bindings:
        entries_by_resource.setdefault(item.resource_id, []).append(item)
    selected_resource_ids = (
        *manifest.primary_api_candidate_ids,
        *manifest.diagnostic_checkpoint_ids,
    )
    ambiguous = [
        resource_id
        for resource_id in selected_resource_ids
        if len(entries_by_resource.get(resource_id, ())) != 1
    ]
    if ambiguous:
        raise ValueError(
            "review activation resources require exactly one project binding: "
            + ", ".join(ambiguous)
        )
    entries = {item: entries_by_resource[item][0] for item in selected_resource_ids}
    primary_models = []
    for resource_id in manifest.primary_api_candidate_ids:
        resource = loaded_catalog.catalog.resource(resource_id)
        qualification = None
        if identity_inspection is not None:
            if not isinstance(resource, ApiModelDefinition):
                raise ValueError("primary model candidates must be API model resources")
            qualification = qualify_api_identity_candidate(
                resource,
                identity_inspection.protocol.policy(resource_id),
            )
        primary_models.append(
            _model_candidate(resource, entries.get(resource_id), qualification=qualification)
        )
    primary_models = tuple(primary_models)
    if len({item.provider_id for item in primary_models}) != len(primary_models):
        raise ValueError("primary and robustness API candidates must use distinct providers")
    diagnostics = tuple(
        _diagnostic_checkpoint(
            loaded_catalog.catalog.resource(resource_id), entries.get(resource_id)
        )
        for resource_id in manifest.diagnostic_checkpoint_ids
    )
    source_status_by_id = {item.source_id: item for item in review.source_statuses}
    task_sources = tuple(
        _task_status(requirement, source_status_by_id.get(requirement.source_id))
        for requirement in design.task_requirements
    )
    method_status_by_id = {item.system_id: item for item in review.method_statuses}
    external_systems = tuple(
        _system_status(requirement.system_id, method_status_by_id[requirement.system_id])
        for requirement in design.system_requirements
    )
    task_by_id = {item.source_id: item for item in task_sources}
    system_by_id = {item.system_id: item for item in external_systems}
    studies = tuple(
        _study_status(study, task_by_id=task_by_id, system_by_id=system_by_id)
        for study in design.studies
    )

    acquisition_sources = tuple(
        item.source_id
        for item in review.source_statuses
        if item.kind is SourceProposalKind.ACQUISITION_REQUEST
    )
    next_decision = ActivationOwnerDecision(
        decision_id="review-exact-metadata-acquisition",
        readiness=ActivationReadiness.READY_FOR_OWNER_DECISION,
        source_ids=acquisition_sources,
        requested_item_count=review.requested_metadata_item_count,
        maximum_requested_bytes=review.maximum_requested_metadata_bytes,
        requested_external_action="download_metadata",
    )
    model_ready = all(item.ready_for_conformance_pilot for item in primary_models)
    model_pilot_owner_ready = (
        all(item.pilot_proposal_ready is True for item in primary_models)
        if identity_inspection is not None
        else None
    )
    adapter_ready = all(item.adapter_implementation_ready for item in external_systems)
    blockers = tuple(
        dict.fromkeys(
            [
                *(
                    f"study:{item.study_id}:{code}"
                    for item in studies
                    for code in item.blocker_codes
                ),
                *(
                    f"model:{item.resource_id}:{code}"
                    for item in primary_models
                    for code in item.blocker_codes
                ),
                "human:reviewers_not_recruited",
                "statistics:formal_sample_not_powered",
                "compute:not_allocated",
                "owner:metadata_acquisition_not_approved",
            ]
        )
    )
    return ProjectReviewFollowupActivation.create(
        schema_version=manifest.schema_version,
        project_id=design.project_id,
        run_id=run_id,
        source_commit=source_commit,
        review_id=design.review_id,
        review_iteration_run_id=design.review_iteration_run_id,
        followup_design_run_id=design.run_id,
        followup_design_sha256=design.design_sha256,
        evidence_program_sha256=design.evidence_program_sha256,
        activation_manifest_id=manifest.manifest_id,
        activation_manifest_file_sha256=manifest_inspection.file_sha256,
        evidence_review_package_sha256=review_inspection.package.package_sha256,
        evidence_review_report_sha256=content_sha256(review.model_dump(mode="json")),
        compute_catalog_semantic_sha256=loaded_catalog.semantic_sha256,
        project_resource_binding_semantic_sha256=(binding_inspection.binding_semantic_sha256),
        model_identity_protocol_id=(
            identity_inspection.protocol.protocol_id if identity_inspection is not None else None
        ),
        model_identity_protocol_file_sha256=(
            identity_inspection.file_sha256 if identity_inspection is not None else None
        ),
        model_identity_protocol_semantic_sha256=(
            identity_inspection.semantic_sha256 if identity_inspection is not None else None
        ),
        paper_title=design.paper_title,
        target_venue=design.target_venue,
        studies=studies,
        task_sources=task_sources,
        external_systems=external_systems,
        primary_model_candidates=primary_models,
        diagnostic_checkpoints=diagnostics,
        primary_selection_stage=manifest.primary_selection_stage,
        minimum_independent_reviewers=design.minimum_independent_reviewers,
        automated_judge_role=design.automated_judge_role,
        reviewer_recruitment_state=ActivationReadiness.PROTOCOL_ONLY,
        ready_for_model_pilot_proposal=model_pilot_owner_ready,
        ready_for_model_conformance_pilot=model_ready,
        ready_for_adapter_preflight=adapter_ready,
        next_owner_decision=next_decision,
        blocker_codes=blockers,
    )


def prepare_project_review_followup_activation(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    followup_design_run_id: str,
    manifest_path: str | Path,
    workspace_root: str | Path,
    run_id: str,
    source_commit: str,
    expected_revision: int,
) -> PreparedProjectReviewFollowupActivation:
    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        raise ValueError(
            f"stale project revision {expected_revision}; current is {snapshot.revision}"
        )
    if run_id in {item.run_id for item in snapshot.manifest.runs}:
        raise ValueError("review activation run is already registered")
    design = inspect_project_review_followup_design(runtime, project_id, followup_design_run_id)
    manifest = load_review_followup_activation_manifest(manifest_path)
    _require_git_bound_inputs(source_commit, manifest, Path(workspace_root))
    activation = compile_review_followup_activation(
        design=design,
        manifest_inspection=manifest,
        workspace_root=workspace_root,
        run_id=run_id,
        source_commit=source_commit,
    )
    return PreparedProjectReviewFollowupActivation(
        activation=activation,
        manifest_bytes=manifest.path.read_bytes(),
    )


def publish_project_review_followup_activation(
    runtime: ProjectRuntime,
    *,
    prepared: PreparedProjectReviewFollowupActivation,
    expected_revision: int,
) -> tuple[ProjectSnapshot, ProjectReviewFollowupActivation]:
    activation = prepared.activation
    if runtime.open(activation.project_id).revision != expected_revision:
        raise ValueError("project changed after review activation preparation")
    run = ProjectRun(
        run_id=activation.run_id,
        provider="scitaste-native",
        model="deterministic-review-activation-compiler",
        condition="review-followup-activation-dossier",
        seed=0,
        status="preparing-review-followup-activation",
        evidence_scope="review-activation-only-no-effectiveness-claim",
        review_id=activation.review_id,
        review_iteration_run_id=activation.review_iteration_run_id,
        followup_design_run_id=activation.followup_design_run_id,
        repository_commit=activation.source_commit,
        activation_sha256=activation.activation_sha256,
        authorizes_execution=False,
        no_execution_performed=True,
        scientific_evidence_established=False,
        model_calls=0,
    )
    snapshot = runtime.begin_run(activation.project_id, run, expected_revision=expected_revision)
    run_root = runtime.projects_root / activation.project_id / "runs" / activation.run_id
    target = run_root / "review_followup_activation"
    temporary = Path(tempfile.mkdtemp(prefix=".review-activation-", dir=run_root))
    try:
        _write_exclusive(temporary / "ACTIVATION.json", _json_bytes(activation))
        _write_exclusive(temporary / "MANIFEST.yaml", prepared.manifest_bytes)
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    snapshot = runtime.update_run(
        activation.project_id,
        activation.run_id,
        expected_revision=snapshot.revision,
        status="complete-review-followup-activation",
        stage_path="review_followup_activation",
        artifact=f"runs/{activation.run_id}/review_followup_activation/ACTIVATION.json",
        blocker_count=len(activation.blocker_codes),
        next_owner_decision_id=activation.next_owner_decision.decision_id,
    )
    observed = inspect_project_review_followup_activation(
        runtime, activation.project_id, activation.run_id
    )
    if observed.activation_sha256 != activation.activation_sha256:
        raise ValueError("published review activation differs from prepared bytes")
    return snapshot, observed


def inspect_project_review_followup_activation(
    runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
) -> ProjectReviewFollowupActivation:
    snapshot = runtime.open(project_id)
    run = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    if run is None:
        raise ValueError("unknown project review activation run")
    root = f"runs/{run_id}/review_followup_activation"
    if run.artifact != f"{root}/ACTIVATION.json" or run.stage_path != "review_followup_activation":
        raise ValueError("project run does not identify a complete review activation")
    activation_path = _contained_regular_file(
        runtime.projects_root / project_id, f"{root}/ACTIVATION.json"
    )
    activation = ProjectReviewFollowupActivation.model_validate_json(activation_path.read_bytes())
    if activation.project_id != project_id or activation.run_id != run_id:
        raise ValueError("review activation identity differs from the project run")
    if getattr(run, "activation_sha256", None) != activation.activation_sha256:
        raise ValueError("project run review activation hash differs")
    manifest_path = _contained_regular_file(
        runtime.projects_root / project_id, f"{root}/MANIFEST.yaml"
    )
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != (
        activation.activation_manifest_file_sha256
    ):
        raise ValueError("review activation manifest bytes changed")
    design = inspect_project_review_followup_design(
        runtime, project_id, activation.followup_design_run_id
    )
    if design.design_sha256 != activation.followup_design_sha256:
        raise ValueError("review activation follow-up design changed")
    return activation


def _task_status(
    requirement: ReviewFollowupTaskRequirement, proposal: SourceProposalStatus | None
) -> ActivationTaskStatus:
    source_id = requirement.source_id
    if proposal is None:
        return ActivationTaskStatus(
            source_id=source_id,
            formal_role=requirement.formal_role.value,
            requested_item_count=0,
            maximum_requested_bytes=0,
            ready_for_owner_scope_review=False,
            blocker_codes=("contingent_source_not_resource_bound",),
        )
    blockers = ["task_data_not_acquired"]
    if proposal.kind is SourceProposalKind.CONSTRUCTION_SCREEN:
        blockers.append("natural_cases_and_human_labels_not_curated")
    elif proposal.kind is SourceProposalKind.ACQUIRED_METADATA_INVENTORY:
        blockers.append("runtime_assets_not_qualified")
    return ActivationTaskStatus(
        source_id=source_id,
        formal_role=requirement.formal_role.value,
        proposal_kind=proposal.kind,
        requested_item_count=proposal.requested_item_count,
        maximum_requested_bytes=proposal.maximum_requested_bytes,
        ready_for_owner_scope_review=proposal.ready_for_scope_review,
        blocker_codes=tuple(blockers),
    )


def _system_status(system_id: str, proposal: MethodProposalStatus) -> ActivationSystemStatus:
    blockers = [*proposal.resource_gate_blockers, *proposal.unresolved_requirements]
    if not blockers:
        blockers.append("adapter_preflight_not_completed")
    return ActivationSystemStatus(
        system_id=system_id,
        proposal_viable=proposal.proposal_viable,
        adapter_implementation_ready=proposal.ready_for_adapter_implementation,
        upstream_preflight_ready=proposal.ready_for_upstream_preflight,
        blocker_codes=tuple(dict.fromkeys(blockers)),
    )


def _model_candidate(
    resource: ComputeResourceDefinition,
    binding: ProjectResourceBindingEntry | None,
    *,
    qualification: ApiIdentityCandidateQualification | None = None,
) -> ActivationModelCandidateStatus:
    if not isinstance(resource, ApiModelDefinition):
        raise ValueError("primary model candidates must be API model resources")
    if binding is None or binding.expected_kind is not ResourceKind.API_MODEL:
        raise ValueError("primary model candidate lacks a project API binding")
    role = binding.role
    if role not in {"primary-api-candidate", "robustness-api-candidate"}:
        raise ValueError("primary model candidates require an explicit candidate role")
    if qualification is None:
        blockers: list[str] = []
        if resource.rolling_alias:
            blockers.append("stable_revision_not_pinned")
        if resource.availability is not ObservationStatus.VERIFIED:
            blockers.append("authenticated_identity_not_verified")
        if resource.pricing is None or resource.pricing.status is not ObservationStatus.VERIFIED:
            blockers.append("pricing_ceiling_not_verified")
        return ActivationModelCandidateStatus(
            resource_id=resource.resource_id,
            role=role,
            provider_id=resource.provider_id,
            model_id=resource.model_id,
            declared_revision=resource.model_revision,
            availability=resource.availability,
            rolling_alias=resource.rolling_alias,
            pricing_verified=(
                resource.pricing is not None
                and resource.pricing.status is ObservationStatus.VERIFIED
            ),
            ready_for_conformance_pilot=not blockers,
            blocker_codes=tuple(blockers),
        )
    return ActivationModelCandidateStatus(
        resource_id=resource.resource_id,
        role=role,
        provider_id=resource.provider_id,
        model_id=resource.model_id,
        declared_revision=resource.model_revision,
        availability=resource.availability,
        rolling_alias=resource.rolling_alias,
        pricing_verified=qualification.pricing_verified,
        identity_mode=qualification.identity_mode,
        temporal_identity_protocol_defined=qualification.temporal_protocol_defined,
        authenticated_identity_attested=qualification.authenticated_identity_attested,
        pilot_proposal_ready=qualification.pilot_proposal_ready,
        formal_identity_window_open=qualification.formal_identity_ready,
        ready_for_conformance_pilot=(
            qualification.authenticated_identity_attested and qualification.pricing_verified
        ),
        blocker_codes=qualification.blocker_codes,
    )


def _diagnostic_checkpoint(
    resource: ComputeResourceDefinition,
    binding: ProjectResourceBindingEntry | None,
) -> ActivationDiagnosticCheckpoint:
    if not isinstance(resource, ModelCheckpointDefinition):
        raise ValueError("diagnostic candidates must be checkpoint resources")
    if binding is None or binding.expected_kind is not ResourceKind.MODEL_CHECKPOINT:
        raise ValueError("diagnostic checkpoint lacks a project checkpoint binding")
    return ActivationDiagnosticCheckpoint(
        resource_id=resource.resource_id,
        model_id=resource.model_id,
        declared_revision=resource.model_revision,
        availability=resource.availability,
        role=binding.role,
    )


def _study_status(
    study: ReviewFollowupStudyBinding,
    *,
    task_by_id: dict[str, ActivationTaskStatus],
    system_by_id: dict[str, ActivationSystemStatus],
) -> ActivationStudyStatus:
    task_source_ids = study.task_source_ids
    system_candidate_ids = study.system_candidate_ids
    blockers = [
        *(f"task:{source_id}:not_experiment_ready" for source_id in task_source_ids),
        *(
            f"system:{system_id}:adapter_not_ready"
            for system_id in system_candidate_ids
            if not system_by_id[system_id].adapter_implementation_ready
        ),
        "model:primary_not_selected",
        "statistics:formal_sample_not_powered",
        "human:blinded_review_not_collected",
    ]
    # Resolve every reference before creating a closed study row.
    _ = tuple(task_by_id[item] for item in task_source_ids)
    return ActivationStudyStatus(
        study_id=study.study_id,
        hypothesis=study.hypothesis.value,
        task_source_ids=task_source_ids,
        system_candidate_ids=system_candidate_ids,
        title_critical=study.title_critical,
        blocker_codes=tuple(blockers),
    )


def _verify_binding(root: Path, binding: ActivationFileBinding) -> Path:
    current = root
    for part in PurePosixPath(binding.path).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"review activation binding is a symlink: {binding.path}")
    resolved = current.resolve(strict=True)
    resolved.relative_to(root)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError(f"review activation binding is not bounded: {binding.path}")
    if hashlib.sha256(resolved.read_bytes()).hexdigest() != binding.file_sha256:
        raise ValueError(f"review activation binding hash differs: {binding.path}")
    return resolved


def _activation_hash_payload(value: ProjectReviewFollowupActivation) -> dict[str, object]:
    """Preserve hashes of already-published v1.0 activation records."""

    payload = value.model_dump(mode="json", exclude={"activation_sha256"})
    if value.schema_version == "1.0":
        for field in (
            "model_identity_protocol_id",
            "model_identity_protocol_file_sha256",
            "model_identity_protocol_semantic_sha256",
            "ready_for_model_pilot_proposal",
        ):
            payload.pop(field, None)
        for candidate in payload["primary_model_candidates"]:
            for field in (
                "identity_mode",
                "temporal_identity_protocol_defined",
                "authenticated_identity_attested",
                "pilot_proposal_ready",
                "formal_identity_window_open",
            ):
                candidate.pop(field, None)
    return payload


def _require_git_bound_inputs(
    source_commit: str,
    manifest: ReviewFollowupActivationManifestInspection,
    workspace_root: Path,
) -> None:
    root = workspace_root.resolve(strict=True)
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("review activation source commit is unavailable") from exc
    review_path = root.joinpath(
        *PurePosixPath(manifest.manifest.evidence_review_package.path).parts
    )
    review_package = load_evidence_review_package(review_path).package
    review_children = [
        review_package.evidence_program.path,
        review_package.resource_corpus.path,
        *(item.path for item in review_package.source_proposals),
        *(item.path for item in review_package.method_proposals),
    ]
    catalog_path = root.joinpath(*PurePosixPath(manifest.manifest.compute_catalog.path).parts)
    catalog = load_compute_resource_catalog(catalog_path)
    catalog_children = [catalog_path.parent / item for item in catalog.component_file_sha256]
    paths = [
        manifest.path,
        *(
            root.joinpath(*PurePosixPath(binding.path).parts)
            for binding in (
                manifest.manifest.evidence_review_package,
                manifest.manifest.compute_catalog,
                manifest.manifest.project_resource_binding,
            )
        ),
        root / "src/scitaste/review/activation.py",
        root / "src/scitaste/evaluation/model_identity.py",
        *(root.joinpath(*PurePosixPath(item).parts) for item in review_children),
        *catalog_children,
    ]
    if manifest.manifest.model_identity_protocol is not None:
        paths.append(
            root.joinpath(*PurePosixPath(manifest.manifest.model_identity_protocol.path).parts)
        )
    for path in dict.fromkeys(paths):
        try:
            locator = path.resolve(strict=True).relative_to(root).as_posix()
            observed = subprocess.run(
                ["git", "show", f"{source_commit}:{locator}"],
                cwd=root,
                check=True,
                capture_output=True,
                timeout=10,
            ).stdout
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise ValueError(f"review activation source commit lacks {path}") from exc
        if observed != path.read_bytes():
            raise ValueError(f"review activation source commit has different bytes for {locator}")


def _contained_regular_file(project_root: Path, locator: str) -> Path:
    root = project_root.resolve(strict=True)
    current = root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("project review activation files must not use symlinks")
    resolved = current.resolve(strict=True)
    resolved.relative_to(root)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("project review activation file must be bounded")
    return resolved


def _json_bytes(value: BaseModel) -> bytes:
    return (value.model_dump_json(indent=2) + "\n").encode("utf-8")


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


__all__ = [
    "ActivationDiagnosticCheckpoint",
    "ActivationFileBinding",
    "ActivationModelCandidateStatus",
    "ActivationOwnerDecision",
    "ActivationReadiness",
    "ActivationStudyStatus",
    "ActivationSystemStatus",
    "ActivationTaskStatus",
    "PreparedProjectReviewFollowupActivation",
    "ProjectReviewFollowupActivation",
    "ReviewFollowupActivationManifest",
    "ReviewFollowupActivationManifestInspection",
    "compile_review_followup_activation",
    "inspect_project_review_followup_activation",
    "load_review_followup_activation_manifest",
    "prepare_project_review_followup_activation",
    "publish_project_review_followup_activation",
]

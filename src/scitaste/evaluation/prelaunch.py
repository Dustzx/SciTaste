"""Hash-bound, no-run resource contracts for API and GPU evaluation lanes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.resources import (
    ExternalResourceCorpus,
    ResourceUse,
    evaluate_resource_feasibility,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MANIFEST_BYTES = 1_048_576


class ReadinessStatus(StrEnum):
    VERIFIED = "verified"
    PENDING = "pending"
    BLOCKED = "blocked"


class SystemRole(StrEnum):
    SCITASTE = "scitaste"
    METHOD_COMPARATOR = "method_comparator"
    CONTROL = "control"
    ABLATION = "ablation"


class ExecutionLaneKind(StrEnum):
    API_ONLY = "api_only"
    GPU = "gpu"


class ScientificLaneRole(StrEnum):
    MATCHED_BACKBONE = "matched_backbone"
    SMALL_MODEL_ROBUSTNESS = "small_model_robustness"
    EXPERIMENT_WORKLOAD = "experiment_workload"


class PrelaunchSystem(BaseModel):
    model_config = _CONFIG

    system_id: str = Field(pattern=_ID)
    role: SystemRole
    implementation_ref: str | None = Field(default=None, max_length=1_000)
    external_resource_id: str | None = Field(default=None, pattern=_ID)
    availability: ReadinessStatus
    real_implementation: bool

    @model_validator(mode="after")
    def external_methods_have_resource_identity(self) -> PrelaunchSystem:
        if self.role is SystemRole.METHOD_COMPARATOR and self.external_resource_id is None:
            raise ValueError("method comparators require an external system resource ID")
        if self.role is not SystemRole.METHOD_COMPARATOR and self.external_resource_id is not None:
            raise ValueError("only method comparators may reference external system resources")
        if self.availability is ReadinessStatus.VERIFIED and (
            not self.real_implementation or self.implementation_ref is None
        ):
            raise ValueError("verified systems require a real pinned implementation")
        return self


class PrelaunchTask(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    benchmark_resource_id: str = Field(pattern=_ID)
    split: str = Field(min_length=1, max_length=200)
    selected_asset_manifest: str | None = Field(default=None, max_length=1_000)
    asset_manifest_sha256: str | None = Field(default=None, pattern=_SHA256)
    license_status: ReadinessStatus
    asset_status: ReadinessStatus
    held_out: bool
    source_group_disjoint: bool

    @model_validator(mode="after")
    def verified_assets_are_pinned(self) -> PrelaunchTask:
        if self.asset_status is ReadinessStatus.VERIFIED and (
            self.selected_asset_manifest is None or self.asset_manifest_sha256 is None
        ):
            raise ValueError("verified task assets require a manifest locator and SHA-256")
        return self


class ProviderPricing(BaseModel):
    model_config = _CONFIG

    currency: Literal["USD", "CNY"]
    as_of: date
    source_url: str = Field(min_length=1, max_length=2_000)
    input_cache_hit_per_million: float | None = Field(default=None, ge=0)
    input_cache_miss_per_million: float = Field(ge=0)
    output_per_million: float = Field(ge=0)
    status: ReadinessStatus


class ApiModelResource(BaseModel):
    model_config = _CONFIG

    provider_id: str = Field(pattern=_ID)
    endpoint: str = Field(min_length=1, max_length=2_000)
    interface: Literal["openai-chat-completions", "openai-responses"]
    model_id: str = Field(min_length=1, max_length=200)
    model_revision: str | None = Field(default=None, max_length=200)
    rolling_alias: bool
    identity_source_url: str = Field(min_length=1, max_length=2_000)
    identity_status: ReadinessStatus
    api_key_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,100}$")
    max_input_tokens_per_call: int = Field(gt=0)
    max_output_tokens_per_call: int = Field(gt=0)
    max_requests: int = Field(gt=0)
    max_total_tokens: int = Field(gt=0)
    max_cost: float = Field(gt=0)
    pricing: ProviderPricing

    @model_validator(mode="after")
    def verified_identity_has_exact_revision(self) -> ApiModelResource:
        if self.identity_status is ReadinessStatus.VERIFIED and self.model_revision is None:
            raise ValueError("verified API model identity requires an observed revision")
        if not self.endpoint.startswith("https://"):
            raise ValueError("API endpoint must use HTTPS")
        return self


class GpuModelResource(BaseModel):
    model_config = _CONFIG

    host_alias: str = Field(pattern=_ID)
    device_count: int = Field(gt=0, le=64)
    device_name: str = Field(min_length=1, max_length=200)
    minimum_memory_mb_per_device: int = Field(gt=0)
    checkpoint_id: str = Field(pattern=_ID)
    checkpoint_source_path: str = Field(min_length=1, max_length=2_000)
    checkpoint_sha256: str = Field(pattern=_SHA256)
    checkpoint_bytes: int = Field(gt=0)
    license_identifier: str = Field(min_length=1, max_length=200)
    local_preflight_status: ReadinessStatus
    remote_inventory_status: ReadinessStatus
    remote_checkpoint_status: ReadinessStatus
    max_gpu_hours: float = Field(gt=0)
    max_storage_bytes: int = Field(gt=0)
    network_access: Literal[False] = False


class ExecutionLane(BaseModel):
    model_config = _CONFIG

    lane_id: str = Field(pattern=_ID)
    kind: ExecutionLaneKind
    scientific_role: ScientificLaneRole
    system_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    task_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    seeds: tuple[int, ...] = Field(min_length=1, max_length=100)
    repetitions: int = Field(default=1, gt=0, le=100)
    planned_cells: int = Field(gt=0)
    api_model: ApiModelResource | None = None
    gpu_resource: GpuModelResource | None = None

    @model_validator(mode="after")
    def lane_is_closed(self) -> ExecutionLane:
        if len(set(self.system_ids)) != len(self.system_ids):
            raise ValueError("lane system IDs must be unique")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("lane task IDs must be unique")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("lane seeds must be unique")
        if self.kind is ExecutionLaneKind.API_ONLY:
            if self.api_model is None or self.gpu_resource is not None:
                raise ValueError("API-only lanes require only api_model")
        elif self.gpu_resource is None or self.api_model is not None:
            raise ValueError("GPU lanes require only gpu_resource")
        expected = len(self.system_ids) * len(self.task_ids) * len(self.seeds) * self.repetitions
        if self.planned_cells != expected:
            raise ValueError(f"planned_cells must equal the closed lane matrix ({expected})")
        return self


class HumanReviewResource(BaseModel):
    model_config = _CONFIG

    required: bool
    minimum_reviewers_per_artifact: int = Field(ge=0, le=20)
    condition_blinded: bool
    conflict_check_required: bool
    recruitment_status: ReadinessStatus
    rubric_status: ReadinessStatus
    adjudication_status: ReadinessStatus
    maximum_reviewer_hours: float = Field(ge=0)

    @model_validator(mode="after")
    def required_review_is_real(self) -> HumanReviewResource:
        if self.required and (
            self.minimum_reviewers_per_artifact < 2
            or not self.condition_blinded
            or not self.conflict_check_required
        ):
            raise ValueError("formal human review requires two blinded, conflict-checked reviewers")
        return self


class RetentionContract(BaseModel):
    model_config = _CONFIG

    output_root: str = Field(min_length=1, max_length=1_000)
    archive_root: str = Field(min_length=1, max_length=1_000)
    maximum_output_bytes: int = Field(gt=0)
    retain_raw_provider_responses: bool
    retain_failed_runs: Literal[True] = True
    secrets_forbidden: Literal[True] = True


class PrelaunchApproval(BaseModel):
    model_config = _CONFIG

    approved: bool = False
    approved_proposal_sha256: str | None = Field(default=None, pattern=_SHA256)
    approved_by: str | None = Field(default=None, max_length=200)
    approved_at: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def approval_is_complete_or_empty(self) -> PrelaunchApproval:
        values = (self.approved_proposal_sha256, self.approved_by, self.approved_at)
        if self.approved and not all(values):
            raise ValueError("approval requires proposal hash, author, and timestamp")
        if not self.approved and any(values):
            raise ValueError("an unapproved manifest cannot contain approval metadata")
        return self


class ExperimentPrelaunchManifest(BaseModel):
    """One provider family and closed resource matrix; never a launch command."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    manifest_id: str = Field(pattern=_ID)
    protocol_id: str = Field(pattern=_ID)
    protocol_version: str = Field(min_length=1, max_length=100)
    study_scope: Literal["pilot", "formal", "robustness"]
    scientific_question: str = Field(min_length=1, max_length=4_000)
    claim_allowed: str = Field(min_length=1, max_length=4_000)
    claim_forbidden: str = Field(min_length=1, max_length=4_000)
    source_commit: str | None = Field(default=None, pattern=_COMMIT)
    require_clean_tree: Literal[True] = True
    resource_corpus_sha256: str = Field(pattern=_SHA256)
    systems: tuple[PrelaunchSystem, ...] = Field(min_length=2, max_length=30)
    tasks: tuple[PrelaunchTask, ...] = Field(min_length=1, max_length=500)
    lanes: tuple[ExecutionLane, ...] = Field(min_length=1, max_length=10)
    human_review: HumanReviewResource
    retention: RetentionContract
    launch_order: tuple[str, ...] = Field(min_length=1, max_length=30)
    stop_rules: tuple[str, ...] = Field(min_length=1, max_length=30)
    approval: PrelaunchApproval = Field(default_factory=PrelaunchApproval)

    @model_validator(mode="after")
    def references_and_provider_family_are_closed(self) -> ExperimentPrelaunchManifest:
        system_ids = [item.system_id for item in self.systems]
        task_ids = [item.task_id for item in self.tasks]
        lane_ids = [item.lane_id for item in self.lanes]
        for values, label in (
            (system_ids, "system"),
            (task_ids, "task"),
            (lane_ids, "lane"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"prelaunch {label} IDs must be unique")
        known_systems = set(system_ids)
        known_tasks = set(task_ids)
        providers: set[str] = set()
        for lane in self.lanes:
            unknown_systems = set(lane.system_ids) - known_systems
            unknown_tasks = set(lane.task_ids) - known_tasks
            if unknown_systems or unknown_tasks:
                raise ValueError(
                    f"lane has unknown references: systems={sorted(unknown_systems)}, "
                    f"tasks={sorted(unknown_tasks)}"
                )
            if lane.api_model is not None:
                providers.add(lane.api_model.provider_id)
        if len(providers) > 1:
            raise ValueError("provider alternatives require separate prelaunch manifests")
        if tuple(lane_ids) != self.launch_order:
            raise ValueError("launch_order must name every lane exactly once in declared order")
        return self

    @property
    def proposal_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"approval"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class PrelaunchManifestInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: ExperimentPrelaunchManifest


class PrelaunchBlocker(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class PrelaunchGateReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    manifest_id: str
    protocol_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    observed_source_commit: str | None = Field(default=None, pattern=_COMMIT)
    source_tree_clean: bool | None = None
    planned_cells: int = Field(gt=0)
    ready_for_author_approval: bool
    execution_authorized: bool
    blockers: tuple[PrelaunchBlocker, ...]
    authorization_blockers: tuple[PrelaunchBlocker, ...]
    no_execution_performed: Literal[True] = True


def load_prelaunch_manifest(path: str | Path) -> PrelaunchManifestInspection:
    """Load bounded YAML without following a top-level symlink."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("prelaunch manifest must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("prelaunch manifest must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("prelaunch manifest must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("prelaunch manifest must contain a YAML mapping")
    return PrelaunchManifestInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=ExperimentPrelaunchManifest.model_validate(payload),
    )


def inspect_prelaunch_manifest(
    manifest: ExperimentPrelaunchManifest,
    resource_corpus: ExternalResourceCorpus,
    *,
    observed_source_commit: str | None = None,
    source_tree_clean: bool | None = None,
) -> PrelaunchGateReport:
    """Evaluate readiness and approval without accessing providers or GPUs."""

    blockers: list[PrelaunchBlocker] = []
    if manifest.source_commit is None:
        _block(blockers, "source_commit_pending", "the executable Git commit is not frozen")
    if observed_source_commit is None:
        _block(blockers, "source_commit_unobserved", "the current Git commit was not inspected")
    elif manifest.source_commit != observed_source_commit:
        _block(
            blockers,
            "source_commit_mismatch",
            "the current Git commit differs from the executable commit in the manifest",
        )
    if source_tree_clean is None:
        _block(blockers, "source_tree_unobserved", "Git tree cleanliness was not inspected")
    elif manifest.require_clean_tree and not source_tree_clean:
        _block(blockers, "source_tree_dirty", "the executable Git tree is not clean")
    if manifest.resource_corpus_sha256 != resource_corpus.semantic_sha256:
        _block(blockers, "resource_corpus_drift", "resource corpus hash differs from the manifest")

    for system in manifest.systems:
        if system.availability is not ReadinessStatus.VERIFIED:
            _block(
                blockers,
                f"system_{system.availability.value}:{system.system_id}",
                f"system {system.system_id} is {system.availability.value}",
            )
        if system.external_resource_id is not None:
            report = evaluate_resource_feasibility(
                resource_corpus,
                system.external_resource_id,
                ResourceUse.COMPARISON_SYSTEM,
            )
            for code in report.blocker_codes:
                _block(
                    blockers,
                    f"system_resource:{system.system_id}:{code}",
                    f"system {system.system_id} failed resource gate {code}",
                )

    for task in manifest.tasks:
        if not task.held_out or not task.source_group_disjoint:
            _block(
                blockers,
                f"task_leakage:{task.task_id}",
                f"task {task.task_id} is not held-out and source-group disjoint",
            )
        for label, status in (
            ("license", task.license_status),
            ("assets", task.asset_status),
        ):
            if status is not ReadinessStatus.VERIFIED:
                _block(
                    blockers,
                    f"task_{label}_{status.value}:{task.task_id}",
                    f"task {task.task_id} {label} status is {status.value}",
                )
        report = evaluate_resource_feasibility(
            resource_corpus,
            task.benchmark_resource_id,
            ResourceUse.TASK_SOURCE,
        )
        for code in report.blocker_codes:
            _block(
                blockers,
                f"task_resource:{task.task_id}:{code}",
                f"task {task.task_id} failed resource gate {code}",
            )

    for lane in manifest.lanes:
        if lane.api_model is not None:
            if lane.api_model.identity_status is not ReadinessStatus.VERIFIED:
                _block(
                    blockers,
                    f"api_identity_{lane.api_model.identity_status.value}:{lane.lane_id}",
                    f"API model identity is {lane.api_model.identity_status.value}",
                )
            if lane.api_model.pricing.status is not ReadinessStatus.VERIFIED:
                _block(
                    blockers,
                    f"api_pricing_{lane.api_model.pricing.status.value}:{lane.lane_id}",
                    f"API pricing is {lane.api_model.pricing.status.value}",
                )
        if lane.gpu_resource is not None:
            for label, status in (
                ("local_preflight", lane.gpu_resource.local_preflight_status),
                ("remote_inventory", lane.gpu_resource.remote_inventory_status),
                ("remote_checkpoint", lane.gpu_resource.remote_checkpoint_status),
            ):
                if status is not ReadinessStatus.VERIFIED:
                    _block(
                        blockers,
                        f"gpu_{label}_{status.value}:{lane.lane_id}",
                        f"GPU {label} status is {status.value}",
                    )

    review = manifest.human_review
    if review.required:
        for label, status in (
            ("recruitment", review.recruitment_status),
            ("rubric", review.rubric_status),
            ("adjudication", review.adjudication_status),
        ):
            if status is not ReadinessStatus.VERIFIED:
                _block(
                    blockers,
                    f"human_review_{label}_{status.value}",
                    f"human-review {label} status is {status.value}",
                )

    ready = not blockers
    authorization: list[PrelaunchBlocker] = []
    if not ready:
        _block(
            authorization,
            "readiness_gates_failed",
            "resource readiness must pass before approval can authorize execution",
        )
    approval = manifest.approval
    if not approval.approved:
        _block(
            authorization,
            "author_approval_required",
            "the project owner has not approved this exact proposal hash",
        )
    elif approval.approved_proposal_sha256 != manifest.proposal_sha256:
        _block(
            authorization,
            "approval_hash_mismatch",
            "approval targets different proposal bytes",
        )
    return PrelaunchGateReport(
        manifest_id=manifest.manifest_id,
        protocol_id=manifest.protocol_id,
        proposal_sha256=manifest.proposal_sha256,
        observed_source_commit=observed_source_commit,
        source_tree_clean=source_tree_clean,
        planned_cells=sum(lane.planned_cells for lane in manifest.lanes),
        ready_for_author_approval=ready,
        execution_authorized=ready and not authorization,
        blockers=tuple(blockers),
        authorization_blockers=tuple(authorization),
        no_execution_performed=True,
    )


def inspect_git_source(path: str | Path) -> tuple[str, bool]:
    """Read one repository identity with bounded, shell-free Git calls."""

    candidate = Path(path).resolve(strict=True)
    cwd = candidate if candidate.is_dir() else candidate.parent
    commit = _git(cwd, "rev-parse", "HEAD")
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValueError("Git returned an invalid source commit")
    status = _git(cwd, "status", "--porcelain=v1", "--untracked-files=all")
    return commit, not bool(status)


def _block(blockers: list[PrelaunchBlocker], code: str, message: str) -> None:
    blockers.append(PrelaunchBlocker(code=code, message=message))


def _git(cwd: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("unable to inspect the Git source repository") from exc
    if len(result.stdout) > 1_048_576:
        raise ValueError("Git source inspection exceeded its output limit")
    return result.stdout.strip()


__all__ = [
    "ApiModelResource",
    "ExecutionLane",
    "ExecutionLaneKind",
    "ExperimentPrelaunchManifest",
    "GpuModelResource",
    "HumanReviewResource",
    "PrelaunchApproval",
    "PrelaunchBlocker",
    "PrelaunchGateReport",
    "PrelaunchManifestInspection",
    "PrelaunchSystem",
    "PrelaunchTask",
    "ProviderPricing",
    "ReadinessStatus",
    "RetentionContract",
    "ScientificLaneRole",
    "SystemRole",
    "inspect_git_source",
    "inspect_prelaunch_manifest",
    "load_prelaunch_manifest",
]

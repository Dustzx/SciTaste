"""No-run qualification for executable objective-progress benchmark candidates."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.resources import (
    EvaluationResourceKind,
    ResourceGateName,
    ResourceGateStatus,
    load_external_resource_corpus,
)
from scitaste.resources import (
    ApiModelDefinition,
    GpuHostDefinition,
    ObservationStatus,
    load_compute_resource_catalog,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_BYTES = 1_048_576
_REQUIRED_CONDITIONS = frozenset(
    {
        "scitaste-native-base",
        "scitaste-native-full",
        "scitaste-native-mismatched-taste",
    }
)


class CandidateEvidenceStatus(StrEnum):
    """Four-state evidence status; ``not_required`` is never implicit readiness."""

    VERIFIED = "verified"
    PENDING = "pending"
    BLOCKED = "blocked"
    NOT_REQUIRED = "not_required"


class CandidateDataAccess(StrEnum):
    PUBLIC_REGISTRY = "public_registry"
    PUBLIC_DIRECT = "public_direct"
    MANUAL_TERMS = "manual_terms"
    AUTHENTICATED_PLATFORM = "authenticated_platform"


class CandidateTestMode(StrEnum):
    LOCAL_HELD_OUT = "local_held_out"
    LOCAL_AFTER_AUTHENTICATED_ACQUISITION = "local_after_authenticated_acquisition"
    EXTERNAL_MANUAL_SUBMISSION = "external_manual_submission"


class CandidateMetricDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class CandidateTask(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    paper_task_name: str = Field(min_length=1, max_length=300)
    source_group: str = Field(pattern=_ID)
    repository_path: str = Field(min_length=1, max_length=500)
    source_refs: tuple[str, ...] = Field(min_length=1, max_length=40)
    metric: str = Field(min_length=1, max_length=300)
    metric_direction: CandidateMetricDirection
    paper_test_runtime_hours: float = Field(gt=0, le=24)
    paper_gpu_memory_mb: int = Field(gt=0, le=200_000)
    data_access: CandidateDataAccess
    test_mode: CandidateTestMode
    input_license_status: CandidateEvidenceStatus
    task_assets_status: CandidateEvidenceStatus
    environment_status: CandidateEvidenceStatus
    authentication_status: CandidateEvidenceStatus
    held_out_evaluation_status: CandidateEvidenceStatus
    qualification_blockers: tuple[str, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def paths_statuses_and_blockers_are_consistent(self) -> CandidateTask:
        path = PurePosixPath(self.repository_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("candidate task repository path must be relative and contained")
        if len(self.source_refs) != len(set(self.source_refs)) or any(
            not item.startswith("https://") for item in self.source_refs
        ):
            raise ValueError("candidate task source references must be unique HTTPS URLs")
        if len(self.qualification_blockers) != len(set(self.qualification_blockers)):
            raise ValueError("candidate task qualification blockers must be unique")
        statuses = self.evidence_statuses
        incomplete = any(
            item in {CandidateEvidenceStatus.PENDING, CandidateEvidenceStatus.BLOCKED}
            for item in statuses
        )
        if incomplete != bool(self.qualification_blockers):
            raise ValueError("candidate task qualification blockers must match evidence status")
        return self

    @property
    def evidence_statuses(self) -> tuple[CandidateEvidenceStatus, ...]:
        return (
            self.input_license_status,
            self.task_assets_status,
            self.environment_status,
            self.authentication_status,
            self.held_out_evaluation_status,
        )


class ExcludedCandidateTask(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    paper_task_name: str = Field(min_length=1, max_length=300)
    source_group: str = Field(pattern=_ID)
    repository_path: str = Field(min_length=1, max_length=500)
    paper_gpu_memory_mb: int = Field(gt=0, le=200_000)
    exclusion_code: Literal["single-device-memory-exceeds-current-host"]
    exclusion_reason: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def repository_path_is_contained(self) -> ExcludedCandidateTask:
        path = PurePosixPath(self.repository_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("excluded task repository path must be relative and contained")
        return self


class CandidateExecutionBinding(BaseModel):
    model_config = _CONFIG

    benchmark_corpus_id: str = Field(pattern=_ID)
    benchmark_resource_id: str = Field(pattern=_ID)
    repository_commit: str = Field(pattern=_COMMIT)
    compute_catalog_id: str = Field(pattern=_ID)
    compute_catalog_semantic_sha256: str = Field(pattern=_SHA256)
    agent_api_resource_id: str = Field(pattern=_ID)
    gpu_resource_id: str = Field(pattern=_ID)
    devices_per_cell: Literal[1] = 1


class CandidateStudyPlan(BaseModel):
    model_config = _CONFIG

    condition_ids: tuple[str, ...] = Field(min_length=3, max_length=3)
    seeds: tuple[int, ...] = Field(min_length=3, max_length=20)
    planned_cells: int = Field(gt=0)
    per_cell_agent_hours: float = Field(gt=0, le=24)
    planned_gpu_hours: float = Field(gt=0)
    formal_gpu_hour_cap: float = Field(gt=0)
    sampling_unit: Literal["task"] = "task"
    evidence_role: Literal["transfer-and-mechanism"] = "transfer-and-mechanism"
    task_level_population_claim_authorized: Literal[False] = False

    @model_validator(mode="after")
    def contrast_and_budget_are_exact(self) -> CandidateStudyPlan:
        if set(self.condition_ids) != _REQUIRED_CONDITIONS:
            raise ValueError("candidate study requires Base, Full, and mismatched-Taste conditions")
        if len(set(self.condition_ids)) != len(self.condition_ids):
            raise ValueError("candidate study condition IDs must be unique")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("candidate study seeds must be unique")
        if self.planned_gpu_hours > self.formal_gpu_hour_cap:
            raise ValueError("candidate study exceeds the formal GPU-hour cap")
        return self


class ExecutableBenchmarkCandidateManifest(BaseModel):
    """A reviewable scope; the manifest can never authorize acquisition or work."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str = Field(pattern=_ID)
    authorization_scope: Literal["metadata-only-no-download-no-execution"]
    binding: CandidateExecutionBinding
    accepted_task_ids: tuple[str, ...] = Field(min_length=2, max_length=100)
    selected_tasks: tuple[CandidateTask, ...] = Field(min_length=2, max_length=100)
    excluded_tasks: tuple[ExcludedCandidateTask, ...] = Field(default=(), max_length=100)
    study_plan: CandidateStudyPlan
    owner_preflight_approval: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def task_partition_and_arithmetic_are_exact(self) -> ExecutableBenchmarkCandidateManifest:
        accepted = list(self.accepted_task_ids)
        selected = [item.task_id for item in self.selected_tasks]
        excluded = [item.task_id for item in self.excluded_tasks]
        if len(accepted) != len(set(accepted)):
            raise ValueError("accepted candidate task IDs must be unique")
        if len(selected) != len(set(selected)) or len(excluded) != len(set(excluded)):
            raise ValueError("selected and excluded candidate task IDs must be unique")
        if set(selected) & set(excluded) or set(selected) | set(excluded) != set(accepted):
            raise ValueError("selected and excluded tasks must partition the accepted task set")
        source_groups = [
            *(item.source_group for item in self.selected_tasks),
            *(item.source_group for item in self.excluded_tasks),
        ]
        if len(source_groups) != len(set(source_groups)):
            raise ValueError("accepted candidate source groups must be unique")
        expected_cells = (
            len(self.selected_tasks)
            * len(self.study_plan.condition_ids)
            * len(self.study_plan.seeds)
        )
        if self.study_plan.planned_cells != expected_cells:
            raise ValueError("planned cells differ from tasks x conditions x seeds")
        expected_hours = expected_cells * self.study_plan.per_cell_agent_hours
        if abs(self.study_plan.planned_gpu_hours - expected_hours) > 1e-9:
            raise ValueError("planned GPU hours differ from cell count x per-cell hours")
        return self

    @computed_field
    @property
    def proposal_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"proposal_sha256"})
        return _canonical_sha256(payload)


class ExecutableCandidateInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: ExecutableBenchmarkCandidateManifest


class CandidateFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9:_-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)
    task_id: str | None = Field(default=None, pattern=_ID)


class CandidateTaskQualification(BaseModel):
    model_config = _CONFIG

    task_id: str
    fits_current_gpu_memory: bool
    legal_access_ready: bool
    assets_ready: bool
    environment_ready: bool
    authentication_ready: bool
    held_out_evaluation_ready: bool
    first_preflight_candidate: bool
    ready_for_local_preflight: bool
    ready_for_experiment: bool
    blockers: tuple[str, ...]


class ExecutableCandidateReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    manifest_file_sha256: str = Field(pattern=_SHA256)
    benchmark_corpus_file_sha256: str = Field(pattern=_SHA256)
    benchmark_corpus_semantic_sha256: str = Field(pattern=_SHA256)
    compute_catalog_file_sha256: str = Field(pattern=_SHA256)
    compute_catalog_semantic_sha256: str = Field(pattern=_SHA256)
    accepted_task_count: int = Field(gt=0)
    selected_task_count: int = Field(gt=0)
    excluded_task_count: int = Field(ge=0)
    selected_task_ids: tuple[str, ...]
    excluded_task_ids: tuple[str, ...]
    first_preflight_candidate_ids: tuple[str, ...]
    planned_cells: int = Field(gt=0)
    planned_gpu_hours: float = Field(gt=0)
    formal_gpu_hour_cap: float = Field(gt=0)
    task_qualifications: tuple[CandidateTaskQualification, ...]
    metadata_review_ready: bool
    acquisition_request_ready: Literal[False] = False
    local_preflight_ready: bool
    experiment_ready: bool
    requires_additional_48gb_single_device_resource: bool
    integrity_blockers: tuple[CandidateFinding, ...]
    qualification_blockers: tuple[CandidateFinding, ...]
    pending_qualifications: tuple[CandidateFinding, ...]
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False
    external_action_performed: Literal[False] = False

    @computed_field
    @property
    def report_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        return _canonical_sha256(payload)


def load_executable_candidate_manifest(
    path: str | Path,
) -> ExecutableCandidateInspection:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("executable candidate manifest must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_BYTES:
        raise ValueError("executable candidate manifest must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("executable candidate manifest must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("executable candidate manifest must contain a YAML mapping")
    return ExecutableCandidateInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=ExecutableBenchmarkCandidateManifest.model_validate(payload),
    )


def inspect_executable_candidate(
    inspection: ExecutableCandidateInspection,
    *,
    resource_corpus_path: str | Path,
    compute_catalog_path: str | Path,
) -> ExecutableCandidateReport:
    """Cross-check the candidate against immutable benchmark and compute identities."""

    manifest = inspection.manifest
    corpus = load_external_resource_corpus(resource_corpus_path)
    compute = load_compute_resource_catalog(compute_catalog_path)
    integrity: list[CandidateFinding] = []
    blocked: list[CandidateFinding] = []
    pending: list[CandidateFinding] = []

    if corpus.corpus.corpus_id != manifest.binding.benchmark_corpus_id:
        _add(integrity, "benchmark-corpus-id-mismatch", "benchmark corpus ID differs")
    resources = {item.resource_id: item for item in corpus.corpus.resources}
    benchmark = resources.get(manifest.binding.benchmark_resource_id)
    if benchmark is None:
        _add(integrity, "benchmark-resource-missing", "benchmark resource is absent")
    else:
        if benchmark.resource_kind is not EvaluationResourceKind.BENCHMARK:
            _add(integrity, "benchmark-resource-kind-mismatch", "resource is not a benchmark")
        if benchmark.repository_commit != manifest.binding.repository_commit:
            _add(integrity, "benchmark-repository-pin-mismatch", "repository commit differs")
        if (
            benchmark.code_license is None
            or benchmark.gates.get(ResourceGateName.CODE_LICENSE) is None
        ):
            _add(integrity, "benchmark-code-license-missing", "code license is not recorded")
        elif (
            benchmark.gates[ResourceGateName.CODE_LICENSE].status is not ResourceGateStatus.VERIFIED
        ):
            _add(blocked, "benchmark-code-license-blocked", "code license gate is blocked")
        for gate_name in (
            ResourceGateName.OFFICIAL_IDENTITY,
            ResourceGateName.REPOSITORY_PIN,
            ResourceGateName.PUBLICATION_IDENTITY,
            ResourceGateName.DATASET_PIN,
            ResourceGateName.SOURCE_GROUPS,
            ResourceGateName.SELECTED_TASK_MANIFEST,
        ):
            decision = benchmark.gates.get(gate_name)
            if decision is None:
                _add(
                    integrity,
                    f"benchmark-gate-missing:{gate_name.value}",
                    f"benchmark metadata gate {gate_name.value} is absent",
                )
            elif decision.status is not ResourceGateStatus.VERIFIED:
                _add(
                    integrity,
                    f"benchmark-gate-not-verified:{gate_name.value}",
                    f"benchmark metadata gate {gate_name.value} is not verified",
                )
        selection_gate = benchmark.gates.get(ResourceGateName.SELECTED_TASK_MANIFEST)
        if selection_gate is not None and inspection.file_sha256 not in selection_gate.evidence:
            _add(
                integrity,
                "candidate-file-hash-not-bound-by-resource",
                "benchmark resource evidence does not bind this candidate manifest file",
            )

    if compute.catalog.catalog_id != manifest.binding.compute_catalog_id:
        _add(integrity, "compute-catalog-id-mismatch", "compute catalog ID differs")
    if compute.semantic_sha256 != manifest.binding.compute_catalog_semantic_sha256:
        _add(integrity, "compute-catalog-semantic-mismatch", "compute catalog semantics differ")

    try:
        api_resource = compute.catalog.resource(manifest.binding.agent_api_resource_id)
    except ValueError:
        api_resource = None
        _add(integrity, "agent-api-resource-missing", "agent API resource is absent")
    if api_resource is not None and not isinstance(api_resource, ApiModelDefinition):
        _add(integrity, "agent-api-resource-kind-mismatch", "agent resource is not an API model")

    try:
        gpu_resource = compute.catalog.resource(manifest.binding.gpu_resource_id)
    except ValueError:
        gpu_resource = None
        _add(integrity, "gpu-resource-missing", "GPU resource is absent")
    if gpu_resource is not None and not isinstance(gpu_resource, GpuHostDefinition):
        _add(integrity, "gpu-resource-kind-mismatch", "execution resource is not a GPU host")
        gpu_resource = None

    if api_resource is not None and api_resource.availability is not ObservationStatus.VERIFIED:
        _add(
            pending,
            "agent-api-availability-not-verified",
            f"agent API availability is {api_resource.availability.value}",
        )
    if gpu_resource is not None and gpu_resource.availability is not ObservationStatus.VERIFIED:
        _add(
            pending,
            "gpu-availability-not-verified",
            f"GPU host availability is {gpu_resource.availability.value}",
        )

    capacity_mb = gpu_resource.minimum_memory_mb_per_device if gpu_resource is not None else 0
    qualifications: list[CandidateTaskQualification] = []
    for task in manifest.selected_tasks:
        fits = task.paper_gpu_memory_mb <= capacity_mb
        if not fits:
            _add(
                integrity,
                "selected-task-exceeds-device-memory",
                f"task requires {task.paper_gpu_memory_mb} MB but host guarantees {capacity_mb} MB",
                task.task_id,
            )
        legal = task.input_license_status is CandidateEvidenceStatus.VERIFIED
        assets = task.task_assets_status is CandidateEvidenceStatus.VERIFIED
        environment = task.environment_status is CandidateEvidenceStatus.VERIFIED
        authentication = task.authentication_status in {
            CandidateEvidenceStatus.VERIFIED,
            CandidateEvidenceStatus.NOT_REQUIRED,
        }
        held_out = task.held_out_evaluation_status is CandidateEvidenceStatus.VERIFIED
        first = (
            fits
            and legal
            and authentication
            and task.data_access
            in {CandidateDataAccess.PUBLIC_DIRECT, CandidateDataAccess.PUBLIC_REGISTRY}
            and task.task_assets_status is not CandidateEvidenceStatus.BLOCKED
            and task.environment_status is not CandidateEvidenceStatus.BLOCKED
            and task.held_out_evaluation_status is not CandidateEvidenceStatus.BLOCKED
        )
        ready = fits and legal and assets and environment and authentication and held_out
        qualifications.append(
            CandidateTaskQualification(
                task_id=task.task_id,
                fits_current_gpu_memory=fits,
                legal_access_ready=legal,
                assets_ready=assets,
                environment_ready=environment,
                authentication_ready=authentication,
                held_out_evaluation_ready=held_out,
                first_preflight_candidate=first,
                ready_for_local_preflight=ready,
                ready_for_experiment=ready,
                blockers=task.qualification_blockers,
            )
        )
        for code in task.qualification_blockers:
            target = (
                blocked if CandidateEvidenceStatus.BLOCKED in task.evidence_statuses else pending
            )
            _add(target, code, f"task qualification remains incomplete: {code}", task.task_id)

    requires_48gb = False
    for task in manifest.excluded_tasks:
        if task.paper_gpu_memory_mb <= capacity_mb:
            _add(
                integrity,
                "excluded-task-fits-device-memory",
                "task was excluded for memory but fits the selected host guarantee",
                task.task_id,
            )
        else:
            requires_48gb = requires_48gb or task.paper_gpu_memory_mb >= 48_000

    _add(
        pending,
        "exact-acquisition-allowlist-missing",
        "candidate metadata does not enumerate content-hashed downloadable task assets",
    )
    _add(
        pending,
        "task-level-generalization-limited",
        "four task sampling units support transfer/mechanism evidence, "
        "not a broad population claim",
    )

    all_tasks_ready = bool(qualifications) and all(
        item.ready_for_local_preflight for item in qualifications
    )
    external_resources_ready = (
        isinstance(api_resource, ApiModelDefinition)
        and api_resource.availability is ObservationStatus.VERIFIED
        and isinstance(gpu_resource, GpuHostDefinition)
        and gpu_resource.availability is ObservationStatus.VERIFIED
    )
    metadata_ready = not integrity
    experiment_ready = metadata_ready and not blocked and not pending and all_tasks_ready
    experiment_ready = experiment_ready and external_resources_ready
    return ExecutableCandidateReport(
        candidate_id=manifest.candidate_id,
        proposal_sha256=manifest.proposal_sha256,
        manifest_file_sha256=inspection.file_sha256,
        benchmark_corpus_file_sha256=corpus.file_sha256,
        benchmark_corpus_semantic_sha256=corpus.semantic_sha256,
        compute_catalog_file_sha256=compute.file_sha256,
        compute_catalog_semantic_sha256=compute.semantic_sha256,
        accepted_task_count=len(manifest.accepted_task_ids),
        selected_task_count=len(manifest.selected_tasks),
        excluded_task_count=len(manifest.excluded_tasks),
        selected_task_ids=tuple(item.task_id for item in manifest.selected_tasks),
        excluded_task_ids=tuple(item.task_id for item in manifest.excluded_tasks),
        first_preflight_candidate_ids=tuple(
            item.task_id for item in qualifications if item.first_preflight_candidate
        ),
        planned_cells=manifest.study_plan.planned_cells,
        planned_gpu_hours=manifest.study_plan.planned_gpu_hours,
        formal_gpu_hour_cap=manifest.study_plan.formal_gpu_hour_cap,
        task_qualifications=tuple(qualifications),
        metadata_review_ready=metadata_ready,
        local_preflight_ready=metadata_ready and all_tasks_ready,
        experiment_ready=experiment_ready,
        requires_additional_48gb_single_device_resource=requires_48gb,
        integrity_blockers=tuple(integrity),
        qualification_blockers=tuple(blocked),
        pending_qualifications=tuple(pending),
    )


def save_executable_candidate_report(
    report: ExecutableCandidateReport,
    path: str | Path,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_executable_candidate_report(path: str | Path) -> ExecutableCandidateReport:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("executable candidate report must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_BYTES:
        raise ValueError("executable candidate report must be a bounded regular file")
    try:
        payload = json.loads(resolved.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("executable candidate report must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("executable candidate report must contain a JSON object")
    recorded_hash = payload.pop("report_sha256", None)
    report = ExecutableCandidateReport.model_validate(payload)
    if report.report_sha256 != recorded_hash:
        raise ValueError("executable candidate report hash mismatch")
    return report


def _add(
    target: list[CandidateFinding],
    code: str,
    message: str,
    task_id: str | None = None,
) -> None:
    finding = CandidateFinding(code=code, message=message, task_id=task_id)
    if finding not in target:
        target.append(finding)


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()

"""No-run bridges from acquired benchmark bytes to lifecycle task packages.

The bridge is deliberately not a scorer or an executor.  It verifies an
existing acquisition receipt, projects only agent-visible task inputs, and
records every missing admission or scoring dependency as a blocker.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.acquisition import (
    AcquiredItemReceipt,
    AcquisitionItem,
    DatasetAcquisitionReceipt,
    DatasetAcquisitionRequest,
    load_dataset_acquisition_receipt,
    load_dataset_acquisition_request,
)
from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.evaluation.task_selection import load_task_selection_manifest

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 16 * 1024 * 1024
_MAX_TASK_COUNT = 2_000
_PROGRAM_ID = "scitaste-iclr2027-complete-autoresearch-program-v3"
_REQUIRED_PROGRAM_STATES = {
    "task-acquisition-proposed",
    "acquired-quarantined",
    "task-admitted-and-split-frozen",
}
_EXP_COLUMNS = (
    "conference",
    "paper_id",
    "paper_title",
    "task_index",
    "task_type",
    "subtask_count",
    "question",
    "agent_instructions",
    "impl_requirements",
    "expected_outcome",
    "source_files",
)


class BenchmarkBridgeKind(StrEnum):
    MLR_BENCH = "mlr-bench"
    EXP_BENCH = "exp-bench"


class LifecycleStage(StrEnum):
    IDEA = "idea"
    PROPOSAL = "proposal"
    HYPOTHESIS = "hypothesis"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    EXECUTION = "execution"
    EVIDENCE = "evidence"
    CONCLUSION = "conclusion"
    PAPER = "paper"
    REVIEW = "review"
    REVIEW_REVISION = "review-revision"


class BridgePhase(StrEnum):
    ACQUISITION = "task-acquisition"
    ADMISSION = "task-admission"
    SCORING = "scoring"
    MATERIALIZATION = "materialization"


class ScoringAuthority(StrEnum):
    BENCHMARK_RUBRIC_DUAL_AI = "benchmark-rubric-plus-dual-ai"
    EXTERNAL_ISOLATED_SCORER = "external-isolated-benchmark-scorer"


class OutputStatus(StrEnum):
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"


class StageStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class BridgeFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    phase: BridgePhase
    message: str = Field(min_length=1, max_length=4_000)
    blocks_materialization: bool
    blocks_admission: bool


class SourceProvenance(BaseModel):
    """Receipt, license, and byte identity for one projected task input."""

    model_config = _CONFIG

    acquisition_request_id: str = Field(pattern=_ID)
    acquisition_request_sha256: str = Field(pattern=_SHA256)
    acquisition_receipt_sha256: str = Field(pattern=_SHA256)
    item_id: str = Field(pattern=_ID)
    source_url: str = Field(min_length=1, max_length=2_000)
    source_revision: str = Field(min_length=1, max_length=200)
    acquired_asset_ref: str = Field(min_length=1, max_length=1_000)
    acquired_asset_size_bytes: int = Field(gt=0)
    acquired_asset_sha256: str = Field(pattern=_SHA256)
    license_identifier: str = Field(min_length=1, max_length=200)
    license_scope: str = Field(min_length=1, max_length=2_000)
    license_status: ReadinessStatus

    @model_validator(mode="after")
    def source_is_content_bound(self) -> SourceProvenance:
        if not self.source_url.startswith("https://"):
            raise ValueError("benchmark source provenance must use HTTPS")
        _validate_relative_path(self.acquired_asset_ref, "acquired benchmark asset")
        return self


class ScoringBoundary(BaseModel):
    """Fields and artifacts crossing from an agent package to an external scorer."""

    model_config = _CONFIG

    boundary_id: str = Field(pattern=_ID)
    authority: ScoringAuthority
    agent_visible_input_fields: tuple[str, ...] = Field(min_length=1, max_length=50)
    scorer_only_input_fields: tuple[str, ...] = Field(default=(), max_length=50)
    required_result_artifact_roles: tuple[str, ...] = Field(min_length=1, max_length=50)
    conjunctive_components: tuple[LifecycleStage, ...] = Field(min_length=1, max_length=20)
    scorer_only_source_ref: str | None = Field(default=None, max_length=1_000)
    scorer_only_source_sha256: str | None = Field(default=None, pattern=_SHA256)
    hidden_label_materialized_in_task_package: Literal[False] = False
    scorer_implemented_by_bridge: Literal[False] = False
    external_scoring_required: Literal[True] = True
    current_status: Literal["blocked", "pending-external-scoring"]
    blockers: tuple[BridgeFinding, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def firewall_is_closed(self) -> ScoringBoundary:
        if set(self.agent_visible_input_fields) & set(self.scorer_only_input_fields):
            raise ValueError("agent-visible and scorer-only fields must be disjoint")
        if (self.scorer_only_source_ref is None) != (self.scorer_only_source_sha256 is None):
            raise ValueError("scorer-only source reference and hash must be paired")
        if self.scorer_only_source_ref is not None:
            _validate_relative_path(self.scorer_only_source_ref, "scorer-only source")
        if (
            self.authority is ScoringAuthority.EXTERNAL_ISOLATED_SCORER
            and "expected_outcome" not in self.scorer_only_input_fields
        ):
            raise ValueError("EXP-Bench boundary must keep expected_outcome scorer-only")
        return self


class LifecycleBenchmarkTask(BaseModel):
    """One controller-facing task with an immutable visible-input boundary."""

    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    benchmark_id: BenchmarkBridgeKind
    source_group: str = Field(pattern=_ID)
    title: str = Field(min_length=1, max_length=1_000)
    task_family: str = Field(min_length=1, max_length=200)
    scientific_use: Literal[
        "brief-only-stagewise-prepilot",
        "metadata-only-experiment-chain-planning",
    ]
    starting_input_ref: str = Field(min_length=1, max_length=1_000)
    starting_input_sha256: str = Field(pattern=_SHA256)
    starting_input_media_type: Literal["text/markdown", "application/json"]
    lifecycle_stages: tuple[LifecycleStage, ...] = Field(min_length=1, max_length=20)
    required_output_roles: tuple[str, ...] = Field(min_length=1, max_length=50)
    scoring_boundary_id: str = Field(pattern=_ID)
    provenance: SourceProvenance
    runtime_assets_available: bool
    formal_execution_admitted: Literal[False] = False
    admission_blockers: tuple[BridgeFinding, ...] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def task_contract_is_closed(self) -> LifecycleBenchmarkTask:
        _validate_relative_path(self.starting_input_ref, "task visible input")
        for values, label in (
            (self.lifecycle_stages, "lifecycle stages"),
            (self.required_output_roles, "required output roles"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"task {label} must be unique")
        if any(not item.blocks_admission for item in self.admission_blockers):
            raise ValueError("task admission blockers must block admission")
        return self


class ControllerPhaseBinding(BaseModel):
    """Readiness projection for the v3 acquisition and admission states."""

    model_config = _CONFIG

    program_id: Literal[_PROGRAM_ID]
    program_file_sha256: str = Field(pattern=_SHA256)
    acquisition_state: Literal["ready", "blocked"]
    quarantined_bytes_state: Literal["ready", "blocked"]
    admission_state: Literal["ready", "blocked"]
    ready_state_ids: tuple[str, ...] = Field(default=(), max_length=10)
    next_required_state_id: Literal["task-admitted-and-split-frozen"]
    blockers: tuple[BridgeFinding, ...] = Field(default=(), max_length=100)


class TaskPackage(BaseModel):
    """Lifecycle task package consumed by the future research-program controller."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    package_id: str = Field(pattern=_ID)
    benchmark_id: BenchmarkBridgeKind
    bridge_contract: Literal["iclr2027-v3-lifecycle-benchmark-bridge"]
    scientific_use: Literal[
        "brief-only-stagewise-prepilot",
        "metadata-only-experiment-chain-planning",
    ]
    acquisition_request_ref: str = Field(min_length=1, max_length=1_000)
    acquisition_request_file_sha256: str = Field(pattern=_SHA256)
    acquisition_receipt_ref: str = Field(min_length=1, max_length=1_000)
    acquisition_receipt_file_sha256: str = Field(pattern=_SHA256)
    acquisition_receipt_sha256: str = Field(pattern=_SHA256)
    task_count: int = Field(ge=1, le=_MAX_TASK_COUNT)
    source_group_count: int = Field(ge=1, le=_MAX_TASK_COUNT)
    tasks: tuple[LifecycleBenchmarkTask, ...] = Field(min_length=1, max_length=_MAX_TASK_COUNT)
    scoring_boundary: ScoringBoundary
    controller_binding: ControllerPhaseBinding
    ready_for_controller_acquisition_binding: bool
    ready_for_controller_admission_binding: Literal[False] = False
    complete_e3_claim_allowed: Literal[False] = False
    complete_e4_claim_allowed: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False
    authorizes_scoring: Literal[False] = False

    @model_validator(mode="after")
    def task_inventory_is_closed(self) -> TaskPackage:
        for locator in (self.acquisition_request_ref, self.acquisition_receipt_ref):
            _validate_relative_path(locator, "task-package acquisition evidence")
        task_ids = [item.task_id for item in self.tasks]
        if self.task_count != len(self.tasks) or len(task_ids) != len(set(task_ids)):
            raise ValueError("task-package task inventory is not unique and complete")
        groups = {item.source_group for item in self.tasks}
        if self.source_group_count != len(groups):
            raise ValueError("task-package source-group count differs from its tasks")
        if any(item.benchmark_id is not self.benchmark_id for item in self.tasks):
            raise ValueError("task-package tasks belong to another benchmark")
        if any(item.scientific_use != self.scientific_use for item in self.tasks):
            raise ValueError("task-package scientific use differs from its tasks")
        if any(
            item.scoring_boundary_id != self.scoring_boundary.boundary_id for item in self.tasks
        ):
            raise ValueError("task-package scoring-boundary references are not closed")
        expected_acquisition = self.controller_binding.acquisition_state == "ready"
        if self.ready_for_controller_acquisition_binding != expected_acquisition:
            raise ValueError("controller acquisition readiness differs from its phase binding")
        return self

    @computed_field
    @property
    def package_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"package_sha256"}))


class OutputArtifact(BaseModel):
    model_config = _CONFIG

    role: str = Field(pattern=_ID)
    relative_path: str = Field(min_length=1, max_length=1_000)
    byte_size: int = Field(gt=0)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_safe(self) -> OutputArtifact:
        _validate_relative_path(self.relative_path, "lifecycle output artifact")
        return self


class StageOutput(BaseModel):
    model_config = _CONFIG

    stage: LifecycleStage
    status: StageStatus
    artifacts: tuple[OutputArtifact, ...] = Field(default=(), max_length=50)
    failure_code: str | None = Field(default=None, pattern=_ID)

    @model_validator(mode="after")
    def failure_is_explicit(self) -> StageOutput:
        if (self.status is StageStatus.SUCCEEDED) == (self.failure_code is not None):
            raise ValueError("failed or blocked stage outputs require exactly one failure code")
        return self


class ConjunctiveResultInput(BaseModel):
    """Unscored stage results handed to, but never interpreted by, the bridge."""

    model_config = _CONFIG

    candidate_manifest_sha256: str = Field(pattern=_SHA256)
    stage_outputs: tuple[StageOutput, ...] = Field(min_length=1, max_length=20)
    external_score: None = None

    @model_validator(mode="after")
    def stages_are_unique(self) -> ConjunctiveResultInput:
        stages = [item.stage for item in self.stage_outputs]
        if len(stages) != len(set(stages)):
            raise ValueError("conjunctive-result stages must be unique")
        return self


class OutputPackage(BaseModel):
    """Typed result envelope; it contains no bridge-generated benchmark score."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    output_package_id: str = Field(pattern=_ID)
    task_package_sha256: str = Field(pattern=_SHA256)
    benchmark_id: BenchmarkBridgeKind
    task_id: str = Field(pattern=_ID)
    system_id: str = Field(pattern=_ID)
    status: OutputStatus
    candidate_frozen: bool
    result_input: ConjunctiveResultInput
    scoring_boundary_id: str = Field(pattern=_ID)
    scorer_receipt_ref: None = None
    score_attached: Literal[False] = False
    authorizes_scoring: Literal[False] = False

    @model_validator(mode="after")
    def completion_requires_a_frozen_candidate(self) -> OutputPackage:
        if self.status is OutputStatus.COMPLETE and not self.candidate_frozen:
            raise ValueError("complete output packages require a frozen candidate")
        return self


class InputProjection(BaseModel):
    model_config = _CONFIG

    task_id: str = Field(pattern=_ID)
    source_asset_ref: str = Field(min_length=1, max_length=1_000)
    source_asset_sha256: str = Field(pattern=_SHA256)
    source_row_index: int | None = Field(default=None, ge=0)
    output_ref: str = Field(min_length=1, max_length=1_000)
    output_sha256: str = Field(pattern=_SHA256)
    projection_kind: Literal["exact-copy", "agent-visible-json"]
    excluded_source_fields: tuple[str, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def paths_are_safe(self) -> InputProjection:
        _validate_relative_path(self.source_asset_ref, "bridge source asset")
        _validate_relative_path(self.output_ref, "bridge projected input")
        if self.projection_kind == "agent-visible-json" and "expected_outcome" not in (
            self.excluded_source_fields
        ):
            raise ValueError("EXP-Bench visible projection must exclude expected_outcome")
        return self


class AcquisitionBinding(BaseModel):
    model_config = _CONFIG

    request_ref: str = Field(min_length=1, max_length=1_000)
    request_file_sha256: str | None = Field(default=None, pattern=_SHA256)
    request_sha256: str | None = Field(default=None, pattern=_SHA256)
    receipt_ref: str = Field(min_length=1, max_length=1_000)
    receipt_file_sha256: str | None = Field(default=None, pattern=_SHA256)
    receipt_sha256: str | None = Field(default=None, pattern=_SHA256)
    acquisition_root_ref: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def paths_are_safe(self) -> AcquisitionBinding:
        for locator in (self.request_ref, self.receipt_ref, self.acquisition_root_ref):
            _validate_relative_path(locator, "bridge acquisition binding")
        return self


class LifecycleBenchmarkBridgePlan(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    benchmark_id: BenchmarkBridgeKind
    program_id: str = Field(pattern=_ID)
    program_ref: str = Field(min_length=1, max_length=1_000)
    program_file_sha256: str | None = Field(default=None, pattern=_SHA256)
    acquisition: AcquisitionBinding
    input_projections: tuple[InputProjection, ...] = Field(default=(), max_length=_MAX_TASK_COUNT)
    task_package: TaskPackage | None = None
    findings: tuple[BridgeFinding, ...] = Field(default=(), max_length=200)
    ready_to_materialize: bool
    ready_for_controller_acquisition_binding: bool
    ready_for_controller_admission_binding: Literal[False] = False
    reads_existing_bytes_only: Literal[True] = True
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False
    authorizes_scoring: Literal[False] = False

    @model_validator(mode="after")
    def readiness_is_derived(self) -> LifecycleBenchmarkBridgePlan:
        _validate_relative_path(self.program_ref, "bridge program")
        materialization_blocked = any(item.blocks_materialization for item in self.findings)
        expected_materialization = self.task_package is not None and not materialization_blocked
        if self.ready_to_materialize != expected_materialization:
            raise ValueError("bridge materialization readiness differs from blockers")
        expected_acquisition = (
            expected_materialization
            and self.task_package is not None
            and self.task_package.ready_for_controller_acquisition_binding
        )
        if self.ready_for_controller_acquisition_binding != expected_acquisition:
            raise ValueError("bridge acquisition readiness differs from task package")
        if self.task_package is not None and len(self.input_projections) != len(
            self.task_package.tasks
        ):
            raise ValueError("bridge input projections must cover every task")
        return self

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))


class BridgeMaterializationReceipt(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    task_package_sha256: str = Field(pattern=_SHA256)
    projected_file_count: int = Field(ge=1, le=_MAX_TASK_COUNT)
    projected_total_bytes: int = Field(gt=0)
    task_package_manifest_sha256: str = Field(pattern=_SHA256)
    used_existing_bytes_only: Literal[True] = True
    network_access_performed: Literal[False] = False
    model_call_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    scorer_run_performed: Literal[False] = False


class BridgeStatus(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    source_bytes_match_plan: bool
    materialized: bool
    materialized_package_valid: bool
    task_count: int = Field(ge=0, le=_MAX_TASK_COUNT)
    source_group_count: int = Field(ge=0, le=_MAX_TASK_COUNT)
    metadata_ready: bool
    brief_only_stagewise_prepilot_ready: bool
    runtime_ready: Literal[False] = False
    scorer_ready: Literal[False] = False
    formal_task_ready: Literal[False] = False
    ready_for_controller_acquisition_binding: bool
    ready_for_controller_admission_binding: Literal[False] = False
    findings: tuple[BridgeFinding, ...] = Field(default=(), max_length=300)
    authorizes_execution: Literal[False] = False
    authorizes_scoring: Literal[False] = False


def plan_lifecycle_benchmark_bridge(
    benchmark: BenchmarkBridgeKind | str,
    *,
    request_path: str | Path,
    acquisition_root: str | Path,
    program_path: str | Path,
    workspace_root: str | Path = ".",
) -> LifecycleBenchmarkBridgePlan:
    """Inspect existing bytes and compile a no-run lifecycle package plan."""

    benchmark_id = BenchmarkBridgeKind(benchmark)
    root = Path(workspace_root).resolve(strict=True)
    request_ref = _owned_ref(root, request_path, strict=False)
    acquisition_ref = _owned_ref(root, acquisition_root, strict=False)
    receipt_ref = f"{acquisition_ref}/RECEIPT.json"
    program_ref = _owned_ref(root, program_path, strict=False)
    findings: list[BridgeFinding] = []

    program_sha = _inspect_program(root, program_ref, findings)
    request, request_file_sha = _load_request(root, request_ref, findings)
    receipt, receipt_file_sha = _load_receipt(root, receipt_ref, findings)
    acquisition = AcquisitionBinding(
        request_ref=request_ref,
        request_file_sha256=request_file_sha,
        request_sha256=request.request_sha256 if request is not None else None,
        receipt_ref=receipt_ref,
        receipt_file_sha256=receipt_file_sha,
        receipt_sha256=receipt.receipt_sha256 if receipt is not None else None,
        acquisition_root_ref=acquisition_ref,
    )

    tasks: tuple[LifecycleBenchmarkTask, ...] = ()
    projections: tuple[InputProjection, ...] = ()
    if request is not None and receipt is not None:
        source_items = _inspect_acquisition_bindings(
            root,
            acquisition_ref,
            request,
            receipt,
            findings,
        )
        if source_items is not None and program_sha is not None:
            if benchmark_id is BenchmarkBridgeKind.MLR_BENCH:
                tasks, projections = _plan_mlr_tasks(
                    root,
                    request,
                    receipt,
                    source_items,
                    program_sha,
                    findings,
                )
            else:
                tasks, projections = _plan_exp_tasks(
                    root,
                    request,
                    receipt,
                    source_items,
                    program_sha,
                    findings,
                )

    package = None
    if tasks and program_sha is not None and request_file_sha and receipt_file_sha and receipt:
        scoring = _scoring_boundary(benchmark_id, tasks[0].provenance, findings)
        binding_blockers = tuple(item for item in findings if item.blocks_admission)
        controller = ControllerPhaseBinding(
            program_id=_PROGRAM_ID,
            program_file_sha256=program_sha,
            acquisition_state="ready",
            quarantined_bytes_state="ready",
            admission_state="blocked",
            ready_state_ids=("task-acquisition-proposed", "acquired-quarantined"),
            next_required_state_id="task-admitted-and-split-frozen",
            blockers=binding_blockers,
        )
        package = TaskPackage(
            package_id=f"{benchmark_id.value}-lifecycle-task-package-v1",
            benchmark_id=benchmark_id,
            bridge_contract="iclr2027-v3-lifecycle-benchmark-bridge",
            scientific_use=(
                "brief-only-stagewise-prepilot"
                if benchmark_id is BenchmarkBridgeKind.MLR_BENCH
                else "metadata-only-experiment-chain-planning"
            ),
            acquisition_request_ref=request_ref,
            acquisition_request_file_sha256=request_file_sha,
            acquisition_receipt_ref=receipt_ref,
            acquisition_receipt_file_sha256=receipt_file_sha,
            acquisition_receipt_sha256=receipt.receipt_sha256,
            task_count=len(tasks),
            source_group_count=len({item.source_group for item in tasks}),
            tasks=tasks,
            scoring_boundary=scoring,
            controller_binding=controller,
            ready_for_controller_acquisition_binding=True,
        )

    materialization_blocked = any(item.blocks_materialization for item in findings)
    ready = package is not None and not materialization_blocked
    return LifecycleBenchmarkBridgePlan(
        plan_id=f"{benchmark_id.value}-lifecycle-bridge-plan-v1",
        benchmark_id=benchmark_id,
        program_id=_PROGRAM_ID,
        program_ref=program_ref,
        program_file_sha256=program_sha,
        acquisition=acquisition,
        input_projections=projections,
        task_package=package,
        findings=tuple(findings),
        ready_to_materialize=ready,
        ready_for_controller_acquisition_binding=bool(
            ready and package and package.ready_for_controller_acquisition_binding
        ),
    )


def save_lifecycle_benchmark_bridge_plan(
    plan: LifecycleBenchmarkBridgePlan,
    path: str | Path,
) -> Path:
    return _write_new_json(
        path,
        plan.model_dump(
            mode="json",
            exclude={
                "plan_sha256": True,
                "task_package": {"package_sha256": True},
            },
        ),
    )


def load_lifecycle_benchmark_bridge_plan(
    path: str | Path,
) -> LifecycleBenchmarkBridgePlan:
    return LifecycleBenchmarkBridgePlan.model_validate(_load_json_mapping(path, "bridge plan"))


def materialize_lifecycle_task_package(
    plan: LifecycleBenchmarkBridgePlan,
    *,
    workspace_root: str | Path,
    output_root: str | Path,
) -> BridgeMaterializationReceipt:
    """Copy/project verified local bytes into a new package; never score or run them."""

    root = Path(workspace_root).resolve(strict=True)
    fresh = plan_lifecycle_benchmark_bridge(
        plan.benchmark_id,
        request_path=root.joinpath(*PurePosixPath(plan.acquisition.request_ref).parts),
        acquisition_root=root.joinpath(
            *PurePosixPath(plan.acquisition.acquisition_root_ref).parts
        ),
        program_path=root.joinpath(*PurePosixPath(plan.program_ref).parts),
        workspace_root=root,
    )
    if fresh.plan_sha256 != plan.plan_sha256:
        raise ValueError("benchmark bridge plan or source bytes have drifted")
    if not fresh.ready_to_materialize or fresh.task_package is None:
        codes = ", ".join(item.code for item in fresh.findings) or "task-package-unavailable"
        raise ValueError(f"benchmark bridge is blocked: {codes}")

    target_ref = _owned_ref(root, output_root, strict=False)
    target = root.joinpath(*PurePosixPath(target_ref).parts)
    if target.is_symlink() or target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target_parent = target.parent.resolve(strict=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".tmp", dir=target_parent))
    published = False
    try:
        projected_bytes = 0
        for projection in fresh.input_projections:
            payload = _projection_bytes(fresh, projection, root)
            if hashlib.sha256(payload).hexdigest() != projection.output_sha256:
                raise ValueError(f"projected task input drifted: {projection.task_id}")
            destination = temporary.joinpath(*PurePosixPath(projection.output_ref).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _write_new_bytes(destination, payload)
            projected_bytes += len(payload)

        manifest_bytes = _json_bytes(
            fresh.task_package.model_dump(
                mode="json",
                exclude={"package_sha256"},
            )
        )
        manifest_path = temporary / "TASK_PACKAGE.json"
        _write_new_bytes(manifest_path, manifest_bytes)
        receipt = BridgeMaterializationReceipt(
            plan_id=fresh.plan_id,
            plan_sha256=fresh.plan_sha256,
            task_package_sha256=fresh.task_package.package_sha256,
            projected_file_count=len(fresh.input_projections),
            projected_total_bytes=projected_bytes,
            task_package_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        )
        _write_new_bytes(
            temporary / "MATERIALIZATION.json",
            _json_bytes(receipt.model_dump(mode="json")),
        )
        os.rename(temporary, target)
        published = True
        return receipt
    finally:
        if not published:
            shutil.rmtree(temporary, ignore_errors=True)


def inspect_lifecycle_benchmark_bridge(
    plan: LifecycleBenchmarkBridgePlan,
    *,
    workspace_root: str | Path,
    package_root: str | Path | None = None,
) -> BridgeStatus:
    root = Path(workspace_root).resolve(strict=True)
    findings = list(plan.findings)
    fresh = plan_lifecycle_benchmark_bridge(
        plan.benchmark_id,
        request_path=root.joinpath(*PurePosixPath(plan.acquisition.request_ref).parts),
        acquisition_root=root.joinpath(
            *PurePosixPath(plan.acquisition.acquisition_root_ref).parts
        ),
        program_path=root.joinpath(*PurePosixPath(plan.program_ref).parts),
        workspace_root=root,
    )
    sources_match = fresh.plan_sha256 == plan.plan_sha256
    if not sources_match:
        _add(
            findings,
            "plan-or-source-drift",
            BridgePhase.MATERIALIZATION,
            "the saved plan no longer matches its source bytes or control files",
            materialization=True,
            admission=True,
        )

    materialized = False
    package_valid = False
    if package_root is not None:
        package = _existing_owned_directory_path(root, package_root)
        materialized = package is not None
        if not materialized:
            _add(
                findings,
                "materialized-package-missing",
                BridgePhase.MATERIALIZATION,
                "the requested materialized package directory is absent or unsafe",
                materialization=True,
                admission=True,
            )
        else:
            assert package is not None
            package_valid = _verify_materialized_package(plan, package, findings)

    task_count = len(plan.task_package.tasks) if plan.task_package else 0
    source_group_count = plan.task_package.source_group_count if plan.task_package else 0
    acquisition_ready = sources_match and plan.ready_for_controller_acquisition_binding
    if package_root is not None:
        acquisition_ready = acquisition_ready and package_valid
    return BridgeStatus(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        source_bytes_match_plan=sources_match,
        materialized=materialized,
        materialized_package_valid=package_valid,
        task_count=task_count,
        source_group_count=source_group_count,
        metadata_ready=bool(sources_match and plan.task_package is not None),
        brief_only_stagewise_prepilot_ready=bool(
            sources_match
            and plan.task_package is not None
            and plan.task_package.scientific_use == "brief-only-stagewise-prepilot"
        ),
        ready_for_controller_acquisition_binding=acquisition_ready,
        findings=tuple(_deduplicate(findings)),
    )


def _inspect_program(root: Path, ref: str, findings: list[BridgeFinding]) -> str | None:
    path = _existing_owned_file(root, ref)
    if path is None:
        _add(
            findings,
            "program-missing",
            BridgePhase.ACQUISITION,
            "the v3 research program is missing or unsafe",
            materialization=True,
            admission=True,
        )
        return None
    raw = path.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        payload = None
    states = set()
    if isinstance(payload, dict):
        machine = payload.get("lifecycle_state_machine")
        if isinstance(machine, dict) and isinstance(machine.get("states"), list):
            states = {
                item.get("state_id")
                for item in machine["states"]
                if isinstance(item, dict) and isinstance(item.get("state_id"), str)
            }
    if not isinstance(payload, dict) or payload.get("program_id") != _PROGRAM_ID:
        _add(
            findings,
            "program-id-mismatch",
            BridgePhase.ACQUISITION,
            "the bridge must bind the exact v3 complete AutoResearch program",
            materialization=True,
            admission=True,
        )
        return None
    if not _REQUIRED_PROGRAM_STATES <= states:
        _add(
            findings,
            "program-state-machine-incomplete",
            BridgePhase.ACQUISITION,
            "the v3 program lacks the acquisition/admission states required by the bridge",
            materialization=True,
            admission=True,
        )
        return None
    return hashlib.sha256(raw).hexdigest()


def _load_request(
    root: Path,
    ref: str,
    findings: list[BridgeFinding],
) -> tuple[DatasetAcquisitionRequest | None, str | None]:
    path = _existing_owned_file(root, ref)
    if path is None:
        _add(
            findings,
            "acquisition-request-missing",
            BridgePhase.ACQUISITION,
            "the acquisition request is missing or unsafe",
            materialization=True,
            admission=True,
        )
        return None, None
    try:
        inspection = load_dataset_acquisition_request(path)
    except ValueError as exc:
        _add(
            findings,
            "acquisition-request-invalid",
            BridgePhase.ACQUISITION,
            str(exc),
            materialization=True,
            admission=True,
        )
        return None, hashlib.sha256(path.read_bytes()).hexdigest()
    return inspection.request, inspection.file_sha256


def _load_receipt(
    root: Path,
    ref: str,
    findings: list[BridgeFinding],
) -> tuple[DatasetAcquisitionReceipt | None, str | None]:
    path = _existing_owned_file(root, ref)
    if path is None:
        _add(
            findings,
            "acquisition-receipt-missing",
            BridgePhase.ACQUISITION,
            "the typed acquisition receipt is missing or unsafe",
            materialization=True,
            admission=True,
        )
        return None, None
    raw = path.read_bytes()
    try:
        inspection = load_dataset_acquisition_receipt(path)
    except ValueError as exc:
        _add(
            findings,
            "acquisition-receipt-invalid",
            BridgePhase.ACQUISITION,
            str(exc),
            materialization=True,
            admission=True,
        )
        return None, hashlib.sha256(raw).hexdigest()
    return inspection.receipt, inspection.file_sha256


def _inspect_acquisition_bindings(
    root: Path,
    acquisition_ref: str,
    request: DatasetAcquisitionRequest,
    receipt: DatasetAcquisitionReceipt,
    findings: list[BridgeFinding],
) -> dict[str, tuple[AcquisitionItem, AcquiredItemReceipt, Path]] | None:
    before = len(findings)
    if receipt.request_id != request.request_id:
        _integrity(findings, "receipt-request-id-mismatch", "receipt belongs to another request")
    if receipt.request_sha256 != request.request_sha256:
        _integrity(findings, "receipt-request-hash-mismatch", "receipt binds another request")
    expected_root = f"{acquisition_ref}/raw"
    if receipt.destination_root != expected_root:
        _integrity(
            findings,
            "receipt-destination-mismatch",
            "receipt destination differs from the supplied acquisition root",
        )
    requested = {item.item_id: item for item in request.items}
    received = {item.item_id: item for item in receipt.items}
    if set(requested) != set(received):
        _integrity(findings, "receipt-item-set-mismatch", "request and receipt items differ")
    raw_root = _existing_owned_directory(root, expected_root)
    if raw_root is None:
        _integrity(findings, "raw-assets-missing", "acquired raw directory is absent or unsafe")
        return None

    observed: dict[str, tuple[AcquisitionItem, AcquiredItemReceipt, Path]] = {}
    for item_id in sorted(set(requested) & set(received)):
        request_item = requested[item_id]
        receipt_item = received[item_id]
        if request_item.license_status is not ReadinessStatus.VERIFIED:
            _integrity(findings, "license-not-verified", f"license is not verified for {item_id}")
        if (
            request_item.source_url != receipt_item.source_url
            or request_item.source_revision != receipt_item.source_revision
            or request_item.destination != receipt_item.destination
        ):
            _integrity(findings, "item-binding-mismatch", f"request/receipt differs for {item_id}")
            continue
        candidate = _existing_owned_file(raw_root, receipt_item.destination)
        if candidate is None:
            _integrity(findings, "acquired-item-missing", f"acquired bytes missing for {item_id}")
            continue
        raw = candidate.read_bytes()
        if len(raw) != receipt_item.size_bytes:
            _integrity(findings, "acquired-size-mismatch", f"acquired size differs for {item_id}")
            continue
        if hashlib.sha256(raw).hexdigest() != receipt_item.sha256:
            _integrity(findings, "acquired-hash-mismatch", f"acquired hash differs for {item_id}")
            continue
        observed[item_id] = (request_item, receipt_item, candidate)

    expected_paths = {item.destination for item in receipt.items}
    actual_paths = {
        item.relative_to(raw_root).as_posix()
        for item in raw_root.rglob("*")
        if item.is_file() and not item.is_symlink()
    }
    if actual_paths != expected_paths:
        _integrity(findings, "raw-inventory-mismatch", "raw files differ from receipt inventory")
    if any(item.is_symlink() for item in raw_root.rglob("*")):
        _integrity(findings, "raw-symlink-forbidden", "raw acquisition contains symlinks")
    return observed if len(findings) == before else None


def _plan_mlr_tasks(
    root: Path,
    request: DatasetAcquisitionRequest,
    receipt: DatasetAcquisitionReceipt,
    items: dict[str, tuple[AcquisitionItem, AcquiredItemReceipt, Path]],
    program_sha: str,
    findings: list[BridgeFinding],
) -> tuple[tuple[LifecycleBenchmarkTask, ...], tuple[InputProjection, ...]]:
    del program_sha
    selection_binding = next(
        (item for item in request.evidence if item.evidence_id == "task-selection"), None
    )
    if selection_binding is None:
        _integrity(findings, "task-selection-binding-missing", "MLR request lacks task selection")
        return (), ()
    selection_path = _existing_owned_file(root, selection_binding.path)
    if selection_path is None or _sha256_file(selection_path) != selection_binding.sha256:
        _integrity(findings, "task-selection-drift", "MLR source-group selection is unavailable")
        return (), ()
    try:
        selection = load_task_selection_manifest(selection_path).manifest
    except ValueError as exc:
        _integrity(findings, "task-selection-invalid", str(exc))
        return (), ()
    if (
        selection.selection_id != request.selection_id
        or selection.proposal_sha256 != request.selection_proposal_sha256
    ):
        _integrity(findings, "task-selection-mismatch", "MLR task selection binding drifted")
        return (), ()
    selected = {item.task_id: item for item in selection.tasks}
    if set(selected) != set(items):
        _integrity(
            findings,
            "task-selection-set-mismatch",
            "MLR selected and acquired tasks differ",
        )
        return (), ()

    admission = (
        _finding(
            "heldout-source-group-audit-pending",
            BridgePhase.ADMISSION,
            "MLR source groups are preserved but not admitted as held out against SciTaste",
            admission=True,
        ),
        _finding(
            "runtime-assets-absent",
            BridgePhase.ADMISSION,
            "the acquired MLR package contains briefs but no empirical runtime assets",
            admission=True,
        ),
        _finding(
            "benchmark-rubric-unmaterialized",
            BridgePhase.SCORING,
            "the official package rubric is not present in this acquisition",
            admission=True,
        ),
    )
    findings.extend(admission)
    tasks: list[LifecycleBenchmarkTask] = []
    projections: list[InputProjection] = []
    stages = (
        LifecycleStage.IDEA,
        LifecycleStage.PROPOSAL,
        LifecycleStage.HYPOTHESIS,
        LifecycleStage.DESIGN,
        LifecycleStage.IMPLEMENTATION,
        LifecycleStage.EXECUTION,
        LifecycleStage.EVIDENCE,
        LifecycleStage.CONCLUSION,
        LifecycleStage.PAPER,
        LifecycleStage.REVIEW,
        LifecycleStage.REVIEW_REVISION,
    )
    outputs = (
        "idea-candidates",
        "idea-decision-lock",
        "proposal",
        "experiment-plan",
        "source-code",
        "execution-log",
        "evidence-ledger",
        "paper",
        "dual-ai-review",
        "review-driven-revision",
    )
    for task_id in sorted(items):
        request_item, receipt_item, source_path = items[task_id]
        brief = source_path.read_bytes()
        try:
            text = brief.decode("utf-8")
        except UnicodeDecodeError:
            _integrity(findings, "brief-not-utf8", f"MLR brief is not UTF-8: {task_id}")
            continue
        title = next(
            (line.removeprefix("#").strip() for line in text.splitlines() if line.startswith("#")),
            task_id,
        )
        output_ref = f"inputs/briefs/{receipt_item.destination}"
        provenance = _provenance(root, request, receipt, request_item, receipt_item, source_path)
        tasks.append(
            LifecycleBenchmarkTask(
                task_id=task_id,
                benchmark_id=BenchmarkBridgeKind.MLR_BENCH,
                source_group=selected[task_id].source_group,
                title=title,
                task_family="idea-to-paper",
                scientific_use="brief-only-stagewise-prepilot",
                starting_input_ref=output_ref,
                starting_input_sha256=receipt_item.sha256,
                starting_input_media_type="text/markdown",
                lifecycle_stages=stages,
                required_output_roles=outputs,
                scoring_boundary_id="mlr-bench-package-review-v1",
                provenance=provenance,
                runtime_assets_available=False,
                admission_blockers=admission,
            )
        )
        projections.append(
            InputProjection(
                task_id=task_id,
                source_asset_ref=_owned_ref(root, source_path),
                source_asset_sha256=receipt_item.sha256,
                output_ref=output_ref,
                output_sha256=receipt_item.sha256,
                projection_kind="exact-copy",
            )
        )
    return tuple(tasks), tuple(projections)


def _plan_exp_tasks(
    root: Path,
    request: DatasetAcquisitionRequest,
    receipt: DatasetAcquisitionReceipt,
    items: dict[str, tuple[AcquisitionItem, AcquiredItemReceipt, Path]],
    program_sha: str,
    findings: list[BridgeFinding],
) -> tuple[tuple[LifecycleBenchmarkTask, ...], tuple[InputProjection, ...]]:
    del program_sha
    if set(items) != {"exp_bench_dataset"}:
        _integrity(findings, "exp-metadata-item-mismatch", "EXP bridge requires one pinned CSV")
        return (), ()
    request_item, receipt_item, source_path = items["exp_bench_dataset"]
    try:
        rows = _read_exp_rows(source_path)
    except ValueError as exc:
        _integrity(findings, "exp-metadata-invalid", str(exc))
        return (), ()
    admission = (
        _finding(
            "metadata-only-runtime-assets-absent",
            BridgePhase.ADMISSION,
            "EXP acquisition contains metadata, not task repositories, data, or environments",
            admission=True,
        ),
        _finding(
            "formal-source-group-allocation-unfrozen",
            BridgePhase.ADMISSION,
            "the 51 source-paper groups are identified but no formal subset is frozen",
            admission=True,
        ),
        _finding(
            "upstream-license-audit-incomplete",
            BridgePhase.ADMISSION,
            "per-task repository, dataset, checkpoint, and dependency rights are unverified",
            admission=True,
        ),
        _finding(
            "external-scorer-unmaterialized",
            BridgePhase.SCORING,
            "the bridge defines scorer input but does not contain or imitate EXP-Bench scoring",
            admission=True,
        ),
    )
    findings.extend(admission)
    provenance = _provenance(root, request, receipt, request_item, receipt_item, source_path)
    tasks: list[LifecycleBenchmarkTask] = []
    projections: list[InputProjection] = []
    stages = (
        LifecycleStage.HYPOTHESIS,
        LifecycleStage.DESIGN,
        LifecycleStage.IMPLEMENTATION,
        LifecycleStage.EXECUTION,
        LifecycleStage.CONCLUSION,
    )
    outputs = (
        "hypothesis",
        "experiment-design",
        "source-code",
        "execution-log",
        "conclusion",
        "conjunctive-result-input",
    )
    source_ref = _owned_ref(root, source_path)
    for row_index, row in enumerate(rows):
        task_id = _exp_task_id(row)
        source_group = _exp_source_group(row)
        visible = _exp_visible_payload(task_id, source_group, row)
        visible_bytes = _json_bytes(visible)
        output_ref = f"inputs/tasks/{task_id}.json"
        tasks.append(
            LifecycleBenchmarkTask(
                task_id=task_id,
                benchmark_id=BenchmarkBridgeKind.EXP_BENCH,
                source_group=source_group,
                title=row["question"],
                task_family=f"experiment-chain-type-{row['task_type']}",
                scientific_use="metadata-only-experiment-chain-planning",
                starting_input_ref=output_ref,
                starting_input_sha256=hashlib.sha256(visible_bytes).hexdigest(),
                starting_input_media_type="application/json",
                lifecycle_stages=stages,
                required_output_roles=outputs,
                scoring_boundary_id="exp-bench-isolated-scorer-v1",
                provenance=provenance,
                runtime_assets_available=False,
                admission_blockers=admission,
            )
        )
        projections.append(
            InputProjection(
                task_id=task_id,
                source_asset_ref=source_ref,
                source_asset_sha256=receipt_item.sha256,
                source_row_index=row_index,
                output_ref=output_ref,
                output_sha256=hashlib.sha256(visible_bytes).hexdigest(),
                projection_kind="agent-visible-json",
                excluded_source_fields=("expected_outcome",),
            )
        )
    return tuple(tasks), tuple(projections)


def _scoring_boundary(
    benchmark: BenchmarkBridgeKind,
    provenance: SourceProvenance,
    findings: list[BridgeFinding],
) -> ScoringBoundary:
    if benchmark is BenchmarkBridgeKind.MLR_BENCH:
        blockers = tuple(item for item in findings if item.phase is BridgePhase.SCORING)
        return ScoringBoundary(
            boundary_id="mlr-bench-package-review-v1",
            authority=ScoringAuthority.BENCHMARK_RUBRIC_DUAL_AI,
            agent_visible_input_fields=("research_brief",),
            scorer_only_input_fields=("benchmark_rubric", "dual_ai_raw_reviews"),
            required_result_artifact_roles=(
                "idea-candidates",
                "proposal",
                "source-code",
                "execution-log",
                "evidence-ledger",
                "paper",
                "review-driven-revision",
            ),
            conjunctive_components=(
                LifecycleStage.IDEA,
                LifecycleStage.PROPOSAL,
                LifecycleStage.EXECUTION,
                LifecycleStage.EVIDENCE,
                LifecycleStage.PAPER,
                LifecycleStage.REVIEW_REVISION,
            ),
            current_status="blocked",
            blockers=blockers,
        )
    blockers = tuple(item for item in findings if item.phase is BridgePhase.SCORING)
    return ScoringBoundary(
        boundary_id="exp-bench-isolated-scorer-v1",
        authority=ScoringAuthority.EXTERNAL_ISOLATED_SCORER,
        agent_visible_input_fields=(
            "conference",
            "paper_title",
            "task_type",
            "subtask_count",
            "question",
            "agent_instructions",
            "impl_requirements",
            "source_files",
        ),
        scorer_only_input_fields=("expected_outcome", "official_benchmark_rubric"),
        required_result_artifact_roles=(
            "hypothesis",
            "experiment-design",
            "source-code",
            "execution-log",
            "conclusion",
            "conjunctive-result-input",
        ),
        conjunctive_components=(
            LifecycleStage.HYPOTHESIS,
            LifecycleStage.DESIGN,
            LifecycleStage.IMPLEMENTATION,
            LifecycleStage.EXECUTION,
            LifecycleStage.CONCLUSION,
        ),
        scorer_only_source_ref=provenance.acquired_asset_ref,
        scorer_only_source_sha256=provenance.acquired_asset_sha256,
        current_status="blocked",
        blockers=blockers,
    )


def _projection_bytes(
    plan: LifecycleBenchmarkBridgePlan,
    projection: InputProjection,
    root: Path,
) -> bytes:
    source = _existing_owned_file(root, projection.source_asset_ref)
    if source is None or _sha256_file(source) != projection.source_asset_sha256:
        raise ValueError(f"bridge source asset drifted: {projection.task_id}")
    if projection.projection_kind == "exact-copy":
        return source.read_bytes()
    rows = _read_exp_rows(source)
    if projection.source_row_index is None or projection.source_row_index >= len(rows):
        raise ValueError(f"EXP-Bench row is unavailable: {projection.task_id}")
    row = rows[projection.source_row_index]
    task = next(
        item
        for item in (plan.task_package.tasks if plan.task_package else ())
        if item.task_id == projection.task_id
    )
    return _json_bytes(_exp_visible_payload(task.task_id, task.source_group, row))


def _verify_materialized_package(
    plan: LifecycleBenchmarkBridgePlan,
    package: Path,
    findings: list[BridgeFinding],
) -> bool:
    if plan.task_package is None:
        return False
    manifest = package / "TASK_PACKAGE.json"
    receipt_path = package / "MATERIALIZATION.json"
    try:
        observed_package = TaskPackage.model_validate(_load_json_mapping(manifest, "task package"))
        receipt = BridgeMaterializationReceipt.model_validate(
            _load_json_mapping(receipt_path, "bridge materialization receipt")
        )
    except (OSError, ValueError) as exc:
        _add(
            findings,
            "materialized-control-invalid",
            BridgePhase.MATERIALIZATION,
            str(exc),
            materialization=True,
            admission=True,
        )
        return False
    valid = True
    if observed_package.package_sha256 != plan.task_package.package_sha256:
        valid = False
    manifest_sha = _sha256_file(manifest)
    if (
        receipt.plan_sha256 != plan.plan_sha256
        or receipt.task_package_sha256 != observed_package.package_sha256
        or receipt.task_package_manifest_sha256 != manifest_sha
    ):
        valid = False
    total = 0
    for projection in plan.input_projections:
        candidate = _existing_owned_file(package, projection.output_ref)
        if candidate is None or _sha256_file(candidate) != projection.output_sha256:
            valid = False
            continue
        total += candidate.stat().st_size
    if (
        receipt.projected_file_count != len(plan.input_projections)
        or receipt.projected_total_bytes != total
    ):
        valid = False
    if not valid:
        _add(
            findings,
            "materialized-package-drift",
            BridgePhase.MATERIALIZATION,
            "materialized task inputs or receipts differ from the bridge plan",
            materialization=True,
            admission=True,
        )
    return valid


def _provenance(
    root: Path,
    request: DatasetAcquisitionRequest,
    receipt: DatasetAcquisitionReceipt,
    request_item: AcquisitionItem,
    receipt_item: AcquiredItemReceipt,
    path: Path,
) -> SourceProvenance:
    return SourceProvenance(
        acquisition_request_id=request.request_id,
        acquisition_request_sha256=request.request_sha256,
        acquisition_receipt_sha256=receipt.receipt_sha256,
        item_id=request_item.item_id,
        source_url=receipt_item.source_url,
        source_revision=receipt_item.source_revision,
        acquired_asset_ref=_owned_ref(root, path),
        acquired_asset_size_bytes=receipt_item.size_bytes,
        acquired_asset_sha256=receipt_item.sha256,
        license_identifier=request_item.license_identifier,
        license_scope=request_item.license_scope,
        license_status=request_item.license_status,
    )


def _read_exp_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != _EXP_COLUMNS:
                raise ValueError("EXP-Bench CSV columns differ from the pinned schema")
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("EXP-Bench CSV cannot be parsed") from exc
    if not rows or len(rows) > _MAX_TASK_COUNT:
        raise ValueError("EXP-Bench CSV task count is empty or exceeds the bridge ceiling")
    task_ids: set[str] = set()
    for row in rows:
        if any(row.get(field) in {None, ""} for field in _EXP_COLUMNS):
            raise ValueError("EXP-Bench CSV contains an incomplete row")
        task_id = _exp_task_id(row)
        if task_id in task_ids:
            raise ValueError("EXP-Bench CSV contains duplicate task identities")
        task_ids.add(task_id)
    return rows


def _exp_visible_payload(task_id: str, source_group: str, row: dict[str, str]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "benchmark_id": BenchmarkBridgeKind.EXP_BENCH.value,
        "task_id": task_id,
        "source_group": source_group,
        "conference": row["conference"],
        "paper_title": row["paper_title"],
        "task_type": row["task_type"],
        "subtask_count": int(row["subtask_count"]),
        "question": row["question"],
        "agent_instructions": row["agent_instructions"],
        "impl_requirements": row["impl_requirements"],
        "source_files": row["source_files"],
    }


def _exp_task_id(row: dict[str, str]) -> str:
    return _safe_id(f"exp-{row['conference']}-{row['paper_id']}-{row['task_index']}")


def _exp_source_group(row: dict[str, str]) -> str:
    return _safe_id(f"exp-{row['conference']}-{row['paper_id']}")


def _safe_id(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in normalized.split("-") if part)


def _integrity(findings: list[BridgeFinding], code: str, message: str) -> None:
    _add(
        findings,
        code,
        BridgePhase.ACQUISITION,
        message,
        materialization=True,
        admission=True,
    )


def _finding(
    code: str,
    phase: BridgePhase,
    message: str,
    *,
    materialization: bool = False,
    admission: bool = False,
) -> BridgeFinding:
    return BridgeFinding(
        code=code,
        phase=phase,
        message=message,
        blocks_materialization=materialization,
        blocks_admission=admission,
    )


def _add(
    findings: list[BridgeFinding],
    code: str,
    phase: BridgePhase,
    message: str,
    *,
    materialization: bool,
    admission: bool,
) -> None:
    findings.append(
        _finding(
            code,
            phase,
            message,
            materialization=materialization,
            admission=admission,
        )
    )


def _deduplicate(findings: list[BridgeFinding]) -> list[BridgeFinding]:
    observed: set[tuple[str, str]] = set()
    output: list[BridgeFinding] = []
    for finding in findings:
        key = (finding.phase.value, finding.code)
        if key not in observed:
            observed.add(key)
            output.append(finding)
    return output


def _owned_ref(root: Path, path: str | Path, *, strict: bool = True) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=strict)
    if not resolved.is_relative_to(root):
        raise ValueError("benchmark bridge path escapes the workspace root")
    return resolved.relative_to(root).as_posix()


def _existing_owned_file(root: Path, ref: str) -> Path | None:
    pure = PurePosixPath(ref)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    candidate = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_relative_to(root) and resolved.is_file() else None


def _existing_owned_directory(root: Path, ref: str) -> Path | None:
    pure = PurePosixPath(ref)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    return _existing_owned_directory_path(root, root.joinpath(*pure.parts))


def _existing_owned_directory_path(root: Path, path: str | Path) -> Path | None:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return None
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_relative_to(root) and resolved.is_dir() else None


def _validate_relative_path(value: str, label: str) -> None:
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != value
    ):
        raise ValueError(f"{label} must be a normalized relative path")


def _load_json_mapping(path: str | Path, label: str) -> dict[str, object]:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"{label} must be a regular file")
    raw = source.read_bytes()
    if not raw or len(raw) > _MAX_CONTROL_BYTES:
        raise ValueError(f"{label} exceeds its byte boundary")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must contain UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _write_new_json(path: str | Path, value: object) -> Path:
    target = Path(path)
    if target.is_symlink() or target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_new_bytes(target, _json_bytes(value))
    return target


def _write_new_bytes(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "BenchmarkBridgeKind",
    "BridgeFinding",
    "BridgeMaterializationReceipt",
    "BridgeStatus",
    "ConjunctiveResultInput",
    "ControllerPhaseBinding",
    "InputProjection",
    "LifecycleBenchmarkBridgePlan",
    "LifecycleBenchmarkTask",
    "LifecycleStage",
    "OutputArtifact",
    "OutputPackage",
    "ScoringBoundary",
    "SourceProvenance",
    "StageOutput",
    "TaskPackage",
    "inspect_lifecycle_benchmark_bridge",
    "load_lifecycle_benchmark_bridge_plan",
    "materialize_lifecycle_task_package",
    "plan_lifecycle_benchmark_bridge",
    "save_lifecycle_benchmark_bridge_plan",
]

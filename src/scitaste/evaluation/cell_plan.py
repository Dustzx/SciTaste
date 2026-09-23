"""Compile one prelaunch proposal into a closed, no-run evaluation-cell plan."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_serializer, model_validator

from scitaste.evaluation.prelaunch import (
    ApiModelResource,
    ComparisonRegime,
    ConfirmatoryEstimandKind,
    ExecutionLane,
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    GpuWorkloadKind,
    PrelaunchSystem,
    PrelaunchTask,
    ReadinessStatus,
    ScientificLaneRole,
    SystemRole,
    TaskFreezeSemantics,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_PLAN_BYTES = 64 * 1024 * 1024


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class EvaluationCellResource(BaseModel):
    """Non-secret model or checkpoint identity inherited from one lane."""

    model_config = _CONFIG

    kind: ExecutionLaneKind
    resource_sha256: str = Field(pattern=_SHA256)
    provider_id: str | None = None
    model_id: str | None = None
    model_revision: str | None = None
    api_key_env: str | None = None
    max_input_tokens_per_call: int | None = Field(default=None, gt=0)
    max_output_tokens_per_call: int | None = Field(default=None, gt=0)
    max_requests: int | None = Field(default=None, gt=0)
    max_total_tokens: int | None = Field(default=None, gt=0)
    max_cost: float | None = Field(default=None, gt=0)
    host_alias: str | None = None
    allocated_device_count_per_cell: int | None = Field(default=None, gt=0, le=64)
    gpu_workload_kind: GpuWorkloadKind | None = None
    checkpoint_id: str | None = None
    checkpoint_sha256: str | None = Field(default=None, pattern=_SHA256)
    initialization_contract_sha256: str | None = Field(default=None, pattern=_SHA256)
    max_gpu_hours: float | None = Field(default=None, gt=0)
    max_storage_bytes: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def identity_matches_lane_kind(self) -> EvaluationCellResource:
        api_values = (
            self.provider_id,
            self.model_id,
            self.api_key_env,
            self.max_input_tokens_per_call,
            self.max_output_tokens_per_call,
            self.max_requests,
            self.max_total_tokens,
            self.max_cost,
        )
        gpu_base_values = (
            self.host_alias,
            self.max_gpu_hours,
            self.max_storage_bytes,
        )
        gpu_workload_kind = self.gpu_workload_kind or GpuWorkloadKind.CHECKPOINT_MODEL
        gpu_identity_complete = all(gpu_base_values) and (
            (
                self.checkpoint_id is not None
                and self.checkpoint_sha256 is not None
                and self.initialization_contract_sha256 is None
            )
            if gpu_workload_kind is GpuWorkloadKind.CHECKPOINT_MODEL
            else (
                self.checkpoint_id is None
                and self.checkpoint_sha256 is None
                and self.initialization_contract_sha256 is not None
            )
        )
        any_gpu_value = any(
            value is not None
            for value in (
                *gpu_base_values,
                self.allocated_device_count_per_cell,
                self.gpu_workload_kind,
                self.checkpoint_id,
                self.checkpoint_sha256,
                self.initialization_contract_sha256,
            )
        )
        if self.kind is ExecutionLaneKind.API_ONLY:
            if not all(api_values) or any_gpu_value:
                raise ValueError("API cell resources require only provider/model/key-env identity")
        elif self.kind is ExecutionLaneKind.GPU:
            if not gpu_identity_complete or any(value is not None for value in api_values):
                raise ValueError("GPU cell resources require one complete compute identity")
        elif not all(api_values) or not gpu_identity_complete:
            raise ValueError("hybrid cell resources require complete API and GPU identities")
        return self

    @model_serializer(mode="wrap")
    def omit_absent_gpu_workload_fields(self, handler):  # type: ignore[no-untyped-def]
        payload = handler(self)
        for key in (
            "allocated_device_count_per_cell",
            "gpu_workload_kind",
            "initialization_contract_sha256",
        ):
            if payload.get(key) is None:
                payload.pop(key, None)
        return payload


class PlannedEvaluationCell(BaseModel):
    """One blinded matrix member; this record is not a launch instruction."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    cell_id: str = Field(pattern=r"^cell-[0-9a-f]{24}$")
    review_blind_id: str = Field(pattern=r"^blind-[0-9a-f]{24}$")
    proposal_sha256: str = Field(pattern=_SHA256)
    lane_id: str
    lane_kind: ExecutionLaneKind
    scientific_role: ScientificLaneRole
    comparison_regime: ComparisonRegime | None = None
    model_effects_confounded: bool | None = None
    system_id: str
    system_role: SystemRole
    implementation_ref: str | None = None
    adapter_preflight_ref: str | None = None
    adapter_preflight_sha256: str | None = Field(default=None, pattern=_SHA256)
    task_id: str
    task_asset_manifest: str | None = None
    task_asset_manifest_sha256: str | None = Field(default=None, pattern=_SHA256)
    seed: int
    repetition: int = Field(ge=1)
    resource: EvaluationCellResource
    ready_for_launch_preparation: bool
    readiness_blockers: tuple[str, ...]
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def readiness_matches_blockers(self) -> PlannedEvaluationCell:
        if self.ready_for_launch_preparation == bool(self.readiness_blockers):
            raise ValueError("cell readiness must be exactly the absence of blockers")
        if (self.adapter_preflight_ref is None) != (self.adapter_preflight_sha256 is None):
            raise ValueError("cell adapter preflight reference and hash must be paired")
        if (self.task_asset_manifest is None) != (self.task_asset_manifest_sha256 is None):
            raise ValueError("cell task asset reference and hash must be paired")
        return self


class PlannedEvaluationLane(BaseModel):
    model_config = _CONFIG

    lane_id: str
    kind: ExecutionLaneKind
    scientific_role: ScientificLaneRole
    comparison_regime: ComparisonRegime | None = None
    model_effects_confounded: bool | None = None
    comparison_claim_boundary: str | None = None
    resource: EvaluationCellResource | None = None
    system_resources: dict[str, EvaluationCellResource] | None = None
    system_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    seeds: tuple[int, ...]
    repetitions: int = Field(ge=1)
    cell_ids: tuple[str, ...] = Field(min_length=1)
    ready_cells: int = Field(ge=0)
    blocked_cells: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_are_closed(self) -> PlannedEvaluationLane:
        expected = len(self.system_ids) * len(self.task_ids) * len(self.seeds) * self.repetitions
        if len(self.cell_ids) != expected:
            raise ValueError("planned lane cell IDs do not cover the declared matrix")
        if self.ready_cells + self.blocked_cells != expected:
            raise ValueError("planned lane readiness counts do not cover every cell")
        if self.comparison_regime is ComparisonRegime.BEST_NATIVE:
            if self.resource is not None or self.system_resources is None:
                raise ValueError("best-native planned lanes require per-system resources")
            if set(self.system_resources) != set(self.system_ids):
                raise ValueError("best-native planned resources must cover every system")
            if self.model_effects_confounded is not True:
                raise ValueError("best-native planned lanes must retain model confounding")
        elif self.resource is None or self.system_resources is not None:
            raise ValueError("matched and legacy planned lanes require one common resource")
        return self


class EvaluationCellPlan(BaseModel):
    """Content-addressed expansion of a proposal, with no execution authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2", "1.3"] = "1.0"
    manifest_id: str
    protocol_id: str
    protocol_version: str
    proposal_sha256: str = Field(pattern=_SHA256)
    study_scope: Literal["pilot", "formal", "robustness"]
    lanes: tuple[PlannedEvaluationLane, ...] = Field(min_length=1)
    cells: tuple[PlannedEvaluationCell, ...] = Field(min_length=1)
    plan_blockers: tuple[str, ...]
    ready_for_launch_preparation: bool
    proposal_author_approved: bool
    claim_estimand_kind: ConfirmatoryEstimandKind | None = None
    claim_lane_id: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
    claim_contract_sha256: str | None = Field(default=None, pattern=_SHA256)
    formal_task_set_sha256: str | None = Field(default=None, pattern=_SHA256)
    task_freeze_file_sha256: str | None = Field(default=None, pattern=_SHA256)
    authorizes_execution: Literal[False] = False
    no_provider_call_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    no_task_download_performed: Literal[True] = True

    @model_validator(mode="after")
    def plan_is_closed(self) -> EvaluationCellPlan:
        lane_cell_ids = [cell_id for lane in self.lanes for cell_id in lane.cell_ids]
        cell_ids = [cell.cell_id for cell in self.cells]
        if len(cell_ids) != len(set(cell_ids)):
            raise ValueError("evaluation cell IDs must be unique")
        if len({cell.review_blind_id for cell in self.cells}) != len(self.cells):
            raise ValueError("evaluation review blind IDs must be unique")
        if lane_cell_ids != cell_ids:
            raise ValueError("plan lanes and cells must have identical declared ordering")
        if any(cell.proposal_sha256 != self.proposal_sha256 for cell in self.cells):
            raise ValueError("all evaluation cells must bind the plan proposal")
        if self.ready_for_launch_preparation == bool(self.plan_blockers):
            raise ValueError("plan readiness must be exactly the absence of blockers")
        claim_values = (
            self.claim_estimand_kind,
            self.claim_lane_id,
            self.claim_contract_sha256,
        )
        if self.schema_version in {"1.2", "1.3"}:
            if any(value is None for value in claim_values):
                raise ValueError("cell plan v1.2 requires a complete claim binding")
            if self.claim_lane_id not in {lane.lane_id for lane in self.lanes}:
                raise ValueError("cell plan claim lane is not registered")
        elif any(value is not None for value in claim_values):
            raise ValueError("cell plan v1.2 is required for claim bindings")
        task_freeze_values = (
            self.formal_task_set_sha256,
            self.task_freeze_file_sha256,
        )
        if self.schema_version == "1.3":
            if any(value is None for value in task_freeze_values):
                raise ValueError("cell plan v1.3 requires a complete formal task-set binding")
        elif any(value is not None for value in task_freeze_values):
            raise ValueError("cell plan v1.3 is required for formal task-set bindings")
        return self

    @computed_field
    @property
    def plan_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"plan_sha256"})
        if self.schema_version == "1.0":
            for lane in payload["lanes"]:
                for key in (
                    "comparison_regime",
                    "model_effects_confounded",
                    "comparison_claim_boundary",
                    "system_resources",
                ):
                    lane.pop(key, None)
            for cell in payload["cells"]:
                cell.pop("comparison_regime", None)
                cell.pop("model_effects_confounded", None)
        if self.schema_version in {"1.0", "1.1"}:
            payload.pop("claim_estimand_kind", None)
            payload.pop("claim_lane_id", None)
            payload.pop("claim_contract_sha256", None)
        if self.schema_version != "1.3":
            payload.pop("formal_task_set_sha256", None)
            payload.pop("task_freeze_file_sha256", None)
        return _canonical_sha256(payload)


def compile_evaluation_cell_plan(
    manifest: ExperimentPrelaunchManifest,
) -> EvaluationCellPlan:
    """Expand a validated proposal without checking out data or invoking any resource."""

    systems = {item.system_id: item for item in manifest.systems}
    tasks = {item.task_id: item for item in manifest.tasks}
    all_cells: list[PlannedEvaluationCell] = []
    planned_lanes: list[PlannedEvaluationLane] = []
    proposal_sha256 = manifest.proposal_sha256
    for lane in manifest.lanes:
        common_resource = (
            _resource_for(lane, None)
            if lane.comparison_regime is not ComparisonRegime.BEST_NATIVE
            else None
        )
        system_resources = (
            {system_id: _resource_for(lane, system_id) for system_id in lane.system_ids}
            if lane.comparison_regime is ComparisonRegime.BEST_NATIVE
            else None
        )
        lane_cells: list[PlannedEvaluationCell] = []
        for system_id in lane.system_ids:
            system = systems[system_id]
            resource = (
                system_resources[system_id] if system_resources is not None else common_resource
            )
            assert resource is not None
            for task_id in lane.task_ids:
                task = tasks[task_id]
                for seed in lane.seeds:
                    for repetition in range(1, lane.repetitions + 1):
                        identity = {
                            "proposal_sha256": proposal_sha256,
                            "lane_id": lane.lane_id,
                            "system_id": system_id,
                            "task_id": task_id,
                            "seed": seed,
                            "repetition": repetition,
                        }
                        blockers = _cell_blockers(system, task, lane)
                        cell = PlannedEvaluationCell(
                            cell_id=f"cell-{_canonical_sha256(identity)[:24]}",
                            review_blind_id=(
                                f"blind-{_canonical_sha256({'review': identity})[:24]}"
                            ),
                            proposal_sha256=proposal_sha256,
                            lane_id=lane.lane_id,
                            lane_kind=lane.kind,
                            scientific_role=lane.scientific_role,
                            comparison_regime=lane.comparison_regime,
                            model_effects_confounded=lane.model_effects_confounded,
                            system_id=system_id,
                            system_role=system.role,
                            implementation_ref=system.implementation_ref,
                            adapter_preflight_ref=system.adapter_preflight_ref,
                            adapter_preflight_sha256=system.adapter_preflight_sha256,
                            task_id=task_id,
                            task_asset_manifest=task.selected_asset_manifest,
                            task_asset_manifest_sha256=task.asset_manifest_sha256,
                            seed=seed,
                            repetition=repetition,
                            resource=resource,
                            ready_for_launch_preparation=not blockers,
                            readiness_blockers=blockers,
                        )
                        lane_cells.append(cell)
                        all_cells.append(cell)
        ready = sum(cell.ready_for_launch_preparation for cell in lane_cells)
        planned_lanes.append(
            PlannedEvaluationLane(
                lane_id=lane.lane_id,
                kind=lane.kind,
                scientific_role=lane.scientific_role,
                comparison_regime=lane.comparison_regime,
                model_effects_confounded=lane.model_effects_confounded,
                comparison_claim_boundary=lane.comparison_claim_boundary,
                resource=common_resource,
                system_resources=system_resources,
                system_ids=lane.system_ids,
                task_ids=lane.task_ids,
                seeds=lane.seeds,
                repetitions=lane.repetitions,
                cell_ids=tuple(cell.cell_id for cell in lane_cells),
                ready_cells=ready,
                blocked_cells=len(lane_cells) - ready,
            )
        )

    plan_blockers = _plan_blockers(manifest, tuple(all_cells))
    claim = manifest.analysis.claim_admission if manifest.analysis is not None else None
    return EvaluationCellPlan(
        schema_version=(
            "1.3"
            if manifest.integrity is not None
            and manifest.integrity.task_freeze_semantics
            is TaskFreezeSemantics.BENCHMARK_METADATA_ALLOCATION
            else "1.2"
            if claim is not None
            else "1.1"
            if any(
                lane.comparison_regime is ComparisonRegime.BEST_NATIVE for lane in manifest.lanes
            )
            else "1.0"
        ),
        manifest_id=manifest.manifest_id,
        protocol_id=manifest.protocol_id,
        protocol_version=manifest.protocol_version,
        proposal_sha256=proposal_sha256,
        study_scope=manifest.study_scope,
        lanes=tuple(planned_lanes),
        cells=tuple(all_cells),
        plan_blockers=plan_blockers,
        ready_for_launch_preparation=not plan_blockers,
        proposal_author_approved=manifest.approval.approved,
        claim_estimand_kind=claim.estimand_kind if claim is not None else None,
        claim_lane_id=claim.lane_id if claim is not None else None,
        claim_contract_sha256=(
            _canonical_sha256(claim.model_dump(mode="json")) if claim is not None else None
        ),
        formal_task_set_sha256=(
            manifest.integrity.formal_task_set_sha256
            if manifest.integrity is not None
            and manifest.integrity.task_freeze_semantics
            is TaskFreezeSemantics.BENCHMARK_METADATA_ALLOCATION
            else None
        ),
        task_freeze_file_sha256=(
            manifest.integrity.task_freeze_sha256
            if manifest.integrity is not None
            and manifest.integrity.task_freeze_semantics
            is TaskFreezeSemantics.BENCHMARK_METADATA_ALLOCATION
            else None
        ),
    )


def save_evaluation_cell_plan(plan: EvaluationCellPlan, path: str | Path) -> Path:
    """Atomically write canonical plan JSON without granting launch authority."""

    target = Path(path)
    if target.is_symlink():
        raise ValueError("evaluation cell plan output cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = plan.model_dump_json(indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_evaluation_cell_plan(path: str | Path) -> EvaluationCellPlan:
    """Load a bounded cell plan and verify its serialized computed fingerprint."""

    requested = Path(path)
    if requested.is_symlink() or not requested.is_file():
        raise ValueError("evaluation cell plan must be a regular non-symlink file")
    if requested.stat().st_size > _MAX_PLAN_BYTES:
        raise ValueError("evaluation cell plan exceeds its size limit")
    try:
        payload = json.loads(requested.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("evaluation cell plan must contain UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("evaluation cell plan root must be an object")
    serialized_sha256 = payload.pop("plan_sha256", None)
    plan = EvaluationCellPlan.model_validate(payload)
    if serialized_sha256 is not None and serialized_sha256 != plan.plan_sha256:
        raise ValueError("evaluation cell plan fingerprint mismatch")
    return plan


def _resource_for(
    lane: ExecutionLane,
    system_id: str | None,
) -> EvaluationCellResource:
    if lane.kind is ExecutionLaneKind.API_ONLY:
        model = _api_model_for(lane, system_id)
        snapshot = model.model_dump(mode="json")
        return EvaluationCellResource(
            kind=lane.kind,
            resource_sha256=_canonical_sha256(snapshot),
            provider_id=model.provider_id,
            model_id=model.model_id,
            model_revision=model.model_revision,
            api_key_env=model.api_key_env,
            max_input_tokens_per_call=model.max_input_tokens_per_call,
            max_output_tokens_per_call=model.max_output_tokens_per_call,
            max_requests=model.max_requests,
            max_total_tokens=model.max_total_tokens,
            max_cost=model.max_cost,
        )
    assert lane.gpu_resource is not None
    model = _api_model_for(lane, system_id) if lane.kind is ExecutionLaneKind.HYBRID else None
    snapshot = (
        {
            "api_model": model.model_dump(mode="json"),
            "gpu_resource": lane.gpu_resource.model_dump(mode="json"),
        }
        if model is not None
        else lane.gpu_resource.model_dump(mode="json")
    )
    return EvaluationCellResource(
        kind=lane.kind,
        resource_sha256=_canonical_sha256(snapshot),
        provider_id=None if model is None else model.provider_id,
        model_id=None if model is None else model.model_id,
        model_revision=None if model is None else model.model_revision,
        api_key_env=None if model is None else model.api_key_env,
        max_input_tokens_per_call=(None if model is None else model.max_input_tokens_per_call),
        max_output_tokens_per_call=(None if model is None else model.max_output_tokens_per_call),
        max_requests=None if model is None else model.max_requests,
        max_total_tokens=None if model is None else model.max_total_tokens,
        max_cost=None if model is None else model.max_cost,
        host_alias=lane.gpu_resource.host_alias,
        allocated_device_count_per_cell=(
            lane.gpu_resource.allocated_device_count_per_cell
        ),
        gpu_workload_kind=lane.gpu_resource.workload_kind,
        checkpoint_id=lane.gpu_resource.checkpoint_id,
        checkpoint_sha256=lane.gpu_resource.checkpoint_sha256,
        initialization_contract_sha256=(
            lane.gpu_resource.initialization_contract_sha256
        ),
        max_gpu_hours=lane.gpu_resource.max_gpu_hours,
        max_storage_bytes=lane.gpu_resource.max_storage_bytes,
    )


def _api_model_for(lane: ExecutionLane, system_id: str | None) -> ApiModelResource:
    if lane.api_model is not None:
        if system_id is not None:
            raise ValueError("matched API lane does not accept a system-specific model lookup")
        return lane.api_model
    if system_id is None or lane.system_api_models is None:
        raise ValueError("best-native API lane requires a system-specific model lookup")
    try:
        return next(
            item.api_model for item in lane.system_api_models if item.system_id == system_id
        )
    except StopIteration as exc:
        raise ValueError(f"best-native API model is missing for system {system_id}") from exc


def _cell_blockers(
    system: PrelaunchSystem,
    task: PrelaunchTask,
    lane: ExecutionLane,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if system.availability is not ReadinessStatus.VERIFIED:
        blockers.append(f"system:{system.system_id}:{system.availability.value}")
    if not system.real_implementation or system.implementation_ref is None:
        blockers.append(f"system:{system.system_id}:implementation-unverified")
    if system.role in {SystemRole.CONTROL, SystemRole.METHOD_COMPARATOR} and (
        system.adapter_preflight_ref is None or system.adapter_preflight_sha256 is None
    ):
        blockers.append(f"system:{system.system_id}:adapter-preflight-unbound")
    for label, ready in (
        ("license", task.license_status is ReadinessStatus.VERIFIED),
        ("asset", task.asset_status is ReadinessStatus.VERIFIED),
        ("held-out", task.held_out),
        ("source-disjoint", task.source_group_disjoint),
        (
            "asset-manifest",
            task.selected_asset_manifest is not None and task.asset_manifest_sha256 is not None,
        ),
    ):
        if not ready:
            blockers.append(f"task:{task.task_id}:{label}-unverified")
    if lane.kind in {ExecutionLaneKind.API_ONLY, ExecutionLaneKind.HYBRID}:
        model = _api_model_for(
            lane,
            system.system_id if lane.comparison_regime is ComparisonRegime.BEST_NATIVE else None,
        )
        if model.identity_status is not ReadinessStatus.VERIFIED:
            blockers.append(f"lane:{lane.lane_id}:api-identity-unverified")
        if model.pricing.status is not ReadinessStatus.VERIFIED:
            blockers.append(f"lane:{lane.lane_id}:api-pricing-unverified")
    if lane.gpu_resource is not None:
        readiness = [
            ("local", lane.gpu_resource.local_preflight_status),
            ("inventory", lane.gpu_resource.remote_inventory_status),
        ]
        if lane.gpu_resource.remote_checkpoint_status is not None:
            readiness.append(("checkpoint", lane.gpu_resource.remote_checkpoint_status))
        for label, status in readiness:
            if status is not ReadinessStatus.VERIFIED:
                blockers.append(f"lane:{lane.lane_id}:gpu-{label}-unverified")
    return tuple(sorted(set(blockers)))


def _plan_blockers(
    manifest: ExperimentPrelaunchManifest,
    cells: tuple[PlannedEvaluationCell, ...],
) -> tuple[str, ...]:
    blockers = {blocker for cell in cells for blocker in cell.readiness_blockers}
    if manifest.analysis is None:
        blockers.add("protocol:analysis-contract-missing")
    if manifest.integrity is None:
        blockers.add("protocol:integrity-contract-missing")
    if manifest.source_commit is None:
        blockers.add("protocol:source-commit-unfrozen")
    if manifest.human_review.required:
        for label, status in (
            ("recruitment", manifest.human_review.recruitment_status),
            ("rubric", manifest.human_review.rubric_status),
            ("adjudication", manifest.human_review.adjudication_status),
        ):
            if status is not ReadinessStatus.VERIFIED:
                blockers.add(f"review:{label}-{status.value}")
    return tuple(sorted(blockers))


__all__ = [
    "EvaluationCellPlan",
    "EvaluationCellResource",
    "PlannedEvaluationCell",
    "PlannedEvaluationLane",
    "compile_evaluation_cell_plan",
    "load_evaluation_cell_plan",
    "save_evaluation_cell_plan",
]

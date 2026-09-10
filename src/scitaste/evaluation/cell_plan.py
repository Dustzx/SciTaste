"""Compile one prelaunch proposal into a closed, no-run evaluation-cell plan."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.prelaunch import (
    ExecutionLane,
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    PrelaunchSystem,
    PrelaunchTask,
    ReadinessStatus,
    ScientificLaneRole,
    SystemRole,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


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
    checkpoint_id: str | None = None
    checkpoint_sha256: str | None = Field(default=None, pattern=_SHA256)
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
        gpu_values = (
            self.host_alias,
            self.checkpoint_id,
            self.checkpoint_sha256,
            self.max_gpu_hours,
            self.max_storage_bytes,
        )
        if self.kind is ExecutionLaneKind.API_ONLY:
            if not all(api_values) or any(value is not None for value in gpu_values):
                raise ValueError("API cell resources require only provider/model/key-env identity")
        elif not all(gpu_values) or any(value is not None for value in api_values):
            raise ValueError("GPU cell resources require only host/checkpoint identity")
        return self


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
    resource: EvaluationCellResource
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
        return self


class EvaluationCellPlan(BaseModel):
    """Content-addressed expansion of a proposal, with no execution authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
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
        return self

    @computed_field
    @property
    def plan_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))


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
        resource = _resource_for(lane)
        lane_cells: list[PlannedEvaluationCell] = []
        for system_id in lane.system_ids:
            system = systems[system_id]
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
                resource=resource,
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
    return EvaluationCellPlan(
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


def _resource_for(lane: ExecutionLane) -> EvaluationCellResource:
    if lane.kind is ExecutionLaneKind.API_ONLY:
        assert lane.api_model is not None
        snapshot = lane.api_model.model_dump(mode="json")
        return EvaluationCellResource(
            kind=lane.kind,
            resource_sha256=_canonical_sha256(snapshot),
            provider_id=lane.api_model.provider_id,
            model_id=lane.api_model.model_id,
            model_revision=lane.api_model.model_revision,
            api_key_env=lane.api_model.api_key_env,
            max_input_tokens_per_call=lane.api_model.max_input_tokens_per_call,
            max_output_tokens_per_call=lane.api_model.max_output_tokens_per_call,
            max_requests=lane.api_model.max_requests,
            max_total_tokens=lane.api_model.max_total_tokens,
            max_cost=lane.api_model.max_cost,
        )
    assert lane.gpu_resource is not None
    snapshot = lane.gpu_resource.model_dump(mode="json")
    return EvaluationCellResource(
        kind=lane.kind,
        resource_sha256=_canonical_sha256(snapshot),
        host_alias=lane.gpu_resource.host_alias,
        checkpoint_id=lane.gpu_resource.checkpoint_id,
        checkpoint_sha256=lane.gpu_resource.checkpoint_sha256,
        max_gpu_hours=lane.gpu_resource.max_gpu_hours,
        max_storage_bytes=lane.gpu_resource.max_storage_bytes,
    )


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
    if lane.api_model is not None:
        if lane.api_model.identity_status is not ReadinessStatus.VERIFIED:
            blockers.append(f"lane:{lane.lane_id}:api-identity-unverified")
        if lane.api_model.pricing.status is not ReadinessStatus.VERIFIED:
            blockers.append(f"lane:{lane.lane_id}:api-pricing-unverified")
    if lane.gpu_resource is not None:
        for label, status in (
            ("local", lane.gpu_resource.local_preflight_status),
            ("inventory", lane.gpu_resource.remote_inventory_status),
            ("checkpoint", lane.gpu_resource.remote_checkpoint_status),
        ):
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
    "save_evaluation_cell_plan",
]

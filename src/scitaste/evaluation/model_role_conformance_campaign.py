"""Project-owned, byte-bound scheduling for model-role conformance.

Preparation is local and side-effect limited to project-owned manifests.  It
does not load a model or contact a provider.  Dispatch requests point at the
existing durable model-node runtime (or the dedicated embedding runner where no
generation executor applies) and keep execution behind explicit live/local
flags.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

from scitaste.evaluation.model_role_conformance import (
    ConformanceCase,
    ConformanceCaseManifest,
    ExecutionKind,
    ModelRole,
    ModelRoleConformancePlan,
    PlannedModelRoleCandidate,
    SelectionStatus,
    TaskExclusionContract,
    compile_model_role_selection,
    plan_model_role_conformance,
    save_model_role_document,
)
from scitaste.project import ProjectRuntime

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_BYTES = 8 * 1024 * 1024


class CampaignReadiness(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    COMPLETE = "complete"


class ConformanceRunnerKind(StrEnum):
    MODEL_NODE_RUNTIME = "model_node_runtime"
    EMBEDDING_LOCAL = "embedding_local"


class CampaignCaseReference(BaseModel):
    model_config = _CONFIG

    path: str
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_safe(self) -> CampaignCaseReference:
        _validate_relative(self.path, "campaign case path")
        return self


class CampaignBudget(BaseModel):
    model_config = _CONFIG

    max_api_calls: int = Field(ge=0)
    max_input_tokens_per_call: int = Field(gt=0)
    max_output_tokens_per_call: int = Field(gt=0)
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_api_cost_usd: float = Field(ge=0.0)
    max_local_gpu_hours: float = Field(ge=0.0)
    max_local_cpu_hours: float = Field(ge=0.0)
    max_disk_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def aggregate_covers_calls(self) -> CampaignBudget:
        if self.max_input_tokens < self.max_api_calls * self.max_input_tokens_per_call:
            raise ValueError("campaign input-token budget does not cover all API calls")
        if self.max_output_tokens < self.max_api_calls * self.max_output_tokens_per_call:
            raise ValueError("campaign output-token budget does not cover all API calls")
        return self


class ByteBoundCampaignSpec(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str = Field(pattern=_ID)
    base_suite_ref: str
    base_suite_sha256: str = Field(pattern=_SHA256)
    formal_program_ref: str
    formal_program_sha256: str = Field(pattern=_SHA256)
    formal_partition_source_groups: tuple[str, ...] = Field(min_length=4)
    source_group_overlap_allowed: Literal[False] = False
    cases: tuple[CampaignCaseReference, ...] = Field(min_length=5)
    candidate_ids: tuple[str, ...] = Field(min_length=5)
    repetitions: int = Field(ge=2, le=10)
    api_backend_refs: dict[str, str]
    campaign_budget: CampaignBudget
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def entries_are_unique(self) -> ByteBoundCampaignSpec:
        _unique([item.path for item in self.cases], "campaign case paths")
        _unique(list(self.candidate_ids), "campaign candidate IDs")
        _unique(list(self.formal_partition_source_groups), "formal source groups")
        references = (
            self.base_suite_ref,
            self.formal_program_ref,
            *self.api_backend_refs.values(),
        )
        for value in references:
            _validate_relative(value, "campaign repository reference")
        return self


class ByteBoundCasePayload(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    task_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    role: ModelRole
    selection_scope_id: str = Field(pattern=_ID)
    formal_or_heldout: Literal[False] = False
    objective: str = Field(min_length=1, max_length=4_000)
    payload: dict[str, JsonValue]
    required_response_fields: tuple[str, ...] = Field(min_length=1)
    allowed_tool_names: tuple[str, ...] = ()
    expected: dict[str, JsonValue]


class DispatchResource(BaseModel):
    model_config = _CONFIG

    execution_kind: ExecutionKind
    resource_id: str = Field(pattern=_ID)
    provider: str
    model_id: str
    backend_config_ref: str | None = None
    backend_config_sha256: str | None = Field(default=None, pattern=_SHA256)
    local_model_path: str | None = None
    local_architecture: str | None = None
    exact_checkpoint_hash_resolved: Literal[False] = False

    @model_validator(mode="after")
    def resource_route_is_atomic(self) -> DispatchResource:
        api = (self.backend_config_ref, self.backend_config_sha256)
        local = (self.local_model_path, self.local_architecture)
        if self.execution_kind is ExecutionKind.API:
            if (any(api) and not all(api)) or any(value is not None for value in local):
                raise ValueError("API dispatch requires an atomic backend config binding")
        elif not all(local) or any(value is not None for value in api):
            raise ValueError("local dispatch requires only a local checkpoint binding")
        return self


class ExistingRunnerBinding(BaseModel):
    """Template for the existing executor; it is not execution authority."""

    model_config = _CONFIG

    command: Literal["python -m scitaste.cli model-node runtime execute"]
    node_name: Literal["role-conformance"]
    invocation_id: str = Field(pattern=_ID)
    runtime_config_required: Literal[True] = True
    profile_set_required: Literal[True] = True
    executor_receipt_contract: Literal["scitaste-model-node-runtime-v1"]
    next_command: str = Field(min_length=1)


class ConformanceDispatchRequest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    project_run_id: str = Field(pattern=_ID)
    campaign_id: str = Field(pattern=_ID)
    model_role_plan_sha256: str = Field(pattern=_SHA256)
    candidate: PlannedModelRoleCandidate
    case_id: str = Field(pattern=_ID)
    case_path: str
    case_sha256: str = Field(pattern=_SHA256)
    case_payload: ByteBoundCasePayload
    repetition: int = Field(ge=1)
    runner_kind: ConformanceRunnerKind
    resource: DispatchResource
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_api_cost_usd: float = Field(ge=0.0)
    max_gpu_hours: float = Field(ge=0.0)
    max_disk_bytes: int = Field(gt=0)
    required_execution_flag: Literal["allow-live", "allow-local"]
    readiness: CampaignReadiness
    blockers: tuple[str, ...]
    expected_executor_receipt: Literal[
        "scitaste-model-node-runtime-v1", "scitaste-conformance-execution-v1"
    ]
    existing_runner_binding: ExistingRunnerBinding | None
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def readiness_matches_blockers(self) -> ConformanceDispatchRequest:
        if (self.readiness is CampaignReadiness.READY) == bool(self.blockers):
            raise ValueError("dispatch readiness must equal the absence of blockers")
        if self.candidate.candidate.role is ModelRole.EMBEDDING:
            if self.runner_kind is not ConformanceRunnerKind.EMBEDDING_LOCAL:
                raise ValueError("embedding dispatch requires the embedding runner")
        elif self.runner_kind is not ConformanceRunnerKind.MODEL_NODE_RUNTIME:
            raise ValueError("generative role dispatch requires the model-node runtime")
        expected_flag = (
            "allow-live" if self.resource.execution_kind is ExecutionKind.API else "allow-local"
        )
        if self.required_execution_flag != expected_flag:
            raise ValueError("dispatch execution flag differs from its resource kind")
        if self.case_id != self.case_payload.task_id:
            raise ValueError("dispatch case ID differs from its byte-bound payload")
        if self.candidate.candidate.role is not self.case_payload.role or (
            self.candidate.candidate.selection_scope_id != self.case_payload.selection_scope_id
        ):
            raise ValueError("dispatch candidate and case role/scope differ")
        if self.runner_kind is ConformanceRunnerKind.MODEL_NODE_RUNTIME:
            if self.existing_runner_binding is None:
                raise ValueError("model-node dispatch requires an existing-runner binding")
        elif self.existing_runner_binding is not None:
            raise ValueError("embedding dispatch cannot claim a model-node binding")
        return self

    @property
    def request_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class ByteBoundConformanceCampaignPlan(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    project_run_id: str = Field(pattern=_ID)
    source_spec_sha256: str = Field(pattern=_SHA256)
    formal_program_sha256: str = Field(pattern=_SHA256)
    model_role_plan_ref: str
    model_role_plan_sha256: str = Field(pattern=_SHA256)
    case_manifest_ref: str
    case_manifest_file_sha256: str = Field(pattern=_SHA256)
    case_manifest_sha256: str = Field(pattern=_SHA256)
    formal_partition_source_groups: tuple[str, ...]
    development_source_groups: tuple[str, ...]
    source_groups_disjoint: Literal[True] = True
    budget: CampaignBudget
    model_candidate_ids: tuple[str, ...] = Field(min_length=5)
    task_ids: tuple[str, ...] = Field(min_length=5)
    requests: tuple[ConformanceDispatchRequest, ...] = Field(min_length=1)
    expected_api_calls: int = Field(ge=0)
    expected_local_dispatches: int = Field(ge=0)
    expected_max_gpu_hours: float = Field(ge=0.0)
    expected_max_disk_bytes: int = Field(ge=0)
    execution_authorized: Literal[False] = False
    no_api_call_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True

    @model_validator(mode="after")
    def request_matrix_and_budget_are_closed(self) -> ByteBoundConformanceCampaignPlan:
        _unique([item.request_id for item in self.requests], "dispatch request IDs")
        if set(self.model_candidate_ids) != {
            item.candidate.candidate.candidate_id for item in self.requests
        }:
            raise ValueError("campaign model summary differs from its request matrix")
        if set(self.task_ids) != {item.case_id for item in self.requests}:
            raise ValueError("campaign task summary differs from its request matrix")
        api_calls = sum(item.resource.execution_kind is ExecutionKind.API for item in self.requests)
        local_calls = len(self.requests) - api_calls
        if (api_calls, local_calls) != (
            self.expected_api_calls,
            self.expected_local_dispatches,
        ):
            raise ValueError("campaign dispatch counts differ from the request matrix")
        if api_calls > self.budget.max_api_calls:
            raise ValueError("campaign request matrix exceeds its API-call budget")
        if self.expected_max_gpu_hours > self.budget.max_local_gpu_hours:
            raise ValueError("campaign request matrix exceeds its GPU-hour budget")
        if self.expected_max_disk_bytes > self.budget.max_disk_bytes:
            raise ValueError("campaign request matrix exceeds its disk budget")
        return self

    @computed_field
    @property
    def campaign_plan_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"campaign_plan_sha256"}))


class ByteBoundCampaignStatus(BaseModel):
    model_config = _CONFIG

    campaign_id: str
    campaign_plan_sha256: str = Field(pattern=_SHA256)
    readiness: CampaignReadiness
    ready_requests: int = Field(ge=0)
    blocked_requests: int = Field(ge=0)
    completed_requests: int = Field(ge=0)
    pending_request_ids: tuple[str, ...]
    blocked_request_ids: tuple[str, ...]
    receipt_paths: tuple[str, ...]
    selection_status: SelectionStatus
    selection_ref: str | None
    selection_sha256: str | None = Field(default=None, pattern=_SHA256)
    headline_eligible: bool
    next_action: str


def prepare_bytebound_conformance_campaign(
    spec_path: str | Path,
    *,
    project_id: str,
    run_id: str,
    outputs_root: str | Path = "outputs",
    repository_root: str | Path = ".",
) -> tuple[ByteBoundConformanceCampaignPlan, Path]:
    """Materialize case bytes, scoped requests, and a successor role plan."""

    root = Path(repository_root).resolve(strict=True)
    spec_source, spec = _load_yaml_model(spec_path, ByteBoundCampaignSpec, "campaign spec")
    _verify_bound_file(root, spec.base_suite_ref, spec.base_suite_sha256, "base suite")
    _verify_bound_file(
        root,
        spec.formal_program_ref,
        spec.formal_program_sha256,
        "formal program",
    )
    snapshot = ProjectRuntime(outputs_root).open(project_id)
    if run_id not in {item.run_id for item in snapshot.manifest.runs}:
        raise ValueError(f"project run {run_id!r} is not registered")

    base_plan = plan_model_role_conformance(root / spec.base_suite_ref, repository_root=root)
    candidate_by_id = {item.candidate.candidate_id: item for item in base_plan.candidates}
    try:
        candidates = tuple(candidate_by_id[item] for item in spec.candidate_ids)
    except KeyError as exc:
        message = f"campaign references unknown model-role candidate {exc.args[0]!r}"
        raise ValueError(message) from exc
    cases = tuple(_load_campaign_case(root, item) for item in spec.cases)
    _validate_case_partition(cases, spec.formal_partition_source_groups)
    _validate_candidate_case_coverage(candidates, cases)

    task_hashes = {
        case.task_id: reference.sha256 for case, reference in zip(cases, spec.cases, strict=True)
    }
    source_by_task = {case.task_id: case.source_group_id for case in cases}
    exclusions = TaskExclusionContract(
        conformance_task_ids=tuple(case.task_id for case in cases),
        conformance_source_group_ids=tuple(dict.fromkeys(source_by_task.values())),
        formal_task_ids=base_plan.exclusions.formal_task_ids,
        heldout_task_ids=base_plan.exclusions.heldout_task_ids,
        formal_source_group_ids=tuple(spec.formal_partition_source_groups),
        heldout_source_group_ids=base_plan.exclusions.heldout_source_group_ids,
        formal_or_heldout_inputs_allowed=False,
        conformance_task_bytes_bound=True,
        conformance_tasks_are_planning_labels_only=False,
        conformance_case_input_sha256=task_hashes,
        conformance_source_group_by_task=source_by_task,
    )
    model_role_plan = base_plan.model_copy(
        update={"exclusions": exclusions, "candidates": candidates}
    )
    campaign_root = _campaign_root(outputs_root, project_id, run_id, spec.campaign_id)
    campaign_root.mkdir(parents=True, exist_ok=True)
    role_plan_path = save_model_role_document(
        model_role_plan, campaign_root / "MODEL_ROLE_PLAN.json"
    )
    case_manifest = ConformanceCaseManifest.create(
        manifest_id=f"{spec.campaign_id}-cases",
        cases=tuple(
            ConformanceCase(
                case_id=case.task_id,
                task_id=case.task_id,
                source_group_id=case.source_group_id,
                input_sha256=reference.sha256,
            )
            for case, reference in zip(cases, spec.cases, strict=True)
        ),
        formal_or_heldout_content_present=False,
    )
    case_manifest_path = save_model_role_document(case_manifest, campaign_root / "CASES.json")
    inventory = _load_inventory(root / base_plan.inventory_ref)
    requests = _build_requests(
        spec,
        model_role_plan,
        candidates,
        cases,
        inventory,
        root=root,
        project_id=project_id,
        run_id=run_id,
    )
    api_calls = sum(item.resource.execution_kind is ExecutionKind.API for item in requests)
    local_calls = len(requests) - api_calls
    gpu_hours = sum(item.max_gpu_hours for item in requests)
    disk_bytes = sum(item.max_disk_bytes for item in requests)
    plan = ByteBoundConformanceCampaignPlan(
        campaign_id=spec.campaign_id,
        project_id=project_id,
        project_run_id=run_id,
        source_spec_sha256=_file_sha256(spec_source),
        formal_program_sha256=spec.formal_program_sha256,
        model_role_plan_ref=role_plan_path.relative_to(campaign_root).as_posix(),
        model_role_plan_sha256=model_role_plan.plan_sha256,
        case_manifest_ref=case_manifest_path.relative_to(campaign_root).as_posix(),
        case_manifest_file_sha256=_file_sha256(case_manifest_path),
        case_manifest_sha256=case_manifest.manifest_sha256,
        formal_partition_source_groups=spec.formal_partition_source_groups,
        development_source_groups=tuple(dict.fromkeys(source_by_task.values())),
        budget=spec.campaign_budget,
        model_candidate_ids=tuple(item.candidate.candidate_id for item in candidates),
        task_ids=tuple(case.task_id for case in cases),
        requests=requests,
        expected_api_calls=api_calls,
        expected_local_dispatches=local_calls,
        expected_max_gpu_hours=gpu_hours,
        expected_max_disk_bytes=disk_bytes,
    )
    plan_path = _save_document(plan, campaign_root / "CAMPAIGN_PLAN.json")
    request_root = campaign_root / "requests"
    for request in requests:
        _save_document(request, request_root / f"{request.request_id}.json")
    return plan, plan_path


def inspect_bytebound_conformance_campaign(
    plan_path: str | Path,
) -> ByteBoundCampaignStatus:
    source = _regular_file(plan_path, "byte-bound campaign plan")
    plan = _load_json_model(source, ByteBoundConformanceCampaignPlan, "campaign plan")
    campaign_root = source.parent
    role_plan = _load_json_model(
        campaign_root / plan.model_role_plan_ref,
        ModelRoleConformancePlan,
        "campaign model-role plan",
    )
    if role_plan.plan_sha256 != plan.model_role_plan_sha256:
        raise ValueError("campaign model-role plan hash drift")
    case_manifest_path = campaign_root / plan.case_manifest_ref
    if _file_sha256(_regular_file(case_manifest_path, "campaign case manifest")) != (
        plan.case_manifest_file_sha256
    ):
        raise ValueError("campaign case-manifest file hash drift")
    case_manifest = _load_json_model(
        case_manifest_path,
        ConformanceCaseManifest,
        "campaign case manifest",
    )
    if case_manifest.manifest_sha256 != plan.case_manifest_sha256:
        raise ValueError("campaign case-manifest identity drift")
    for request in plan.requests:
        request_path = campaign_root / "requests" / f"{request.request_id}.json"
        persisted = _load_json_model(
            request_path,
            ConformanceDispatchRequest,
            "campaign dispatch request",
        )
        if persisted != request:
            raise ValueError(f"campaign request file drift: {request.request_id}")
    receipt_root = campaign_root / "receipts"
    receipt_paths = (
        tuple(sorted(receipt_root.glob("*/RUN_RESULT.json"))) if receipt_root.exists() else ()
    )
    completed_ids = {path.parent.name for path in receipt_paths}
    request_ids = {item.request_id for item in plan.requests}
    if not completed_ids <= request_ids:
        raise ValueError("campaign contains receipts for unknown dispatch requests")
    selection = compile_model_role_selection(
        role_plan,
        list(receipt_paths),
        evidence_root=campaign_root,
    )
    selection_path: Path | None = None
    if selection.status is not SelectionStatus.INCOMPLETE:
        selection_path = save_model_role_document(selection, campaign_root / "SELECTION.json")
    blocked = tuple(
        item.request_id
        for item in plan.requests
        if item.readiness is CampaignReadiness.BLOCKED and item.request_id not in completed_ids
    )
    pending = tuple(
        item.request_id
        for item in plan.requests
        if item.readiness is CampaignReadiness.READY and item.request_id not in completed_ids
    )
    if selection.status is SelectionStatus.COMPLETE:
        readiness = CampaignReadiness.COMPLETE
        next_action = "bind SELECTION.json to the project research-program controller"
    elif pending:
        readiness = CampaignReadiness.READY
        next_action = f"dispatch {pending[0]} with its explicit execution flag"
    else:
        readiness = CampaignReadiness.BLOCKED
        next_action = "resolve blocked runner or resource bindings"
    return ByteBoundCampaignStatus(
        campaign_id=plan.campaign_id,
        campaign_plan_sha256=plan.campaign_plan_sha256,
        readiness=readiness,
        ready_requests=sum(item.readiness is CampaignReadiness.READY for item in plan.requests),
        blocked_requests=sum(item.readiness is CampaignReadiness.BLOCKED for item in plan.requests),
        completed_requests=len(completed_ids),
        pending_request_ids=pending,
        blocked_request_ids=blocked,
        receipt_paths=tuple(path.relative_to(campaign_root).as_posix() for path in receipt_paths),
        selection_status=selection.status,
        selection_ref=(
            selection_path.relative_to(campaign_root).as_posix() if selection_path else None
        ),
        selection_sha256=(selection.selection_sha256 if selection_path else None),
        headline_eligible=selection.headline_eligible,
        next_action=next_action,
    )


def load_bytebound_campaign_plan(path: str | Path) -> ByteBoundConformanceCampaignPlan:
    return _load_json_model(path, ByteBoundConformanceCampaignPlan, "campaign plan")


def _build_requests(
    spec: ByteBoundCampaignSpec,
    plan: ModelRoleConformancePlan,
    candidates: tuple[PlannedModelRoleCandidate, ...],
    cases: tuple[ByteBoundCasePayload, ...],
    inventory: dict[str, dict[str, object]],
    *,
    root: Path,
    project_id: str,
    run_id: str,
) -> tuple[ConformanceDispatchRequest, ...]:
    requests: list[ConformanceDispatchRequest] = []
    for candidate in candidates:
        definition = inventory[candidate.candidate.resource_id]
        matching_cases = [
            case
            for case in cases
            if (case.role, case.selection_scope_id)
            == (candidate.candidate.role, candidate.candidate.selection_scope_id)
        ]
        for case in matching_cases:
            for repetition in range(1, spec.repetitions + 1):
                resource, blockers = _dispatch_resource(
                    spec,
                    candidate,
                    definition,
                    root=root,
                )
                runner_kind = (
                    ConformanceRunnerKind.EMBEDDING_LOCAL
                    if candidate.candidate.role is ModelRole.EMBEDDING
                    else ConformanceRunnerKind.MODEL_NODE_RUNTIME
                )
                request_id = _request_id(candidate.candidate.candidate_id, case.task_id, repetition)
                is_local = resource.execution_kind is ExecutionKind.LOCAL
                case_reference = next(
                    item
                    for item in spec.cases
                    if item.sha256 == plan.exclusions.conformance_case_input_sha256[case.task_id]
                )
                runner_blockers = list(blockers)
                binding = None
                if runner_kind is ConformanceRunnerKind.EMBEDDING_LOCAL:
                    runner_blockers.append("embedding-dispatcher-not-implemented")
                else:
                    flag = "--allow-local" if is_local else "--allow-live"
                    binding = ExistingRunnerBinding(
                        command="python -m scitaste.cli model-node runtime execute",
                        node_name="role-conformance",
                        invocation_id=request_id,
                        executor_receipt_contract="scitaste-model-node-runtime-v1",
                        next_command=(
                            "python -m scitaste.cli model-node runtime execute "
                            f"--project-id {project_id} --run-id {run_id} "
                            f"--invocation-id {request_id} --expected-revision "
                            "<CURRENT_PROJECT_REVISION> --config <RUNTIME_CONFIG_JSON> "
                            "--profile-set <PROFILE_SET_YAML> "
                            f"--profile-id {candidate.profile.profile_id} {flag}"
                        ),
                    )
                requests.append(
                    ConformanceDispatchRequest(
                        request_id=request_id,
                        project_id=project_id,
                        project_run_id=run_id,
                        campaign_id=spec.campaign_id,
                        model_role_plan_sha256=plan.plan_sha256,
                        candidate=candidate,
                        case_id=case.task_id,
                        case_path=case_reference.path,
                        case_sha256=plan.exclusions.conformance_case_input_sha256[case.task_id],
                        case_payload=case,
                        repetition=repetition,
                        runner_kind=runner_kind,
                        resource=resource,
                        max_input_tokens=spec.campaign_budget.max_input_tokens_per_call,
                        max_output_tokens=spec.campaign_budget.max_output_tokens_per_call,
                        max_api_cost_usd=(
                            0.0
                            if is_local
                            else spec.campaign_budget.max_api_cost_usd
                            / max(spec.campaign_budget.max_api_calls, 1)
                        ),
                        max_gpu_hours=(
                            0.25
                            if is_local and runner_kind is ConformanceRunnerKind.MODEL_NODE_RUNTIME
                            else 0.0
                        ),
                        max_disk_bytes=32 * 1024 * 1024,
                        required_execution_flag="allow-local" if is_local else "allow-live",
                        readiness=(
                            CampaignReadiness.BLOCKED
                            if runner_blockers
                            else CampaignReadiness.READY
                        ),
                        blockers=tuple(runner_blockers),
                        expected_executor_receipt=(
                            "scitaste-conformance-execution-v1"
                            if runner_kind is ConformanceRunnerKind.EMBEDDING_LOCAL
                            else "scitaste-model-node-runtime-v1"
                        ),
                        existing_runner_binding=binding,
                    )
                )
    return tuple(requests)


def _dispatch_resource(
    spec: ByteBoundCampaignSpec,
    candidate: PlannedModelRoleCandidate,
    definition: dict[str, object],
    *,
    root: Path,
) -> tuple[DispatchResource, list[str]]:
    declared = candidate.candidate.identity
    blockers: list[str] = []
    if declared.execution_kind is ExecutionKind.API:
        try:
            ref = spec.api_backend_refs[candidate.candidate.resource_id]
        except KeyError:
            ref = ""
            blockers.append("api-backend-config-not-bound")
        config_sha = None
        if ref:
            config_path = _resolve(root, ref, "API backend config")
            config_sha = _file_sha256(config_path)
            payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or (payload.get("provider"), payload.get("model")) != (
                declared.provider,
                declared.model_id,
            ):
                blockers.append("api-backend-identity-drift")
        return (
            DispatchResource(
                execution_kind=ExecutionKind.API,
                resource_id=candidate.candidate.resource_id,
                provider=declared.provider,
                model_id=declared.model_id,
                backend_config_ref=ref or None,
                backend_config_sha256=config_sha,
            ),
            blockers,
        )
    source_root = str(definition["source_root"])
    path_name = str(definition["path_name"])
    model_path = Path(source_root) / path_name
    if not model_path.is_dir():
        blockers.append("local-model-directory-missing")
    architecture = definition.get("architecture")
    if not isinstance(architecture, str) or not architecture:
        blockers.append("local-model-architecture-missing")
        architecture = "unknown"
    return (
        DispatchResource(
            execution_kind=ExecutionKind.LOCAL,
            resource_id=candidate.candidate.resource_id,
            provider=declared.provider,
            model_id=declared.model_id,
            local_model_path=str(model_path),
            local_architecture=architecture,
        ),
        blockers,
    )


def _load_inventory(path: Path) -> dict[str, dict[str, object]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("model inventory root must be an object")
    sources = {
        str(item["source_id"]): item
        for item in payload.get("sources", [])
        if isinstance(item, dict) and "source_id" in item
    }
    local_source = sources.get("local-weights-20260915")
    if not isinstance(local_source, dict) or not isinstance(local_source.get("root"), str):
        raise ValueError("model inventory omits the observed local source root")
    result: dict[str, dict[str, object]] = {}
    for item in payload.get("api_models", []):
        if isinstance(item, dict):
            result[str(item["resource_id"])] = dict(item)
    for item in payload.get("local_assets", []):
        if isinstance(item, dict):
            result[str(item["asset_id"])] = {**item, "source_root": local_source["root"]}
    return result


def _validate_candidate_case_coverage(
    candidates: tuple[PlannedModelRoleCandidate, ...],
    cases: tuple[ByteBoundCasePayload, ...],
) -> None:
    candidate_scopes = {
        (item.candidate.role, item.candidate.selection_scope_id) for item in candidates
    }
    case_scopes = {(item.role, item.selection_scope_id) for item in cases}
    if candidate_scopes != case_scopes:
        raise ValueError("campaign candidates and cases must cover identical role/scope cells")


def _validate_case_partition(
    cases: tuple[ByteBoundCasePayload, ...],
    formal_groups: tuple[str, ...],
) -> None:
    _unique([item.task_id for item in cases], "byte-bound task IDs")
    development = {item.source_group_id for item in cases}
    overlap = development & set(formal_groups)
    if overlap:
        raise ValueError("development and E1-E4 formal source groups overlap")
    if any(not item.source_group_id.startswith("b0-dev-") for item in cases):
        raise ValueError("B0 development source groups must use the b0-dev namespace")


def _load_campaign_case(root: Path, reference: CampaignCaseReference) -> ByteBoundCasePayload:
    source = _verify_bound_file(root, reference.path, reference.sha256, "campaign case")
    return _load_json_model(source, ByteBoundCasePayload, "campaign case")


def _campaign_root(
    outputs_root: str | Path,
    project_id: str,
    run_id: str,
    campaign_id: str,
) -> Path:
    return (
        Path(outputs_root)
        / "projects"
        / project_id
        / "runs"
        / run_id
        / "model_role_conformance"
        / campaign_id
    )


def _request_id(candidate_id: str, task_id: str, repetition: int) -> str:
    digest = _canonical_sha256([candidate_id, task_id, repetition])[:20]
    return f"b0-{digest}-r{repetition}"


def _load_yaml_model(path: str | Path, model: type[BaseModel], label: str):
    source = _regular_file(path, label)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root must be an object")
    return source, model.model_validate(payload)


def _load_json_model(path: str | Path, model: type[BaseModel], label: str):
    source = _regular_file(path, label)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must contain UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root must be an object")
    for field in ("campaign_plan_sha256", "request_sha256", "plan_sha256"):
        if field in payload and field in getattr(model, "model_computed_fields", {}):
            serialized = payload.pop(field)
            document = model.model_validate(payload)
            if getattr(document, field) != serialized:
                raise ValueError(f"{label} serialized hash is invalid")
            return document
    return model.model_validate(payload)


def _save_document(document: BaseModel, path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("campaign output cannot be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = document.model_dump_json(indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _verify_bound_file(root: Path, ref: str, expected: str, label: str) -> Path:
    source = _resolve(root, ref, label)
    if _file_sha256(source) != expected:
        raise ValueError(f"{label} hash drift")
    return source


def _resolve(root: Path, ref: str, label: str) -> Path:
    _validate_relative(ref, f"{label} path")
    try:
        source = (root / PurePosixPath(ref)).resolve(strict=True)
        source.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(f"{label} is missing or escapes the repository") from exc
    return _regular_file(source, label)


def _regular_file(path: str | Path, label: str) -> Path:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    if source.stat().st_size > _MAX_BYTES:
        raise ValueError(f"{label} exceeds its size limit")
    return source.resolve(strict=True)


def _validate_relative(value: str, label: str) -> None:
    path = PurePosixPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "//" in value
    ):
        raise ValueError(f"{label} must be a normalized relative POSIX path")


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


__all__ = [
    "ByteBoundCampaignSpec",
    "ByteBoundCampaignStatus",
    "ByteBoundConformanceCampaignPlan",
    "CampaignReadiness",
    "ConformanceDispatchRequest",
    "ConformanceRunnerKind",
    "ExistingRunnerBinding",
    "inspect_bytebound_conformance_campaign",
    "load_bytebound_campaign_plan",
    "prepare_bytebound_conformance_campaign",
]

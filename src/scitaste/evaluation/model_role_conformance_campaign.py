"""Project-owned, byte-bound scheduling for model-role conformance.

Preparation is local and side-effect limited to project-owned manifests.  It
does not load a model or contact a provider.  Dispatch requests point at the
existing durable model-node runtime (or the dedicated embedding runner where no
generation executor applies) and keep execution behind explicit live/local
flags.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import shlex
import tempfile
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field, model_validator

from scitaste.backends.checkpoint_manifest import (
    LocalCheckpointIdentityManifest,
    build_local_checkpoint_identity_manifest,
)
from scitaste.backends.local_transformers import LocalTransformersConfig
from scitaste.evaluation.model_role_conformance import (
    ConformanceCase,
    ConformanceCaseManifest,
    ConformanceCaseResult,
    ConformanceCaseResults,
    ConformanceMeasurements,
    EvidenceArtifact,
    EvidenceKind,
    EvidenceValidator,
    ExactModelIdentity,
    ExecutionKind,
    IdentityScope,
    ModelRole,
    ModelRoleConformancePlan,
    ModelRoleConformanceRunResult,
    PlannedModelRoleCandidate,
    SelectionStatus,
    TaskExclusionContract,
    compile_model_role_selection,
    plan_model_role_conformance,
    save_model_role_document,
)
from scitaste.model_nodes.models import (
    CumulativeProjectBudget,
    NodeAdmissionBudget,
    NodePolicy,
    ProviderGenerationEnvelope,
)
from scitaste.model_nodes.openai_compatible import (
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import (
    ModelNodeProfile,
    ModelNodeProfileReference,
    ModelNodeProfileSet,
    load_model_node_profile_set,
)
from scitaste.model_nodes.role_conformance import RoleConformanceInput
from scitaste.model_nodes.runtime import RuntimeLedgerEntry, RuntimeOutcome
from scitaste.model_nodes.runtime_config import (
    LiveRuntimeBackend,
    LocalRuntimeBackend,
    ModelNodeRuntimeConfig,
    load_model_node_runtime_config,
)
from scitaste.project import ProjectRuntime

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_BYTES = 8 * 1024 * 1024


class CampaignReadiness(StrEnum):
    REQUEST_PREPARED = "request-prepared"
    LAUNCH_READY = "launch-ready"
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
    exact_checkpoint_hash_resolved: bool = False
    local_checkpoint_sha256: str | None = Field(default=None, pattern=_SHA256)
    local_revision: str | None = None
    local_checkpoint_manifest_ref: str | None = None
    local_checkpoint_manifest_file_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def resource_route_is_atomic(self) -> DispatchResource:
        api = (self.backend_config_ref, self.backend_config_sha256)
        local = (self.local_model_path, self.local_architecture)
        if self.execution_kind is ExecutionKind.API:
            if (
                (any(api) and not all(api))
                or any(value is not None for value in local)
                or self.local_checkpoint_sha256 is not None
                or self.local_revision is not None
                or self.local_checkpoint_manifest_ref is not None
                or self.local_checkpoint_manifest_file_sha256 is not None
                or self.exact_checkpoint_hash_resolved
            ):
                raise ValueError("API dispatch requires an atomic backend config binding")
        else:
            if not all(local) or any(value is not None for value in api):
                raise ValueError("local dispatch requires only a local checkpoint binding")
            exact = (
                self.local_checkpoint_sha256,
                self.local_revision,
                self.local_checkpoint_manifest_ref,
                self.local_checkpoint_manifest_file_sha256,
            )
            if self.exact_checkpoint_hash_resolved != all(exact):
                raise ValueError("local exact-identity status differs from its bindings")
        return self


class ExistingRunnerBinding(BaseModel):
    """Template for the existing executor; it is not execution authority."""

    model_config = _CONFIG

    command: Literal["python -m scitaste.cli model-node runtime execute"]
    node_name: Literal["role-conformance"]
    invocation_id: str = Field(pattern=_ID)
    runtime_config_required: Literal[True] = True
    profile_set_required: Literal[True] = True
    runtime_config_ref: str | None = None
    runtime_config_sha256: str | None = Field(default=None, pattern=_SHA256)
    profile_set_ref: str | None = None
    profile_set_sha256: str | None = Field(default=None, pattern=_SHA256)
    receipt_output_root: str
    recording_output_locator: str
    campaign_run_result_ref: str
    receipt_adapter_state: Literal["required-after-execution"]
    executor_receipt_contract: Literal["scitaste-model-node-runtime-v1"]
    next_command: str = Field(min_length=1)

    @model_validator(mode="after")
    def materialized_files_are_atomic(self) -> ExistingRunnerBinding:
        runtime = (self.runtime_config_ref, self.runtime_config_sha256)
        profile = (self.profile_set_ref, self.profile_set_sha256)
        if any(runtime) != all(runtime) or any(profile) != all(profile):
            raise ValueError("executor binding files require atomic ref/hash pairs")
        if bool(all(runtime)) != bool(all(profile)):
            raise ValueError("runtime config and profile set must be materialized together")
        return self

    @property
    def materialized(self) -> bool:
        return all(
            (
                self.runtime_config_ref,
                self.runtime_config_sha256,
                self.profile_set_ref,
                self.profile_set_sha256,
            )
        )


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
        if (self.readiness is CampaignReadiness.BLOCKED) != bool(self.blockers):
            raise ValueError("blocked dispatch state must equal the presence of blockers")
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
        launch_bound = bool(
            self.existing_runner_binding is not None
            and self.existing_runner_binding.materialized
            and (
                self.resource.execution_kind is ExecutionKind.API
                or self.resource.exact_checkpoint_hash_resolved
            )
        )
        if (self.readiness is CampaignReadiness.LAUNCH_READY) != launch_bound:
            raise ValueError("launch-ready requires materialized executor and exact identity")
        return self

    @property
    def request_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))

    @property
    def execution_payload_sha256(self) -> str:
        return _canonical_sha256(
            self.model_dump(
                mode="json",
                exclude={"readiness", "blockers", "existing_runner_binding"},
            )
        )


class ModelSelectionGuard(BaseModel):
    model_config = _CONFIG

    default_model_candidate_id: Literal[None] = None
    qwen3_vl_2b_role: Literal["low-cost-lower-bound-only"]
    inventory_presence_selects_model: Literal[False] = False
    all_registered_inventory_candidates_supported: Literal[True] = True
    task_required_external_candidates_supported: Literal[True] = True
    external_candidate_max_download_bytes: Literal[10_000_000_000]
    role_scope_selection_requires_task_excluded_receipts: Literal[True] = True

    @property
    def guard_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"guard_sha256"}))


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
    model_selection_guard: ModelSelectionGuard
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
    request_prepared_requests: int = Field(ge=0)
    launch_ready_requests: int = Field(ge=0)
    blocked_requests: int = Field(ge=0)
    completed_requests: int = Field(ge=0)
    request_prepared_ids: tuple[str, ...]
    launch_ready_request_ids: tuple[str, ...]
    blocked_request_ids: tuple[str, ...]
    blocker_counts: dict[str, int]
    receipt_paths: tuple[str, ...]
    selection_status: SelectionStatus
    selection_ref: str | None
    selection_sha256: str | None = Field(default=None, pattern=_SHA256)
    headline_eligible: bool
    next_action: str


class RuntimeReceiptImportStatus(BaseModel):
    model_config = _CONFIG

    campaign_id: str
    imported_request_ids: tuple[str, ...]
    imported_entries: int = Field(ge=0)
    accepted_entries: int = Field(ge=0)
    unsuccessful_entries: int = Field(ge=0)
    task_succeeded_entries: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)
    no_failure_promoted: Literal[True] = True


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
        model_selection_guard=ModelSelectionGuard(
            qwen3_vl_2b_role="low-cost-lower-bound-only",
            external_candidate_max_download_bytes=10_000_000_000,
        ),
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
        if request.readiness is CampaignReadiness.LAUNCH_READY:
            _verify_launch_binding(request, campaign_root=campaign_root)
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
    prepared = tuple(
        item.request_id
        for item in plan.requests
        if item.readiness is CampaignReadiness.REQUEST_PREPARED
        and item.request_id not in completed_ids
    )
    launch_ready = tuple(
        item.request_id
        for item in plan.requests
        if item.readiness is CampaignReadiness.LAUNCH_READY and item.request_id not in completed_ids
    )
    if selection.status is SelectionStatus.COMPLETE:
        readiness = CampaignReadiness.COMPLETE
        next_action = "bind SELECTION.json to the project research-program controller"
    elif launch_ready:
        readiness = CampaignReadiness.LAUNCH_READY
        next_action = f"dispatch {launch_ready[0]} with its explicit execution flag"
    elif prepared:
        readiness = CampaignReadiness.REQUEST_PREPARED
        next_action = (
            "materialize executor bindings and resolve exact local identities before dispatch"
        )
    else:
        readiness = CampaignReadiness.BLOCKED
        next_action = "resolve blocked runner or resource bindings"
    return ByteBoundCampaignStatus(
        campaign_id=plan.campaign_id,
        campaign_plan_sha256=plan.campaign_plan_sha256,
        readiness=readiness,
        request_prepared_requests=len(prepared),
        launch_ready_requests=len(launch_ready),
        blocked_requests=len(blocked),
        completed_requests=len(completed_ids),
        request_prepared_ids=prepared,
        launch_ready_request_ids=launch_ready,
        blocked_request_ids=blocked,
        blocker_counts={
            reason: sum(reason in item.blockers for item in plan.requests)
            for reason in sorted({reason for item in plan.requests for reason in item.blockers})
        },
        receipt_paths=tuple(path.relative_to(campaign_root).as_posix() for path in receipt_paths),
        selection_status=selection.status,
        selection_ref=(
            selection_path.relative_to(campaign_root).as_posix() if selection_path else None
        ),
        selection_sha256=(selection.selection_sha256 if selection_path else None),
        headline_eligible=selection.headline_eligible,
        next_action=next_action,
    )


def materialize_conformance_executor_bindings(
    plan_path: str | Path,
    *,
    repository_root: str | Path = ".",
) -> tuple[ByteBoundConformanceCampaignPlan, Path]:
    """Render existing-runtime inputs without loading or invoking any model."""

    source = _regular_file(plan_path, "byte-bound campaign plan")
    campaign_root = source.parent
    root = Path(repository_root).resolve(strict=True)
    plan = _load_json_model(source, ByteBoundConformanceCampaignPlan, "campaign plan")
    outputs_root = _outputs_root_from_campaign(campaign_root, plan)
    snapshot = ProjectRuntime(outputs_root).open(plan.project_id)
    if plan.project_run_id not in {item.run_id for item in snapshot.manifest.runs}:
        raise ValueError("campaign project run is no longer registered")

    manifest_cache: dict[str, tuple[LocalCheckpointIdentityManifest, Path, str]] = {}
    updated: list[ConformanceDispatchRequest] = []
    for request in plan.requests:
        if request.runner_kind is ConformanceRunnerKind.EMBEDDING_LOCAL:
            updated.append(request)
            continue
        blockers = [item for item in request.blockers if not item.startswith("executor-")]
        resource = request.resource
        checkpoint_manifest_path: Path | None = None
        if resource.execution_kind is ExecutionKind.LOCAL and not blockers:
            assert resource.local_model_path is not None
            try:
                cached = manifest_cache.get(resource.local_model_path)
                if cached is None:
                    manifest = build_local_checkpoint_identity_manifest(resource.local_model_path)
                    checkpoint_manifest_path = (
                        campaign_root / "checkpoint_identities" / f"{resource.resource_id}.json"
                    )
                    _save_document(manifest, checkpoint_manifest_path)
                    cached = (
                        manifest,
                        checkpoint_manifest_path,
                        _file_sha256(checkpoint_manifest_path),
                    )
                    manifest_cache[resource.local_model_path] = cached
                manifest, checkpoint_manifest_path, manifest_file_sha256 = cached
                revision = f"hf-manifest-{manifest.checkpoint_identity_sha256[:12]}"
                resource = resource.model_copy(
                    update={
                        "exact_checkpoint_hash_resolved": True,
                        "local_checkpoint_sha256": manifest.checkpoint_identity_sha256,
                        "local_revision": revision,
                        "local_checkpoint_manifest_ref": checkpoint_manifest_path.relative_to(
                            campaign_root
                        ).as_posix(),
                        "local_checkpoint_manifest_file_sha256": manifest_file_sha256,
                    }
                )
                if not _architecture_available(resource.local_architecture):
                    blockers.append("local-model-architecture-unavailable")
            except (OSError, RuntimeError, ValueError):
                blockers.append("local-checkpoint-identity-unresolved")

        draft = request.model_copy(
            update={
                "resource": resource,
                "readiness": (
                    CampaignReadiness.BLOCKED if blockers else CampaignReadiness.REQUEST_PREPARED
                ),
                "blockers": tuple(dict.fromkeys(blockers)),
            }
        )
        if blockers:
            updated.append(draft)
            continue
        binding = _materialize_model_node_binding(
            draft,
            plan=plan,
            campaign_root=campaign_root,
            outputs_root=outputs_root,
            project_revision=snapshot.revision,
            repository_root=root,
            checkpoint_manifest_path=checkpoint_manifest_path,
        )
        updated.append(
            draft.model_copy(
                update={
                    "existing_runner_binding": binding,
                    "readiness": CampaignReadiness.LAUNCH_READY,
                }
            )
        )

    materialized = plan.model_copy(update={"requests": tuple(updated)})
    materialized_path = _save_document(materialized, source)
    request_root = campaign_root / "requests"
    for request in materialized.requests:
        _save_document(request, request_root / f"{request.request_id}.json")
    return materialized, materialized_path


def import_model_node_runtime_receipts(
    plan_path: str | Path,
    *,
    request_ids: tuple[str, ...] = (),
) -> RuntimeReceiptImportStatus:
    """Adapt actual durable ledger entries into model-role evidence packages."""

    source = _regular_file(plan_path, "byte-bound campaign plan")
    campaign_root = source.parent
    plan = _load_json_model(source, ByteBoundConformanceCampaignPlan, "campaign plan")
    role_plan = _load_json_model(
        campaign_root / plan.model_role_plan_ref,
        ModelRoleConformancePlan,
        "campaign model-role plan",
    )
    outputs_root = _outputs_root_from_campaign(campaign_root, plan)
    request_by_id = {item.request_id: item for item in plan.requests}
    unknown = set(request_ids) - set(request_by_id)
    if unknown:
        raise ValueError(f"unknown campaign request IDs: {sorted(unknown)!r}")
    ledger_root = (
        outputs_root
        / "projects"
        / plan.project_id
        / "runs"
        / plan.project_run_id
        / "model_nodes"
        / "ledger"
    )
    entries: dict[str, tuple[RuntimeLedgerEntry, Path, bytes]] = {}
    if ledger_root.is_dir():
        for path in sorted(ledger_root.glob("*.json")):
            entry = _load_json_model(path, RuntimeLedgerEntry, "model-node ledger entry")
            invocation_id = entry.intent.invocation_id
            if invocation_id in request_by_id:
                if invocation_id in entries:
                    raise ValueError(f"duplicate runtime entry for {invocation_id}")
                entries[invocation_id] = (entry, path, path.read_bytes())
    selected_ids = tuple(request_ids) if request_ids else tuple(sorted(entries))
    missing = set(selected_ids) - set(entries)
    if missing:
        raise ValueError(f"runtime entries are missing: {sorted(missing)!r}")
    if not selected_ids:
        raise ValueError("no campaign runtime entries are available to import")

    validated: dict[str, tuple[ConformanceDispatchRequest, RuntimeLedgerEntry, bytes, bytes]] = {}
    success_by_group: dict[tuple[str, str], list[bool]] = {}
    for request_id in selected_ids:
        request = request_by_id[request_id]
        entry, _, ledger_bytes = entries[request_id]
        recording_path = (
            outputs_root
            / "projects"
            / plan.project_id
            / "runs"
            / plan.project_run_id
            / "model_nodes"
            / "recordings"
            / f"{request_id}.jsonl"
        )
        recording_bytes = _validate_runtime_entry(
            request,
            entry,
            recording_path=recording_path,
            campaign_root=campaign_root,
        )
        succeeded = _runtime_task_succeeded(request, entry)
        group = (request.candidate.candidate.candidate_id, request.case_id)
        success_by_group.setdefault(group, []).append(succeeded)
        validated[request_id] = (request, entry, ledger_bytes, recording_bytes)

    packages = []
    for request_id in selected_ids:
        request, entry, ledger_bytes, recording_bytes = validated[request_id]
        group = (request.candidate.candidate.candidate_id, request.case_id)
        reproducible = len(success_by_group[group]) >= 2 and len(set(success_by_group[group])) == 1
        packages.append(
            _runtime_receipt_package(
                request,
                entry,
                ledger_bytes=ledger_bytes,
                recording_bytes=recording_bytes,
                reproducible=reproducible,
                suite_id=role_plan.suite_id,
            )
        )

    for request_id, files in packages:
        receipt_root = campaign_root / "receipts" / request_id
        for name, payload in files.items():
            _save_bytes(payload, receipt_root / name)
    return RuntimeReceiptImportStatus(
        campaign_id=plan.campaign_id,
        imported_request_ids=selected_ids,
        imported_entries=len(selected_ids),
        accepted_entries=sum(
            entry.outcome is RuntimeOutcome.ACCEPTED for _, entry, _, _ in validated.values()
        ),
        unsuccessful_entries=sum(
            entry.outcome is not RuntimeOutcome.ACCEPTED for _, entry, _, _ in validated.values()
        ),
        task_succeeded_entries=sum(
            _runtime_task_succeeded(request, entry) for request, entry, _, _ in validated.values()
        ),
        input_tokens=sum(entry.input_tokens for _, entry, _, _ in validated.values()),
        output_tokens=sum(entry.output_tokens for _, entry, _, _ in validated.values()),
        cost_usd=sum(float(entry.cost_effect_usd or 0.0) for _, entry, _, _ in validated.values()),
    )


def _validate_runtime_entry(
    request: ConformanceDispatchRequest,
    entry: RuntimeLedgerEntry,
    *,
    recording_path: Path,
    campaign_root: Path,
) -> bytes:
    if request.readiness is not CampaignReadiness.LAUNCH_READY:
        raise ValueError(f"request {request.request_id} was not launch-ready")
    binding = request.existing_runner_binding
    if binding is None:
        raise ValueError("runtime entry request has no executor binding")
    _verify_launch_binding(request, campaign_root=campaign_root)
    intent = entry.intent
    expected_input = {
        **request.case_payload.model_dump(mode="json", exclude={"expected"}),
        "case_id": request.case_id,
    }
    if (
        intent.project_id != request.project_id
        or intent.run_id != request.project_run_id
        or intent.invocation_id != request.request_id
        or intent.request_id != request.request_id
        or intent.node_name != "role-conformance"
        or intent.seed != request.repetition
        or intent.node_input != expected_input
        or intent.context.state_snapshot_id != request.case_sha256
        or intent.context.metadata.get("execution_payload_sha256")
        != request.execution_payload_sha256
    ):
        raise ValueError(f"runtime entry identity drift for {request.request_id}")
    expected_mode = "live" if request.resource.execution_kind is ExecutionKind.API else "local"
    if intent.backend_mode.value != expected_mode:
        raise ValueError("runtime entry backend mode differs from the dispatch request")
    assert binding.profile_set_ref is not None
    profiles = load_model_node_profile_set(
        _resolve_owned_file(campaign_root, binding.profile_set_ref, "profile-set binding")
    )
    profile = profiles.profiles[request.candidate.profile.profile_id]
    if intent.profile != profile or (
        intent.profile.provider,
        intent.profile.model,
    ) != (
        request.resource.provider,
        _exact_dispatch_model(request.resource),
    ):
        raise ValueError("runtime entry model/profile differs from its binding")
    if (
        entry.input_tokens > request.max_input_tokens
        or entry.output_tokens > request.max_output_tokens
        or entry.latency_ms > request.candidate.budget.max_latency_ms
        or (entry.cost_effect_usd is not None and entry.cost_effect_usd > request.max_api_cost_usd)
    ):
        raise ValueError("runtime entry exceeds its frozen request budget")
    if request.resource.execution_kind is ExecutionKind.API and entry.cost_effect_usd is None:
        raise ValueError("API runtime entry has unknown cost")
    if entry.cached or entry.replayed or entry.recording_sha256 is None:
        raise ValueError("runtime entry is not an actual recorded generation")
    recording = _regular_file(recording_path, "model-node runtime recording").read_bytes()
    if hashlib.sha256(recording).hexdigest() != entry.recording_sha256:
        raise ValueError("runtime recording hash differs from its ledger entry")
    if entry.outcome is RuntimeOutcome.ACCEPTED:
        if entry.result is None or entry.result.get("status") != "accepted":
            raise ValueError("accepted runtime entry omits its accepted result")
    elif entry.result is not None and entry.result.get("status") == "accepted":
        raise ValueError("unsuccessful runtime entry cannot contain an accepted result")
    return recording


def _runtime_receipt_package(
    request: ConformanceDispatchRequest,
    entry: RuntimeLedgerEntry,
    *,
    ledger_bytes: bytes,
    recording_bytes: bytes,
    reproducible: bool,
    suite_id: str,
) -> tuple[str, dict[str, bytes]]:
    executor_file_sha256 = hashlib.sha256(ledger_bytes).hexdigest()
    case_manifest = ConformanceCaseManifest.create(
        manifest_id=f"{request.request_id}-case",
        cases=(
            ConformanceCase(
                case_id=request.case_id,
                task_id=request.case_payload.task_id,
                source_group_id=request.case_payload.source_group_id,
                input_sha256=request.case_sha256,
            ),
        ),
        formal_or_heldout_content_present=False,
    )
    case_manifest_bytes = _document_bytes(case_manifest)
    succeeded = _runtime_task_succeeded(request, entry)
    output_sha256 = entry.result_sha256 or entry.entry_sha256
    case_results = ConformanceCaseResults.create(
        case_manifest_sha256=case_manifest.manifest_sha256,
        executor_receipt_file_sha256=executor_file_sha256,
        cases=(
            ConformanceCaseResult(
                case_id=request.case_id,
                succeeded=succeeded,
                output_sha256=output_sha256,
            ),
        ),
    )
    case_results_bytes = _document_bytes(case_results)
    accepted = entry.outcome is RuntimeOutcome.ACCEPTED
    known_cost = float(entry.cost_effect_usd or 0.0)
    within_budget = (
        entry.input_tokens <= request.max_input_tokens
        and entry.output_tokens <= request.max_output_tokens
        and entry.latency_ms <= request.candidate.budget.max_latency_ms
        and known_cost <= request.max_api_cost_usd
    )
    exact_identity = ExactModelIdentity(
        execution_kind=request.resource.execution_kind,
        provider=request.resource.provider,
        model_id=request.resource.model_id,
        revision=request.resource.local_revision,
        route=(
            f"hosted:{request.resource.provider}"
            if request.resource.execution_kind is ExecutionKind.API
            else str(request.resource.local_model_path)
        ),
        scope=(
            IdentityScope.HOSTED_TEMPORAL_WINDOW
            if request.resource.execution_kind is ExecutionKind.API
            else IdentityScope.IMMUTABLE_CHECKPOINT
        ),
        artifact_sha256=(
            request.resource.local_checkpoint_sha256
            if request.resource.execution_kind is ExecutionKind.LOCAL
            else None
        ),
        temporal_window_id=(
            f"{request.campaign_id}-{entry.completed_at:%Y%m%d}"
            if request.resource.execution_kind is ExecutionKind.API
            else None
        ),
        identity_evidence_sha256=executor_file_sha256,
    )
    receipt = ModelRoleConformanceRunResult(
        suite_id=suite_id,
        plan_sha256=request.model_role_plan_sha256,
        run_id=request.request_id,
        candidate_id=request.candidate.candidate.candidate_id,
        role=request.candidate.candidate.role,
        selection_scope_id=request.candidate.candidate.selection_scope_id,
        exact_identity=exact_identity,
        profile_sha256=request.candidate.profile.profile_sha256,
        budget_sha256=request.candidate.budget.budget_sha256,
        task_ids=(request.case_payload.task_id,),
        source_group_ids=(request.case_payload.source_group_id,),
        measurements=ConformanceMeasurements(
            schema_adherence=1.0 if accepted else 0.0,
            tool_adherence=1.0 if accepted else 0.0,
            success=1.0 if succeeded else 0.0,
            context=1.0,
            latency_cost=1.0 if within_budget else 0.0,
            reproducibility=1.0 if reproducible else 0.0,
            task_fit=1.0 if succeeded else 0.0,
            successful_cases=int(succeeded),
            total_cases=1,
            latency_p95_ms=math.ceil(entry.latency_ms),
            cost_usd=float(entry.cost_effect_usd or 0.0),
        ),
        evidence_artifacts=(
            EvidenceArtifact(
                kind=EvidenceKind.EXECUTOR_RECEIPT,
                validator=EvidenceValidator.MODEL_NODE_LEDGER_ENTRY_V1,
                locator=f"receipts/{request.request_id}/RUNTIME_LEDGER_ENTRY.json",
                sha256=executor_file_sha256,
            ),
            EvidenceArtifact(
                kind=EvidenceKind.CASE_MANIFEST,
                validator=EvidenceValidator.CASE_MANIFEST_V1,
                locator=f"receipts/{request.request_id}/CASE_MANIFEST.json",
                sha256=hashlib.sha256(case_manifest_bytes).hexdigest(),
            ),
            EvidenceArtifact(
                kind=EvidenceKind.CASE_RESULTS,
                validator=EvidenceValidator.CASE_RESULTS_V1,
                locator=f"receipts/{request.request_id}/CASE_RESULTS.json",
                sha256=hashlib.sha256(case_results_bytes).hexdigest(),
            ),
        ),
        actual_execution=True,
        inventory_presence_was_not_used_as_result=True,
        formal_or_heldout_content_used=False,
    )
    return request.request_id, {
        "RUNTIME_LEDGER_ENTRY.json": ledger_bytes,
        "RUNTIME_RECORDING.jsonl": recording_bytes,
        "CASE_MANIFEST.json": case_manifest_bytes,
        "CASE_RESULTS.json": case_results_bytes,
        "RUN_RESULT.json": _document_bytes(receipt),
    }


def _runtime_task_succeeded(
    request: ConformanceDispatchRequest,
    entry: RuntimeLedgerEntry,
) -> bool:
    if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
        return False
    proposal = entry.result.get("proposal")
    if not isinstance(proposal, dict) or proposal.get("abstained") is True:
        return False
    response = proposal.get("response")
    if not isinstance(response, dict):
        return False
    expected = request.case_payload.expected
    for key, value in expected.items():
        if key == "replacement_contains":
            replacement = response.get("replacement")
            if not isinstance(replacement, str) or str(value) not in replacement:
                return False
        elif key == "first_tool":
            sequence = response.get("tool_sequence")
            if not isinstance(sequence, list) or not sequence or sequence[0] != value:
                return False
        elif key == "top_document_indices":
            ranking = response.get("ranking")
            if (
                not isinstance(value, list)
                or not isinstance(ranking, list)
                or ranking[: len(value)] != value
            ):
                return False
        elif response.get(key) != value:
            return False
    return True


def _materialize_model_node_binding(
    request: ConformanceDispatchRequest,
    *,
    plan: ByteBoundConformanceCampaignPlan,
    campaign_root: Path,
    outputs_root: Path,
    project_revision: int,
    repository_root: Path,
    checkpoint_manifest_path: Path | None,
) -> ExistingRunnerBinding:
    exact_model = request.resource.model_id
    if request.resource.execution_kind is ExecutionKind.LOCAL:
        assert request.resource.local_revision is not None
        exact_model = f"{exact_model}@{request.resource.local_revision}"
    profile = ModelNodeProfile(
        profile_id=request.candidate.profile.profile_id,
        profile_version=request.candidate.profile.profile_version,
        provider=request.resource.provider,
        model=exact_model,
        allowed_node_names=("role-conformance",),
        live_execution_permitted=request.resource.execution_kind is ExecutionKind.API,
        local_execution_permitted=request.resource.execution_kind is ExecutionKind.LOCAL,
        generation=ProviderGenerationEnvelope(
            max_request_bytes=1_048_576,
            max_output_tokens=request.max_output_tokens,
            context_window_tokens=request.max_input_tokens + request.max_output_tokens,
            deterministic_seed_supported=request.resource.execution_kind is ExecutionKind.LOCAL,
        ),
        admission=NodeAdmissionBudget(
            max_request_bytes=1_048_576,
            max_input_tokens=request.max_input_tokens,
            max_output_tokens=request.max_output_tokens,
            max_total_tokens=request.max_input_tokens + request.max_output_tokens,
            max_latency_ms=request.candidate.budget.max_latency_ms,
            max_response_cost_usd=request.max_api_cost_usd,
            allowed_tool_names=list(request.case_payload.allowed_tool_names),
            max_tool_call_proposals=len(request.case_payload.allowed_tool_names),
        ),
        cumulative_project=CumulativeProjectBudget(
            max_invocations=len(plan.requests),
            max_total_tokens=len(plan.requests)
            * (request.max_input_tokens + request.max_output_tokens),
            max_api_cost_usd=plan.budget.max_api_cost_usd,
        ),
    )
    policy = NodePolicy(
        policy_id=f"{request.request_id}-policy",
        enabled=True,
        allowed_node_names=["role-conformance"],
        expected_backend=request.resource.provider,
        expected_model=exact_model,
        allowed_tool_names=list(request.case_payload.allowed_tool_names),
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    if request.resource.execution_kind is ExecutionKind.API:
        assert request.resource.backend_config_ref is not None
        backend_source = _verify_bound_file(
            repository_root,
            request.resource.backend_config_ref,
            request.resource.backend_config_sha256 or "",
            "API backend config",
        )
        backend_config = load_structured_openai_compatible_config(backend_source).model_copy(
            update={"live_enabled": True, "max_output_tokens": request.max_output_tokens}
        )
        backend = LiveRuntimeBackend(config=backend_config)
    else:
        assert request.resource.local_model_path is not None
        assert request.resource.local_revision is not None
        assert request.resource.local_checkpoint_sha256 is not None
        assert request.resource.local_checkpoint_manifest_file_sha256 is not None
        assert checkpoint_manifest_path is not None
        backend = LocalRuntimeBackend(
            config=LocalTransformersConfig(
                provider=request.resource.provider,
                model_path=Path(request.resource.local_model_path),
                model_id=request.resource.model_id,
                model_revision=request.resource.local_revision,
                checkpoint_identity_manifest_path=checkpoint_manifest_path,
                checkpoint_identity_manifest_file_sha256=(
                    request.resource.local_checkpoint_manifest_file_sha256
                ),
                checkpoint_identity_sha256=request.resource.local_checkpoint_sha256,
                architecture=request.resource.local_architecture or "unknown",
                max_new_tokens=request.max_output_tokens,
                max_context_tokens=request.max_input_tokens + request.max_output_tokens,
                max_retries=0,
                execution_enabled=True,
            )
        )
    runtime_config = ModelNodeRuntimeConfig(
        node_name="role-conformance",
        request_id=request.request_id,
        node_input={
            **request.case_payload.model_dump(mode="json", exclude={"expected"}),
            "case_id": request.case_id,
        },
        state_projection={
            "project_id": request.project_id,
            "state_snapshot_id": request.case_sha256,
            "state_revision": project_revision,
            "stage": "model-role-conformance",
            "metadata": {
                "campaign_id": request.campaign_id,
                "model_role_plan_sha256": request.model_role_plan_sha256,
                "case_sha256": request.case_sha256,
                "execution_payload_sha256": request.execution_payload_sha256,
                "model_selection_guard_sha256": plan.model_selection_guard.guard_sha256,
                "formal_or_heldout": False,
            },
        },
        trigger={
            "trigger_id": request.request_id,
            "reason": "byte-bound task-excluded B0 model-role conformance",
        },
        policy=policy,
        backend=backend,
        seed=request.repetition,
    )
    RoleConformanceInput.model_validate(runtime_config.node_input)
    binding_root = campaign_root / "bindings" / request.request_id
    profile_path = _save_config_document(profile, binding_root / "profile.json")
    profile_set = ModelNodeProfileSet(
        profile_set_id=f"{request.request_id}-profiles",
        profile_set_version="1.0.0",
        live_enabled=request.resource.execution_kind is ExecutionKind.API,
        profiles=(
            ModelNodeProfileReference(
                path=profile_path.name,
                sha256=_file_sha256(profile_path),
                profile_sha256=profile.fingerprint,
            ),
        ),
    )
    profile_set_path = _save_config_document(profile_set, binding_root / "profile-set.json")
    runtime_path = _save_config_document(runtime_config, binding_root / "runtime.json")
    load_model_node_profile_set(profile_set_path)
    load_model_node_runtime_config(runtime_path)
    flag = "--allow-live" if request.required_execution_flag == "allow-live" else "--allow-local"
    command = " ".join(
        (
            "python -m scitaste.cli model-node runtime execute",
            f"--project-id {shlex.quote(request.project_id)}",
            f"--run-id {shlex.quote(request.project_run_id)}",
            f"--invocation-id {shlex.quote(request.request_id)}",
            f"--expected-revision {project_revision}",
            f"--config {shlex.quote(str(runtime_path))}",
            f"--profile-set {shlex.quote(str(profile_set_path))}",
            f"--profile-id {shlex.quote(profile.profile_id)}",
            f"--outputs-root {shlex.quote(str(outputs_root))}",
            flag,
        )
    )
    return ExistingRunnerBinding(
        command="python -m scitaste.cli model-node runtime execute",
        node_name="role-conformance",
        invocation_id=request.request_id,
        runtime_config_ref=runtime_path.relative_to(campaign_root).as_posix(),
        runtime_config_sha256=_file_sha256(runtime_path),
        profile_set_ref=profile_set_path.relative_to(campaign_root).as_posix(),
        profile_set_sha256=_file_sha256(profile_set_path),
        receipt_output_root=(
            f"projects/{request.project_id}/runs/{request.project_run_id}/model_nodes"
        ),
        recording_output_locator=(
            f"projects/{request.project_id}/runs/{request.project_run_id}/model_nodes/"
            f"recordings/{request.request_id}.jsonl"
        ),
        campaign_run_result_ref=f"receipts/{request.request_id}/RUN_RESULT.json",
        receipt_adapter_state="required-after-execution",
        executor_receipt_contract="scitaste-model-node-runtime-v1",
        next_command=command,
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
                        receipt_output_root=(f"projects/{project_id}/runs/{run_id}/model_nodes"),
                        recording_output_locator=(
                            f"projects/{project_id}/runs/{run_id}/model_nodes/recordings/"
                            f"{request_id}.jsonl"
                        ),
                        campaign_run_result_ref=f"receipts/{request_id}/RUN_RESULT.json",
                        receipt_adapter_state="required-after-execution",
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
                            else CampaignReadiness.REQUEST_PREPARED
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


def _save_config_document(document: BaseModel, path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("campaign config output cannot be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = document.model_dump_json(indent=2, exclude_computed_fields=True) + "\n"
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


def _document_bytes(document: BaseModel) -> bytes:
    return (document.model_dump_json(indent=2) + "\n").encode("utf-8")


def _save_bytes(payload: bytes, path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("campaign evidence output cannot be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _exact_dispatch_model(resource: DispatchResource) -> str:
    if resource.execution_kind is ExecutionKind.API:
        return resource.model_id
    if resource.local_revision is None:
        raise ValueError("local dispatch model has no exact revision")
    return f"{resource.model_id}@{resource.local_revision}"


def _outputs_root_from_campaign(
    campaign_root: Path,
    plan: ByteBoundConformanceCampaignPlan,
) -> Path:
    try:
        outputs_root = campaign_root.parents[5]
    except IndexError as exc:
        raise ValueError("campaign plan is outside a project-owned run") from exc
    expected = _campaign_root(
        outputs_root,
        plan.project_id,
        plan.project_run_id,
        plan.campaign_id,
    ).resolve()
    if campaign_root.resolve() != expected:
        raise ValueError("campaign plan path differs from its project/run identity")
    return outputs_root


def _architecture_available(architecture: str | None) -> bool:
    if not architecture or architecture == "unknown":
        return False
    try:
        transformers = importlib.import_module("transformers")
    except ImportError:
        return False
    return getattr(transformers, architecture, None) is not None


def _verify_launch_binding(
    request: ConformanceDispatchRequest,
    *,
    campaign_root: Path,
) -> None:
    binding = request.existing_runner_binding
    if binding is None or not binding.materialized:
        raise ValueError("launch-ready request has no materialized executor binding")
    assert binding.runtime_config_ref is not None
    assert binding.runtime_config_sha256 is not None
    assert binding.profile_set_ref is not None
    assert binding.profile_set_sha256 is not None
    runtime_path = _resolve_owned_file(campaign_root, binding.runtime_config_ref, "runtime binding")
    profile_set_path = _resolve_owned_file(
        campaign_root, binding.profile_set_ref, "profile-set binding"
    )
    if _file_sha256(runtime_path) != binding.runtime_config_sha256:
        raise ValueError("runtime binding hash drift")
    if _file_sha256(profile_set_path) != binding.profile_set_sha256:
        raise ValueError("profile-set binding hash drift")
    runtime = load_model_node_runtime_config(runtime_path).config
    profiles = load_model_node_profile_set(profile_set_path)
    if runtime.node_name != "role-conformance" or runtime.request_id != request.request_id:
        raise ValueError("runtime binding belongs to another conformance request")
    metadata = runtime.state_projection.metadata
    if (
        metadata.get("execution_payload_sha256") != request.execution_payload_sha256
        or metadata.get("case_sha256") != request.case_sha256
        or runtime.policy.expected_backend != request.resource.provider
    ):
        raise ValueError("runtime binding content differs from its dispatch request")
    profile = profiles.profiles.get(request.candidate.profile.profile_id)
    if profile is None:
        raise ValueError("profile-set binding omits the selected role profile")
    if (profile.provider, profile.model) != (
        runtime.policy.expected_backend,
        runtime.policy.expected_model,
    ):
        raise ValueError("runtime and profile identities differ")
    if request.resource.execution_kind is ExecutionKind.LOCAL:
        assert request.resource.local_checkpoint_manifest_ref is not None
        assert request.resource.local_checkpoint_manifest_file_sha256 is not None
        assert request.resource.local_checkpoint_sha256 is not None
        manifest_path = _resolve_owned_file(
            campaign_root,
            request.resource.local_checkpoint_manifest_ref,
            "checkpoint identity manifest",
        )
        if _file_sha256(manifest_path) != (request.resource.local_checkpoint_manifest_file_sha256):
            raise ValueError("checkpoint identity-manifest file hash drift")
        manifest = LocalCheckpointIdentityManifest.model_validate_json(
            manifest_path.read_bytes(), strict=True
        )
        if manifest.checkpoint_identity_sha256 != request.resource.local_checkpoint_sha256:
            raise ValueError("local checkpoint identity differs from its dispatch request")


def _resolve_owned_file(root: Path, ref: str, label: str) -> Path:
    _validate_relative(ref, f"{label} path")
    try:
        source = (root / PurePosixPath(ref)).resolve(strict=True)
        source.relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(f"{label} is missing or escapes the campaign") from exc
    return _regular_file(source, label)


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
    "RuntimeReceiptImportStatus",
    "import_model_node_runtime_receipts",
    "inspect_bytebound_conformance_campaign",
    "load_bytebound_campaign_plan",
    "materialize_conformance_executor_bindings",
    "prepare_bytebound_conformance_campaign",
]

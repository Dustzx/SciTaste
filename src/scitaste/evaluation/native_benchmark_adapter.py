"""First-party adapter from an authorized campaign cell to benchmark research."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.benchmark.study_models import StudyOutcome
from scitaste.evaluation.campaign_execution import (
    EvaluationAdapterResult,
    EvaluationAdapterUsage,
    EvaluationCampaignLaunchConfig,
    EvaluationCampaignManifest,
)
from scitaste.evaluation.cell_plan import (
    EvaluationCellPlan,
    PlannedEvaluationCell,
    load_evaluation_cell_plan,
)
from scitaste.evaluation.h4_execution import (
    BENCHMARK_H4_ACTION_ELIGIBILITY_SHA256,
    BENCHMARK_H4_ACTION_MENU_BUILDER_SHA256,
    BENCHMARK_H4_ACTION_MENU_TEMPLATE_SHA256,
    BENCHMARK_H4_ACTION_ONTOLOGY_SHA256,
    BENCHMARK_H4_ACTION_TO_PATCH_ADAPTER_SHA256,
    BENCHMARK_H4_ADAPTER_IMPLEMENTATION_SHA256,
    BENCHMARK_H4_CONTROLLER_IMPLEMENTATION_SHA256,
    H4ArmRunRequest,
    H4BenchmarkResearchActionProvider,
    H4ExecutionProfile,
    H4PairedResult,
    H4TaskExecutionProfile,
    H4TerminalOutcomeReceipt,
    H4TerminalResourceUsage,
    load_h4_arm_run_request,
    load_h4_execution_profile,
    observe_h4_task_execution_profile,
    observe_h4_task_execution_profile_from_fingerprints,
    save_h4_arm_run_request,
)
from scitaste.evaluation.h4_policy_reproduction import (
    load_h4_policy_reproduction_report,
    load_h4_policy_reproduction_spec,
    reproduce_h4_lifecycle_policy,
)
from scitaste.evaluation.h4_state_probe import (
    inspect_h4_state_probe_manipulation,
    load_h4_state_probe_contract,
    load_h4_state_probe_report,
)
from scitaste.evaluation.native_measurement import NativeBenchmarkObjectiveMeasurement
from scitaste.evaluation.objective_analysis import load_objective_outcome_contract
from scitaste.evaluation.prelaunch import ExecutionLaneKind, load_prelaunch_manifest
from scitaste.evaluation.source_identity import (
    canonical_benchmark_task_source_group_id,
    load_canonical_source_identity_registry,
)
from scitaste.evaluation.task_condition import (
    BenchmarkResearchConditionGuidance,
    BenchmarkResearchGuidanceSet,
    compile_benchmark_condition_guidance,
    load_benchmark_research_guidance_set,
)
from scitaste.evaluation.task_execution import (
    BenchmarkDevelopmentLimits,
    BenchmarkDevelopmentRunner,
    BenchmarkResourceVerificationReceipt,
    load_benchmark_resource_verification_receipt,
    verify_benchmark_execution_resources,
)
from scitaste.evaluation.task_patch import BenchmarkPatchPolicy, hash_editable_surface
from scitaste.evaluation.task_patch_generation import BenchmarkPatchGenerationNode
from scitaste.evaluation.task_research_loop import (
    BenchmarkResearchCellBinding,
    BenchmarkResearchLoop,
    BenchmarkResearchLoopConfig,
    BenchmarkResearchLoopResult,
    RuntimeBenchmarkPatchDecisionProvider,
    bind_benchmark_research_cell,
)
from scitaste.evaluation.task_runtime import (
    BenchmarkTaskRuntimeSpec,
    PreparedBenchmarkWorkspace,
    inspect_benchmark_task_runtime,
    load_benchmark_task_runtime_spec,
    prepare_benchmark_workspace,
)
from scitaste.evaluation.task_scoring import (
    BenchmarkFrozenCandidate,
    BenchmarkHeldoutExecutionReceipt,
    BenchmarkHeldoutRunner,
    BenchmarkHeldoutRunRequest,
    freeze_benchmark_candidate,
    load_benchmark_development_execution_receipt,
)
from scitaste.executor.native_profile import (
    PreparedNativeExecutionProfile,
    inspect_native_execution_profile,
    load_native_execution_profile_request,
    load_prepared_native_execution_profile_record,
    prepare_native_execution_profile,
)
from scitaste.model_nodes.facade import ModelNodeFacade
from scitaste.model_nodes.local_transformers import StructuredLocalTransformersBackend
from scitaste.model_nodes.models import NodePolicy
from scitaste.model_nodes.profiles import (
    ModelNodeProfile,
    load_model_node_profile_set,
    validate_profile_binding,
)
from scitaste.model_nodes.registry import first_party_node_types
from scitaste.model_nodes.runtime import ModelNodeRuntime
from scitaste.model_nodes.runtime_config import (
    LiveRuntimeBackend,
    LocalRuntimeBackend,
    RuntimeBackendBinding,
    ScriptedRuntimeBackend,
)
from scitaste.project import ProjectRuntime, inspect_current_idea_revision
from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.state.research_state import ResourceBudget
from scitaste.taste.conditions import load_native_condition_matrix
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.decision_families import (
    ScientificTasteDecisionFamily,
    load_family_conditioned_lifecycle_taste_policy,
)
from scitaste.taste.intervention import TasteInterventionCondition

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONFIG_BYTES = 1_048_576
_MAX_CELL_REQUEST_BYTES = 4 * 1_048_576


class AdapterFileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @field_validator("locator")
    @classmethod
    def locator_is_safe(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="adapter file locator")


class NativeBenchmarkTaskBinding(BaseModel):
    model_config = _CONFIG

    task_spec: AdapterFileBinding
    development_execution_profile: AdapterFileBinding
    heldout_execution_profile: AdapterFileBinding
    selected_context_paths: tuple[str, ...] = Field(min_length=1, max_length=50)
    failure_directed_progress_penalty: float | None = Field(
        default=None,
        le=0.0,
        allow_inf_nan=False,
    )

    @field_validator("selected_context_paths")
    @classmethod
    def selected_paths_are_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("native benchmark selected context paths must be unique")
        return tuple(
            validate_relative_locator(value, field_name="selected context path") for value in values
        )


class NativeBenchmarkAdapterConfig(BaseModel):
    """Non-secret configuration shared by all native cells in one campaign."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    config_id: str
    condition_matrix: AdapterFileBinding
    guidance_set: AdapterFileBinding | None = None
    guidance_by_task: dict[str, AdapterFileBinding] = Field(
        default_factory=dict,
        max_length=20,
    )
    corpus_pair_report: AdapterFileBinding
    model_profile_set: AdapterFileBinding
    model_profile_id: str
    node_policy: NodePolicy
    backend: RuntimeBackendBinding
    tasks: dict[str, NativeBenchmarkTaskBinding] = Field(min_length=1, max_length=20)
    maximum_patch_iterations: int = Field(default=4, ge=1, le=20)
    maximum_failed_experiments: int = Field(default=2, ge=1, le=10)
    minimum_absolute_improvement: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    constraints: tuple[str, ...] = Field(min_length=1, max_length=64)
    patch_policy: BenchmarkPatchPolicy = Field(default_factory=BenchmarkPatchPolicy)
    development_limits: BenchmarkDevelopmentLimits = Field(
        default_factory=BenchmarkDevelopmentLimits
    )
    h4_execution_profile: AdapterFileBinding | None = None
    lifecycle_policy: AdapterFileBinding | None = None
    h4_policy_reproduction_spec: AdapterFileBinding | None = None
    h4_policy_reproduction_report: AdapterFileBinding | None = None
    source_identity_registry: AdapterFileBinding | None = None
    objective_outcome_contract: AdapterFileBinding | None = None
    h4_state_probe_contract: AdapterFileBinding | None = None
    h4_state_probe_report: AdapterFileBinding | None = None

    @model_validator(mode="after")
    def identities_and_backend_are_closed(self) -> NativeBenchmarkAdapterConfig:
        validate_entry_id(self.config_id, field_name="config_id")
        validate_entry_id(self.model_profile_id, field_name="model_profile_id")
        for task_id in self.tasks:
            validate_entry_id(task_id, field_name="task_id")
        for task_id in self.guidance_by_task:
            validate_entry_id(task_id, field_name="guidance task_id")
        if isinstance(self.backend, ScriptedRuntimeBackend):
            raise ValueError("native benchmark adapter cannot publish scripted evidence")
        identity = (
            (self.backend.config.provider, self.backend.config.model)
            if isinstance(self.backend, LiveRuntimeBackend)
            else (self.backend.config.provider, self.backend.config.model_identity)
        )
        if identity != (self.node_policy.expected_backend, self.node_policy.expected_model):
            raise ValueError("native benchmark backend identity differs from its node policy")
        if "benchmark-research-patch" not in self.node_policy.allowed_node_names:
            raise ValueError("native benchmark node policy does not permit research patches")
        if self.node_policy.allowed_tool_names or self.node_policy.allowed_action_types:
            raise ValueError("native benchmark patch policy cannot grant tools or actions")
        if len(self.constraints) != len(set(self.constraints)):
            raise ValueError("native benchmark constraints must be unique")
        h4_bindings = (
            self.h4_execution_profile,
            self.lifecycle_policy,
            self.h4_policy_reproduction_spec,
            self.h4_policy_reproduction_report,
            self.source_identity_registry,
            self.objective_outcome_contract,
            self.h4_state_probe_contract,
            self.h4_state_probe_report,
        )
        if self.schema_version == "1.1" and any(item is None for item in h4_bindings):
            raise ValueError("native benchmark adapter v1.1 requires complete H4 bindings")
        if self.schema_version == "1.0" and any(item is not None for item in h4_bindings):
            raise ValueError("native benchmark adapter v1.0 cannot carry H4 bindings")
        if self.schema_version == "1.1":
            if self.guidance_set is not None or set(self.guidance_by_task) != set(self.tasks):
                raise ValueError("native H4 requires one task-specific guidance binding per task")
        elif self.guidance_set is None or self.guidance_by_task:
            raise ValueError("legacy native adapter requires one shared guidance binding")
        task_penalties = tuple(
            item.failure_directed_progress_penalty for item in self.tasks.values()
        )
        if self.schema_version == "1.1" and any(item is None for item in task_penalties):
            raise ValueError("native benchmark adapter H4 tasks require failure penalties")
        if self.schema_version == "1.0" and any(item is not None for item in task_penalties):
            raise ValueError("native benchmark adapter v1.0 cannot carry H4 failure penalties")
        return self


class NativeBenchmarkCellRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    evaluation_id: str
    campaign_manifest_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    cell: PlannedEvaluationCell
    adapter_result_path: Path

    @model_validator(mode="after")
    def request_matches_cell(self) -> NativeBenchmarkCellRequest:
        validate_project_id(self.project_id)
        validate_entry_id(self.evaluation_id, field_name="evaluation_id")
        return self


def load_native_benchmark_adapter_config(
    path: str | Path,
) -> NativeBenchmarkAdapterConfig:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_CONFIG_BYTES:
        raise ValueError("native benchmark adapter config must be a bounded regular file")
    raw = source.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
        rendered = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("native benchmark adapter config is invalid") from exc
    _reject_secret_values(payload)
    return NativeBenchmarkAdapterConfig.model_validate_json(rendered, strict=True)


def _reject_secret_values(value: object) -> None:
    if isinstance(value, dict):
        forbidden = {"api_key", "authorization", "bearer_token", "password", "secret"}
        if any(str(key).casefold().replace("-", "_") in forbidden for key in value):
            raise ValueError("native benchmark adapter config contains a credential field")
        for nested in value.values():
            _reject_secret_values(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_values(nested)


class NativeBenchmarkCellRunner:
    """Close one campaign cell from registered inputs through hidden-test evidence."""

    def __init__(
        self,
        repository_root: str | Path,
        config: NativeBenchmarkAdapterConfig,
        request: NativeBenchmarkCellRequest,
        *,
        cell_request_path: str | Path,
    ) -> None:
        self.repository_root = Path(repository_root).resolve(strict=True)
        self.config = config
        self.request = request
        self.cell_request_path = Path(cell_request_path).resolve(strict=True)
        self.cell_directory = self.cell_request_path.parent
        if self.cell_directory.parent.name != "cells":
            raise ValueError("native benchmark cell request is outside a campaign cells directory")
        self.campaign_root = self.cell_directory.parent.parent

    def run(self, *, allow_execution: bool = False) -> EvaluationAdapterResult:
        if not allow_execution:
            raise ValueError("native benchmark adapter requires explicit execution authorization")
        campaign = self._load_campaign()
        cell = self.request.cell
        task_binding = self.config.tasks.get(cell.task_id)
        if task_binding is None:
            raise ValueError("native benchmark adapter has no binding for the selected task")
        spec_path = self._bound_file(task_binding.task_spec)
        spec = load_benchmark_task_runtime_spec(spec_path)
        if spec.task_id != cell.task_id or spec.project_id != self.request.project_id:
            raise ValueError("native benchmark task specification belongs to another cell")
        matrix_path = self._bound_file(self.config.condition_matrix)
        matrix = load_native_condition_matrix(matrix_path)
        if (self.config.schema_version == "1.1") != (matrix.matrix.schema_version == "1.2"):
            raise ValueError("native benchmark H4 adapter and condition matrix differ")
        guidance_binding = (
            self.config.guidance_by_task[cell.task_id]
            if self.config.schema_version == "1.1"
            else self.config.guidance_set
        )
        assert guidance_binding is not None
        guidance = load_benchmark_research_guidance_set(self._bound_file(guidance_binding))
        self._verify_guidance(guidance)
        condition = compile_benchmark_condition_guidance(matrix, guidance, cell.system_id)
        cell_binding = bind_benchmark_research_cell(campaign, cell)

        spec_sha256 = _file_sha256(spec_path)
        task_inspection = inspect_benchmark_task_runtime(
            spec,
            workspace_root=self.repository_root,
            spec_sha256=spec_sha256,
        )
        if not task_inspection.ready_for_development_execution:
            blockers = ",".join(task_inspection.blocker_codes)
            raise ValueError(f"native benchmark task is not execution-ready: {blockers}")

        native_root = self.cell_directory / "native_benchmark"
        if native_root.exists() or native_root.is_symlink():
            raise FileExistsError(native_root)
        native_root.mkdir()
        workspace = native_root / "workspace"
        prepared_workspace = prepare_benchmark_workspace(
            spec,
            task_inspection,
            workspace_root=self.repository_root,
            destination=workspace,
            allow_materialization=True,
        )
        development_profile, development_verification = self._prepare_profile(
            task_binding.development_execution_profile,
            resource_role="development",
        )
        heldout_profile: PreparedNativeExecutionProfile | None = None
        heldout_verification: BenchmarkResourceVerificationReceipt | None = None
        if self.config.schema_version == "1.1":
            # H4 binds both resource profiles before baseline execution while the
            # held-out dataset itself remains outside the model-visible workspace.
            heldout_profile, heldout_verification = self._prepare_profile(
                task_binding.heldout_execution_profile,
                resource_role="heldout",
            )
        profile, backend = self._model_backend(cell, development_profile)

        project_runtime = ProjectRuntime(self.repository_root / "outputs")
        snapshot = project_runtime.open(self.request.project_id)
        facade = ModelNodeFacade(
            ModelNodeRuntime(project_runtime, node_types=first_party_node_types())
        )
        provider = RuntimeBenchmarkPatchDecisionProvider(
            facade,
            project_id=self.request.project_id,
            run_id=campaign.run_id,
            expected_project_revision=snapshot.revision,
            state_revision=snapshot.revision,
            profile=profile,
            policy=self.config.node_policy,
            backend_mode=self.config.backend.mode,
            backend=backend,
            seed=cell.seed,
            allow_live=isinstance(self.config.backend, LiveRuntimeBackend),
            allow_local=isinstance(self.config.backend, LocalRuntimeBackend),
        )
        h4_action_provider: H4BenchmarkResearchActionProvider | None = None
        h4_arm_request: H4ArmRunRequest | None = None
        research_resource_budget: ResourceBudget | None = None
        if self.config.schema_version == "1.1":
            assert heldout_profile is not None
            assert heldout_verification is not None
            (
                h4_action_provider,
                h4_arm_request,
                research_resource_budget,
            ) = self._prepare_h4_action_control(
                campaign=campaign,
                cell_binding=cell_binding,
                spec=spec,
                spec_sha256=spec_sha256,
                prepared_workspace=prepared_workspace,
                development_profile=development_profile,
                development_verification=development_verification,
                heldout_profile=heldout_profile,
                heldout_verification=heldout_verification,
                model_profile=profile,
                guidance=guidance,
                condition=condition,
                project_runtime=project_runtime,
                native_root=native_root,
            )
        development_runner = BenchmarkDevelopmentRunner(
            spec,
            prepared_workspace,
            development_profile,
            development_verification,
            source_root=self.repository_root,
            workspace=workspace,
        )
        loop_directory = native_root / "development_loop"
        loop = BenchmarkResearchLoop(
            spec,
            prepared_workspace,
            provider,
            development_runner,
            research_action_provider=h4_action_provider,
            source_root=self.repository_root,
            workspace=workspace,
        )
        loop_result = loop.run(
            BenchmarkResearchLoopConfig(
                schema_version=("1.1" if h4_arm_request is not None else "1.0"),
                loop_id=f"{cell.cell_id}-research",
                cell=cell_binding,
                condition=condition,
                execution_profile_fingerprint=development_profile.fingerprint,
                resource_verification_receipt_sha256=development_verification.receipt_sha256,
                selected_context_paths=task_binding.selected_context_paths,
                maximum_patch_iterations=self.config.maximum_patch_iterations,
                maximum_failed_experiments=self.config.maximum_failed_experiments,
                minimum_absolute_improvement=self.config.minimum_absolute_improvement,
                constraints=self.config.constraints,
                patch_policy=self.config.patch_policy,
                development_limits=self.config.development_limits,
                h4_arm_run_request_sha256=(
                    h4_arm_request.request_sha256 if h4_arm_request is not None else None
                ),
                research_resource_budget=research_resource_budget,
            ),
            output_directory=loop_directory,
            allow_model_decisions=True,
            allow_source_mutation=True,
            allow_development_execution=True,
        )
        loop_result_path = loop_directory / "RESULT.json"
        if loop_result.status == "failed" or loop_result.best_iteration is None:
            if h4_arm_request is not None and h4_action_provider is not None:
                failure_penalty = h4_action_provider.profile.task_profile(
                    spec.task_id
                ).failure_directed_progress_penalty
                usage = self._usage(loop_result, heldout_executed=False)
                terminal = H4TerminalOutcomeReceipt.create(
                    profile_sha256=h4_action_provider.profile.profile_sha256,
                    arm_run_request_sha256=h4_arm_request.request_sha256,
                    campaign_manifest_sha256=campaign.manifest_sha256,
                    cell_id=cell.cell_id,
                    task_id=cell.task_id,
                    condition=h4_arm_request.condition,
                    failure_stage="development",
                    error_code="development-loop-failed",
                    failure_artifact_sha256=loop_result.result_sha256,
                    last_valid_predecessor_sha256=(
                        loop_result.iterations[-1].iteration_receipt_sha256
                    ),
                    resource_usage=_h4_terminal_resource_usage(usage),
                    usage_accounting="measured",
                )
                terminal_path = native_root / "H4_TERMINAL_OUTCOME.json"
                _write_json(terminal_path, terminal.model_dump(mode="json"))
                measurement = NativeBenchmarkObjectiveMeasurement.create(
                    schema_version="1.1",
                    cell_id=cell.cell_id,
                    task_id=cell.task_id,
                    condition_id=cell.system_id,
                    outcome_status="itt_bounded_failure",
                    frozen_candidate_sha256=None,
                    heldout_receipt_sha256=None,
                    metric_name=spec.primary_metric,
                    metric_direction=spec.metric_direction,
                    heldout_score=None,
                    baseline_heldout_score=spec.baseline_heldout_score,
                    directed_progress=failure_penalty,
                    h4_execution_profile_sha256=(h4_action_provider.profile.profile_sha256),
                    h4_arm_run_request_sha256=h4_arm_request.request_sha256,
                    loop_result_sha256=loop_result.result_sha256,
                    terminal_evidence_sha256=terminal.receipt_sha256,
                    lifecycle_policy_weight=h4_arm_request.lifecycle_policy_weight,
                )
                measurement_path = native_root / "OBJECTIVE_MEASUREMENT.json"
                _write_json(measurement_path, measurement.model_dump(mode="json"))
                evidence = self._write_evidence_index(
                    native_root,
                    campaign,
                    spec,
                    loop_result,
                    heldout=None,
                    measurement=measurement,
                    terminal=terminal,
                )
                return EvaluationAdapterResult(
                    status="failed",
                    evidence_class="real",
                    usage=usage,
                    artifact_paths=self._artifact_paths(
                        loop_result_path,
                        terminal_path,
                        measurement_path,
                        evidence,
                    ),
                    error_code="h4-itt-bounded-failure",
                )
            evidence = self._write_evidence_index(
                native_root,
                campaign,
                spec,
                loop_result,
                heldout=None,
                measurement=None,
                terminal=None,
            )
            return EvaluationAdapterResult(
                status="failed",
                evidence_class="real",
                usage=self._usage(loop_result, heldout_executed=False),
                artifact_paths=self._artifact_paths(loop_result_path, evidence),
                error_code="development-loop-failed",
            )

        development_receipt_path = _best_development_receipt_path(
            loop_directory,
            loop_result.best_iteration,
        )
        development_receipt = load_benchmark_development_execution_receipt(development_receipt_path)
        candidate_path = native_root / "FROZEN_CANDIDATE.json"
        candidate = freeze_benchmark_candidate(
            spec,
            prepared_workspace,
            cell_binding,
            loop_result,
            development_receipt,
            loop_directory=loop_directory,
            workspace=workspace,
            output_path=candidate_path,
        )

        # Hidden data is deliberately unavailable to every model decision above.
        if heldout_profile is None or heldout_verification is None:
            heldout_profile, heldout_verification = self._prepare_profile(
                task_binding.heldout_execution_profile,
                resource_role="heldout",
            )
        heldout_request = BenchmarkHeldoutRunRequest(
            request_id=f"{cell.cell_id}-heldout",
            cell_id=cell.cell_id,
            campaign_manifest_sha256=campaign.manifest_sha256,
            owner_approval_sha256=campaign.evaluation_bundle_sha256,
            cell_binding_sha256=cell_binding.binding_sha256,
            spec_id=spec.spec_id,
            spec_fingerprint=spec.fingerprint,
            prepared_workspace_receipt_sha256=prepared_workspace.receipt_sha256,
            frozen_candidate_sha256=candidate.candidate_sha256,
            execution_profile_fingerprint=heldout_profile.fingerprint,
            resource_verification_receipt_sha256=heldout_verification.receipt_sha256,
            seed=cell.seed,
            limits=self.config.development_limits,
        )
        heldout_root = native_root / "heldout"
        _write_json(heldout_root / "REQUEST.json", heldout_request.model_dump(mode="json"))
        heldout = BenchmarkHeldoutRunner(
            spec,
            prepared_workspace,
            heldout_profile,
            heldout_verification,
            candidate,
            source_root=self.repository_root,
            workspace=workspace,
            loop_directory=loop_directory,
        ).run(
            heldout_request,
            result_directory=heldout_root / "execution",
            allow_heldout_execution=True,
        )
        heldout_result_path = heldout_root / "execution" / "RESULT.json"
        if heldout.status == "failed" or heldout.objective is None:
            if h4_arm_request is not None and h4_action_provider is not None:
                failure_penalty = h4_action_provider.profile.task_profile(
                    spec.task_id
                ).failure_directed_progress_penalty
                usage = self._usage(loop_result, heldout_executed=True)
                terminal = H4TerminalOutcomeReceipt.create(
                    profile_sha256=h4_action_provider.profile.profile_sha256,
                    arm_run_request_sha256=h4_arm_request.request_sha256,
                    campaign_manifest_sha256=campaign.manifest_sha256,
                    cell_id=cell.cell_id,
                    task_id=cell.task_id,
                    condition=h4_arm_request.condition,
                    failure_stage="heldout",
                    error_code=heldout.error_code or "heldout-scoring-failed",
                    failure_artifact_sha256=heldout.receipt_sha256,
                    last_valid_predecessor_sha256=candidate.candidate_sha256,
                    resource_usage=_h4_terminal_resource_usage(usage),
                    usage_accounting="measured",
                )
                terminal_path = native_root / "H4_TERMINAL_OUTCOME.json"
                _write_json(terminal_path, terminal.model_dump(mode="json"))
                measurement = NativeBenchmarkObjectiveMeasurement.create(
                    schema_version="1.1",
                    cell_id=cell.cell_id,
                    task_id=cell.task_id,
                    condition_id=cell.system_id,
                    outcome_status="itt_bounded_failure",
                    frozen_candidate_sha256=candidate.candidate_sha256,
                    heldout_receipt_sha256=heldout.receipt_sha256,
                    metric_name=spec.primary_metric,
                    metric_direction=spec.metric_direction,
                    heldout_score=None,
                    baseline_heldout_score=spec.baseline_heldout_score,
                    directed_progress=failure_penalty,
                    h4_execution_profile_sha256=(h4_action_provider.profile.profile_sha256),
                    h4_arm_run_request_sha256=h4_arm_request.request_sha256,
                    loop_result_sha256=loop_result.result_sha256,
                    terminal_evidence_sha256=terminal.receipt_sha256,
                    lifecycle_policy_weight=h4_arm_request.lifecycle_policy_weight,
                )
                measurement_path = native_root / "OBJECTIVE_MEASUREMENT.json"
                _write_json(measurement_path, measurement.model_dump(mode="json"))
                evidence = self._write_evidence_index(
                    native_root,
                    campaign,
                    spec,
                    loop_result,
                    heldout=heldout,
                    measurement=measurement,
                    terminal=terminal,
                )
                return EvaluationAdapterResult(
                    status="failed",
                    evidence_class="real",
                    usage=usage,
                    artifact_paths=self._artifact_paths(
                        loop_result_path,
                        candidate_path,
                        heldout_result_path,
                        terminal_path,
                        measurement_path,
                        evidence,
                    ),
                    error_code="h4-itt-bounded-failure",
                )
            evidence = self._write_evidence_index(
                native_root,
                campaign,
                spec,
                loop_result,
                heldout=heldout,
                measurement=None,
                terminal=None,
            )
            return EvaluationAdapterResult(
                status="failed",
                evidence_class="real",
                usage=self._usage(loop_result, heldout_executed=True),
                artifact_paths=self._artifact_paths(
                    loop_result_path,
                    candidate_path,
                    heldout_result_path,
                    evidence,
                ),
                error_code="heldout-scoring-failed",
            )

        progress = (
            heldout.objective.score - spec.baseline_heldout_score
            if spec.metric_direction == "higher"
            else spec.baseline_heldout_score - heldout.objective.score
        )
        measurement = NativeBenchmarkObjectiveMeasurement.create(
            schema_version=("1.1" if h4_arm_request is not None else "1.0"),
            cell_id=cell.cell_id,
            task_id=cell.task_id,
            condition_id=cell.system_id,
            frozen_candidate_sha256=candidate.candidate_sha256,
            heldout_receipt_sha256=heldout.receipt_sha256,
            metric_name=spec.primary_metric,
            metric_direction=spec.metric_direction,
            heldout_score=heldout.objective.score,
            baseline_heldout_score=spec.baseline_heldout_score,
            directed_progress=progress,
            h4_execution_profile_sha256=(
                h4_action_provider.profile.profile_sha256
                if h4_action_provider is not None
                else None
            ),
            h4_arm_run_request_sha256=(
                h4_arm_request.request_sha256 if h4_arm_request is not None else None
            ),
            loop_result_sha256=(loop_result.result_sha256 if h4_arm_request is not None else None),
            terminal_evidence_sha256=(
                loop_result.result_sha256 if h4_arm_request is not None else None
            ),
            lifecycle_policy_weight=(
                h4_arm_request.lifecycle_policy_weight if h4_arm_request is not None else None
            ),
        )
        measurement_path = native_root / "OBJECTIVE_MEASUREMENT.json"
        _write_json(measurement_path, measurement.model_dump(mode="json"))
        evidence = self._write_evidence_index(
            native_root,
            campaign,
            spec,
            loop_result,
            heldout=heldout,
            measurement=measurement,
            terminal=None,
        )
        return EvaluationAdapterResult(
            status="succeeded",
            evidence_class="real",
            usage=self._usage(loop_result, heldout_executed=True),
            outcome=_study_outcome(loop_result, progress),
            artifact_paths=self._artifact_paths(
                loop_result_path,
                candidate_path,
                heldout_result_path,
                measurement_path,
                evidence,
            ),
        )

    def _load_campaign(self) -> EvaluationCampaignManifest:
        source = self.campaign_root / "CAMPAIGN.json"
        if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_CONFIG_BYTES:
            raise ValueError("native benchmark campaign manifest is unavailable")
        campaign = EvaluationCampaignManifest.model_validate_json(source.read_bytes())
        cell = self.request.cell
        project_runtime = ProjectRuntime(self.repository_root / "outputs")
        snapshot = project_runtime.open(self.request.project_id)
        evaluation = project_runtime.open_evaluation(
            self.request.project_id,
            self.request.evaluation_id,
        )
        evaluation_root = (
            project_runtime.projects_root
            / self.request.project_id
            / "evaluations"
            / self.request.evaluation_id
        )
        plan_binding = evaluation.files.get("cell_plan")
        manifest_binding = evaluation.files.get("prelaunch_manifest")
        if plan_binding is None or manifest_binding is None:
            raise ValueError("registered evaluation lacks a manifest or cell plan")
        plan = load_evaluation_cell_plan(evaluation_root / plan_binding.locator)
        manifest = load_prelaunch_manifest(evaluation_root / manifest_binding.locator).manifest
        registered = next(
            (item for item in plan.cells if item.cell_id == cell.cell_id),
            None,
        )
        registered_run = next(
            (item for item in snapshot.manifest.runs if item.run_id == campaign.run_id),
            None,
        )
        run_extra = {} if registered_run is None else registered_run.model_extra or {}
        if (
            campaign.project_id != self.request.project_id
            or campaign.evaluation_id != self.request.evaluation_id
            or campaign.manifest_sha256 != self.request.campaign_manifest_sha256
            or campaign.plan_sha256 != self.request.plan_sha256
            or campaign.evaluation_bundle_sha256 != evaluation.bundle_sha256
            or campaign.proposal_sha256 != evaluation.proposal_sha256
            or plan.plan_sha256 != campaign.plan_sha256
            or cell.cell_id not in campaign.selected_cell_ids
            or self.cell_directory.name != cell.cell_id
            or cell.proposal_sha256 != campaign.proposal_sha256
            or registered is None
            or content_sha256(registered) != content_sha256(cell)
            or not cell.ready_for_launch_preparation
            or registered_run is None
            or registered_run.condition != "authorized-evaluation-campaign"
            or registered_run.stage_path != "evaluation_campaign"
            or run_extra.get("evaluation_id") != campaign.evaluation_id
            or run_extra.get("campaign_manifest_sha256") != campaign.manifest_sha256
            or self.campaign_root
            != project_runtime.projects_root
            / self.request.project_id
            / "runs"
            / campaign.run_id
            / "evaluation_campaign"
        ):
            raise ValueError("native benchmark cell request differs from its campaign")
        if self.config.schema_version == "1.1":
            self._verify_h4_campaign_preparation(
                project_runtime,
                snapshot=snapshot,
                campaign=campaign,
                plan=plan,
                manifest=manifest,
            )
        return campaign

    def _verify_h4_campaign_preparation(
        self,
        project_runtime: ProjectRuntime,
        *,
        snapshot,
        campaign: EvaluationCampaignManifest,
        plan: EvaluationCellPlan,
        manifest,
    ) -> None:  # type: ignore[no-untyped-def]
        from scitaste.evaluation.h4_preparation import (
            load_h4_formal_preparation,
            verify_h4_formal_preparation,
        )

        launch_path = self.campaign_root / "LAUNCH_CONFIG.json"
        if launch_path.is_symlink() or not launch_path.is_file():
            raise ValueError("native H4 campaign lacks its launch config")
        launch_config = EvaluationCampaignLaunchConfig.model_validate_json(launch_path.read_bytes())
        binding = launch_config.formal_preparation
        run = next(item for item in snapshot.manifest.runs if item.run_id == campaign.run_id)
        extra = run.model_extra or {}
        if (
            campaign.schema_version != "1.2"
            or campaign.formal_preparation_sha256 is None
            or launch_config.schema_version != "1.1"
            or launch_config.config_sha256 != campaign.launch_config_sha256
            or binding is None
            or binding.preparation_sha256 != campaign.formal_preparation_sha256
            or extra.get("formal_preparation_sha256") != campaign.formal_preparation_sha256
        ):
            raise ValueError("native H4 campaign preparation provenance differs")
        preparation_path = _repository_regular_file(
            self.repository_root,
            binding.locator,
        )
        if _file_sha256(preparation_path) != binding.sha256:
            raise ValueError("native H4 preparation file hash drifted")
        preparation = load_h4_formal_preparation(preparation_path)
        idea = inspect_current_idea_revision(project_runtime, self.request.project_id)
        if idea.current_binding is None or not idea.experiment_freeze_eligible:
            raise ValueError("native H4 current Idea is not experiment-freeze eligible")
        selected = tuple(item for item in plan.cells if item.cell_id in campaign.selected_cell_ids)
        verify_h4_formal_preparation(
            self.repository_root,
            preparation,
            project_id=self.request.project_id,
            evaluation_id=self.request.evaluation_id,
            evaluation_bundle_sha256=campaign.evaluation_bundle_sha256,
            proposal_sha256=campaign.proposal_sha256,
            plan_sha256=campaign.plan_sha256,
            selected_cells=selected,
            current_idea_revision=idea.current_binding,
            launchers=launch_config.launchers,
            prelaunch_manifest=manifest,
        )

    def validate_h4_arm_for_recovery(self) -> H4ArmRunRequest:
        """Rebuild an exposed H4 arm from frozen inputs before crash recovery."""

        if self.config.schema_version != "1.1":
            raise ValueError("H4 recovery requires the formal native adapter")
        campaign = self._load_campaign()
        cell = self.request.cell
        task_binding = self.config.tasks.get(cell.task_id)
        if task_binding is None or task_binding.heldout_execution_profile is None:
            raise ValueError("H4 recovery task bindings are incomplete")
        spec_path = self._bound_file(task_binding.task_spec)
        spec = load_benchmark_task_runtime_spec(spec_path)
        matrix = load_native_condition_matrix(self._bound_file(self.config.condition_matrix))
        guidance_binding = self.config.guidance_by_task[cell.task_id]
        guidance = load_benchmark_research_guidance_set(self._bound_file(guidance_binding))
        self._verify_guidance(guidance)
        condition = compile_benchmark_condition_guidance(matrix, guidance, cell.system_id)
        cell_binding = bind_benchmark_research_cell(campaign, cell)
        inspection = inspect_benchmark_task_runtime(
            spec,
            workspace_root=self.repository_root,
            spec_sha256=_file_sha256(spec_path),
        )
        if not inspection.ready_for_development_execution:
            raise ValueError("H4 recovery canonical task source is no longer ready")
        native_root = self.cell_directory / "native_benchmark"
        arm_path = native_root / "H4_ARM_REQUEST.json"
        observed = load_h4_arm_run_request(arm_path)
        project_runtime = ProjectRuntime(self.repository_root / "outputs")
        recovery_root = self.cell_directory / "recovery"
        if recovery_root.is_symlink() or (recovery_root.exists() and not recovery_root.is_dir()):
            raise ValueError("H4 recovery workspace root is not a regular directory")
        recovery_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".h4-arm-rebuild-", dir=recovery_root) as temporary:
            pristine = prepare_benchmark_workspace(
                spec,
                inspection,
                workspace_root=self.repository_root,
                destination=Path(temporary) / "workspace",
                allow_materialization=True,
            )
            workspace_receipt_path = native_root / "workspace.receipt.json"
            if workspace_receipt_path.is_symlink() or not workspace_receipt_path.is_file():
                raise ValueError("H4 recovery workspace receipt is unavailable")
            recorded_workspace = PreparedBenchmarkWorkspace.model_validate_json(
                workspace_receipt_path.read_bytes(), strict=True
            )
            if recorded_workspace != pristine:
                raise ValueError("H4 recovery workspace receipt differs from canonical source")
            development_profile, development_verification = self._prepare_profile(
                task_binding.development_execution_profile,
                resource_role="development",
            )
            heldout_profile, heldout_verification = self._prepare_profile(
                task_binding.heldout_execution_profile,
                resource_role="heldout",
            )
            model_profile, _backend = self._model_backend(cell, development_profile)
            _provider, expected, _budget = self._prepare_h4_action_control(
                campaign=campaign,
                cell_binding=cell_binding,
                spec=spec,
                spec_sha256=_file_sha256(spec_path),
                prepared_workspace=pristine,
                development_profile=development_profile,
                development_verification=development_verification,
                heldout_profile=heldout_profile,
                heldout_verification=heldout_verification,
                model_profile=model_profile,
                guidance=guidance,
                condition=condition,
                project_runtime=project_runtime,
                native_root=native_root,
                persist_arm_request=False,
                prepared_workspace_root=Path(temporary),
            )
        if observed != expected:
            raise ValueError("H4 recovery arm differs from its frozen runtime reconstruction")
        return observed

    def _bound_file(self, binding: AdapterFileBinding) -> Path:
        candidate = self.repository_root.joinpath(*Path(binding.locator).parts)
        if candidate.is_symlink():
            raise ValueError("native benchmark bound file cannot be a symbolic link")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(self.repository_root) or not resolved.is_file():
            raise ValueError("native benchmark bound file escapes the repository")
        if _file_sha256(resolved) != binding.sha256:
            raise ValueError(f"native benchmark bound file hash drift: {binding.locator}")
        return resolved

    def _verify_guidance(self, guidance: BenchmarkResearchGuidanceSet) -> None:
        corpus = self._bound_file(self.config.corpus_pair_report)
        if _file_sha256(corpus) != guidance.corpus_pair_report_sha256:
            raise ValueError("benchmark guidance binds another corpus-pair report")
        for artifact in (
            guidance.utility,
            guidance.knowledge,
            guidance.matched_taste,
            guidance.mismatched_taste,
            guidance.critic,
        ):
            source = self.repository_root.joinpath(*Path(artifact.source_locator).parts)
            derivation = self.repository_root.joinpath(
                *Path(artifact.derivation_receipt_locator).parts
            )
            _verify_repository_file(
                self.repository_root,
                source,
                artifact.source_sha256,
                label="guidance source",
            )
            _verify_repository_file(
                self.repository_root,
                derivation,
                artifact.derivation_receipt_sha256,
                label="guidance derivation",
            )

    def _prepare_profile(
        self,
        binding: AdapterFileBinding,
        *,
        resource_role: Literal["development", "heldout"],
    ) -> tuple[PreparedNativeExecutionProfile, BenchmarkResourceVerificationReceipt]:
        profile_path = self._bound_file(binding)
        root = self.campaign_root / "native_resources" / self.request.cell.task_id / resource_role
        root.mkdir(parents=True, exist_ok=True)
        receipt_path = root / "RESOURCE_VERIFICATION.json"
        with (root / ".resource.lock").open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            if receipt_path.is_file() and not receipt_path.is_symlink():
                request = load_native_execution_profile_request(profile_path)
                prepared = load_prepared_native_execution_profile_record(
                    request,
                    run_root=root,
                )
                receipt = load_benchmark_resource_verification_receipt(
                    receipt_path,
                    prepared,
                )
            else:
                inspection = inspect_native_execution_profile(profile_path)
                prepared = prepare_native_execution_profile(inspection, run_root=root)
                receipt = verify_benchmark_execution_resources(
                    prepared,
                    receipt_path=receipt_path,
                    verified_during_materialization=True,
                )
        return prepared, receipt

    def _model_backend(
        self,
        cell: PlannedEvaluationCell,
        development_profile: PreparedNativeExecutionProfile,
    ) -> tuple[object, object]:
        profile_set_path = self._bound_file(self.config.model_profile_set)
        loaded = load_model_node_profile_set(profile_set_path)
        if loaded.source_sha256 != self.config.model_profile_set.sha256:
            raise ValueError("native benchmark model profile-set hash mismatch")
        try:
            profile = loaded.profiles[self.config.model_profile_id]
        except KeyError as exc:
            raise ValueError("native benchmark model profile is unavailable") from exc
        validate_profile_binding(
            profile,
            self.config.node_policy,
            node_name="benchmark-research-patch",
        )
        backend = self.config.backend.build(f"{cell.cell_id}-research")
        resource = cell.resource
        if isinstance(self.config.backend, LiveRuntimeBackend):
            backend_config = self.config.backend.config
            if (
                resource.kind is not ExecutionLaneKind.API_ONLY
                or resource.provider_id != backend_config.provider
                or resource.model_id != backend_config.model
                or resource.api_key_env != backend_config.api_key_env
                or not profile.live_execution_permitted
                or self.config.maximum_patch_iterations > int(resource.max_requests or 0)
                or profile.admission.max_input_tokens > int(resource.max_input_tokens_per_call or 0)
                or profile.admission.max_output_tokens
                > int(resource.max_output_tokens_per_call or 0)
                or self.config.maximum_patch_iterations * profile.admission.max_total_tokens
                > int(resource.max_total_tokens or 0)
                or self.config.maximum_patch_iterations * profile.admission.max_response_cost_usd
                > float(resource.max_cost or 0)
            ):
                raise ValueError("native benchmark live model differs from cell resources")
        elif isinstance(self.config.backend, LocalRuntimeBackend):
            backend_config = self.config.backend.config
            matching_models = [
                item
                for item in development_profile.external_resources
                if item.resource_kind == "model"
                and item.content_sha256 == backend_config.checkpoint_sha256
                and item.source_path.resolve(strict=True)
                == backend_config.model_path.expanduser().resolve(strict=True)
            ]
            if (
                resource.kind is not ExecutionLaneKind.GPU
                or resource.checkpoint_sha256 != backend_config.checkpoint_sha256
                or not profile.local_execution_permitted
                or development_profile.profile.gpu.max_gpu_hours
                > float(resource.max_gpu_hours or 0)
                or len(matching_models) != 1
                or not isinstance(backend, StructuredLocalTransformersBackend)
            ):
                raise ValueError("native benchmark local model differs from cell resources")
            backend.accept_campaign_checkpoint_verification(
                model_path=matching_models[0].source_path,
                checkpoint_sha256=matching_models[0].content_sha256,
            )
        else:  # pragma: no cover - schema validation already rejects scripted bindings
            raise ValueError("native benchmark adapter requires a real model backend")
        return profile, backend

    def _prepare_h4_action_control(
        self,
        *,
        campaign: EvaluationCampaignManifest,
        cell_binding: BenchmarkResearchCellBinding,
        spec: BenchmarkTaskRuntimeSpec,
        spec_sha256: str,
        prepared_workspace: PreparedBenchmarkWorkspace,
        development_profile: PreparedNativeExecutionProfile,
        development_verification: BenchmarkResourceVerificationReceipt,
        heldout_profile: PreparedNativeExecutionProfile,
        heldout_verification: BenchmarkResourceVerificationReceipt,
        model_profile: ModelNodeProfile,
        guidance: BenchmarkResearchGuidanceSet,
        condition: BenchmarkResearchConditionGuidance,
        project_runtime: ProjectRuntime,
        native_root: Path,
        persist_arm_request: bool = True,
        prepared_workspace_root: Path | None = None,
    ) -> tuple[H4BenchmarkResearchActionProvider, H4ArmRunRequest, ResourceBudget]:
        """Bind real runner objects before the H4 baseline, model, or mutation."""

        if (
            self.config.h4_execution_profile is None
            or self.config.lifecycle_policy is None
            or self.config.h4_policy_reproduction_spec is None
            or self.config.h4_policy_reproduction_report is None
            or self.config.source_identity_registry is None
            or self.config.objective_outcome_contract is None
        ):
            raise ValueError("native H4 bindings are incomplete")
        h4_profile = load_h4_execution_profile(self._bound_file(self.config.h4_execution_profile))
        registry = load_canonical_source_identity_registry(
            self._bound_file(self.config.source_identity_registry)
        )
        objective_contract = load_objective_outcome_contract(
            self._bound_file(self.config.objective_outcome_contract)
        ).contract
        assert self.config.h4_state_probe_contract is not None
        assert self.config.h4_state_probe_report is not None
        probe_contract = load_h4_state_probe_contract(
            self._bound_file(self.config.h4_state_probe_contract)
        )
        probe_report = load_h4_state_probe_report(
            self._bound_file(self.config.h4_state_probe_report)
        )
        idea_report = inspect_current_idea_revision(
            project_runtime,
            self.request.project_id,
        )
        if idea_report.current_binding is None or not idea_report.experiment_freeze_eligible:
            raise ValueError("native H4 requires an experiment-freeze-eligible current Idea")
        idea_binding = idea_report.current_binding
        reproduction_spec = load_h4_policy_reproduction_spec(
            self._bound_file(self.config.h4_policy_reproduction_spec)
        )
        recorded_reproduction = load_h4_policy_reproduction_report(
            self._bound_file(self.config.h4_policy_reproduction_report)
        )
        reproduced_report, policy = reproduce_h4_lifecycle_policy(
            self.repository_root,
            reproduction_spec,
            current_idea_revision=idea_binding,
        )
        family_policy = None
        if reproduction_spec.schema_version == "1.1":
            assert reproduced_report.family_conditioned_policy is not None
            family_binding = AdapterFileBinding(
                locator=reproduced_report.family_conditioned_policy.locator,
                sha256=reproduced_report.family_conditioned_policy.file_sha256,
            )
            family_policy = load_family_conditioned_lifecycle_taste_policy(
                self._bound_file(family_binding)
            )
        if (
            reproduced_report != recorded_reproduction
            or reproduced_report.report_sha256 != h4_profile.policy_reproduction_report_sha256
            or reproduction_spec.project_id != self.request.project_id
            or reproduction_spec.evaluation_id != self.request.evaluation_id
            or reproduced_report.policy.file_sha256 != self.config.lifecycle_policy.sha256
        ):
            raise ValueError("native H4 lifecycle policy reproduction differs")
        h4_profile.verify_scientific_artifacts(
            policy=policy,
            family_policy=family_policy,
            registry=registry,
            current_idea_revision=idea_binding,
        )
        replayed_probe_report = inspect_h4_state_probe_manipulation(
            probe_contract,
            policy,
            current_idea_revision=idea_binding,
        )
        if (
            not probe_report.passed
            or replayed_probe_report != probe_report
            or h4_profile.state_probe_contract_sha256 != probe_contract.contract_sha256
            or h4_profile.state_probe_report_sha256 != probe_report.report_sha256
            or probe_report.contract_sha256 != probe_contract.contract_sha256
            or probe_contract.lifecycle_policy_sha256 != policy.policy_sha256
            or probe_report.lifecycle_policy_sha256 != policy.policy_sha256
            or probe_contract.controller_backbone_sha256 != h4_profile.controller_backbone_sha256
            or probe_report.controller_backbone_sha256 != h4_profile.controller_backbone_sha256
            or probe_contract.project_id != self.request.project_id
            or probe_contract.evaluation_id != self.request.evaluation_id
            or probe_contract.evaluation_bundle_sha256 != campaign.evaluation_bundle_sha256
            or probe_contract.plan_sha256 != campaign.plan_sha256
            or probe_contract.maximum_patch_iterations != h4_profile.maximum_patch_iterations
            or probe_contract.maximum_failed_experiments != h4_profile.maximum_failed_experiments
            or probe_contract.target_domain != spec.benchmark_id
            or probe_contract.target_venue != "ICLR 2027"
            or content_sha256(probe_contract.resource_budget) != h4_profile.resource_budget_sha256
        ):
            raise ValueError("native H4 state-probe manipulation check differs or failed")
        cell = self.request.cell
        try:
            arm_condition = TasteInterventionCondition(cell.system_id)
        except ValueError as exc:
            raise ValueError("native H4 cell is not a learned-policy arm") from exc
        if arm_condition not in {
            TasteInterventionCondition.LEARNED_POLICY_ON,
            TasteInterventionCondition.LEARNED_POLICY_OFF,
        }:
            raise ValueError("native H4 cell is not a learned-policy arm")
        expected_task_group = canonical_benchmark_task_source_group_id(
            spec.benchmark_id,
            spec.task_id,
        )
        if spec.canonical_source_group_id != expected_task_group:
            raise ValueError("native H4 task canonical source identity differs")
        if (
            guidance.mechanism_context is None
            or guidance.mechanism_context.held_out_source_group_id != spec.canonical_source_group_id
        ):
            raise ValueError("native H4 mechanism context binds another held-out task")
        task_binding = self.config.tasks[spec.task_id]
        assert task_binding.failure_directed_progress_penalty is not None
        try:
            task_score_contract = next(
                item for item in objective_contract.task_scores if item.task_id == spec.task_id
            )
        except StopIteration as exc:
            raise ValueError("native H4 objective contract lacks its task") from exc
        expected_failure_penalty = (
            task_score_contract.raw_minimum - spec.baseline_heldout_score
            if spec.metric_direction == "higher"
            else spec.baseline_heldout_score - task_score_contract.raw_maximum
        )
        if (
            task_score_contract.metric_id != spec.primary_metric
            or task_score_contract.direction.value != spec.metric_direction
            or task_score_contract.starting_score != spec.baseline_heldout_score
            or task_score_contract.source_group_id != spec.canonical_source_group_id
            or abs(task_binding.failure_directed_progress_penalty - expected_failure_penalty)
            > 1e-12
        ):
            raise ValueError("native H4 task metric or ITT failure penalty drifted")
        guidance_groups = tuple(
            sorted(
                registry.resolve(item)
                for item in _h4_guidance_source_group_ids(guidance, condition)
            )
        )
        protocol_guidance_sha256 = _h4_protocol_authored_guidance_sha256(guidance)
        observed_task = observe_h4_task_execution_profile(
            spec,
            task_file_sha256=spec_sha256,
            development_profile_file_sha256=(task_binding.development_execution_profile.sha256),
            heldout_profile_file_sha256=task_binding.heldout_execution_profile.sha256,
            development_profile=development_profile,
            heldout_profile=heldout_profile,
            scorer_contract_sha256=content_sha256(task_score_contract.scorer_artifact),
            baseline_score_contract_sha256=content_sha256(task_score_contract),
            failure_directed_progress_penalty=(task_binding.failure_directed_progress_penalty),
            precedent_source_group_ids=guidance_groups,
            protocol_authored_guidance_sha256=protocol_guidance_sha256,
        )
        if observed_task != h4_profile.task_profile(spec.task_id):
            raise ValueError("native H4 task, scorer, split, or executor drifted")
        if guidance_groups != observed_task.precedent_source_group_ids:
            raise ValueError("native H4 guidance source partition drifted")
        source_partition_sha256 = content_sha256(
            {
                "policy": h4_profile.policy_source_group_ids,
                "guidance": h4_profile.precedent_source_group_ids,
                "heldout": h4_profile.heldout_source_group_ids,
            }
        )
        resource_budget = _h4_resource_budget(self.config, cell)
        repair_policy_sha256 = _h4_repair_policy_sha256(self.config)
        registered_plan = _load_registered_cell_plan(
            project_runtime,
            self.request.project_id,
            self.request.evaluation_id,
        )
        selected_cells = tuple(
            item for item in registered_plan.cells if item.cell_id in campaign.selected_cell_ids
        )
        runtime_checks = {
            "project": h4_profile.project_id == self.request.project_id,
            "evaluation": h4_profile.evaluation_id == self.request.evaluation_id,
            "evaluation bundle": h4_profile.evaluation_bundle_sha256
            == campaign.evaluation_bundle_sha256,
            "plan": h4_profile.plan_sha256 == campaign.plan_sha256,
            "repository": _verify_h4_repository_identity(
                self.repository_root,
                h4_profile,
            ),
            "adapter": h4_profile.adapter_implementation_sha256
            == BENCHMARK_H4_ADAPTER_IMPLEMENTATION_SHA256,
            "controller": h4_profile.controller_implementation_sha256
            == BENCHMARK_H4_CONTROLLER_IMPLEMENTATION_SHA256,
            "controller identity": (
                h4_profile.decision_provider,
                h4_profile.decision_model,
            )
            == ("scitaste-native", "deterministic-utility-controller"),
            "patch model profile": h4_profile.patch_model_profile_sha256
            == model_profile.fingerprint,
            "patch node policy": h4_profile.patch_node_policy_sha256
            == content_sha256(self.config.node_policy),
            "patch prompt": h4_profile.patch_prompt_sha256 == _h4_patch_prompt_sha256(),
            "decoding config": h4_profile.decoding_config_sha256
            == content_sha256(self.config.backend),
            "tool policy": h4_profile.tool_policy_sha256
            == _h4_tool_policy_sha256(self.config.node_policy),
            "repair policy": h4_profile.repair_policy_sha256 == repair_policy_sha256,
            "resource budget": h4_profile.resource_budget_sha256 == content_sha256(resource_budget),
            "seed schedule": h4_profile.seed_schedule_sha256
            == _h4_seed_schedule_sha256(selected_cells),
            "paired plan": _h4_selected_cells_are_paired(selected_cells),
            "campaign model budget reserve": _h4_model_budget_reserves_campaign(
                model_profile,
                selected_cells=selected_cells,
                maximum_patch_iterations=self.config.maximum_patch_iterations,
            ),
            "task population": {item.task_id for item in h4_profile.task_profiles}
            == {item.task_id for item in selected_cells},
            "source partition": h4_profile.source_partition_sha256 == source_partition_sha256,
            "protocol-authored guidance": (
                h4_profile.protocol_authored_guidance_channels == ("utility", "critic")
                and observed_task.protocol_authored_guidance_sha256 == protocol_guidance_sha256
            ),
            "objective contract": h4_profile.objective_outcome_contract_sha256
            == objective_contract.contract_sha256,
            "maximum iterations": h4_profile.maximum_patch_iterations
            == self.config.maximum_patch_iterations,
            "failed experiment limit": h4_profile.maximum_failed_experiments
            == self.config.maximum_failed_experiments,
            "stopping rule": h4_profile.stopping_rule_sha256
            == _h4_stopping_rule_sha256(self.config),
        }
        failed = tuple(label for label, passed in runtime_checks.items() if not passed)
        if failed:
            raise ValueError("native H4 pre-run drift: " + ", ".join(failed))
        initial_editable_surface_sha256, _ = hash_editable_surface(
            spec,
            (prepared_workspace_root or native_root) / prepared_workspace.workspace_locator,
        )
        arm_request = H4ArmRunRequest.create_from_profile(
            h4_profile,
            request_id=f"{cell.cell_id}-h4-arm",
            campaign_manifest_sha256=campaign.manifest_sha256,
            condition=arm_condition,
            cell_id=cell.cell_id,
            cell_binding_sha256=cell_binding.binding_sha256,
            condition_matrix_fingerprint=condition.condition_matrix_fingerprint,
            condition_guidance_sha256=condition.fingerprint,
            task_id=cell.task_id,
            seed=cell.seed,
            repetition=cell.repetition,
            plan_position=next(
                index
                for index, selected_cell in enumerate(selected_cells)
                if selected_cell.cell_id == cell.cell_id
            ),
            task_file_sha256=spec_sha256,
            task_spec_fingerprint=spec.fingerprint,
            resource_budget_sha256=content_sha256(resource_budget),
            prepared_workspace_receipt_sha256=prepared_workspace.receipt_sha256,
            initial_workspace_tree_sha256=prepared_workspace.workspace_tree_sha256,
            initial_editable_surface_sha256=initial_editable_surface_sha256,
            protected_surface_sha256=prepared_workspace.protected_surface_sha256,
            development_execution_profile_sha256=(
                task_binding.development_execution_profile.sha256
            ),
            development_prepared_record_sha256=development_profile.record_sha256,
            development_resource_verification_sha256=(development_verification.receipt_sha256),
            heldout_execution_profile_sha256=(task_binding.heldout_execution_profile.sha256),
            heldout_prepared_record_sha256=heldout_profile.record_sha256,
            heldout_resource_verification_sha256=heldout_verification.receipt_sha256,
            patch_model_profile_sha256=model_profile.fingerprint,
            patch_node_policy_sha256=content_sha256(self.config.node_policy),
            patch_prompt_sha256=_h4_patch_prompt_sha256(),
            decoding_config_sha256=content_sha256(self.config.backend),
            patch_visible_guidance_sha256=_h4_patch_visible_guidance_sha256(condition),
        )
        if persist_arm_request:
            save_h4_arm_run_request(arm_request, native_root / "H4_ARM_REQUEST.json")
        controller_arguments = {
            "seed": cell.seed,
            "mode": TasteMode.INTRINSIC,
            "critics_enabled": False,
            "lifecycle_policy_weight": arm_request.lifecycle_policy_weight,
        }
        if family_policy is None:
            controller_arguments["lifecycle_policy"] = policy
        else:
            controller_arguments.update(
                family_conditioned_policy=family_policy,
                lifecycle_decision_family=ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION,
            )
        controller = TasteController(**controller_arguments)
        action_provider = H4BenchmarkResearchActionProvider(
            h4_profile,
            arm_request,
            controller,
            current_idea_revision=idea_binding,
        )
        return action_provider, arm_request, resource_budget

    def _usage(
        self,
        loop: BenchmarkResearchLoopResult,
        *,
        heldout_executed: bool,
    ) -> EvaluationAdapterUsage:
        decisions = sum(item.decision_sha256 is not None for item in loop.iterations)
        return EvaluationAdapterUsage(
            request_count=decisions,
            input_tokens=loop.input_tokens,
            output_tokens=loop.output_tokens,
            max_input_tokens_observed=loop.max_input_tokens_observed,
            max_output_tokens_observed=loop.max_output_tokens_observed,
            api_cost=(
                loop.model_cost_usd if isinstance(self.config.backend, LiveRuntimeBackend) else None
            ),
            experiment_count=loop.development_experiment_count + int(heldout_executed),
        )

    def _write_evidence_index(
        self,
        native_root: Path,
        campaign: EvaluationCampaignManifest,
        spec: BenchmarkTaskRuntimeSpec,
        loop: BenchmarkResearchLoopResult,
        *,
        heldout: BenchmarkHeldoutExecutionReceipt | None,
        measurement: NativeBenchmarkObjectiveMeasurement | None,
        terminal: H4TerminalOutcomeReceipt | None,
    ) -> Path:
        path = native_root / "EVIDENCE_INDEX.json"
        evidence_files = (
            _native_h4_evidence_files(native_root) if self.config.schema_version == "1.1" else ()
        )
        payload = {
            "schema_version": "1.1" if self.config.schema_version == "1.1" else "1.0",
            "adapter_config_id": self.config.config_id,
            "campaign_manifest_sha256": campaign.manifest_sha256,
            "plan_sha256": campaign.plan_sha256,
            "cell_sha256": content_sha256(self.request.cell),
            "task_spec_fingerprint": spec.fingerprint,
            "loop_result_sha256": loop.result_sha256,
            "terminal_outcome_receipt_sha256": (
                terminal.receipt_sha256 if terminal is not None else None
            ),
            "heldout_receipt_sha256": (heldout.receipt_sha256 if heldout is not None else None),
            "objective_measurement_sha256": (
                measurement.measurement_sha256 if measurement is not None else None
            ),
            "heldout_scoring_executed_only_after_candidate_freeze": heldout is not None,
            "model_invocations_after_candidate_freeze": 0,
            "evidence_files": evidence_files,
            "evidence_tree_sha256": content_sha256(evidence_files),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        payload["evidence_index_sha256"] = content_sha256(payload)
        _write_json(path, payload)
        return path

    def _artifact_paths(self, *paths: Path) -> tuple[str, ...]:
        arm_request_path = self.cell_directory / "native_benchmark" / "H4_ARM_REQUEST.json"
        if arm_request_path.is_file() and arm_request_path not in paths:
            paths = (arm_request_path, *paths)
        locators: list[str] = []
        for path in paths:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(self.cell_directory) or not resolved.is_file():
                raise ValueError("native benchmark artifact escapes its campaign cell")
            locators.append(resolved.relative_to(self.cell_directory).as_posix())
        return tuple(locators)


def _native_h4_evidence_files(native_root: Path) -> tuple[dict[str, object], ...]:
    """Hash bounded protocol evidence without archiving the mutable workspace tree."""

    selected: list[Path] = []
    for candidate in native_root.rglob("*"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        relative = candidate.relative_to(native_root)
        if relative.parts[0] in {"development_loop", "heldout"} or relative.name in {
            "H4_ARM_REQUEST.json",
            "H4_TERMINAL_OUTCOME.json",
            "FAILURE.json",
            "FROZEN_CANDIDATE.json",
            "OBJECTIVE_MEASUREMENT.json",
        }:
            selected.append(candidate)
    if len(selected) > 5_000:
        raise ValueError("native H4 evidence tree exceeds its file-count ceiling")
    entries: list[dict[str, object]] = []
    for candidate in sorted(selected, key=lambda item: item.relative_to(native_root).as_posix()):
        size = candidate.stat().st_size
        if not 1 <= size <= 64 * 1_048_576:
            raise ValueError("native H4 evidence file exceeds its size ceiling")
        entries.append(
            {
                "locator": candidate.relative_to(native_root).as_posix(),
                "sha256": _file_sha256(candidate),
                "size_bytes": size,
            }
        )
    observed = {str(item["locator"]) for item in entries}
    if "H4_ARM_REQUEST.json" not in observed or not (
        {"development_loop/RESULT.json", "H4_TERMINAL_OUTCOME.json"} & observed
    ):
        raise ValueError("native H4 evidence tree lacks a terminal arm or loop receipt")
    return tuple(entries)


def load_native_benchmark_cell_request(path: str | Path) -> NativeBenchmarkCellRequest:
    source = Path(path)
    if (
        source.is_symlink()
        or not source.is_file()
        or source.stat().st_size > _MAX_CELL_REQUEST_BYTES
    ):
        raise ValueError("native benchmark cell request must be a bounded regular file")
    return NativeBenchmarkCellRequest.model_validate_json(source.read_bytes(), strict=True)


def pair_h4_objective_measurements(
    learned_policy_on_request: H4ArmRunRequest,
    learned_policy_on_measurement: NativeBenchmarkObjectiveMeasurement,
    learned_policy_off_request: H4ArmRunRequest,
    learned_policy_off_measurement: NativeBenchmarkObjectiveMeasurement,
    *,
    pair_id: str,
) -> H4PairedResult:
    """Close one frozen-plan pair while rejecting non-treatment factor drift."""

    expected = (
        (
            learned_policy_on_request,
            learned_policy_on_measurement,
            TasteInterventionCondition.LEARNED_POLICY_ON,
        ),
        (
            learned_policy_off_request,
            learned_policy_off_measurement,
            TasteInterventionCondition.LEARNED_POLICY_OFF,
        ),
    )
    for request, measurement, condition in expected:
        if (
            request.condition is not condition
            or measurement.schema_version != "1.1"
            or measurement.condition_id != condition.value
            or measurement.h4_arm_run_request_sha256 != request.request_sha256
            or measurement.h4_execution_profile_sha256 != request.profile_sha256
            or measurement.cell_id != request.cell_id
            or measurement.task_id != request.task_id
        ):
            raise ValueError("H4 pair arm request and measurement differ")
    if (
        learned_policy_on_request.profile_sha256 != learned_policy_off_request.profile_sha256
        or learned_policy_on_request.task_id != learned_policy_off_request.task_id
        or learned_policy_on_request.seed != learned_policy_off_request.seed
        or learned_policy_on_request.repetition != learned_policy_off_request.repetition
        or learned_policy_on_request.common_arm_factors_sha256
        != learned_policy_off_request.common_arm_factors_sha256
    ):
        raise ValueError("H4 paired arms differ outside the policy intervention")
    ordered_conditions = tuple(
        request.condition
        for request in sorted(
            (learned_policy_on_request, learned_policy_off_request),
            key=lambda item: item.plan_position,
        )
    )
    if learned_policy_on_request.plan_position == learned_policy_off_request.plan_position:
        raise ValueError("H4 pair has duplicate frozen-plan positions")
    return H4PairedResult.create(
        pair_id=pair_id,
        profile_sha256=learned_policy_on_request.profile_sha256,
        task_id=learned_policy_on_request.task_id,
        seed=learned_policy_on_request.seed,
        repetition=learned_policy_on_request.repetition,
        learned_policy_on_plan_position=learned_policy_on_request.plan_position,
        learned_policy_off_plan_position=learned_policy_off_request.plan_position,
        execution_order=ordered_conditions,
        learned_policy_on_arm_request_sha256=(learned_policy_on_request.request_sha256),
        learned_policy_off_arm_request_sha256=(learned_policy_off_request.request_sha256),
        learned_policy_on_measurement_sha256=(learned_policy_on_measurement.measurement_sha256),
        learned_policy_off_measurement_sha256=(learned_policy_off_measurement.measurement_sha256),
        learned_policy_on_directed_progress=(learned_policy_on_measurement.directed_progress),
        learned_policy_off_directed_progress=(learned_policy_off_measurement.directed_progress),
    )


def _h4_guidance_source_group_ids(
    guidance: BenchmarkResearchGuidanceSet,
    condition: BenchmarkResearchConditionGuidance,
) -> tuple[str, ...]:
    context = guidance.mechanism_context
    if context is None:
        raise ValueError("native H4 guidance lacks its formal source context")
    sources = []
    if "knowledge" in condition.artifact_sha256:
        sources.extend(context.raw_source_rag.sources)
    if "taste" in condition.artifact_sha256:
        sources.extend(context.matched_abstracted_taste.sources)
    return tuple(sorted({item.source_group_id for item in sources}))


def _h4_protocol_authored_guidance_sha256(
    guidance: BenchmarkResearchGuidanceSet,
) -> str:
    """Bind local protocol advice that is not represented as external evidence."""

    return content_sha256(
        {
            channel: {
                "source_locator": artifact.source_locator,
                "source_sha256": artifact.source_sha256,
                "derivation_receipt_locator": artifact.derivation_receipt_locator,
                "derivation_receipt_sha256": artifact.derivation_receipt_sha256,
                "entries": artifact.entries,
            }
            for channel, artifact in (
                ("utility", guidance.utility),
                ("critic", guidance.critic),
            )
        }
    )


def _h4_patch_visible_guidance_sha256(
    condition: BenchmarkResearchConditionGuidance,
) -> str:
    """Hash only guidance bytes exposed to the patch model, excluding arm labels."""

    return content_sha256(
        {
            "utility": condition.utility_guidance,
            "knowledge": condition.knowledge_guidance,
            "taste": condition.taste_guidance,
            "critic": condition.critic_guidance,
            "artifacts": condition.artifact_sha256,
        }
    )


def _h4_resource_budget(
    config: NativeBenchmarkAdapterConfig,
    cell: PlannedEvaluationCell,
) -> ResourceBudget:
    return ResourceBudget(
        gpu_hours=(
            float(cell.resource.max_gpu_hours or 0)
            if cell.resource.kind is ExecutionLaneKind.GPU
            else None
        ),
        max_experiments=config.maximum_patch_iterations + 1,
        max_api_cost_usd=(
            float(cell.resource.max_cost or 0)
            if cell.resource.kind is ExecutionLaneKind.API_ONLY
            else None
        ),
        compute_constraints=[
            "one-development-baseline",
            "one-patch-model-call-per-selected-non-stop-action",
            "one-heldout-score-after-candidate-freeze",
        ],
    )


def _load_registered_cell_plan(
    runtime: ProjectRuntime,
    project_id: str,
    evaluation_id: str,
) -> EvaluationCellPlan:
    evaluation = runtime.open_evaluation(project_id, evaluation_id)
    binding = evaluation.files.get("cell_plan")
    if binding is None:
        raise ValueError("native H4 evaluation lacks its registered cell plan")
    root = runtime.projects_root / project_id / "evaluations" / evaluation_id
    return load_evaluation_cell_plan(root / binding.locator)


def _h4_seed_schedule_sha256(cells: tuple[PlannedEvaluationCell, ...]) -> str:
    return content_sha256(
        tuple(
            {
                "cell_id": item.cell_id,
                "task_id": item.task_id,
                "condition": item.system_id,
                "seed": item.seed,
                "repetition": item.repetition,
                "resource_sha256": item.resource.resource_sha256,
            }
            for item in cells
        )
    )


def verify_native_h4_static_preparation(
    repository_root: str | Path,
    config: NativeBenchmarkAdapterConfig,
    profile: H4ExecutionProfile,
    *,
    selected_cells: tuple[PlannedEvaluationCell, ...],
) -> None:
    """Replay every no-execution native H4 check before campaign registration."""

    root = Path(repository_root).resolve(strict=True)
    if config.schema_version != "1.1":
        raise ValueError("native H4 static preparation requires adapter schema 1.1")
    matrix = load_native_condition_matrix(_adapter_bound_file(root, config.condition_matrix))
    if matrix.matrix.schema_version != "1.2":
        raise ValueError("native H4 static preparation requires condition matrix 1.2")
    loaded_profiles = load_model_node_profile_set(
        _adapter_bound_file(root, config.model_profile_set)
    )
    if loaded_profiles.source_sha256 != config.model_profile_set.sha256:
        raise ValueError("native H4 model profile-set bytes differ")
    try:
        model_profile = loaded_profiles.profiles[config.model_profile_id]
    except KeyError as exc:
        raise ValueError("native H4 model profile is unavailable") from exc
    validate_profile_binding(
        model_profile,
        config.node_policy,
        node_name="benchmark-research-patch",
    )
    objective = load_objective_outcome_contract(
        _adapter_bound_file(root, config.objective_outcome_contract)
    ).contract
    registry = load_canonical_source_identity_registry(
        _adapter_bound_file(root, config.source_identity_registry)
    )
    observed_tasks: list[H4TaskExecutionProfile] = []
    for task_id, task_binding in sorted(config.tasks.items()):
        task_path = _adapter_bound_file(root, task_binding.task_spec)
        spec = load_benchmark_task_runtime_spec(task_path)
        inspection = inspect_benchmark_task_runtime(
            spec,
            workspace_root=root,
            spec_sha256=_file_sha256(task_path),
        )
        if (
            spec.task_id != task_id
            or spec.project_id != profile.project_id
            or not inspection.ready_for_development_execution
        ):
            raise ValueError(f"native H4 task is not static-preparation ready: {task_id}")
        guidance = load_benchmark_research_guidance_set(
            _adapter_bound_file(root, config.guidance_by_task[task_id])
        )
        _verify_h4_guidance_files(root, config, guidance)
        if (
            spec.canonical_source_group_id
            != canonical_benchmark_task_source_group_id(
                spec.benchmark_id,
                spec.task_id,
            )
            or guidance.mechanism_context is None
            or guidance.mechanism_context.held_out_source_group_id != spec.canonical_source_group_id
        ):
            raise ValueError(f"native H4 held-out source identity differs: {task_id}")
        for system_id in sorted(
            {item.system_id for item in selected_cells if item.task_id == task_id}
        ):
            compile_benchmark_condition_guidance(matrix, guidance, system_id)
        development = inspect_native_execution_profile(
            _adapter_bound_file(root, task_binding.development_execution_profile)
        )
        heldout = inspect_native_execution_profile(
            _adapter_bound_file(root, task_binding.heldout_execution_profile)
        )
        _verify_h4_static_model_resources(
            config,
            model_profile,
            development,
            heldout,
            tuple(item for item in selected_cells if item.task_id == task_id),
        )
        score_contracts = [item for item in objective.task_scores if item.task_id == task_id]
        if len(score_contracts) != 1:
            raise ValueError(f"native H4 objective contract lacks one task score: {task_id}")
        score = score_contracts[0]
        expected_failure_penalty = (
            score.raw_minimum - spec.baseline_heldout_score
            if spec.metric_direction == "higher"
            else spec.baseline_heldout_score - score.raw_maximum
        )
        guidance_groups = tuple(
            sorted(
                registry.resolve(item)
                for item in _h4_guidance_source_group_ids(
                    guidance,
                    compile_benchmark_condition_guidance(
                        matrix,
                        guidance,
                        TasteInterventionCondition.LEARNED_POLICY_ON.value,
                    ),
                )
            )
        )
        if (
            task_binding.failure_directed_progress_penalty is None
            or abs(task_binding.failure_directed_progress_penalty - expected_failure_penalty)
            > 1e-12
            or score.metric_id != spec.primary_metric
            or score.direction.value != spec.metric_direction
            or score.starting_score != spec.baseline_heldout_score
            or score.source_group_id != spec.canonical_source_group_id
        ):
            raise ValueError(f"native H4 task score contract differs: {task_id}")
        observed_tasks.append(
            observe_h4_task_execution_profile_from_fingerprints(
                spec,
                task_file_sha256=_file_sha256(task_path),
                development_profile_file_sha256=(task_binding.development_execution_profile.sha256),
                heldout_profile_file_sha256=(task_binding.heldout_execution_profile.sha256),
                development_profile_fingerprint=development.fingerprint,
                heldout_profile_fingerprint=heldout.fingerprint,
                scorer_contract_sha256=content_sha256(score.scorer_artifact),
                baseline_score_contract_sha256=content_sha256(score),
                failure_directed_progress_penalty=(task_binding.failure_directed_progress_penalty),
                precedent_source_group_ids=guidance_groups,
                protocol_authored_guidance_sha256=(_h4_protocol_authored_guidance_sha256(guidance)),
            )
        )
    resource_budgets = tuple(
        content_sha256(_h4_resource_budget(config, item)) for item in selected_cells
    )
    checks = {
        "task population": tuple(observed_tasks) == profile.task_profiles,
        "adapter implementation": profile.adapter_implementation_sha256
        == BENCHMARK_H4_ADAPTER_IMPLEMENTATION_SHA256,
        "controller implementation": profile.controller_implementation_sha256
        == BENCHMARK_H4_CONTROLLER_IMPLEMENTATION_SHA256,
        "menu builder": profile.menu_builder_implementation_sha256
        == BENCHMARK_H4_ACTION_MENU_BUILDER_SHA256,
        "action ontology": profile.action_ontology_sha256 == BENCHMARK_H4_ACTION_ONTOLOGY_SHA256,
        "action menu": profile.action_menu_template_sha256
        == BENCHMARK_H4_ACTION_MENU_TEMPLATE_SHA256,
        "action eligibility": profile.action_eligibility_rule_sha256
        == BENCHMARK_H4_ACTION_ELIGIBILITY_SHA256,
        "action adapter": profile.action_to_patch_adapter_sha256
        == BENCHMARK_H4_ACTION_TO_PATCH_ADAPTER_SHA256,
        "controller identity": (profile.decision_provider, profile.decision_model)
        == ("scitaste-native", "deterministic-utility-controller"),
        "model profile": profile.patch_model_profile_sha256 == model_profile.fingerprint,
        "node policy": profile.patch_node_policy_sha256 == content_sha256(config.node_policy),
        "prompt": profile.patch_prompt_sha256 == _h4_patch_prompt_sha256(),
        "decoding": profile.decoding_config_sha256 == content_sha256(config.backend),
        "tool policy": profile.tool_policy_sha256 == _h4_tool_policy_sha256(config.node_policy),
        "repair policy": profile.repair_policy_sha256 == _h4_repair_policy_sha256(config),
        "paired cells": _h4_selected_cells_are_paired(selected_cells),
        "seed schedule": profile.seed_schedule_sha256 == _h4_seed_schedule_sha256(selected_cells),
        "resource budget": bool(resource_budgets)
        and len(set(resource_budgets)) == 1
        and resource_budgets[0] == profile.resource_budget_sha256,
        "model budget": _h4_model_budget_reserves_campaign(
            model_profile,
            selected_cells=selected_cells,
            maximum_patch_iterations=config.maximum_patch_iterations,
        ),
        "source registry": profile.source_identity_registry_sha256 == registry.registry_sha256,
        "objective contract": profile.objective_outcome_contract_sha256
        == objective.contract_sha256,
        "patch iterations": profile.maximum_patch_iterations == config.maximum_patch_iterations,
        "failed experiments": profile.maximum_failed_experiments
        == config.maximum_failed_experiments,
        "stopping rule": profile.stopping_rule_sha256 == _h4_stopping_rule_sha256(config),
    }
    failed = tuple(label for label, passed in checks.items() if not passed)
    if failed:
        raise ValueError("native H4 static preparation drift: " + ", ".join(failed))


def _adapter_bound_file(root: Path, binding: AdapterFileBinding | None) -> Path:
    if binding is None:
        raise ValueError("native H4 static adapter binding is missing")
    path = _repository_regular_file(root, binding.locator)
    if _file_sha256(path) != binding.sha256:
        raise ValueError(f"native H4 static adapter file drift: {binding.locator}")
    return path


def _verify_h4_guidance_files(
    root: Path,
    config: NativeBenchmarkAdapterConfig,
    guidance: BenchmarkResearchGuidanceSet,
) -> None:
    corpus = _adapter_bound_file(root, config.corpus_pair_report)
    if _file_sha256(corpus) != guidance.corpus_pair_report_sha256:
        raise ValueError("native H4 guidance binds another corpus-pair report")
    for artifact in (
        guidance.utility,
        guidance.knowledge,
        guidance.matched_taste,
        guidance.mismatched_taste,
        guidance.critic,
    ):
        _verify_repository_file(
            root,
            root.joinpath(*Path(artifact.source_locator).parts),
            artifact.source_sha256,
            label="H4 guidance source",
        )
        _verify_repository_file(
            root,
            root.joinpath(*Path(artifact.derivation_receipt_locator).parts),
            artifact.derivation_receipt_sha256,
            label="H4 guidance derivation",
        )


def _verify_h4_static_model_resources(
    config: NativeBenchmarkAdapterConfig,
    model_profile: ModelNodeProfile,
    development_inspection,
    heldout_inspection,
    cells: tuple[PlannedEvaluationCell, ...],
) -> None:  # type: ignore[no-untyped-def]
    if not cells:
        raise ValueError("native H4 task has no selected cells")
    if isinstance(config.backend, LiveRuntimeBackend):
        backend = config.backend.config
        valid = (
            model_profile.live_execution_permitted
            and not development_inspection.profile.gpu.enabled
            and not heldout_inspection.profile.gpu.enabled
            and all(
                cell.resource.kind is ExecutionLaneKind.API_ONLY
                and cell.resource.provider_id == backend.provider
                and cell.resource.model_id == backend.model
                and cell.resource.api_key_env == backend.api_key_env
                and config.maximum_patch_iterations <= int(cell.resource.max_requests or 0)
                and model_profile.admission.max_input_tokens
                <= int(cell.resource.max_input_tokens_per_call or 0)
                and model_profile.admission.max_output_tokens
                <= int(cell.resource.max_output_tokens_per_call or 0)
                and config.maximum_patch_iterations * model_profile.admission.max_total_tokens
                <= int(cell.resource.max_total_tokens or 0)
                and config.maximum_patch_iterations * model_profile.admission.max_response_cost_usd
                <= float(cell.resource.max_cost or 0)
                for cell in cells
            )
        )
    elif isinstance(config.backend, LocalRuntimeBackend):
        backend = config.backend.config
        matching = [
            item
            for item in development_inspection.external_resources
            if item.resource_kind == "model"
            and item.content_sha256 == backend.checkpoint_sha256
            and item.source_path.resolve(strict=True)
            == backend.model_path.expanduser().resolve(strict=True)
        ]
        valid = (
            model_profile.local_execution_permitted
            and len(matching) == 1
            and development_inspection.profile.gpu.enabled
            and heldout_inspection.profile.gpu.enabled
            and all(
                cell.resource.kind is ExecutionLaneKind.GPU
                and cell.resource.checkpoint_sha256 == backend.checkpoint_sha256
                and development_inspection.profile.gpu.max_gpu_hours
                <= float(cell.resource.max_gpu_hours or 0)
                and heldout_inspection.profile.gpu.max_gpu_hours
                <= float(cell.resource.max_gpu_hours or 0)
                for cell in cells
            )
        )
    else:
        valid = False
    if not valid:
        raise ValueError("native H4 static model or resource binding differs")


def _h4_selected_cells_are_paired(cells: tuple[PlannedEvaluationCell, ...]) -> bool:
    expected = {
        TasteInterventionCondition.LEARNED_POLICY_ON.value,
        TasteInterventionCondition.LEARNED_POLICY_OFF.value,
    }
    pairs: dict[tuple[str, int, int], list[PlannedEvaluationCell]] = {}
    for cell in cells:
        if cell.system_id not in expected:
            return False
        pairs.setdefault((cell.task_id, cell.seed, cell.repetition), []).append(cell)
    return bool(pairs) and all(
        len(pair) == 2
        and {item.system_id for item in pair} == expected
        and len({item.resource.resource_sha256 for item in pair}) == 1
        for pair in pairs.values()
    )


def _h4_model_budget_reserves_campaign(
    profile: ModelNodeProfile,
    *,
    selected_cells: tuple[PlannedEvaluationCell, ...],
    maximum_patch_iterations: int,
) -> bool:
    """Reserve worst-case model capacity for every arm before the first call."""

    maximum_calls = len(selected_cells) * maximum_patch_iterations
    return (
        profile.cumulative_project.max_invocations >= maximum_calls
        and profile.cumulative_project.max_total_tokens
        >= maximum_calls * profile.admission.max_total_tokens
        and profile.cumulative_project.max_api_cost_usd
        >= maximum_calls * profile.admission.max_response_cost_usd
    )


def _h4_patch_prompt_sha256() -> str:
    return content_sha256(
        {
            "node": BenchmarkPatchGenerationNode.node_name,
            "prompt_version": BenchmarkPatchGenerationNode.prompt_version,
            "system_instruction": BenchmarkPatchGenerationNode.system_instruction,
        }
    )


def _h4_tool_policy_sha256(policy: NodePolicy) -> str:
    return content_sha256(
        {
            "allowed_tool_names": policy.allowed_tool_names,
            "allowed_action_types": policy.allowed_action_types,
            "model_has_no_filesystem_or_process_authority": True,
        }
    )


def _h4_repair_policy_sha256(config: NativeBenchmarkAdapterConfig) -> str:
    return content_sha256(
        {
            "patch_policy": config.patch_policy,
            "minimum_absolute_improvement": config.minimum_absolute_improvement,
            "maximum_failed_experiments": config.maximum_failed_experiments,
            "adoption": "strict-development-improvement-else-rollback-v1",
        }
    )


def _h4_stopping_rule_sha256(config: NativeBenchmarkAdapterConfig) -> str:
    return content_sha256(
        {
            "maximum_patch_iterations": config.maximum_patch_iterations,
            "maximum_failed_experiments": config.maximum_failed_experiments,
            "taste_stop_is_terminal": True,
            "patch_model_stop_after-non-stop-action": "protocol-failure",
            "optional_stopping": False,
        }
    )


def _verify_h4_repository_identity(
    repository_root: Path,
    profile: H4ExecutionProfile,
) -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repository_root,
        check=True,
        capture_output=True,
    ).stdout
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked_tree = subprocess.run(
        ["git", "ls-files", "-s", "-z"],
        cwd=repository_root,
        check=True,
        capture_output=True,
    ).stdout
    return (
        not status
        and commit == profile.repository_commit
        and hashlib.sha256(tracked_tree).hexdigest() == profile.repository_tree_sha256
    )


def _study_outcome(
    loop: BenchmarkResearchLoopResult,
    directed_progress: float,
) -> StudyOutcome:
    proposed = loop.patch_proposal_count
    adopted = loop.adopted_patch_count
    return StudyOutcome(
        useful_results=int(directed_progress > 0),
        proposed_ideas=proposed,
        valid_ideas=adopted,
        pilots=loop.development_experiment_count,
        discarded_ideas=proposed - adopted,
        unproductive_experiments=loop.reverted_patch_count,
        total_experiments=loop.development_experiment_count + 1,
        gpu_hours_before_useful_signal=None,
        pivots=proposed,
        correct_pivots=(adopted if directed_progress > 0 else 0),
        evidence_sufficiency=1.0,
        reviewer_concerns_opened=0,
        reviewer_concerns_closed=0,
        total_claims=0,
        unsupported_claims=0,
    )


def _best_development_receipt_path(loop_directory: Path, iteration: int) -> Path:
    directory = "000-baseline" if iteration == 0 else f"{iteration:03d}"
    return loop_directory / "iterations" / directory / "development" / "RESULT.json"


def _verify_repository_file(
    repository_root: Path,
    candidate: Path,
    expected_sha256: str,
    *,
    label: str,
) -> None:
    if candidate.is_symlink():
        raise ValueError(f"native benchmark {label} cannot be a symbolic link")
    resolved = candidate.resolve(strict=True)
    if (
        not resolved.is_relative_to(repository_root)
        or not resolved.is_file()
        or _file_sha256(resolved) != expected_sha256
    ):
        raise ValueError(f"native benchmark {label} identity mismatch")


def _repository_regular_file(repository_root: Path, locator: str) -> Path:
    current = repository_root
    for part in Path(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("native H4 repository artifact traverses a symbolic link")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(repository_root) or not resolved.is_file():
        raise ValueError("native H4 repository artifact escapes the repository")
    return resolved


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(
            (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
        )
        handle.flush()
        os.fsync(handle.fileno())


def _post_assignment_h4_failure_result(
    repository_root: Path,
    config: NativeBenchmarkAdapterConfig,
    request: NativeBenchmarkCellRequest,
    *,
    failure_path: Path,
) -> EvaluationAdapterResult | None:
    """Convert a post-assignment protocol exception into a conservative ITT outcome."""

    if config.schema_version != "1.1":
        return None
    native_root = failure_path.parent
    arm_path = native_root / "H4_ARM_REQUEST.json"
    if not arm_path.is_file():
        return None
    arm = load_h4_arm_run_request(arm_path)
    cell = request.cell
    if (
        arm.campaign_manifest_sha256 != request.campaign_manifest_sha256
        or arm.plan_sha256 != request.plan_sha256
        or arm.cell_id != cell.cell_id
        or arm.task_id != cell.task_id
        or arm.condition.value != cell.system_id
        or arm.seed != cell.seed
        or arm.repetition != cell.repetition
    ):
        return None
    task_binding = config.tasks[cell.task_id]
    if (
        task_binding.failure_directed_progress_penalty is None
        or config.h4_execution_profile is None
    ):
        return None
    profile_path = repository_root.joinpath(
        *Path(config.h4_execution_profile.locator).parts
    ).resolve(strict=True)
    if (
        not profile_path.is_relative_to(repository_root)
        or _file_sha256(profile_path) != config.h4_execution_profile.sha256
    ):
        return None
    profile = load_h4_execution_profile(profile_path)
    if profile.profile_sha256 != arm.profile_sha256:
        return None
    spec_path = repository_root.joinpath(*Path(task_binding.task_spec.locator).parts).resolve(
        strict=True
    )
    if (
        not spec_path.is_relative_to(repository_root)
        or _file_sha256(spec_path) != task_binding.task_spec.sha256
    ):
        return None
    spec = load_benchmark_task_runtime_spec(spec_path)
    usage = _conservative_h4_failure_usage(config, cell)
    (
        exception_loop_sha256,
        exception_candidate_sha256,
        exception_heldout_sha256,
        exception_predecessor_sha256,
    ) = _h4_exception_evidence_bindings(native_root, arm)
    receipt = H4TerminalOutcomeReceipt.create(
        profile_sha256=profile.profile_sha256,
        arm_run_request_sha256=arm.request_sha256,
        campaign_manifest_sha256=request.campaign_manifest_sha256,
        cell_id=cell.cell_id,
        task_id=cell.task_id,
        condition=arm.condition,
        failure_stage="adapter-exception",
        error_code="native-benchmark-adapter-failed",
        failure_artifact_sha256=_file_sha256(failure_path),
        last_valid_predecessor_sha256=exception_predecessor_sha256,
        resource_usage=_h4_terminal_resource_usage(usage),
        usage_accounting="conservative-authorized-ceiling",
    )
    terminal_path = native_root / "H4_TERMINAL_OUTCOME.json"
    _write_json(terminal_path, receipt.model_dump(mode="json"))
    measurement = NativeBenchmarkObjectiveMeasurement.create(
        schema_version="1.1",
        cell_id=cell.cell_id,
        task_id=cell.task_id,
        condition_id=cell.system_id,
        outcome_status="itt_bounded_failure",
        frozen_candidate_sha256=exception_candidate_sha256,
        heldout_receipt_sha256=exception_heldout_sha256,
        metric_name=spec.primary_metric,
        metric_direction=spec.metric_direction,
        heldout_score=None,
        baseline_heldout_score=spec.baseline_heldout_score,
        directed_progress=task_binding.failure_directed_progress_penalty,
        h4_execution_profile_sha256=profile.profile_sha256,
        h4_arm_run_request_sha256=arm.request_sha256,
        loop_result_sha256=exception_loop_sha256,
        terminal_evidence_sha256=receipt.receipt_sha256,
        lifecycle_policy_weight=arm.lifecycle_policy_weight,
    )
    measurement_path = native_root / "OBJECTIVE_MEASUREMENT.json"
    _write_json(measurement_path, measurement.model_dump(mode="json"))
    evidence_files = _native_h4_evidence_files(native_root)
    index_payload = {
        "schema_version": "1.1",
        "adapter_config_id": config.config_id,
        "campaign_manifest_sha256": request.campaign_manifest_sha256,
        "plan_sha256": request.plan_sha256,
        "cell_sha256": content_sha256(cell),
        "task_spec_fingerprint": spec.fingerprint,
        "loop_result_sha256": exception_loop_sha256,
        "terminal_outcome_receipt_sha256": receipt.receipt_sha256,
        "heldout_receipt_sha256": exception_heldout_sha256,
        "objective_measurement_sha256": measurement.measurement_sha256,
        "heldout_scoring_executed_only_after_candidate_freeze": False,
        "model_invocations_after_candidate_freeze": 0,
        "evidence_files": evidence_files,
        "evidence_tree_sha256": content_sha256(evidence_files),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    index_payload["evidence_index_sha256"] = content_sha256(index_payload)
    index_path = native_root / "EVIDENCE_INDEX.json"
    _write_json(index_path, index_payload)
    artifacts = (arm_path, terminal_path, measurement_path, index_path, failure_path)
    return EvaluationAdapterResult(
        status="failed",
        evidence_class="real",
        usage=usage,
        artifact_paths=tuple(
            path.relative_to(failure_path.parent.parent).as_posix() for path in artifacts
        ),
        error_code="h4-itt-bounded-failure",
    )


def _conservative_h4_failure_usage(
    config: NativeBenchmarkAdapterConfig,
    cell: PlannedEvaluationCell,
) -> EvaluationAdapterUsage:
    resource = cell.resource
    if cell.lane_kind is ExecutionLaneKind.API_ONLY:
        return EvaluationAdapterUsage(
            request_count=resource.max_requests,
            input_tokens=resource.max_total_tokens,
            output_tokens=0,
            max_input_tokens_observed=resource.max_input_tokens_per_call,
            max_output_tokens_observed=resource.max_output_tokens_per_call,
            api_cost=resource.max_cost,
            experiment_count=config.maximum_patch_iterations + 2,
        )
    return EvaluationAdapterUsage(
        experiment_count=config.maximum_patch_iterations + 2,
    )


def _h4_terminal_resource_usage(
    usage: EvaluationAdapterUsage,
) -> H4TerminalResourceUsage:
    return H4TerminalResourceUsage.model_validate(usage.model_dump(mode="json"))


def _h4_exception_evidence_bindings(
    native_root: Path,
    arm: H4ArmRunRequest,
) -> tuple[str | None, str | None, str | None, str]:
    """Bind the latest valid immutable evidence written before an exception."""

    loop_sha256: str | None = None
    candidate_sha256: str | None = None
    heldout_sha256: str | None = None
    predecessor_sha256 = arm.request_sha256
    loop_path = native_root / "development_loop" / "RESULT.json"
    if loop_path.is_file():
        try:
            loop_sha256 = BenchmarkResearchLoopResult.model_validate_json(
                loop_path.read_bytes()
            ).result_sha256
            predecessor_sha256 = loop_sha256
        except ValueError:
            pass
    candidate_path = native_root / "FROZEN_CANDIDATE.json"
    if candidate_path.is_file():
        try:
            candidate_sha256 = BenchmarkFrozenCandidate.model_validate_json(
                candidate_path.read_bytes()
            ).candidate_sha256
            predecessor_sha256 = candidate_sha256
        except ValueError:
            pass
    heldout_path = native_root / "heldout" / "execution" / "RESULT.json"
    if heldout_path.is_file():
        try:
            heldout_sha256 = BenchmarkHeldoutExecutionReceipt.model_validate_json(
                heldout_path.read_bytes()
            ).receipt_sha256
            predecessor_sha256 = heldout_sha256
        except ValueError:
            pass
    return (
        loop_sha256,
        candidate_sha256,
        heldout_sha256,
        predecessor_sha256,
    )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--cell-request")
    parser.add_argument("--allow-execution", action="store_true")
    args = parser.parse_args(argv)
    repository_root = Path(args.repository_root).resolve(strict=True)
    config_path = Path(args.config).resolve(strict=True)
    if args.config_sha256 != _file_sha256(config_path):
        raise ValueError("native benchmark adapter config hash differs from its launcher")
    request_value = args.cell_request or os.environ.get("SCITASTE_EVALUATION_CELL_REQUEST")
    if not request_value:
        raise ValueError("native benchmark cell request is unavailable")
    request_path = Path(request_value).resolve(strict=True)
    request = load_native_benchmark_cell_request(request_path)
    expected_cell_id = os.environ.get("SCITASTE_EVALUATION_CELL_ID")
    if expected_cell_id is not None and request.cell.cell_id != expected_cell_id:
        raise ValueError("native benchmark cell identity differs from campaign environment")
    expected_result = os.environ.get("SCITASTE_EVALUATION_CELL_RESULT")
    result_path = request.adapter_result_path.resolve()
    if expected_result is not None and result_path != Path(expected_result).resolve():
        raise ValueError("native benchmark result path differs from the campaign environment")
    if (
        result_path.parent != request_path.parent
        or result_path.exists()
        or result_path.is_symlink()
    ):
        raise ValueError("native benchmark result path is outside its fresh campaign cell")
    config = load_native_benchmark_adapter_config(config_path)
    runner = NativeBenchmarkCellRunner(
        repository_root,
        config,
        request,
        cell_request_path=request_path,
    )
    try:
        result = runner.run(allow_execution=args.allow_execution)
    except Exception as exc:
        failure = request_path.parent / "native_benchmark" / "FAILURE.json"
        if not failure.exists():
            _write_json(
                failure,
                {
                    "schema_version": "1.0",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:2_000],
                },
            )
        try:
            h4_failure = _post_assignment_h4_failure_result(
                repository_root,
                config,
                request,
                failure_path=failure,
            )
        except (KeyError, OSError, RuntimeError, ValueError):
            h4_failure = None
        result = h4_failure or EvaluationAdapterResult(
            status="failed",
            evidence_class="real",
            usage=EvaluationAdapterUsage(experiment_count=0),
            artifact_paths=(failure.relative_to(request_path.parent).as_posix(),),
            error_code="native-benchmark-adapter-failed",
        )
    _write_json(result_path, result.model_dump(mode="json"))
    return 0


__all__ = [
    "AdapterFileBinding",
    "NativeBenchmarkAdapterConfig",
    "NativeBenchmarkCellRequest",
    "NativeBenchmarkCellRunner",
    "NativeBenchmarkObjectiveMeasurement",
    "NativeBenchmarkTaskBinding",
    "load_native_benchmark_adapter_config",
    "load_native_benchmark_cell_request",
    "pair_h4_objective_measurements",
    "verify_native_h4_static_preparation",
]


if __name__ == "__main__":
    raise SystemExit(_main())

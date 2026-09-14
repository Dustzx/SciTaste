"""First-party adapter from an authorized campaign cell to benchmark research."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.benchmark.study_models import StudyOutcome
from scitaste.evaluation.campaign_execution import (
    EvaluationAdapterResult,
    EvaluationAdapterUsage,
    EvaluationCampaignManifest,
)
from scitaste.evaluation.cell_plan import PlannedEvaluationCell, load_evaluation_cell_plan
from scitaste.evaluation.prelaunch import ExecutionLaneKind
from scitaste.evaluation.task_condition import (
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
from scitaste.evaluation.task_patch import BenchmarkPatchPolicy
from scitaste.evaluation.task_research_loop import (
    BenchmarkResearchLoop,
    BenchmarkResearchLoopConfig,
    BenchmarkResearchLoopResult,
    RuntimeBenchmarkPatchDecisionProvider,
    bind_benchmark_research_cell,
)
from scitaste.evaluation.task_runtime import (
    BenchmarkTaskRuntimeSpec,
    inspect_benchmark_task_runtime,
    load_benchmark_task_runtime_spec,
    prepare_benchmark_workspace,
)
from scitaste.evaluation.task_scoring import (
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
from scitaste.model_nodes.profiles import load_model_node_profile_set, validate_profile_binding
from scitaste.model_nodes.registry import first_party_node_types
from scitaste.model_nodes.runtime import ModelNodeRuntime
from scitaste.model_nodes.runtime_config import (
    LiveRuntimeBackend,
    LocalRuntimeBackend,
    RuntimeBackendBinding,
    ScriptedRuntimeBackend,
)
from scitaste.project import ProjectRuntime
from scitaste.project.models import (
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.taste.conditions import load_native_condition_matrix

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

    @field_validator("selected_context_paths")
    @classmethod
    def selected_paths_are_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("native benchmark selected context paths must be unique")
        return tuple(
            validate_relative_locator(value, field_name="selected context path")
            for value in values
        )


class NativeBenchmarkAdapterConfig(BaseModel):
    """Non-secret configuration shared by all native cells in one campaign."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    config_id: str
    condition_matrix: AdapterFileBinding
    guidance_set: AdapterFileBinding
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

    @model_validator(mode="after")
    def identities_and_backend_are_closed(self) -> NativeBenchmarkAdapterConfig:
        validate_entry_id(self.config_id, field_name="config_id")
        validate_entry_id(self.model_profile_id, field_name="model_profile_id")
        for task_id in self.tasks:
            validate_entry_id(task_id, field_name="task_id")
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


class NativeBenchmarkObjectiveMeasurement(BaseModel):
    """Raw task score retained outside the legacy count-oriented study outcome."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    cell_id: str
    task_id: str
    condition_id: str
    frozen_candidate_sha256: str = Field(pattern=_SHA256)
    heldout_receipt_sha256: str = Field(pattern=_SHA256)
    metric_name: str
    metric_direction: Literal["higher", "lower"]
    heldout_score: float = Field(allow_inf_nan=False)
    baseline_heldout_score: float = Field(allow_inf_nan=False)
    directed_progress: float = Field(allow_inf_nan=False)
    scorer_owned: Literal[True] = True
    model_invocations_after_freeze: Literal[0] = 0
    measurement_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def identity_and_hash_are_closed(self) -> NativeBenchmarkObjectiveMeasurement:
        validate_entry_id(self.cell_id, field_name="cell_id")
        validate_entry_id(self.task_id, field_name="task_id")
        validate_entry_id(self.condition_id, field_name="condition_id")
        expected_progress = (
            self.heldout_score - self.baseline_heldout_score
            if self.metric_direction == "higher"
            else self.baseline_heldout_score - self.heldout_score
        )
        if abs(self.directed_progress - expected_progress) > 1e-12:
            raise ValueError("native benchmark directed progress mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"measurement_sha256"}))
        if self.measurement_sha256 != expected:
            raise ValueError("native benchmark objective measurement hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> NativeBenchmarkObjectiveMeasurement:
        payload = {"schema_version": "1.0", **values}
        payload.pop("measurement_sha256", None)
        unsigned = cls.model_construct(measurement_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"measurement_sha256"}))
        return cls(**payload, measurement_sha256=digest)


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
        guidance = load_benchmark_research_guidance_set(
            self._bound_file(self.config.guidance_set)
        )
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
            source_root=self.repository_root,
            workspace=workspace,
        )
        loop_result = loop.run(
            BenchmarkResearchLoopConfig(
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
            ),
            output_directory=loop_directory,
            allow_model_decisions=True,
            allow_source_mutation=True,
            allow_development_execution=True,
        )
        loop_result_path = loop_directory / "RESULT.json"
        if loop_result.status == "failed" or loop_result.best_iteration is None:
            evidence = self._write_evidence_index(
                native_root,
                campaign,
                spec,
                loop_result,
                heldout=None,
                measurement=None,
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
        development_receipt = load_benchmark_development_execution_receipt(
            development_receipt_path
        )
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
            evidence = self._write_evidence_index(
                native_root,
                campaign,
                spec,
                loop_result,
                heldout=heldout,
                measurement=None,
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
        if plan_binding is None:
            raise ValueError("registered evaluation lacks a cell plan")
        plan = load_evaluation_cell_plan(evaluation_root / plan_binding.locator)
        registered = next(
            (item for item in plan.cells if item.cell_id == cell.cell_id),
            None,
        )
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
        ):
            raise ValueError("native benchmark cell request differs from its campaign")
        return campaign

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
                or profile.admission.max_input_tokens
                > int(resource.max_input_tokens_per_call or 0)
                or profile.admission.max_output_tokens
                > int(resource.max_output_tokens_per_call or 0)
                or self.config.maximum_patch_iterations * profile.admission.max_total_tokens
                > int(resource.max_total_tokens or 0)
                or self.config.maximum_patch_iterations
                * profile.admission.max_response_cost_usd
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
                loop.model_cost_usd
                if isinstance(self.config.backend, LiveRuntimeBackend)
                else None
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
    ) -> Path:
        path = native_root / "EVIDENCE_INDEX.json"
        payload = {
            "schema_version": "1.0",
            "adapter_config_id": self.config.config_id,
            "campaign_manifest_sha256": campaign.manifest_sha256,
            "plan_sha256": campaign.plan_sha256,
            "cell_sha256": content_sha256(self.request.cell),
            "task_spec_fingerprint": spec.fingerprint,
            "loop_result_sha256": loop.result_sha256,
            "heldout_receipt_sha256": (
                heldout.receipt_sha256 if heldout is not None else None
            ),
            "objective_measurement_sha256": (
                measurement.measurement_sha256 if measurement is not None else None
            ),
            "heldout_opened_only_after_candidate_freeze": heldout is not None,
            "model_invocations_after_candidate_freeze": 0,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        payload["evidence_index_sha256"] = content_sha256(payload)
        _write_json(path, payload)
        return path

    def _artifact_paths(self, *paths: Path) -> tuple[str, ...]:
        locators: list[str] = []
        for path in paths:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(self.cell_directory) or not resolved.is_file():
                raise ValueError("native benchmark artifact escapes its campaign cell")
            locators.append(resolved.relative_to(self.cell_directory).as_posix())
        return tuple(locators)


def load_native_benchmark_cell_request(path: str | Path) -> NativeBenchmarkCellRequest:
    source = Path(path)
    if (
        source.is_symlink()
        or not source.is_file()
        or source.stat().st_size > _MAX_CELL_REQUEST_BYTES
    ):
        raise ValueError("native benchmark cell request must be a bounded regular file")
    return NativeBenchmarkCellRequest.model_validate_json(source.read_bytes(), strict=True)


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
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
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
        result = EvaluationAdapterResult(
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
]


if __name__ == "__main__":
    raise SystemExit(_main())

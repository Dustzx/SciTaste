"""Evidence-preserving multi-round research control for benchmark task cells."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.campaign_execution import EvaluationCampaignManifest
from scitaste.evaluation.cell_plan import PlannedEvaluationCell
from scitaste.evaluation.h4_execution import (
    H4BenchmarkResearchActionProvider,
    H4ResearchActionDecision,
    build_h4_benchmark_action_menu,
)
from scitaste.evaluation.h4_state_probe import (
    H4DevelopmentFeedbackEvent,
    reduce_h4_feedback_context,
)
from scitaste.evaluation.task_condition import BenchmarkResearchConditionGuidance
from scitaste.evaluation.task_execution import (
    BenchmarkDevelopmentExecutionReceipt,
    BenchmarkDevelopmentLimits,
    BenchmarkDevelopmentRunRequest,
)
from scitaste.evaluation.task_patch import (
    BenchmarkPatchPolicy,
    BenchmarkPatchProducer,
    apply_benchmark_patch,
    hash_editable_surface,
    inspect_benchmark_patch,
    rollback_benchmark_patch,
    snapshot_benchmark_editable_files,
)
from scitaste.evaluation.task_patch_generation import (
    BenchmarkPatchGenerationInput,
    BenchmarkPatchGenerationOutput,
    BenchmarkResearchActionDirective,
    materialize_benchmark_patch_proposal,
)
from scitaste.evaluation.task_runtime import (
    BenchmarkTaskRuntimeSpec,
    PreparedBenchmarkWorkspace,
    hash_benchmark_tree,
    hash_protected_surface,
)
from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.facade import (
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
)
from scitaste.model_nodes.models import NodePolicy, NodeResultStatus
from scitaste.model_nodes.profiles import ModelNodeProfile
from scitaste.model_nodes.runtime import ModelNodeTrigger, RuntimeBackendMode, RuntimeOutcome
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.state.research_state import (
    ExperimentPlan,
    ResearchStage,
    ResearchState,
    ResourceBudget,
    ResourceUsage,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class BenchmarkPatchDecision(BaseModel):
    """One provider result plus its durable model-node provenance and usage."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    output: BenchmarkPatchGenerationOutput
    producer: BenchmarkPatchProducer
    invocation_receipt_sha256: str | None = Field(default=None, pattern=_SHA256)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    decision_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def provenance_and_hash_are_consistent(self) -> BenchmarkPatchDecision:
        if (self.producer.mode == "model") != (self.invocation_receipt_sha256 is not None):
            raise ValueError("benchmark patch decision lacks matching invocation provenance")
        expected = content_sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))
        if self.decision_sha256 != expected:
            raise ValueError("benchmark patch decision hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkPatchDecision:
        payload = {"schema_version": "1.0", **values}
        payload.pop("decision_sha256", None)
        unsigned = cls.model_construct(decision_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"decision_sha256"}))
        return cls(**payload, decision_sha256=digest)


class BenchmarkPatchDecisionProvider(Protocol):
    def decide(
        self,
        input_data: BenchmarkPatchGenerationInput,
        *,
        loop_id: str,
        iteration: int,
    ) -> BenchmarkPatchDecision: ...


class BenchmarkDevelopmentExecutor(Protocol):
    def run(
        self,
        request: BenchmarkDevelopmentRunRequest,
        *,
        result_directory: str | Path,
        allow_execution: bool = False,
    ) -> BenchmarkDevelopmentExecutionReceipt: ...


class RuntimeBenchmarkPatchDecisionProvider:
    """Bind the research loop to SciTaste's durable, budgeted model-node runtime."""

    def __init__(
        self,
        facade: ModelNodeFacade,
        *,
        project_id: str,
        run_id: str,
        expected_project_revision: int,
        state_revision: int,
        profile: ModelNodeProfile,
        policy: NodePolicy,
        backend_mode: RuntimeBackendMode,
        backend: StructuredModelBackend | None,
        seed: int,
        allow_live: bool = False,
        allow_local: bool = False,
    ) -> None:
        self.facade = facade
        self.project_id = project_id
        self.run_id = run_id
        self.expected_project_revision = expected_project_revision
        self.state_revision = state_revision
        self.profile = profile
        self.policy = policy
        self.backend_mode = backend_mode
        self.backend = backend
        self.seed = seed
        self.allow_live = allow_live
        self.allow_local = allow_local

    def decide(
        self,
        input_data: BenchmarkPatchGenerationInput,
        *,
        loop_id: str,
        iteration: int,
    ) -> BenchmarkPatchDecision:
        invocation_id = f"{loop_id}-patch-node-{iteration}"
        request = ModelNodeFacadeRequest(
            project_id=self.project_id,
            run_id=self.run_id,
            invocation_id=invocation_id,
            request_id=invocation_id,
            expected_project_revision=self.expected_project_revision,
            node_name="benchmark-research-patch",
            node_input=_benchmark_patch_node_input(input_data),
            state_projection=ImmutableStateProjection(
                project_id=self.project_id,
                state_snapshot_id=input_data.patch_context.context_sha256,
                state_revision=self.state_revision,
                stage="EXPERIMENTATION",
                metadata={
                    "loop_id": loop_id,
                    "iteration": iteration,
                    "task_id": input_data.task_id,
                },
            ),
            trigger=ModelNodeTrigger(
                trigger_id=f"{loop_id}-iteration-{iteration}",
                reason="Select a bounded source patch or stop from development evidence.",
            ),
            profile=self.profile,
            policy=self.policy,
            backend_mode=self.backend_mode,
            seed=self.seed,
        )
        facade_result = self.facade.execute(
            request,
            backend=self.backend,
            resume=True,
            allow_live=self.allow_live,
            allow_local=self.allow_local,
        )
        result = facade_result.result
        if (
            facade_result.receipt.outcome is not RuntimeOutcome.ACCEPTED
            or result is None
            or result.status is not NodeResultStatus.ACCEPTED
            or result.proposal is None
        ):
            blockers = ", ".join(facade_result.receipt.blockers) or "proposal rejected"
            raise ValueError(f"benchmark patch model node did not produce advice: {blockers}")
        cost = facade_result.receipt.telemetry.cost_usd
        if cost is None:
            raise ValueError("benchmark patch model node lacks cost telemetry")
        return BenchmarkPatchDecision.create(
            output=result.proposal,
            producer=BenchmarkPatchProducer(
                mode="model",
                producer_id="benchmark-research-patch",
                provider=result.response.backend,
                model=result.response.model,
                request_sha256=result.request.fingerprint,
                response_sha256=result.response.raw_response_sha256,
            ),
            invocation_receipt_sha256=facade_result.receipt.entry_sha256,
            input_tokens=facade_result.receipt.telemetry.input_tokens,
            output_tokens=facade_result.receipt.telemetry.output_tokens,
            cost_usd=cost,
        )


class BenchmarkResearchCellBinding(BaseModel):
    """Exact authorized campaign cell whose task loop is being executed."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    evaluation_id: str
    campaign_run_id: str
    campaign_manifest_sha256: str = Field(pattern=_SHA256)
    evaluation_bundle_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    cell_id: str
    cell_sha256: str = Field(pattern=_SHA256)
    system_id: str
    task_id: str
    resource_sha256: str = Field(pattern=_SHA256)
    seed: int = Field(ge=0)
    execution_authorized: Literal[True] = True
    binding_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def identity_and_hash_are_consistent(self) -> BenchmarkResearchCellBinding:
        validate_project_id(self.project_id)
        for value, label in (
            (self.evaluation_id, "evaluation_id"),
            (self.campaign_run_id, "campaign_run_id"),
            (self.cell_id, "cell_id"),
            (self.system_id, "system_id"),
            (self.task_id, "task_id"),
        ):
            validate_entry_id(value, field_name=label)
        expected = content_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("benchmark research cell binding hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkResearchCellBinding:
        payload = {"schema_version": "1.0", **values}
        payload.pop("binding_sha256", None)
        unsigned = cls.model_construct(binding_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"binding_sha256"}))
        return cls(**payload, binding_sha256=digest)


def bind_benchmark_research_cell(
    campaign: EvaluationCampaignManifest,
    cell: PlannedEvaluationCell,
) -> BenchmarkResearchCellBinding:
    """Derive a task-loop identity from an authorized selected campaign cell."""

    if cell.cell_id not in campaign.selected_cell_ids:
        raise ValueError("benchmark research cell is not selected by the campaign")
    if cell.proposal_sha256 != campaign.proposal_sha256:
        raise ValueError("benchmark research cell proposal differs from the campaign")
    return BenchmarkResearchCellBinding.create(
        project_id=campaign.project_id,
        evaluation_id=campaign.evaluation_id,
        campaign_run_id=campaign.run_id,
        campaign_manifest_sha256=campaign.manifest_sha256,
        evaluation_bundle_sha256=campaign.evaluation_bundle_sha256,
        plan_sha256=campaign.plan_sha256,
        cell_id=cell.cell_id,
        cell_sha256=content_sha256(cell),
        system_id=cell.system_id,
        task_id=cell.task_id,
        resource_sha256=cell.resource.resource_sha256,
        seed=cell.seed,
    )


class BenchmarkResearchLoopConfig(BaseModel):
    """Controller-owned scientific, condition, budget, and authorization boundary."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    loop_id: str
    cell: BenchmarkResearchCellBinding
    condition: BenchmarkResearchConditionGuidance
    execution_profile_fingerprint: str = Field(pattern=_SHA256)
    resource_verification_receipt_sha256: str = Field(pattern=_SHA256)
    selected_context_paths: tuple[str, ...] = Field(min_length=1, max_length=50)
    maximum_patch_iterations: int = Field(default=4, ge=1, le=20)
    maximum_failed_experiments: int = Field(default=2, ge=1, le=10)
    minimum_absolute_improvement: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    experiment_feedback_prefix: tuple[str, ...] = Field(default=(), max_length=16)
    constraints: tuple[str, ...] = Field(min_length=1, max_length=64)
    patch_policy: BenchmarkPatchPolicy = Field(default_factory=BenchmarkPatchPolicy)
    development_limits: BenchmarkDevelopmentLimits = Field(
        default_factory=BenchmarkDevelopmentLimits
    )
    h4_arm_run_request_sha256: str | None = Field(default=None, pattern=_SHA256)
    research_resource_budget: ResourceBudget | None = None
    execution_authorized: Literal[True] = True
    heldout_authorized: Literal[False] = False

    @model_validator(mode="after")
    def identifiers_and_guidance_are_canonical(self) -> BenchmarkResearchLoopConfig:
        validate_entry_id(self.loop_id, field_name="loop_id")
        for values in (
            self.selected_context_paths,
            self.experiment_feedback_prefix,
            self.constraints,
        ):
            if len(values) != len(set(values)):
                raise ValueError("benchmark research loop tuple values must be unique")
        h4_fields = (self.h4_arm_run_request_sha256, self.research_resource_budget)
        if self.schema_version == "1.1":
            if any(value is None for value in h4_fields):
                raise ValueError("benchmark research loop v1.1 requires H4 action control")
        elif any(value is not None for value in h4_fields):
            raise ValueError("benchmark research loop v1.0 cannot carry H4 action control")
        return self

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        if self.schema_version == "1.0":
            payload.pop("h4_arm_run_request_sha256")
            payload.pop("research_resource_budget")
        return content_sha256(payload)


class BenchmarkResearchIteration(BaseModel):
    model_config = _CONFIG

    iteration: int = Field(ge=0, le=20)
    disposition: Literal[
        "baseline",
        "adopted",
        "reverted",
        "execution_failed",
        "proposal_rejected",
        "stopped",
    ]
    patch_context_sha256: str | None = Field(default=None, pattern=_SHA256)
    research_state_snapshot_id: str | None = Field(
        default=None,
        pattern=r"^state-[0-9a-f]{64}$",
    )
    research_action_menu_sha256: str | None = Field(default=None, pattern=_SHA256)
    research_action_decision_sha256: str | None = Field(default=None, pattern=_SHA256)
    taste_intervention_contract_sha256: str | None = Field(default=None, pattern=_SHA256)
    selected_research_action_sha256: str | None = Field(default=None, pattern=_SHA256)
    research_action_directive_sha256: str | None = Field(default=None, pattern=_SHA256)
    decision_sha256: str | None = Field(default=None, pattern=_SHA256)
    proposal_sha256: str | None = Field(default=None, pattern=_SHA256)
    admission_sha256: str | None = Field(default=None, pattern=_SHA256)
    application_receipt_sha256: str | None = Field(default=None, pattern=_SHA256)
    development_receipt_sha256: str | None = Field(default=None, pattern=_SHA256)
    rollback_receipt_sha256: str | None = Field(default=None, pattern=_SHA256)
    h4_arm_run_request_sha256: str | None = Field(default=None, pattern=_SHA256)
    previous_iteration_receipt_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
    )
    editable_surface_after_sha256: str | None = Field(default=None, pattern=_SHA256)
    post_iteration_state_sha256: str | None = Field(default=None, pattern=_SHA256)
    iteration_receipt_sha256: str | None = Field(default=None, pattern=_SHA256)
    score: float | None = Field(default=None, allow_inf_nan=False)
    improvement_over_predecessor: float | None = Field(default=None, allow_inf_nan=False)
    best_score_after: float | None = Field(default=None, allow_inf_nan=False)
    error_code: str | None = None

    @model_validator(mode="after")
    def h4_receipt_is_closed(self) -> BenchmarkResearchIteration:
        if self.h4_arm_run_request_sha256 is None:
            if any(
                item is not None
                for item in (
                    self.previous_iteration_receipt_sha256,
                    self.editable_surface_after_sha256,
                    self.post_iteration_state_sha256,
                    self.iteration_receipt_sha256,
                )
            ):
                raise ValueError("legacy research iteration cannot carry H4 receipt fields")
            return self
        if any(
            item is None
            for item in (
                self.editable_surface_after_sha256,
                self.post_iteration_state_sha256,
                self.iteration_receipt_sha256,
            )
        ):
            raise ValueError("H4 research iteration lacks its receipt closure")
        expected_state = _post_iteration_state_sha256(self)
        if self.post_iteration_state_sha256 != expected_state:
            raise ValueError("H4 post-iteration state hash differs")
        expected_receipt = content_sha256(
            self.model_dump(mode="json", exclude={"iteration_receipt_sha256"})
        )
        if self.iteration_receipt_sha256 != expected_receipt:
            raise ValueError("H4 iteration receipt hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkResearchIteration:
        payload = dict(values)
        payload.pop("post_iteration_state_sha256", None)
        payload.pop("iteration_receipt_sha256", None)
        provisional = cls.model_construct(
            post_iteration_state_sha256=None,
            iteration_receipt_sha256=None,
            **payload,
        )
        payload["post_iteration_state_sha256"] = _post_iteration_state_sha256(provisional)
        unsigned = cls.model_construct(iteration_receipt_sha256="0" * 64, **payload)
        payload["iteration_receipt_sha256"] = content_sha256(
            unsigned.model_dump(mode="json", exclude={"iteration_receipt_sha256"})
        )
        return cls(**payload)


class BenchmarkResearchLoopResult(BaseModel):
    """Final development-only candidate and complete decision/resource accounting."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    loop_id: str
    config_sha256: str = Field(pattern=_SHA256)
    task_spec_fingerprint: str = Field(pattern=_SHA256)
    cell_binding_sha256: str = Field(pattern=_SHA256)
    condition_guidance_sha256: str = Field(pattern=_SHA256)
    h4_arm_run_request_sha256: str | None = Field(default=None, pattern=_SHA256)
    status: Literal["completed", "stopped", "failed"]
    stop_reason: str
    baseline_score: float | None = Field(default=None, allow_inf_nan=False)
    best_development_score: float | None = Field(default=None, allow_inf_nan=False)
    best_iteration: int | None = Field(default=None, ge=0, le=20)
    best_editable_surface_sha256: str = Field(pattern=_SHA256)
    development_experiment_count: int = Field(ge=0, le=21)
    unverified_development_attempt_count: int = Field(ge=0, le=20)
    patch_proposal_count: int = Field(ge=0, le=20)
    adopted_patch_count: int = Field(ge=0, le=20)
    reverted_patch_count: int = Field(ge=0, le=20)
    failed_experiment_count: int = Field(ge=0, le=20)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    max_input_tokens_observed: int = Field(default=0, ge=0)
    max_output_tokens_observed: int = Field(default=0, ge=0)
    model_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    gpu_hours: float = Field(ge=0, allow_inf_nan=False)
    iterations: tuple[BenchmarkResearchIteration, ...] = Field(min_length=1, max_length=21)
    heldout_executed: Literal[False] = False
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def counts_and_hash_are_consistent(self) -> BenchmarkResearchLoopResult:
        if tuple(item.iteration for item in self.iterations) != tuple(range(len(self.iterations))):
            raise ValueError("benchmark research loop iterations must be contiguous")
        if self.development_experiment_count != sum(
            item.development_receipt_sha256 is not None for item in self.iterations
        ):
            raise ValueError("benchmark research loop development count mismatch")
        if self.unverified_development_attempt_count != sum(
            item.disposition == "execution_failed" and item.development_receipt_sha256 is None
            for item in self.iterations
        ):
            raise ValueError("benchmark research loop unverified attempt count mismatch")
        if self.patch_proposal_count != sum(
            item.proposal_sha256 is not None for item in self.iterations
        ):
            raise ValueError("benchmark research loop proposal count mismatch")
        if self.adopted_patch_count != sum(
            item.disposition == "adopted" for item in self.iterations
        ):
            raise ValueError("benchmark research loop adoption count mismatch")
        if self.reverted_patch_count != sum(
            item.disposition in {"reverted", "execution_failed"}
            and item.rollback_receipt_sha256 is not None
            for item in self.iterations
        ):
            raise ValueError("benchmark research loop rollback count mismatch")
        if self.failed_experiment_count != sum(
            item.disposition == "execution_failed" for item in self.iterations
        ):
            raise ValueError("benchmark research loop failed experiment count mismatch")
        h4_iterations = self.iterations[1:]
        if self.schema_version == "1.1":
            if self.h4_arm_run_request_sha256 is None or any(
                item.research_action_decision_sha256 is None for item in h4_iterations
            ):
                raise ValueError("benchmark research loop v1.1 lacks H4 decisions")
            previous = None
            for item in self.iterations:
                if (
                    item.h4_arm_run_request_sha256 != self.h4_arm_run_request_sha256
                    or item.previous_iteration_receipt_sha256 != previous
                    or item.editable_surface_after_sha256 is None
                ):
                    raise ValueError("benchmark research loop H4 receipt chain differs")
                previous = item.iteration_receipt_sha256
        elif self.h4_arm_run_request_sha256 is not None or any(
            item.research_action_decision_sha256 is not None
            or item.h4_arm_run_request_sha256 is not None
            or item.previous_iteration_receipt_sha256 is not None
            or item.editable_surface_after_sha256 is not None
            for item in self.iterations
        ):
            raise ValueError("benchmark research loop v1.0 cannot carry H4 decisions")
        expected = content_sha256(_loop_result_hash_payload(self))
        if self.result_sha256 != expected:
            raise ValueError("benchmark research loop result hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkResearchLoopResult:
        payload = {"schema_version": "1.0", **values}
        payload.pop("result_sha256", None)
        unsigned = cls.model_construct(result_sha256="0" * 64, **payload)
        digest = content_sha256(_loop_result_hash_payload(unsigned))
        return cls(**payload, result_sha256=digest)


class BenchmarkResearchLoop:
    """Execute baseline → propose/stop → patch → dev score → adopt/rollback."""

    def __init__(
        self,
        spec: BenchmarkTaskRuntimeSpec,
        prepared_workspace: PreparedBenchmarkWorkspace,
        decision_provider: BenchmarkPatchDecisionProvider,
        development_executor: BenchmarkDevelopmentExecutor,
        research_action_provider: H4BenchmarkResearchActionProvider | None = None,
        *,
        source_root: str | Path,
        workspace: str | Path,
    ) -> None:
        self.spec = spec
        self.prepared_workspace = prepared_workspace
        self.decision_provider = decision_provider
        self.development_executor = development_executor
        self.research_action_provider = research_action_provider
        self.source_root = Path(source_root).resolve(strict=True)
        self.workspace = Path(workspace).resolve(strict=True)

    def run(
        self,
        config: BenchmarkResearchLoopConfig,
        *,
        output_directory: str | Path,
        allow_model_decisions: bool = False,
        allow_source_mutation: bool = False,
        allow_development_execution: bool = False,
    ) -> BenchmarkResearchLoopResult:
        if not allow_model_decisions:
            raise ValueError("benchmark research loop requires model-decision authorization")
        if not allow_source_mutation:
            raise ValueError("benchmark research loop requires source-mutation authorization")
        if not allow_development_execution:
            raise ValueError("benchmark research loop requires development-execution authorization")
        self._validate_configuration(config)
        target = Path(output_directory)
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        target.mkdir(parents=True)
        _write_json(target / "CONFIG.json", config.model_dump(mode="json"))

        surface, _ = hash_editable_surface(self.spec, self.workspace)
        baseline = self._execute(
            config,
            iteration=0,
            surface_sha256=surface,
            patch_receipt_sha256=None,
            result_directory=target / "iterations" / "000-baseline" / "development",
        )
        development_count = 1
        gpu_hours = baseline.gpu_hours
        failed_count = int(baseline.status == "failed")
        baseline_score = baseline.objective.score if baseline.objective is not None else None
        best_score = baseline_score
        best_iteration = 0 if baseline_score is not None else None
        records: list[BenchmarkResearchIteration] = []
        records.append(
            _research_iteration(
                config,
                records,
                editable_surface_after_sha256=surface,
                iteration=0,
                disposition="baseline" if baseline.status == "succeeded" else "execution_failed",
                development_receipt_sha256=baseline.receipt_sha256,
                score=baseline_score,
                best_score_after=best_score,
                error_code=baseline.error_code,
            )
        )
        _write_iteration(target, records[-1])
        if baseline.status == "failed":
            return self._finish(
                config,
                target,
                status="failed",
                stop_reason=f"baseline-development-failed:{baseline.error_code}",
                baseline_score=None,
                best_score=None,
                best_iteration=None,
                development_count=development_count,
                proposal_count=0,
                adopted_count=0,
                reverted_count=0,
                failed_count=failed_count,
                input_tokens=0,
                output_tokens=0,
                max_input_tokens_observed=0,
                max_output_tokens_observed=0,
                model_cost=0,
                gpu_hours=gpu_hours,
                records=records,
            )

        assert baseline_score is not None
        feedback = list(config.experiment_feedback_prefix)
        feedback.append(
            _score_feedback(
                self.spec,
                baseline_score,
                baseline_score,
                improvement=0.0,
                adopted=True,
            )
        )
        proposal_count = 0
        adopted_count = 0
        reverted_count = 0
        input_tokens = 0
        output_tokens = 0
        max_input_tokens_observed = 0
        max_output_tokens_observed = 0
        model_cost = 0.0
        status: Literal["completed", "stopped", "failed"] = "completed"
        stop_reason = "patch-iteration-budget-exhausted"

        for iteration in range(1, config.maximum_patch_iterations + 1):
            iteration_root = target / "iterations" / f"{iteration:03d}"
            iteration_root.mkdir(parents=True)
            context = snapshot_benchmark_editable_files(
                self.spec,
                self.prepared_workspace,
                self.workspace,
                selected_paths=config.selected_context_paths,
            )
            action_decision = None
            action_directive = None
            if self.research_action_provider is not None:
                state = self._research_state(
                    config,
                    iteration=iteration,
                    best_score=best_score,
                    baseline_score=baseline_score,
                    development_count=development_count,
                    failed_count=failed_count,
                    model_cost=model_cost,
                    gpu_hours=gpu_hours,
                    feedback=tuple(feedback),
                    records=tuple(records),
                )
                action_menu = build_h4_benchmark_action_menu(iteration=iteration)
                action_decision = self.research_action_provider.decide(
                    state,
                    action_menu,
                    loop_id=config.loop_id,
                    iteration=iteration,
                )
                _write_json(
                    iteration_root / "RESEARCH_STATE.json",
                    state.model_dump(mode="json"),
                )
                _write_json(
                    iteration_root / "RESEARCH_ACTION_DECISION.json",
                    action_decision.model_dump(mode="json"),
                )
                if action_decision.decision.selected_action.type.value == "STOP":
                    records.append(
                        _research_iteration(
                            config,
                            records,
                            editable_surface_after_sha256=(context.editable_surface_sha256),
                            iteration=iteration,
                            disposition="stopped",
                            patch_context_sha256=context.context_sha256,
                            research_state_snapshot_id=(action_decision.decision.state_snapshot_id),
                            research_action_menu_sha256=(
                                action_decision.contract.action_menu_sha256
                            ),
                            research_action_decision_sha256=(action_decision.decision_sha256),
                            taste_intervention_contract_sha256=(
                                action_decision.contract.contract_sha256
                            ),
                            selected_research_action_sha256=(
                                action_decision.selected_action_sha256
                            ),
                            best_score_after=best_score,
                        )
                    )
                    _write_iteration(target, records[-1])
                    status = "stopped"
                    stop_reason = "taste-controller-stop"
                    break
                action_directive = BenchmarkResearchActionDirective.create(
                    action_id=action_decision.downstream_action_id,
                    action_type=action_decision.downstream_action_type,
                    instruction=action_decision.downstream_instruction,
                )
            input_data = BenchmarkPatchGenerationInput(
                schema_version=("1.1" if action_directive is not None else "1.0"),
                task_id=self.spec.task_id,
                research_problem=self._research_problem_text(),
                primary_metric=self.spec.primary_metric,
                metric_direction=self.spec.metric_direction,
                baseline_development_score=self.spec.baseline_development_score,
                current_development_score=best_score,
                best_development_score=best_score,
                iteration=iteration,
                remaining_experiment_runs=config.maximum_patch_iterations - iteration + 1,
                patch_context=context,
                patch_policy=config.patch_policy,
                experiment_feedback=tuple(feedback[-32:]),
                utility_guidance=config.condition.utility_guidance,
                knowledge_guidance=config.condition.knowledge_guidance,
                taste_guidance=config.condition.taste_guidance,
                critic_guidance=config.condition.critic_guidance,
                research_action=action_directive,
                constraints=config.constraints,
            )
            _write_json(iteration_root / "PATCH_CONTEXT.json", context.model_dump(mode="json"))
            _write_json(iteration_root / "PATCH_INPUT.json", input_data.model_dump(mode="json"))
            decision = self.decision_provider.decide(
                input_data,
                loop_id=config.loop_id,
                iteration=iteration,
            )
            _write_json(iteration_root / "PATCH_DECISION.json", decision.model_dump(mode="json"))
            input_tokens += decision.input_tokens
            output_tokens += decision.output_tokens
            max_input_tokens_observed = max(
                max_input_tokens_observed,
                decision.input_tokens,
            )
            max_output_tokens_observed = max(
                max_output_tokens_observed,
                decision.output_tokens,
            )
            model_cost += decision.cost_usd
            self._verify_model_did_not_mutate(context.editable_surface_sha256)
            if decision.output.decision == "stop":
                if action_decision is not None:
                    records.append(
                        _research_iteration(
                            config,
                            records,
                            editable_surface_after_sha256=(context.editable_surface_sha256),
                            iteration=iteration,
                            disposition="proposal_rejected",
                            patch_context_sha256=context.context_sha256,
                            **_h4_iteration_fields(action_decision, action_directive),
                            decision_sha256=decision.decision_sha256,
                            best_score_after=best_score,
                            error_code="h4-patch-model-failed-to-propose",
                        )
                    )
                    _write_iteration(target, records[-1])
                    status = "failed"
                    stop_reason = "h4-patch-model-failed-to-propose"
                    break
                records.append(
                    _research_iteration(
                        config,
                        records,
                        editable_surface_after_sha256=context.editable_surface_sha256,
                        iteration=iteration,
                        disposition="stopped",
                        patch_context_sha256=context.context_sha256,
                        **_h4_iteration_fields(action_decision, action_directive),
                        decision_sha256=decision.decision_sha256,
                        best_score_after=best_score,
                    )
                )
                _write_iteration(target, records[-1])
                status = "stopped"
                stop_reason = decision.output.stop_reason or "model-stop"
                break

            proposal_count += 1
            proposal = materialize_benchmark_patch_proposal(
                decision.output,
                input_data,
                proposal_id=f"{config.loop_id}-patch-{iteration}",
                producer=decision.producer,
            )
            admission = inspect_benchmark_patch(
                proposal,
                context,
                self.spec,
                self.prepared_workspace,
                config.patch_policy,
                workspace=self.workspace,
            )
            _write_json(iteration_root / "PATCH_PROPOSAL.json", proposal.model_dump(mode="json"))
            _write_json(iteration_root / "PATCH_ADMISSION.json", admission.model_dump(mode="json"))
            if admission.decision == "rejected":
                records.append(
                    _research_iteration(
                        config,
                        records,
                        editable_surface_after_sha256=context.editable_surface_sha256,
                        iteration=iteration,
                        disposition="proposal_rejected",
                        patch_context_sha256=context.context_sha256,
                        **_h4_iteration_fields(action_decision, action_directive),
                        decision_sha256=decision.decision_sha256,
                        proposal_sha256=proposal.fingerprint,
                        admission_sha256=admission.admission_sha256,
                        best_score_after=best_score,
                        error_code="patch-admission-rejected",
                    )
                )
                _write_iteration(target, records[-1])
                status = "failed"
                stop_reason = "patch-admission-rejected"
                break
            application = apply_benchmark_patch(
                proposal,
                admission,
                self.spec,
                config.patch_policy,
                workspace=self.workspace,
                receipt_path=iteration_root / "PATCH_APPLICATION.json",
                allow_mutation=True,
            )
            try:
                development = self._execute(
                    config,
                    iteration=iteration,
                    surface_sha256=application.editable_surface_after_sha256,
                    patch_receipt_sha256=application.receipt_sha256,
                    result_directory=iteration_root / "development",
                )
            except Exception:
                rollback = rollback_benchmark_patch(
                    proposal,
                    context,
                    application,
                    self.spec,
                    workspace=self.workspace,
                    receipt_path=iteration_root / "PATCH_ROLLBACK.json",
                    allow_mutation=True,
                )
                failed_count += 1
                reverted_count += 1
                records.append(
                    _research_iteration(
                        config,
                        records,
                        editable_surface_after_sha256=(rollback.editable_surface_after_sha256),
                        iteration=iteration,
                        disposition="execution_failed",
                        patch_context_sha256=context.context_sha256,
                        **_h4_iteration_fields(action_decision, action_directive),
                        decision_sha256=decision.decision_sha256,
                        proposal_sha256=proposal.fingerprint,
                        admission_sha256=admission.admission_sha256,
                        application_receipt_sha256=application.receipt_sha256,
                        rollback_receipt_sha256=rollback.receipt_sha256,
                        best_score_after=best_score,
                        error_code="development-executor-error",
                    )
                )
                _write_iteration(target, records[-1])
                status = "failed"
                stop_reason = "development-executor-error"
                break
            development_count += 1
            gpu_hours += development.gpu_hours
            score = development.objective.score if development.objective is not None else None
            predecessor_best = best_score
            improvement = (
                None if score is None else _improvement(self.spec, score, predecessor_best)
            )
            adopted = (
                development.status == "succeeded"
                and improvement is not None
                and improvement > config.minimum_absolute_improvement
            )
            rollback_sha256: str | None = None
            if adopted:
                best_score = score
                best_iteration = iteration
                adopted_count += 1
                disposition = "adopted"
            else:
                rollback = rollback_benchmark_patch(
                    proposal,
                    context,
                    application,
                    self.spec,
                    workspace=self.workspace,
                    receipt_path=iteration_root / "PATCH_ROLLBACK.json",
                    allow_mutation=True,
                )
                rollback_sha256 = rollback.receipt_sha256
                reverted_count += 1
                if development.status == "failed":
                    failed_count += 1
                    disposition = "execution_failed"
                else:
                    disposition = "reverted"
            feedback.append(
                _score_feedback(
                    self.spec,
                    score,
                    predecessor_best,
                    improvement=improvement,
                    adopted=adopted,
                )
            )
            records.append(
                _research_iteration(
                    config,
                    records,
                    editable_surface_after_sha256=(
                        application.editable_surface_after_sha256
                        if adopted
                        else rollback.editable_surface_after_sha256
                    ),
                    iteration=iteration,
                    disposition=disposition,
                    patch_context_sha256=context.context_sha256,
                    **_h4_iteration_fields(action_decision, action_directive),
                    decision_sha256=decision.decision_sha256,
                    proposal_sha256=proposal.fingerprint,
                    admission_sha256=admission.admission_sha256,
                    application_receipt_sha256=application.receipt_sha256,
                    development_receipt_sha256=development.receipt_sha256,
                    rollback_receipt_sha256=rollback_sha256,
                    score=score,
                    improvement_over_predecessor=improvement,
                    best_score_after=best_score,
                    error_code=development.error_code,
                )
            )
            _write_iteration(target, records[-1])
            if failed_count >= config.maximum_failed_experiments:
                status = "failed"
                stop_reason = "failed-development-experiment-limit-reached"
                break

        return self._finish(
            config,
            target,
            status=status,
            stop_reason=stop_reason,
            baseline_score=baseline_score,
            best_score=best_score,
            best_iteration=best_iteration,
            development_count=development_count,
            proposal_count=proposal_count,
            adopted_count=adopted_count,
            reverted_count=reverted_count,
            failed_count=failed_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            max_input_tokens_observed=max_input_tokens_observed,
            max_output_tokens_observed=max_output_tokens_observed,
            model_cost=model_cost,
            gpu_hours=gpu_hours,
            records=records,
        )

    def _validate_configuration(self, config: BenchmarkResearchLoopConfig) -> None:
        if (
            self.prepared_workspace.spec_id != self.spec.spec_id
            or self.prepared_workspace.spec_fingerprint != self.spec.fingerprint
        ):
            raise ValueError("benchmark research loop workspace belongs to another task spec")
        if self.prepared_workspace.workspace_locator != self.workspace.name:
            raise ValueError("benchmark research loop workspace locator mismatch")
        _, editable_paths = hash_editable_surface(self.spec, self.workspace)
        workspace_tree, _, _ = hash_benchmark_tree(self.workspace)
        if workspace_tree != self.prepared_workspace.workspace_tree_sha256:
            raise ValueError("benchmark research loop must start from its prepared surface")
        if hash_protected_surface(self.spec, self.workspace) != (
            self.prepared_workspace.protected_surface_sha256
        ):
            raise ValueError("benchmark research loop protected source has drifted")
        if not set(config.selected_context_paths).issubset(editable_paths):
            raise ValueError("benchmark research loop selected context is not editable")
        if config.cell.task_id != self.spec.task_id:
            raise ValueError("benchmark research loop cell belongs to another task")
        if config.cell.system_id != config.condition.condition_id.value:
            raise ValueError("benchmark research loop condition differs from its campaign cell")
        if (config.schema_version == "1.1") != (self.research_action_provider is not None):
            raise ValueError("benchmark research loop H4 provider and config differ")
        if self.research_action_provider is not None and (
            config.h4_arm_run_request_sha256
            != self.research_action_provider.arm_request.request_sha256
        ):
            raise ValueError("benchmark research loop H4 arm request differs")
        self._research_problem_text()

    def _research_state(
        self,
        config: BenchmarkResearchLoopConfig,
        *,
        iteration: int,
        best_score: float,
        baseline_score: float,
        development_count: int,
        failed_count: int,
        model_cost: float,
        gpu_hours: float,
        feedback: tuple[str, ...],
        records: tuple[BenchmarkResearchIteration, ...],
    ) -> ResearchState:
        assert config.research_resource_budget is not None
        feedback_events = _h4_feedback_events(
            self.spec,
            records,
            baseline_score=baseline_score,
        )
        if sum(item.disposition == "failed" for item in feedback_events) != failed_count:
            raise ValueError("H4 feedback reducer and failure counter differ")
        decision_context = reduce_h4_feedback_context(
            maximum_patch_iterations=config.maximum_patch_iterations,
            decision_iteration=iteration,
            history=feedback_events,
        )
        return ResearchState(
            revision=iteration,
            project_id=config.cell.project_id,
            research_direction=self._research_problem_text(),
            target_domain=self.spec.benchmark_id,
            target_venue="ICLR 2027",
            resource_budget=config.research_resource_budget,
            resource_usage=ResourceUsage(
                gpu_hours=gpu_hours,
                experiments=float(development_count),
                api_cost_usd=model_cost,
            ),
            current_stage=ResearchStage.EVIDENCE,
            current_experiment_plan=ExperimentPlan(
                plan_id=f"h4-{self.spec.task_id}",
                objective=(
                    f"Improve held-out {self.spec.primary_metric} under the frozen task "
                    "and resource contract."
                ),
                falsifies=["The selected lifecycle action fails to improve development evidence."],
                estimated_cost={"experiments": float(config.maximum_patch_iterations)},
                matched_baselines=["identical-executor-lifecycle-policy-off"],
                negative_controls=["no-update", "shuffled-credit"],
                expected_information_gain=1.0,
            ),
            executor_context={
                "task_id": self.spec.task_id,
                "iteration": iteration,
                "primary_metric": self.spec.primary_metric,
                "metric_direction": self.spec.metric_direction,
                "baseline_development_score": baseline_score,
                "best_development_score": best_score,
                "failed_experiment_count": failed_count,
                "feedback_sha256": content_sha256(feedback),
                **decision_context.model_dump(mode="json"),
            },
        )

    def _research_problem_text(self) -> str:
        checkout = self.source_root.joinpath(*PurePosixPath(self.spec.source_checkout).parts)
        problem = checkout.joinpath(*PurePosixPath(self.spec.research_problem.locator).parts)
        resolved = problem.resolve(strict=True)
        if not resolved.is_relative_to(checkout.resolve(strict=True)) or not resolved.is_file():
            raise ValueError("benchmark research problem locator escapes its source checkout")
        raw = resolved.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.spec.research_problem.file_sha256:
            raise ValueError("benchmark research problem hash mismatch")
        if not raw or len(raw) > 64_000:
            raise ValueError("benchmark research problem byte size is invalid")
        try:
            text = raw.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("benchmark research problem is not UTF-8") from exc
        if not text or len(text) > 16_000:
            raise ValueError("benchmark research problem text size is invalid")
        return text

    def _verify_model_did_not_mutate(self, editable_surface_sha256: str) -> None:
        editable, _ = hash_editable_surface(self.spec, self.workspace)
        if editable != editable_surface_sha256:
            raise ValueError("benchmark patch decision provider mutated editable source")
        if hash_protected_surface(self.spec, self.workspace) != (
            self.prepared_workspace.protected_surface_sha256
        ):
            raise ValueError("benchmark patch decision provider mutated protected source")

    def _execute(
        self,
        config: BenchmarkResearchLoopConfig,
        *,
        iteration: int,
        surface_sha256: str,
        patch_receipt_sha256: str | None,
        result_directory: Path,
    ) -> BenchmarkDevelopmentExecutionReceipt:
        request = BenchmarkDevelopmentRunRequest(
            request_id=f"{config.loop_id}-dev-{iteration}",
            cell_id=config.cell.cell_id,
            campaign_manifest_sha256=config.cell.campaign_manifest_sha256,
            owner_approval_sha256=config.cell.evaluation_bundle_sha256,
            spec_id=self.spec.spec_id,
            spec_fingerprint=self.spec.fingerprint,
            prepared_workspace_receipt_sha256=self.prepared_workspace.receipt_sha256,
            execution_profile_fingerprint=config.execution_profile_fingerprint,
            resource_verification_receipt_sha256=(config.resource_verification_receipt_sha256),
            editable_surface_sha256=surface_sha256,
            patch_receipt_sha256=patch_receipt_sha256,
            iteration=iteration,
            seed=config.cell.seed,
            limits=config.development_limits,
        )
        result_directory.parent.mkdir(parents=True, exist_ok=True)
        _write_json(
            result_directory.parent / "DEVELOPMENT_REQUEST.json",
            request.model_dump(mode="json"),
        )
        receipt = self.development_executor.run(
            request,
            result_directory=result_directory,
            allow_execution=True,
        )
        self._validate_development_receipt(request, receipt)
        return receipt

    def _validate_development_receipt(
        self,
        request: BenchmarkDevelopmentRunRequest,
        receipt: BenchmarkDevelopmentExecutionReceipt,
    ) -> None:
        expected = (
            (receipt.request_sha256, request.fingerprint, "request"),
            (receipt.spec_fingerprint, self.spec.fingerprint, "task spec"),
            (
                receipt.workspace_receipt_sha256,
                self.prepared_workspace.receipt_sha256,
                "workspace",
            ),
            (
                receipt.execution_profile_fingerprint,
                request.execution_profile_fingerprint,
                "execution profile",
            ),
            (
                receipt.resource_verification_receipt_sha256,
                request.resource_verification_receipt_sha256,
                "resource verification",
            ),
            (receipt.editable_surface_sha256, request.editable_surface_sha256, "editable"),
            (
                receipt.protected_surface_sha256,
                self.prepared_workspace.protected_surface_sha256,
                "protected",
            ),
        )
        for observed, required, label in expected:
            if observed != required:
                raise ValueError(f"benchmark development receipt {label} mismatch")
        editable, _ = hash_editable_surface(self.spec, self.workspace)
        protected = hash_protected_surface(self.spec, self.workspace)
        if editable != request.editable_surface_sha256:
            raise ValueError("benchmark development executor mutated editable source")
        if protected != self.prepared_workspace.protected_surface_sha256:
            raise ValueError("benchmark development executor mutated protected source")
        if receipt.objective is not None and receipt.objective.task_id != self.spec.task_id:
            raise ValueError("benchmark development objective belongs to another task")
        if receipt.objective is not None and receipt.objective.phase != "dev":
            raise ValueError("benchmark development objective belongs to another phase")

    def _finish(
        self,
        config: BenchmarkResearchLoopConfig,
        target: Path,
        *,
        status: Literal["completed", "stopped", "failed"],
        stop_reason: str,
        baseline_score: float | None,
        best_score: float | None,
        best_iteration: int | None,
        development_count: int,
        proposal_count: int,
        adopted_count: int,
        reverted_count: int,
        failed_count: int,
        input_tokens: int,
        output_tokens: int,
        max_input_tokens_observed: int,
        max_output_tokens_observed: int,
        model_cost: float,
        gpu_hours: float,
        records: list[BenchmarkResearchIteration],
    ) -> BenchmarkResearchLoopResult:
        surface, _ = hash_editable_surface(self.spec, self.workspace)
        result = BenchmarkResearchLoopResult.create(
            schema_version=config.schema_version,
            loop_id=config.loop_id,
            config_sha256=config.fingerprint,
            task_spec_fingerprint=self.spec.fingerprint,
            cell_binding_sha256=config.cell.binding_sha256,
            condition_guidance_sha256=config.condition.fingerprint,
            h4_arm_run_request_sha256=config.h4_arm_run_request_sha256,
            status=status,
            stop_reason=stop_reason,
            baseline_score=baseline_score,
            best_development_score=best_score,
            best_iteration=best_iteration,
            best_editable_surface_sha256=surface,
            development_experiment_count=development_count,
            unverified_development_attempt_count=sum(
                item.disposition == "execution_failed" and item.development_receipt_sha256 is None
                for item in records
            ),
            patch_proposal_count=proposal_count,
            adopted_patch_count=adopted_count,
            reverted_patch_count=reverted_count,
            failed_experiment_count=failed_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            max_input_tokens_observed=max_input_tokens_observed,
            max_output_tokens_observed=max_output_tokens_observed,
            model_cost_usd=model_cost,
            gpu_hours=gpu_hours,
            iterations=tuple(records),
        )
        _write_json(target / "RESULT.json", result.model_dump(mode="json"))
        return result


def _improvement(spec: BenchmarkTaskRuntimeSpec, score: float, predecessor: float) -> float:
    return score - predecessor if spec.metric_direction == "higher" else predecessor - score


def _h4_feedback_events(
    spec: BenchmarkTaskRuntimeSpec,
    records: tuple[BenchmarkResearchIteration, ...],
    *,
    baseline_score: float,
) -> tuple[H4DevelopmentFeedbackEvent, ...]:
    events: list[H4DevelopmentFeedbackEvent] = []
    for record in records:
        if record.iteration == 0:
            continue
        if record.disposition == "execution_failed":
            disposition = "failed"
            improvement = None
        elif record.disposition == "adopted":
            disposition = "adopted"
            improvement = record.improvement_over_predecessor
        elif record.improvement_over_predecessor is not None:
            disposition = "reverted"
            improvement = record.improvement_over_predecessor
        else:
            continue
        best_progress = (
            _improvement(spec, record.best_score_after, baseline_score)
            if record.best_score_after is not None
            else 0.0
        )
        events.append(
            H4DevelopmentFeedbackEvent(
                disposition=disposition,
                directed_improvement=improvement,
                best_directed_progress_after=best_progress,
            )
        )
    return tuple(events)


def _score_feedback(
    spec: BenchmarkTaskRuntimeSpec,
    score: float | None,
    predecessor_best: float,
    *,
    improvement: float | None = None,
    adopted: bool,
) -> str:
    if score is None:
        return "The isolated development attempt failed and produced no admissible objective score."
    status = "adopted" if adopted else "reverted"
    return (
        f"Development {spec.primary_metric}={score:.12g}; "
        f"predecessor_best={predecessor_best:.12g}; "
        f"directed_improvement={improvement:.12g}; "
        f"candidate disposition={status}."
    )


def _write_iteration(target: Path, record: BenchmarkResearchIteration) -> None:
    directory = "000-baseline" if record.iteration == 0 else f"{record.iteration:03d}"
    _write_json(
        target / "iterations" / directory / "ITERATION.json",
        record.model_dump(mode="json"),
    )


def _post_iteration_state_sha256(record: BenchmarkResearchIteration) -> str:
    return content_sha256(
        {
            "iteration": record.iteration,
            "disposition": record.disposition,
            "editable_surface_after_sha256": record.editable_surface_after_sha256,
            "score": record.score,
            "best_score_after": record.best_score_after,
            "development_receipt_sha256": record.development_receipt_sha256,
            "rollback_receipt_sha256": record.rollback_receipt_sha256,
            "error_code": record.error_code,
        }
    )


def _research_iteration(
    config: BenchmarkResearchLoopConfig,
    records: list[BenchmarkResearchIteration],
    *,
    editable_surface_after_sha256: str,
    **values: object,
) -> BenchmarkResearchIteration:
    h4_values: dict[str, object] = {}
    if config.schema_version == "1.1":
        h4_values = {
            "h4_arm_run_request_sha256": config.h4_arm_run_request_sha256,
            "previous_iteration_receipt_sha256": (
                records[-1].iteration_receipt_sha256 if records else None
            ),
            "editable_surface_after_sha256": editable_surface_after_sha256,
        }
    if h4_values:
        return BenchmarkResearchIteration.create(**values, **h4_values)
    return BenchmarkResearchIteration(**values)


def _h4_iteration_fields(
    decision: H4ResearchActionDecision | None,
    directive: BenchmarkResearchActionDirective | None,
) -> dict[str, str | None]:
    if decision is None:
        return {}
    return {
        "research_state_snapshot_id": decision.decision.state_snapshot_id,
        "research_action_menu_sha256": decision.contract.action_menu_sha256,
        "research_action_decision_sha256": decision.decision_sha256,
        "taste_intervention_contract_sha256": decision.contract.contract_sha256,
        "selected_research_action_sha256": decision.selected_action_sha256,
        "research_action_directive_sha256": (
            directive.directive_sha256 if directive is not None else None
        ),
    }


def _benchmark_patch_node_input(
    input_data: BenchmarkPatchGenerationInput,
) -> dict[str, object]:
    payload = input_data.model_dump(mode="json")
    if input_data.schema_version == "1.0":
        payload.pop("research_action")
    return payload


def _loop_result_hash_payload(result: BenchmarkResearchLoopResult) -> dict[str, object]:
    payload = result.model_dump(mode="json", exclude={"result_sha256"})
    if result.schema_version == "1.0":
        payload.pop("h4_arm_run_request_sha256")
        for iteration in payload["iterations"]:  # type: ignore[index,union-attr]
            for field in (
                "research_state_snapshot_id",
                "research_action_menu_sha256",
                "research_action_decision_sha256",
                "taste_intervention_contract_sha256",
                "selected_research_action_sha256",
                "research_action_directive_sha256",
                "h4_arm_run_request_sha256",
                "previous_iteration_receipt_sha256",
                "editable_surface_after_sha256",
                "post_iteration_state_sha256",
                "iteration_receipt_sha256",
            ):
                iteration.pop(field)  # type: ignore[union-attr]
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(
            (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
        )
        handle.flush()
        os.fsync(handle.fileno())


__all__ = [
    "BenchmarkDevelopmentExecutor",
    "BenchmarkPatchDecision",
    "BenchmarkPatchDecisionProvider",
    "BenchmarkResearchCellBinding",
    "BenchmarkResearchIteration",
    "BenchmarkResearchLoop",
    "BenchmarkResearchLoopConfig",
    "BenchmarkResearchLoopResult",
    "RuntimeBenchmarkPatchDecisionProvider",
    "bind_benchmark_research_cell",
]

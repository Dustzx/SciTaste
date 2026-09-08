"""Project-owned runner for the preregistered Tool Intelligence study."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.facade import (
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
)
from scitaste.model_nodes.models import NodePolicy, NodeResult, NodeResultStatus
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    StructuredOpenAICompatibleConfig,
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import ModelNodeProfile, load_model_node_profile
from scitaste.model_nodes.runtime import (
    ModelNodeRuntime,
    ModelNodeTrigger,
    RuntimeBackendMode,
    RuntimeOutcome,
    RuntimeVerification,
)
from scitaste.model_nodes.tool_bindings import (
    ContentAddressedRunFile,
    KnowledgeLibraryBinding,
    ProjectToolBindingSet,
    VerifiedProjectToolHandlers,
    load_project_tool_handlers,
)
from scitaste.model_nodes.tool_effectiveness import (
    ToolEffectivenessCondition,
    ToolEffectivenessFixture,
    ToolEffectivenessStudyReport,
    ToolEffectivenessTask,
    ToolEffectivenessTrial,
    build_tool_effectiveness_blind_packet,
    build_tool_effectiveness_trial,
    deterministic_v2_router,
    evaluate_tool_effectiveness_study,
    execute_read_only_step,
    load_tool_effectiveness_fixture,
)
from scitaste.model_nodes.tool_execution import (
    ControlledToolExecutor,
    SemanticGapKind,
    SemanticHotspotKind,
    SemanticHotspotTrigger,
)
from scitaste.model_nodes.tool_execution_runtime import (
    DurableToolExecutionRuntime,
    DurableToolRuntimeVerification,
)
from scitaste.model_nodes.tool_intelligence import (
    ControlledToolProfile,
    EvidenceInspectPermission,
    KnowledgeQueryPermission,
    RegisteredRunComparePermission,
    ToolPlanInput,
    ToolPlanOutput,
    ToolPlanStep,
    canonical_sha256,
)
from scitaste.model_nodes.tool_workflow import (
    ProjectToolIntelligenceBridge,
    ToolHotspotDecision,
    ToolHotspotWorkflowBudget,
    ToolHotspotWorkflowRequest,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime

EFFECTIVENESS_STAGE_PATH = "tool_effectiveness"
_SHA256 = re.compile(r"^[0-9a-f]{40,64}$")


class ToolEffectivenessRunError(ValueError):
    """Raised when a live study cannot preserve its registered identity."""


class ToolEffectivenessRunModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolEffectivenessArtifact(ToolEffectivenessRunModel):
    locator: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ToolEffectivenessRunManifest(ToolEffectivenessRunModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    source_commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    provider: str
    model: str
    protocol_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend_config_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    live_authorized: Literal[True] = True
    retry_count: Literal[0] = 0
    response_count: int = Field(ge=1)
    independent_domain_review_complete: Literal[False] = False
    scientific_effectiveness_claim: Literal[False] = False
    artifacts: tuple[ToolEffectivenessArtifact, ...] = Field(min_length=1)
    model_runtime_verification: RuntimeVerification
    tool_runtime_verification: DurableToolRuntimeVerification
    credentials_persisted: Literal[False] = False
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: Any) -> ToolEffectivenessRunManifest:
        unsigned = cls.model_construct(manifest_sha256="0" * 64, **values)
        return cls.model_validate(
            {
                **values,
                "manifest_sha256": canonical_sha256(
                    unsigned.model_dump(mode="json", exclude={"manifest_sha256"})
                ),
            }
        )

    @model_validator(mode="after")
    def manifest_hash_matches(self) -> ToolEffectivenessRunManifest:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("effectiveness run manifest hash drift")
        return self


class ToolEffectivenessRunBundle(ToolEffectivenessRunModel):
    manifest: ToolEffectivenessRunManifest
    report: ToolEffectivenessStudyReport
    trial_count: int = Field(ge=1)
    recovered_trial_count: int = Field(ge=0)


class ProjectToolEffectivenessRunner:
    """Run or exactly resume one project-owned paired live evaluation."""

    def __init__(
        self,
        *,
        project_runtime: ProjectRuntime,
        fixture: ToolEffectivenessFixture,
        model_profile: ModelNodeProfile,
        backend_config: StructuredOpenAICompatibleConfig,
        run_id: str,
        source_commit: str,
    ) -> None:
        self.project_runtime = project_runtime
        self.fixture = ToolEffectivenessFixture.model_validate_json(
            fixture.model_dump_json(exclude_computed_fields=True), strict=True
        )
        self.model_profile = ModelNodeProfile.model_validate_json(
            model_profile.model_dump_json(exclude_computed_fields=True), strict=True
        )
        self.backend_config = StructuredOpenAICompatibleConfig.model_validate_json(
            backend_config.model_dump_json(), strict=True
        )
        self.run_id = run_id
        self.source_commit = source_commit
        project_ids = {task.scope.project_id for task in self.fixture.protocol.tasks}
        if len(project_ids) != 1:
            raise ToolEffectivenessRunError("study tasks do not share one project identity")
        self.project_id = project_ids.pop()
        if not _SHA256.fullmatch(source_commit):
            raise ToolEffectivenessRunError("source_commit must be a full Git object ID")
        if (self.model_profile.provider, self.model_profile.model) != (
            self.fixture.protocol.provider,
            self.fixture.protocol.model,
        ):
            raise ToolEffectivenessRunError("model profile differs from the protocol identity")
        if (self.backend_config.provider, self.backend_config.model) != (
            self.fixture.protocol.provider,
            self.fixture.protocol.model,
        ):
            raise ToolEffectivenessRunError("backend differs from the protocol identity")
        if not self.model_profile.live_execution_permitted:
            raise ToolEffectivenessRunError("study profile does not permit live execution")
        if self.backend_config.max_retries != 0:
            raise ToolEffectivenessRunError("formal study prohibits provider retries")
        if not self.backend_config.live_enabled or not self.backend_config.pricing_confirmed:
            raise ToolEffectivenessRunError("formal study requires explicit live priced config")

    def run(
        self,
        *,
        blinding_salt: str,
        backend: StructuredModelBackend | None = None,
    ) -> ToolEffectivenessRunBundle:
        snapshot = self._prepare_project()
        stage = self._prepare_stage()
        lock_path = stage / ".study.lock"
        with _exclusive_lock(lock_path, owned_root=self._run_root()):
            controlled = self._controlled_profile()
            verified_handlers = self._materialize_and_bind(snapshot.revision, controlled)
            facade = ModelNodeFacade(ModelNodeRuntime(self.project_runtime))

            def executor_factory() -> ControlledToolExecutor:
                return ControlledToolExecutor(
                    project_runtime=self.project_runtime,
                    state_snapshot_reader=lambda: "study-state-v1",
                    handlers=verified_handlers.handlers,
                )

            tool_runtime = DurableToolExecutionRuntime(
                self.project_runtime,
                executor_factory=executor_factory,
            )
            bridge = ProjectToolIntelligenceBridge(facade, tool_runtime)
            backend = backend or StructuredOpenAICompatibleBackend(self.backend_config)
            if (backend.name, backend.model) != (
                self.fixture.protocol.provider,
                self.fixture.protocol.model,
            ):
                raise ToolEffectivenessRunError("study backend identity drift")
            policy = self._policy(controlled)
            trials: list[ToolEffectivenessTrial] = []
            recovered = 0
            total = len(self.fixture.protocol.tasks) * len(self.fixture.protocol.seeds)
            completed = 0
            for task in self.fixture.protocol.tasks:
                for seed in self.fixture.protocol.seeds:
                    baseline, baseline_recovered = self._baseline_trial(
                        task,
                        seed,
                        verified_handlers,
                    )
                    trials.append(baseline)
                    recovered += baseline_recovered
                    treatment, treatment_recovered = self._treatment_trial(
                        task,
                        seed,
                        controlled=controlled,
                        policy=policy,
                        facade=facade,
                        bridge=bridge,
                        backend=backend,
                        project_revision=snapshot.revision,
                    )
                    trials.append(treatment)
                    recovered += treatment_recovered
                    completed += 1
                    print(
                        json.dumps(
                            {
                                "completed": completed,
                                "total": total,
                                "task_id": task.task_id,
                                "seed": seed,
                                "admitted": treatment.model_admitted,
                                "resolved": treatment.workflow_resolved,
                                "grounded": treatment.grounded_resolution_correct,
                                "tool": (
                                    treatment.selected_step.tool_name.value
                                    if treatment.selected_step is not None
                                    else None
                                ),
                                "tokens": treatment.input_tokens + treatment.output_tokens,
                                "cost_usd": treatment.known_cost_usd,
                                "latency_ms": treatment.model_latency_ms,
                                "recovered": bool(treatment_recovered),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )

            ordered = tuple(sorted(trials, key=lambda item: (item.pair_id, item.condition.value)))
            report = evaluate_tool_effectiveness_study(self.fixture, ordered)
            packet, blind_key = build_tool_effectiveness_blind_packet(
                self.fixture,
                ordered,
                blinding_salt=blinding_salt,
            )
            artifacts = self._publish_final_artifacts(ordered, report, packet, blind_key)
            model_verification = facade.verify(project_id=self.project_id, run_id=self.run_id)
            tool_verification = tool_runtime.verify(
                project_id=self.project_id,
                run_id=self.run_id,
            )
            expected_response_count = len(self.fixture.protocol.tasks) * len(
                self.fixture.protocol.seeds
            )
            if model_verification.totals.entry_count != expected_response_count:
                raise ToolEffectivenessRunError(
                    "model ledger does not contain the exact preregistered response count"
                )
            manifest = ToolEffectivenessRunManifest.create(
                project_id=self.project_id,
                run_id=self.run_id,
                source_commit=self.source_commit,
                provider=self.fixture.protocol.provider,
                model=self.fixture.protocol.model,
                protocol_fingerprint=self.fixture.protocol.fingerprint,
                fixture_fingerprint=self.fixture.fingerprint,
                profile_fingerprint=self.model_profile.fingerprint,
                backend_config_fingerprint=canonical_sha256(
                    self.backend_config.model_dump(mode="json")
                ),
                response_count=expected_response_count,
                artifacts=artifacts,
                model_runtime_verification=model_verification,
                tool_runtime_verification=tool_verification,
            )
            _publish_model(stage / "RUN.json", manifest, owned_root=self._run_root())
            return ToolEffectivenessRunBundle(
                manifest=manifest,
                report=report,
                trial_count=len(ordered),
                recovered_trial_count=recovered,
            )

    def _prepare_project(self):
        try:
            snapshot = self.project_runtime.open(self.project_id)
        except FileNotFoundError:
            snapshot = self.project_runtime.create(
                ProjectManifest(
                    project_id=self.project_id,
                    title="Tool Intelligence grounded-resolution study",
                    research_direction=(
                        "Measure bounded project-evidence acquisition under a frozen "
                        "paired protocol."
                    ),
                    status="active",
                    retrieval_eligible=False,
                    stage_semantics="tool-intelligence-effectiveness-v1",
                )
            )
        expected = {
            item.run_id: ("scripted", "engineering-fixture", item.run_id)
            for item in self.fixture.run_metrics
        }
        expected[self.run_id] = (
            self.fixture.protocol.provider,
            self.fixture.protocol.model,
            ToolEffectivenessCondition.V3_LIVE_PROJECT_LOOP.value,
        )
        known = {item.run_id: item for item in snapshot.manifest.runs}
        for run_id, (provider, model, condition) in expected.items():
            if run_id in known:
                run = known[run_id]
                if (run.provider, run.model, run.condition) != (provider, model, condition):
                    raise ToolEffectivenessRunError("registered study run identity drift")
                continue
            snapshot = self.project_runtime.begin_run(
                self.project_id,
                ProjectRun(
                    run_id=run_id,
                    provider=provider,
                    model=model,
                    condition=condition,
                    seed=0,
                    status="running" if run_id == self.run_id else "reference",
                    evidence_scope="bounded-tool-effectiveness-study-v1",
                ),
                expected_revision=snapshot.revision,
            )
            known = {item.run_id: item for item in snapshot.manifest.runs}
        return snapshot

    def _stage_root(self) -> Path:
        return self._run_root() / EFFECTIVENESS_STAGE_PATH

    def _run_root(self) -> Path:
        return (
            self.project_runtime.outputs_root / "projects" / self.project_id / "runs" / self.run_id
        )

    def _prepare_stage(self) -> Path:
        run_root = self._run_root()
        _require_safe_directory_chain(self.project_runtime.outputs_root, run_root)
        stage = self._stage_root()
        _require_owned_parent(run_root, stage, create=True)
        return stage

    def _controlled_profile(self) -> ControlledToolProfile:
        library_ids = tuple(sorted(self.fixture.knowledge_libraries))
        evidence_ids = tuple(
            sorted(item.evidence.evidence_id for item in self.fixture.evidence_records)
        )
        run_ids = tuple(sorted(item.run_id for item in self.fixture.run_metrics))
        metric_names = tuple(
            sorted({name for item in self.fixture.run_metrics for name in item.metrics})
        )
        return ControlledToolProfile(
            profile_id="tool-effectiveness-readonly",
            profile_version="1.0.0",
            permissions=(
                KnowledgeQueryPermission(
                    allowed_library_ids=library_ids,
                    max_library_ids=1,
                    max_query_chars=500,
                    max_top_k=3,
                ),
                EvidenceInspectPermission(
                    allowed_evidence_ids=evidence_ids,
                    max_evidence_items=1,
                ),
                RegisteredRunComparePermission(
                    allowed_run_ids=run_ids,
                    allowed_metric_names=metric_names,
                    max_runs=2,
                    max_metrics=1,
                ),
            ),
            max_plan_steps=1,
            max_dependency_edges=0,
        )

    def _materialize_and_bind(
        self,
        project_revision: int,
        controlled: ControlledToolProfile,
    ) -> VerifiedProjectToolHandlers:
        run_root = self._stage_root().parent
        libraries: list[KnowledgeLibraryBinding] = []
        for library_id, documents in sorted(self.fixture.knowledge_libraries.items()):
            locator = f"inputs/knowledge/{library_id}.jsonl"
            raw = _jsonl(documents)
            _publish_bytes(run_root / locator, raw, owned_root=run_root)
            libraries.append(
                KnowledgeLibraryBinding(
                    library_id=library_id,
                    source=ContentAddressedRunFile(
                        locator=locator,
                        sha256=hashlib.sha256(raw).hexdigest(),
                    ),
                )
            )
        evidence_raw = _jsonl(self.fixture.evidence_records)
        metrics_raw = _jsonl(self.fixture.run_metrics)
        _publish_bytes(run_root / "inputs/evidence.jsonl", evidence_raw, owned_root=run_root)
        _publish_bytes(run_root / "inputs/run_metrics.jsonl", metrics_raw, owned_root=run_root)
        fixture_raw = _pretty_json(self.fixture)
        profile_raw = _pretty_json(self.model_profile)
        backend_raw = _pretty_json(self.backend_config)
        _publish_bytes(run_root / "inputs/fixture.json", fixture_raw, owned_root=run_root)
        _publish_bytes(run_root / "inputs/model_profile.json", profile_raw, owned_root=run_root)
        _publish_bytes(
            run_root / "inputs/backend_config.redacted.json",
            backend_raw,
            owned_root=run_root,
        )
        binding = ProjectToolBindingSet(
            binding_id="tool-effectiveness-binding-v1",
            project_id=self.project_id,
            run_id=self.run_id,
            project_revision=project_revision,
            knowledge_libraries=tuple(libraries),
            evidence_source=ContentAddressedRunFile(
                locator="inputs/evidence.jsonl",
                sha256=hashlib.sha256(evidence_raw).hexdigest(),
            ),
            run_metrics_source=ContentAddressedRunFile(
                locator="inputs/run_metrics.jsonl",
                sha256=hashlib.sha256(metrics_raw).hexdigest(),
            ),
        )
        _publish_model(run_root / "inputs/tool_binding.json", binding, owned_root=run_root)
        return load_project_tool_handlers(self.project_runtime, binding, controlled)

    def _baseline_trial(
        self,
        task: ToolEffectivenessTask,
        seed: int,
        handlers: VerifiedProjectToolHandlers,
    ) -> tuple[ToolEffectivenessTrial, int]:
        path = self._trial_path(task, seed, ToolEffectivenessCondition.V2_FIXED_ROUTER)
        existing = _load_optional_model(path, ToolEffectivenessTrial, owned_root=self._run_root())
        if existing is not None:
            return existing, 1
        step = deterministic_v2_router(task)
        started = perf_counter()
        observation = execute_read_only_step(step, handlers.handlers)
        latency_ms = (perf_counter() - started) * 1000
        trial = build_tool_effectiveness_trial(
            fixture=self.fixture,
            task=task,
            seed=seed,
            condition=ToolEffectivenessCondition.V2_FIXED_ROUTER,
            model_admitted=False,
            workflow_resolved=True,
            selected_step=step,
            observation_payload=observation,
            model_invocations=0,
            tool_invocations=1,
            tool_latency_ms=latency_ms,
        )
        _publish_model(path, trial, owned_root=self._run_root())
        return trial, 0

    def _treatment_trial(
        self,
        task: ToolEffectivenessTask,
        seed: int,
        *,
        controlled: ControlledToolProfile,
        policy: NodePolicy,
        facade: ModelNodeFacade,
        bridge: ProjectToolIntelligenceBridge,
        backend: StructuredModelBackend,
        project_revision: int,
    ) -> tuple[ToolEffectivenessTrial, int]:
        condition = ToolEffectivenessCondition.V3_LIVE_PROJECT_LOOP
        path = self._trial_path(task, seed, condition)
        existing = _load_optional_model(path, ToolEffectivenessTrial, owned_root=self._run_root())
        if existing is not None:
            return existing, 1
        model_request, workflow_request = self._workflow_request(
            task,
            seed,
            controlled=controlled,
            policy=policy,
            project_revision=project_revision,
        )
        result = bridge.resolve(workflow_request, backend=backend, allow_live=True)
        replayed = facade.execute(
            model_request,
            backend=None,
            resume=True,
            allow_live=True,
        )
        node_result = NodeResult[ToolPlanOutput].model_validate(replayed.result)
        proposal = node_result.proposal or node_result.untrusted_proposal
        selected_step: ToolPlanStep | None = None
        if proposal is not None and result.record.selected_step_id is not None:
            selected_step = next(
                (step for step in proposal.steps if step.step_id == result.record.selected_step_id),
                None,
            )
        response = node_result.response
        trial = build_tool_effectiveness_trial(
            fixture=self.fixture,
            task=task,
            seed=seed,
            condition=condition,
            model_admitted=(
                node_result.status is NodeResultStatus.ACCEPTED
                and result.record.model_outcome is RuntimeOutcome.ACCEPTED
            ),
            workflow_resolved=result.record.decision is ToolHotspotDecision.ACCEPT_AS_ADVICE,
            selected_step=selected_step,
            observation_payload=result.record.advice_payload,
            model_invocations=result.record.model_provider_invocation_count,
            tool_invocations=result.record.tool_handler_invocation_count,
            input_tokens=result.record.model_input_tokens,
            output_tokens=result.record.model_output_tokens,
            known_cost_usd=result.record.model_cost_usd or 0.0,
            unknown_cost_count=int(result.record.model_cost_usd is None),
            model_latency_ms=result.record.model_latency_ms,
            tool_latency_ms=result.record.tool_latency_ms,
            raw_response_sha256=response.raw_response_sha256,
            evidence_locator=result.decision_locator,
            failure_reason_codes=result.record.reasons,
        )
        _publish_model(path, trial, owned_root=self._run_root())
        return trial, 0

    def _workflow_request(
        self,
        task: ToolEffectivenessTask,
        seed: int,
        *,
        controlled: ControlledToolProfile,
        policy: NodePolicy,
        project_revision: int,
    ) -> tuple[ModelNodeFacadeRequest, ToolHotspotWorkflowRequest]:
        invocation_id = f"effectiveness-{task.task_id}-seed-{seed}"
        projection = ImmutableStateProjection(
            project_id=self.project_id,
            state_snapshot_id=task.scope.state_snapshot_id,
            state_revision=1,
            stage="EVIDENCE",
            evidence_ids=task.scope.evidence_ids,
            metadata={"protocol_fingerprint": self.fixture.protocol.fingerprint},
        )
        node_input = ToolPlanInput(
            objective=task.objective,
            scope=task.scope,
            tool_profile=controlled,
        )
        model_request = ModelNodeFacadeRequest(
            project_id=self.project_id,
            run_id=self.run_id,
            invocation_id=invocation_id,
            request_id=invocation_id,
            expected_project_revision=project_revision,
            node_name="tool-plan",
            node_input=node_input.model_dump(mode="json"),
            state_projection=projection,
            trigger=ModelNodeTrigger(
                trigger_id=f"trigger-{task.task_id}-{seed}",
                reason="Preregistered deterministic fast path did not resolve this study task.",
            ),
            profile=self.model_profile,
            policy=policy,
            backend_mode=RuntimeBackendMode.LIVE,
            seed=seed,
        )
        hotspot = SemanticHotspotTrigger(
            trigger_id=f"hotspot-{task.task_id}-{seed}",
            hotspot_kind=SemanticHotspotKind.EVIDENCE_SYNTHESIS,
            semantic_gap=SemanticGapKind.COMPETING_INTERPRETATIONS,
            project_id=self.project_id,
            project_revision=project_revision,
            project_snapshot_sha256=self.project_runtime.open(self.project_id).snapshot_sha256,
            state_snapshot_id=task.scope.state_snapshot_id,
            objective=task.objective,
            controlled_tool_profile_id=controlled.profile_id,
            controlled_tool_profile_fingerprint=controlled.fingerprint,
            candidate_tool_names=task.candidate_tool_names,
            reason_codes=("preregistered-grounded-resolution-task",),
            evidence_ids=task.scope.evidence_ids,
        )
        workflow_request = ToolHotspotWorkflowRequest(
            workflow_id=f"study-{task.task_id}-seed-{seed}",
            project_id=self.project_id,
            run_id=self.run_id,
            attempt_index=0,
            hotspot=hotspot,
            model_request=model_request,
            budget=ToolHotspotWorkflowBudget(
                max_replans=0,
                max_total_tokens=self.model_profile.admission.max_total_tokens,
                max_api_cost_usd=self.model_profile.admission.max_response_cost_usd,
                max_model_latency_ms=self.model_profile.admission.max_latency_ms,
                max_tool_latency_ms=30_000,
                max_end_to_end_latency_ms=self.model_profile.admission.max_latency_ms + 30_000,
            ),
        )
        return model_request, workflow_request

    def _policy(self, controlled: ControlledToolProfile) -> NodePolicy:
        admission = self.model_profile.admission
        return NodePolicy(
            policy_id="tool-effectiveness-live-policy-v1",
            enabled=True,
            allowed_node_names=["tool-plan"],
            expected_backend=self.model_profile.provider,
            expected_model=self.model_profile.model,
            allowed_tool_names=list(controlled.allowed_tool_names),
            max_request_bytes=admission.max_request_bytes,
            max_input_tokens=admission.max_input_tokens,
            max_output_tokens=admission.max_output_tokens,
            max_total_tokens=admission.max_total_tokens,
            max_api_cost_usd=self.model_profile.cumulative_project.max_api_cost_usd,
            max_latency_ms=admission.max_latency_ms,
        )

    def _trial_path(
        self,
        task: ToolEffectivenessTask,
        seed: int,
        condition: ToolEffectivenessCondition,
    ) -> Path:
        return self._stage_root() / "trials" / condition.value / f"{task.task_id}.seed-{seed}.json"

    def _publish_final_artifacts(self, trials, report, packet, blind_key):
        stage = self._stage_root()
        paths = {
            "trials.json": _pretty_json_value([item.model_dump(mode="json") for item in trials]),
            "report.json": _pretty_json(report),
            "blind_review/PACKET.json": _pretty_json(packet),
            "private/BLIND_KEY.json": _pretty_json(blind_key),
        }
        artifacts = []
        for locator, raw in paths.items():
            _publish_bytes(stage / locator, raw, owned_root=self._run_root())
            artifacts.append(
                ToolEffectivenessArtifact(
                    locator=(
                        f"projects/{self.project_id}/runs/{self.run_id}/"
                        f"{EFFECTIVENESS_STAGE_PATH}/{locator}"
                    ),
                    sha256=hashlib.sha256(raw).hexdigest(),
                )
            )
        return tuple(sorted(artifacts, key=lambda item: item.locator))


def _jsonl(values) -> bytes:
    return b"".join(
        json.dumps(
            item.model_dump(mode="json", exclude_computed_fields=True),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
        for item in values
    )


def _pretty_json(model: BaseModel) -> bytes:
    return _pretty_json_value(model.model_dump(mode="json", exclude_computed_fields=True))


def _pretty_json_value(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def _publish_model(path: Path, model: BaseModel, *, owned_root: Path) -> None:
    _publish_bytes(path, _pretty_json(model), owned_root=owned_root)


def _publish_bytes(path: Path, raw: bytes, *, owned_root: Path) -> None:
    _require_owned_parent(owned_root, path.parent, create=True)
    if os.path.lexists(path):
        if _read_regular_bytes(path) != raw:
            raise ToolEffectivenessRunError(f"study artifact identity drift: {path.name}")
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            if _read_regular_bytes(path) != raw:
                raise ToolEffectivenessRunError(
                    f"study artifact publication conflict: {path.name}"
                ) from exc
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _load_optional_model(path: Path, model_type, *, owned_root: Path):
    if not os.path.lexists(path):
        return None
    _require_owned_parent(owned_root, path.parent, create=False)
    try:
        return model_type.model_validate_json(_read_regular_bytes(path), strict=True)
    except ValueError as exc:
        raise ToolEffectivenessRunError("invalid persisted study trial") from exc


def _read_regular_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ToolEffectivenessRunError(
            f"study artifact is not a safe regular file: {path.name}"
        ) from exc
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ToolEffectivenessRunError(
                f"study artifact is not a safe regular file: {path.name}"
            )
        return handle.read()


def _require_safe_directory_chain(root: Path, target: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ToolEffectivenessRunError("outputs root is not a safe directory")
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ToolEffectivenessRunError("study run escapes the outputs root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise ToolEffectivenessRunError("study run contains an unsafe path component")
    if target.resolve(strict=True) != target:
        raise ToolEffectivenessRunError("study run escapes its owned path")


def _require_owned_parent(root: Path, parent: Path, *, create: bool) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ToolEffectivenessRunError("study evidence root is not a safe directory")
    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise ToolEffectivenessRunError("study evidence parent escapes its root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if not os.path.lexists(current) and create:
            try:
                current.mkdir()
            except FileExistsError:
                pass
        if current.is_symlink() or not current.is_dir():
            raise ToolEffectivenessRunError("study evidence parent is unsafe")
    try:
        parent.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ToolEffectivenessRunError("study evidence parent escapes its root") from exc


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class _exclusive_lock:
    def __init__(self, path: Path, *, owned_root: Path) -> None:
        self.path = path
        self.owned_root = owned_root
        self.handle = None

    def __enter__(self):
        import fcntl

        _require_owned_parent(self.owned_root, self.path.parent, create=False)
        if os.path.lexists(self.path) and (self.path.is_symlink() or not self.path.is_file()):
            raise ToolEffectivenessRunError("study lock is not a safe regular file")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise ToolEffectivenessRunError("cannot open the study lock safely") from exc
        self.handle = os.fdopen(descriptor, "a+b")
        if not stat.S_ISREG(os.fstat(self.handle.fileno()).st_mode):
            self.handle.close()
            raise ToolEffectivenessRunError("study lock is not a safe regular file")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.handle.close()
            raise ToolEffectivenessRunError("another process owns the study run") from exc
        return self

    def __exit__(self, *_args):
        import fcntl

        assert self.handle is not None
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--backend-config", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--blinding-salt-env", default="SCITASTE_BLINDING_SALT")
    parser.add_argument("--allow-live", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.allow_live:
        raise ToolEffectivenessRunError("formal study requires explicit --allow-live")
    salt = os.getenv(args.blinding_salt_env)
    if salt is None:
        raise ToolEffectivenessRunError(
            f"missing blinding salt environment variable {args.blinding_salt_env}"
        )
    backend_config = load_structured_openai_compatible_config(args.backend_config)
    if backend_config.live_enabled:
        raise ToolEffectivenessRunError("committed study backend config must remain inert")
    backend_config = backend_config.model_copy(update={"live_enabled": True})
    runner = ProjectToolEffectivenessRunner(
        project_runtime=ProjectRuntime(args.outputs_root),
        fixture=load_tool_effectiveness_fixture(args.fixture),
        model_profile=load_model_node_profile(args.profile),
        backend_config=backend_config,
        run_id=args.run_id,
        source_commit=args.source_commit,
    )
    bundle = runner.run(blinding_salt=salt)
    print(bundle.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the module entry point
    raise SystemExit(main())


__all__ = [
    "EFFECTIVENESS_STAGE_PATH",
    "ProjectToolEffectivenessRunner",
    "ToolEffectivenessRunBundle",
    "ToolEffectivenessRunError",
    "ToolEffectivenessRunManifest",
    "main",
]

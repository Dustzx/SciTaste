"""Project-owned offline composition of the Phase 4--7 workflows."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.data.store import KnowledgeLibrary, build_libraries
from scitaste.discovery.loop import DiscoveryLoop, DiscoveryScenario, load_discovery_scenario
from scitaste.evidence.workflow import (
    EvidenceWorkflow,
    EvidenceWorkflowScenario,
    load_evidence_scenario,
)
from scitaste.executor.base import ResearchExecutor
from scitaste.executor.native import SciTasteNativeExecutor, build_builtin_executor
from scitaste.executor.native_code import (
    NativeCodeInspection,
    inspect_native_code_proposal,
    load_native_code_context_record,
    prepare_native_code_experiment,
)
from scitaste.executor.native_code_generation import (
    GeneratedNativeCodeProposal,
    LoadedNativeCodeGeneration,
    generate_native_code_proposal,
    load_native_code_generation_config,
    load_native_code_generation_record,
)
from scitaste.executor.native_sandbox import (
    NativeExperimentDefinition,
    NativeExperimentRunner,
    load_native_experiment_definition,
)
from scitaste.executor.native_store import NativeExecutionRecord
from scitaste.generative_ui import ProjectSnapshotAdapter
from scitaste.model_nodes.workflow_bridge import (
    FullWorkflowModelAdvisoryRecord,
    LoadedFullWorkflowModelAdvisory,
    execute_full_workflow_model_advisory,
    load_full_workflow_model_advisory,
    publish_full_workflow_model_advisory_input,
    verify_full_workflow_model_advisory,
    verify_full_workflow_model_advisory_input,
)
from scitaste.project import (
    PaperManifest,
    ProjectManifest,
    ProjectRun,
    ProjectRuntime,
    ProjectSnapshot,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.state.research_state import ResearchState
from scitaste.visual.workflow import FigureScenario, FigureWorkflow, load_figure_scenario
from scitaste.writing.evidence_projection import build_writing_evidence_projection
from scitaste.writing.manuscript_quality import (
    ManuscriptAssessment,
    ManuscriptRole,
    assess_manuscript,
    require_requested_manuscript_role,
)
from scitaste.writing.workflow import (
    CommunicationScenario,
    CommunicationWorkflow,
    load_communication_scenario,
)


class FullWorkflowConfig(BaseModel):
    """Paths and publication identity for one deterministic full-workflow case."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    title: str = Field(min_length=1)
    research_direction: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    target_venue: str | None = None
    condition: str = "full_scitaste"
    execution_backend: Literal["scitaste-native", "mock"] = "scitaste-native"
    provider: Literal["mock"] = "mock"
    model: str = "deterministic-controller"
    evidence_scope: str = "offline-integration-only"
    discovery_scenario: Path
    evidence_scenario: Path
    communication_scenario: Path
    figure_scenario: Path
    native_knowledge_config: Path | None = None
    native_experiment_config: Path | None = None
    native_code_proposal_config: Path | None = None
    native_code_generation_config: Path | None = None
    model_node_advisory: Path | None = None
    paper_id: str
    paper_directory: str
    paper_title: str = Field(min_length=1)
    paper_date: date
    paper_role: ManuscriptRole = "integration-fixture"

    @field_validator("project_id")
    @classmethod
    def canonical_project_id(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("paper_id", "paper_directory")
    @classmethod
    def safe_entry_id(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "entry")
        return validate_entry_id(value, field_name=field_name)

    @model_validator(mode="after")
    def native_experiment_source_is_unambiguous(self) -> FullWorkflowConfig:
        configured = tuple(
            item
            for item in (
                self.native_experiment_config,
                self.native_code_proposal_config,
                self.native_code_generation_config,
            )
            if item is not None
        )
        if len(configured) > 1:
            raise ValueError(
                "native experiment, code proposal, and code generation configs are mutually "
                "exclusive"
            )
        if self.native_code_generation_config is not None and (
            self.execution_backend != "scitaste-native"
        ):
            raise ValueError("native code generation requires the scitaste-native executor")
        if self.native_code_generation_config is not None and self.model_node_advisory is not None:
            raise ValueError(
                "native code generation and evidence advisory require a shared extension "
                "registry before they can use one model ledger"
            )
        return self


StageName = Literal["discovery", "evidence", "communication", "figure"]

_STAGE_ORDER: tuple[StageName, ...] = (
    "discovery",
    "evidence",
    "communication",
    "figure",
)
_GENERATION_RECOVERY_CONTRACT = "1.0"
_STAGE_PURPOSES: dict[StageName, str] = {
    "discovery": "Form and probe hypotheses, then select a bounded idea.",
    "evidence": "Test a registered claim and route the interpreted result.",
    "communication": "Draft, review, resolve an obligation, and revise the paper.",
    "figure": "Build, critique, patch, and export an editable claim-linked figure.",
}


class FullStageRecord(BaseModel):
    """Self-hashed completion marker used to validate safe stage reuse."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.1"] = "1.1"
    stage: StageName
    status: Literal["complete"] = "complete"
    purpose: str = Field(min_length=1)
    summary: dict[str, JsonValue]
    input_state_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_state_locator: str = Field(min_length=1)
    output_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_log_locator: str = Field(min_length=1)
    decision_log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: dict[str, str]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("artifact_sha256")
    @classmethod
    def artifact_hashes_are_valid(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("stage record requires at least one artifact hash")
        for locator, digest in value.items():
            if not locator or not _is_sha256(digest):
                raise ValueError("stage artifact locators and hashes must be valid")
        return value

    @model_validator(mode="after")
    def self_hash_matches(self) -> FullStageRecord:
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("stage record hash mismatch")
        return self


class FullWorkflow:
    """Run Discovery through Figure generation inside one managed project run."""

    def __init__(
        self,
        *,
        seed: int = 0,
        executor: ResearchExecutor | None = None,
    ) -> None:
        self.seed = seed
        self.executor = executor

    def run(
        self,
        config: FullWorkflowConfig,
        *,
        outputs_root: str | Path,
        run_id: str,
        resume: bool = False,
        allow_live_model_nodes: bool = False,
    ) -> dict[str, object]:
        validate_entry_id(run_id, field_name="run_id")
        runtime = ProjectRuntime(outputs_root)
        model_advisory = (
            load_full_workflow_model_advisory(config.model_node_advisory)
            if config.model_node_advisory is not None
            else None
        )
        code_generation = (
            load_native_code_generation_config(config.native_code_generation_config)
            if config.native_code_generation_config is not None
            else None
        )
        if (
            model_advisory is not None
            and model_advisory.config.live_enabled
            and not allow_live_model_nodes
        ):
            raise ValueError("live full-workflow model nodes require --allow-live-model-nodes")
        if (
            code_generation is not None
            and code_generation.config.live_enabled
            and not allow_live_model_nodes
        ):
            raise ValueError("live native source generation requires --allow-live-model-nodes")
        code_inspection = (
            inspect_native_code_proposal(config.native_code_proposal_config)
            if config.native_code_proposal_config is not None
            else None
        )
        workflow_config_sha256 = _workflow_config_sha256(
            config,
            model_advisory,
            code_inspection=code_inspection,
            code_generation=code_generation,
        )
        snapshot = self._open_or_create_project(runtime, config, resume=resume)
        if resume:
            snapshot, resume_attempt = self._resume_run(
                runtime,
                snapshot,
                config,
                run_id,
                workflow_config_sha256=workflow_config_sha256,
            )
        else:
            snapshot = runtime.begin_run(
                config.project_id,
                ProjectRun(
                    run_id=run_id,
                    provider=config.provider,
                    model=config.model,
                    condition=config.condition,
                    seed=self.seed,
                    status="running",
                    evidence_scope=config.evidence_scope,
                    stage_path="stages",
                    execution_backend=config.execution_backend,
                    workflow_config_sha256=workflow_config_sha256,
                ),
                expected_revision=snapshot.revision,
            )
            snapshot = runtime.select_run(
                config.project_id,
                run_id,
                expected_revision=snapshot.revision,
            )
            resume_attempt = 0
        run_root = runtime.outputs_root / "projects" / config.project_id / "runs" / run_id

        try:
            generated_code = (
                generate_native_code_proposal(
                    code_generation,
                    project_runtime=runtime,
                    project_id=config.project_id,
                    run_id=run_id,
                    run_root=run_root,
                    expected_project_revision=snapshot.revision,
                    workflow_config_sha256=workflow_config_sha256,
                    seed=self.seed,
                    resume=resume,
                    allow_live=allow_live_model_nodes,
                )
                if code_generation is not None
                else None
            )
            if generated_code is not None:
                code_inspection = generated_code.inspection
            executor = self.executor or _build_full_workflow_executor(
                config,
                run_root=run_root,
                seed=self.seed,
                code_inspection=code_inspection,
                generated_code=generated_code,
            )
            summaries, final_state, reused_stages, archived_attempts = self._run_stages(
                config,
                run_root,
                resume=resume,
                project_runtime=runtime,
                run_id=run_id,
                project_revision=snapshot.revision,
                model_advisory=model_advisory,
                allow_live_model_nodes=allow_live_model_nodes,
                executor=executor,
            )
            reloaded_advisory = (
                load_full_workflow_model_advisory(config.model_node_advisory)
                if config.model_node_advisory is not None
                else None
            )
            reloaded_generation = (
                load_native_code_generation_config(config.native_code_generation_config)
                if config.native_code_generation_config is not None
                else None
            )
            if reloaded_generation is not None:
                generated_code = generate_native_code_proposal(
                    reloaded_generation,
                    project_runtime=runtime,
                    project_id=config.project_id,
                    run_id=run_id,
                    run_root=run_root,
                    expected_project_revision=snapshot.revision,
                    workflow_config_sha256=workflow_config_sha256,
                    seed=self.seed,
                    resume=True,
                    allow_live=allow_live_model_nodes,
                )
            if (
                _workflow_config_sha256(
                    config,
                    reloaded_advisory,
                    code_inspection=(None if generated_code is not None else code_inspection),
                    code_generation=reloaded_generation,
                )
                != workflow_config_sha256
            ):
                raise ValueError("workflow configuration changed during execution")
            if resume and reused_stages == list(_STAGE_ORDER):
                raise ValueError(
                    "all workflow stages are already complete; finalization recovery "
                    "requires manual inspection"
                )
            paper_files, manuscript_assessment = self._materialize_paper(
                config,
                runtime,
                run_root,
            )
            paper = PaperManifest(
                paper_id=config.paper_id,
                project_id=config.project_id,
                title=config.paper_title,
                date=config.paper_date,
                provider=config.provider,
                model=config.model,
                condition=config.condition,
                task="conflict-aware-research-control",
                seed=self.seed,
                stage=18,
                status=manuscript_assessment.paper_status,
                evidence_scope=config.evidence_scope,
                publication_ready=False,
                source_run=run_id,
                files=paper_files,
                stage_semantics=f"{config.execution_backend}-phase-4-to-7-integration",
                manuscript_role=config.paper_role,
                manuscript_assessment="ASSESSMENT.json",
                manuscript_assessment_sha256=manuscript_assessment.record_sha256,
                manuscript_word_count=manuscript_assessment.word_count,
            )
            snapshot = runtime.register_paper(
                config.project_id,
                paper,
                directory_name=config.paper_directory,
                expected_revision=snapshot.revision,
            )
            snapshot = runtime.select_paper(
                config.project_id,
                config.paper_directory,
                expected_revision=snapshot.revision,
            )
            snapshot = runtime.update(
                config.project_id,
                expected_revision=snapshot.revision,
                status=(
                    "research-working-draft"
                    if config.paper_role == "research-working-draft"
                    else "complete"
                ),
            )

            # The summary must exist before the registered run can claim it as its
            # completion artifact. The final metadata update advances one revision.
            summary: dict[str, object] = {
                "schema_version": "1.0",
                "project_id": config.project_id,
                "run_id": run_id,
                "status": "complete",
                "resumed": resume,
                "resume_attempt": resume_attempt,
                "workflow_config_sha256": workflow_config_sha256,
                "reused_stages": reused_stages,
                "archived_attempts": archived_attempts,
                "scope": config.evidence_scope,
                "execution_backend": config.execution_backend,
                "native_execution": _native_execution_summary(executor, run_root=run_root),
                "effectiveness_claim": False,
                "project_revision": snapshot.revision + 1,
                "current_paper": snapshot.current_paper_locator,
                "stages": summaries,
                "final_state": f"runs/{run_id}/{_owned_locator(run_root, final_state)}",
                "paper_files": paper_files,
                "manuscript_assessment": manuscript_assessment.model_dump(mode="json"),
            }
            summary_path = run_root / "full_run_summary.json"
            _write_json(summary_path, summary)
            snapshot = runtime.update_run(
                config.project_id,
                run_id,
                expected_revision=snapshot.revision,
                status="complete",
                artifact=f"runs/{run_id}/full_run_summary.json",
                final_state=f"runs/{run_id}/{_owned_locator(run_root, final_state)}",
                stage_records={
                    name: f"runs/{run_id}/stages/{name}/STAGE.json" for name in summaries
                },
            )
        except BaseException as exc:
            self._mark_failed(runtime, config.project_id, run_id, exc)
            raise
        binding = ProjectSnapshotAdapter(runtime).build_binding(config.project_id)
        binding_path = (
            runtime.outputs_root
            / "projects"
            / config.project_id
            / "surfaces"
            / f"{run_id}-snapshot-binding.json"
        )
        _write_json(binding_path, binding.model_dump(mode="json"))
        return {
            **summary,
            "summary": str(summary_path),
            "snapshot_binding": str(binding_path),
            "snapshot_binding_sha256": binding.snapshot_sha256,
        }

    @staticmethod
    def _open_or_create_project(
        runtime: ProjectRuntime,
        config: FullWorkflowConfig,
        *,
        resume: bool,
    ) -> ProjectSnapshot:
        try:
            snapshot = runtime.open(config.project_id)
        except FileNotFoundError:
            if resume:
                raise ValueError("cannot resume a project that does not exist") from None
            return runtime.create(
                ProjectManifest(
                    project_id=config.project_id,
                    title=config.title,
                    research_direction=config.research_direction,
                    target_domain=config.target_domain,
                    target_venue=config.target_venue,
                    status="active",
                    stage_semantics="scitaste-workflow-phases",
                )
            )
        manifest = snapshot.manifest
        identity = (
            manifest.research_direction,
            manifest.target_domain,
            manifest.target_venue,
        )
        expected = (config.research_direction, config.target_domain, config.target_venue)
        if identity != expected:
            raise ValueError("existing project research identity does not match full config")
        return snapshot

    def _resume_run(
        self,
        runtime: ProjectRuntime,
        snapshot: ProjectSnapshot,
        config: FullWorkflowConfig,
        run_id: str,
        *,
        workflow_config_sha256: str,
    ) -> tuple[ProjectSnapshot, int]:
        matches = [item for item in snapshot.manifest.runs if item.run_id == run_id]
        if not matches:
            raise ValueError(f"cannot resume unknown project run {run_id!r}")
        run = matches[0]
        if run.status == "complete":
            raise ValueError("a completed full-workflow run cannot be resumed")
        if run.status != "failed":
            raise ValueError(f"only a failed full-workflow run can be resumed, got {run.status!r}")
        expected_identity = (
            config.provider,
            config.model,
            config.condition,
            self.seed,
            config.evidence_scope,
            "stages",
        )
        observed_identity = (
            run.provider,
            run.model,
            run.condition,
            run.seed,
            run.evidence_scope,
            run.stage_path,
        )
        if observed_identity != expected_identity:
            raise ValueError("resume configuration does not match the registered run identity")
        extra = run.model_extra or {}
        if extra.get("workflow_config_sha256") != workflow_config_sha256:
            raise ValueError("resume workflow configuration does not match the registered run")
        raw_attempt = extra.get("resume_attempt", 0)
        if not isinstance(raw_attempt, int) or isinstance(raw_attempt, bool) or raw_attempt < 0:
            raise ValueError("registered run has an invalid resume_attempt")
        resume_attempt = raw_attempt + 1
        snapshot = runtime.update_run(
            config.project_id,
            run_id,
            expected_revision=snapshot.revision,
            status="running",
            resume_attempt=resume_attempt,
        )
        if snapshot.manifest.current_run != run_id:
            snapshot = runtime.select_run(
                config.project_id,
                run_id,
                expected_revision=snapshot.revision,
            )
        return snapshot, resume_attempt

    def _run_stages(
        self,
        config: FullWorkflowConfig,
        run_root: Path,
        *,
        resume: bool,
        project_runtime: ProjectRuntime,
        run_id: str,
        project_revision: int,
        model_advisory: LoadedFullWorkflowModelAdvisory | None,
        allow_live_model_nodes: bool,
        executor: ResearchExecutor,
    ) -> tuple[dict[str, object], Path, list[str], list[str]]:
        stages = run_root / "stages"
        summaries: dict[str, object] = {}
        reused_stages: list[str] = []
        archived_attempts: list[str] = []
        reuse_allowed = resume
        previous_state: Path | None = None

        discovery_root = stages / "discovery"
        discovery_record = (
            _load_stage_record(
                discovery_root,
                "discovery",
                run_root=run_root,
                project_id=config.project_id,
                expected_input_sha256=None,
            )
            if reuse_allowed
            else None
        )
        if discovery_record is not None:
            discovery = dict(discovery_record.summary)
            discovery_state = run_root / discovery_record.output_state_locator
            reused_stages.append("discovery")
        else:
            if resume and discovery_root.exists():
                archived_attempts.append(_archive_stage(discovery_root, run_root, "discovery"))
            reuse_allowed = False
            discovery_raw = DiscoveryLoop(seed=self.seed, executor=executor).run(
                _discovery_for_project(config),
                output_dir=discovery_root,
            )
            discovery_state = Path(str(discovery_raw["latest_state"]))
            discovery = _portable_summary_dict(discovery_raw, run_root)
            _stage_record(
                discovery_root,
                "discovery",
                discovery,
                run_root=run_root,
                input_state=None,
            )
        summaries["discovery"] = discovery
        previous_state = discovery_state

        evidence_root = stages / "evidence"
        advisory_artifacts = (
            ("model_advisory_input.json", "model_advisory.json")
            if model_advisory is not None
            else ()
        )
        evidence_record = (
            _load_stage_record(
                evidence_root,
                "evidence",
                run_root=run_root,
                project_id=config.project_id,
                expected_input_sha256=_file_sha256(previous_state),
                extra_artifacts=advisory_artifacts,
            )
            if reuse_allowed
            else None
        )
        if evidence_record is not None:
            evidence = dict(evidence_record.summary)
            evidence_state = run_root / evidence_record.output_state_locator
            if model_advisory is not None:
                verify_full_workflow_model_advisory_input(
                    model_advisory,
                    run_root=run_root,
                    project_id=config.project_id,
                    run_id=run_id,
                    predecessor_state_path=previous_state,
                    record_path=evidence_root / "model_advisory_input.json",
                )
                verify_full_workflow_model_advisory(
                    model_advisory,
                    project_runtime=project_runtime,
                    project_id=config.project_id,
                    run_id=run_id,
                    state_path=evidence_state,
                    record_path=evidence_root / "model_advisory.json",
                )
            reused_stages.append("evidence")
        else:
            input_record_path = evidence_root / "model_advisory_input.json"
            can_recover_advisory = (
                resume
                and reuse_allowed
                and model_advisory is not None
                and evidence_root.exists()
                and input_record_path.exists()
            )
            if can_recover_advisory:
                assert model_advisory is not None
                input_record = verify_full_workflow_model_advisory_input(
                    model_advisory,
                    run_root=run_root,
                    project_id=config.project_id,
                    run_id=run_id,
                    predecessor_state_path=previous_state,
                    record_path=input_record_path,
                )
                evidence_state = run_root / input_record.state_locator
                evidence = _portable_summary_dict(
                    _load_json_mapping(run_root / input_record.evidence_summary_locator),
                    run_root,
                )
                advisory_record_path = evidence_root / "model_advisory.json"
                if advisory_record_path.exists():
                    advisory_record = verify_full_workflow_model_advisory(
                        model_advisory,
                        project_runtime=project_runtime,
                        project_id=config.project_id,
                        run_id=run_id,
                        state_path=evidence_state,
                        record_path=advisory_record_path,
                    )
                else:
                    advisory_record = execute_full_workflow_model_advisory(
                        model_advisory,
                        project_runtime=project_runtime,
                        project_id=config.project_id,
                        run_id=run_id,
                        expected_project_revision=project_revision,
                        evidence_scenario=_evidence_for_project(config),
                        state_path=evidence_state,
                        record_path=advisory_record_path,
                        seed=self.seed,
                        resume=True,
                        allow_live=allow_live_model_nodes,
                        invocation_id=input_record.invocation_id,
                        invocation_project_revision=input_record.project_revision,
                    )
                evidence["model_advisory"] = _model_advisory_summary(
                    advisory_record,
                    run_root=run_root,
                    record_path=advisory_record_path,
                )
                _stage_record(
                    evidence_root,
                    "evidence",
                    evidence,
                    run_root=run_root,
                    input_state=previous_state,
                    extra_artifacts=advisory_artifacts,
                )
                reuse_allowed = False
            else:
                if resume and evidence_root.exists():
                    archived_attempts.append(_archive_stage(evidence_root, run_root, "evidence"))
                reuse_allowed = False
                evidence_raw = EvidenceWorkflow(seed=self.seed, executor=executor).run(
                    _evidence_for_project(config),
                    output_dir=evidence_root,
                    state_path=previous_state,
                )
                evidence_state = Path(str(evidence_raw["latest_state"]))
                evidence = _portable_summary_dict(evidence_raw, run_root)
                if model_advisory is not None:
                    input_record = publish_full_workflow_model_advisory_input(
                        model_advisory,
                        run_root=run_root,
                        project_id=config.project_id,
                        run_id=run_id,
                        project_revision=project_revision,
                        predecessor_state_path=previous_state,
                        state_path=evidence_state,
                        decision_log_path=evidence_root / "decisions.jsonl",
                        evidence_summary_path=evidence_root / "evidence_summary.json",
                        record_path=input_record_path,
                    )
                    advisory_record_path = evidence_root / "model_advisory.json"
                    advisory_record = execute_full_workflow_model_advisory(
                        model_advisory,
                        project_runtime=project_runtime,
                        project_id=config.project_id,
                        run_id=run_id,
                        expected_project_revision=project_revision,
                        evidence_scenario=_evidence_for_project(config),
                        state_path=evidence_state,
                        record_path=advisory_record_path,
                        seed=self.seed,
                        allow_live=allow_live_model_nodes,
                        invocation_id=input_record.invocation_id,
                        invocation_project_revision=input_record.project_revision,
                    )
                    evidence["model_advisory"] = _model_advisory_summary(
                        advisory_record,
                        run_root=run_root,
                        record_path=advisory_record_path,
                    )
                _stage_record(
                    evidence_root,
                    "evidence",
                    evidence,
                    run_root=run_root,
                    input_state=previous_state,
                    extra_artifacts=advisory_artifacts,
                )
        summaries["evidence"] = evidence
        previous_state = evidence_state

        communication_root = stages / "communication"
        communication_artifacts = (
            ("evidence_projection.json",)
            if config.execution_backend == "scitaste-native"
            and _native_experiment_is_configured(config)
            else ()
        )
        communication_record = (
            _load_stage_record(
                communication_root,
                "communication",
                run_root=run_root,
                project_id=config.project_id,
                expected_input_sha256=_file_sha256(previous_state),
                extra_artifacts=communication_artifacts,
            )
            if reuse_allowed
            else None
        )
        if communication_record is not None:
            communication = dict(communication_record.summary)
            communication_state = run_root / communication_record.output_state_locator
            reused_stages.append("communication")
        else:
            if resume and communication_root.exists():
                archived_attempts.append(
                    _archive_stage(communication_root, run_root, "communication")
                )
            reuse_allowed = False
            communication_scenario = _communication_for_project(config)
            evidence_projection = None
            if communication_artifacts:
                evidence_scenario = _evidence_for_project(config)
                evidence_projection = build_writing_evidence_projection(
                    state_path=previous_state,
                    run_root=run_root,
                    expected_claim_id=evidence_scenario.claim.claim_id,
                    expected_experiment_id=evidence_scenario.result.experiment_id,
                )
            communication_raw = CommunicationWorkflow(seed=self.seed, executor=executor).run(
                communication_scenario,
                output_dir=communication_root,
                state_path=previous_state,
                evidence_projection=evidence_projection,
            )
            communication_state = Path(str(communication_raw["latest_state"]))
            communication = _portable_summary_dict(communication_raw, run_root)
            _stage_record(
                communication_root,
                "communication",
                communication,
                run_root=run_root,
                input_state=previous_state,
                extra_artifacts=communication_artifacts,
            )
        summaries["communication"] = communication
        previous_state = communication_state

        figure_root = stages / "figure"
        figure_record = (
            _load_stage_record(
                figure_root,
                "figure",
                run_root=run_root,
                project_id=config.project_id,
                expected_input_sha256=_file_sha256(previous_state),
            )
            if reuse_allowed
            else None
        )
        if figure_record is not None:
            figure = dict(figure_record.summary)
            figure_state = run_root / figure_record.output_state_locator
            reused_stages.append("figure")
        else:
            if resume and figure_root.exists():
                archived_attempts.append(_archive_stage(figure_root, run_root, "figure"))
            figure_raw = FigureWorkflow(seed=self.seed, executor=executor).run(
                _figure_for_project(config),
                output_dir=figure_root,
                state_path=previous_state,
            )
            figure_state = figure_root / "research_state.json"
            figure = _portable_summary_dict(figure_raw, run_root)
            _stage_record(
                figure_root,
                "figure",
                figure,
                run_root=run_root,
                input_state=previous_state,
            )
        summaries["figure"] = figure
        return summaries, figure_state, reused_stages, archived_attempts

    @staticmethod
    def _materialize_paper(
        config: FullWorkflowConfig,
        runtime: ProjectRuntime,
        run_root: Path,
    ) -> tuple[dict[str, str], ManuscriptAssessment]:
        paper_root = (
            runtime.outputs_root
            / "projects"
            / config.project_id
            / "papers"
            / config.paper_directory
        )
        if paper_root.exists():
            raise FileExistsError(f"paper directory already exists: {paper_root}")
        communication_paper = run_root / "stages" / "communication" / "paper.publication.md"
        source = run_root / "stages" / "communication" / "paper_with_title.md"
        source_text = f"## Title\n{config.paper_title}\n\n" + communication_paper.read_text(
            encoding="utf-8"
        )
        assessment = assess_manuscript(source_text, requested_role=config.paper_role)
        require_requested_manuscript_role(assessment)
        source.write_text(source_text, encoding="utf-8")
        paths = materialize_manuscript(markdown_path=source, target_dir=paper_root)
        assessment_path = paper_root / "ASSESSMENT.json"
        _write_json(assessment_path, assessment.model_dump(mode="json"))
        paths.append(assessment_path)
        figures = paper_root / "figures"
        figures.mkdir(parents=True, exist_ok=True)
        for name in ("figure.svg", "figure.drawio"):
            source_figure = run_root / "stages" / "figure" / name
            shutil.copy2(source_figure, figures / name)
            paths.append(figures / name)
        return (
            {
                _paper_file_label(path, paper_root): path.relative_to(paper_root).as_posix()
                for path in sorted(paths)
            },
            assessment,
        )

    @staticmethod
    def _mark_failed(
        runtime: ProjectRuntime,
        project_id: str,
        run_id: str,
        error: BaseException,
    ) -> None:
        try:
            snapshot = runtime.open(project_id)
            runtime.update_run(
                project_id,
                run_id,
                expected_revision=snapshot.revision,
                status="failed",
                failure_type=type(error).__name__,
                failure_message=str(error)[:1000],
            )
        except (FileNotFoundError, ValueError):
            return


def _build_full_workflow_executor(
    config: FullWorkflowConfig,
    *,
    run_root: Path,
    seed: int,
    code_inspection: NativeCodeInspection | None = None,
    generated_code: GeneratedNativeCodeProposal | None = None,
) -> ResearchExecutor:
    if config.execution_backend != SciTasteNativeExecutor.name:
        return build_builtin_executor(config.execution_backend, seed=seed)
    knowledge = _prepare_native_knowledge(config, run_root=run_root)
    experiment = _prepare_native_experiment(
        config,
        run_root=run_root,
        code_inspection=code_inspection,
        generated_code=generated_code,
    )
    if experiment is not None:
        evidence_experiment_id = load_evidence_scenario(
            config.evidence_scenario
        ).result.experiment_id
        if experiment.experiment_id != evidence_experiment_id:
            raise ValueError(
                "native experiment identity does not match the primary evidence scenario"
            )
    return build_builtin_executor(
        config.execution_backend,
        seed=seed,
        workspace=run_root / "native_execution",
        artifact_root=run_root,
        knowledge_library=knowledge,
        experiment_runner=(NativeExperimentRunner(experiment) if experiment is not None else None),
    )


def _prepare_native_knowledge(
    config: FullWorkflowConfig,
    *,
    run_root: Path,
) -> KnowledgeLibrary | None:
    source = config.native_knowledge_config
    if source is None:
        return None
    source_sha256 = _file_sha256(source)
    context_root = run_root / "native_execution" / "context"
    receipt_path = context_root / "CONTEXT.json"
    if receipt_path.exists():
        receipt = _load_json_mapping(
            _owned_regular_file(run_root, _owned_locator(run_root, receipt_path))
        )
        record_sha256 = receipt.pop("record_sha256", None)
        if not isinstance(record_sha256, str) or record_sha256 != content_sha256(receipt):
            raise ValueError("native knowledge context record hash mismatch")
        if receipt.get("source_config_sha256") != source_sha256:
            raise ValueError("native knowledge source changed since the run was created")
        knowledge_locator = receipt.get("knowledge_records_locator")
        knowledge_sha256 = receipt.get("knowledge_records_sha256")
        taste_locator = receipt.get("taste_records_locator")
        taste_sha256 = receipt.get("taste_records_sha256")
        manifest_locator = receipt.get("library_manifest_locator")
        manifest_sha256 = receipt.get("library_manifest_sha256")
        values = (
            knowledge_locator,
            knowledge_sha256,
            taste_locator,
            taste_sha256,
            manifest_locator,
            manifest_sha256,
        )
        if any(not isinstance(item, str) for item in values):
            raise ValueError("native knowledge context record is incomplete")
        knowledge_path = _verified_file(run_root, knowledge_locator, knowledge_sha256)
        _verified_file(run_root, taste_locator, taste_sha256)
        _verified_file(run_root, manifest_locator, manifest_sha256)
        return KnowledgeLibrary(knowledge_path)
    if (context_root / "libraries").exists():
        raise ValueError("incomplete native knowledge context requires manual inspection")
    libraries_root = context_root / "libraries"
    manifest = build_libraries(source, libraries_root)
    knowledge_path = libraries_root / "knowledge" / "records.jsonl"
    taste_path = libraries_root / "taste" / "records.jsonl"
    manifest_path = libraries_root / "library_manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": "1.0",
            "knowledge_count": manifest["knowledge_count"],
            "taste_count": manifest["taste_count"],
            "knowledge_path": "knowledge/records.jsonl",
            "taste_path": "taste/records.jsonl",
        },
    )
    payload = {
        "schema_version": "1.0",
        "source_config_sha256": source_sha256,
        "knowledge_records_locator": _owned_locator(run_root, knowledge_path),
        "knowledge_records_sha256": _file_sha256(knowledge_path),
        "taste_records_locator": _owned_locator(run_root, taste_path),
        "taste_records_sha256": _file_sha256(taste_path),
        "library_manifest_locator": _owned_locator(run_root, manifest_path),
        "library_manifest_sha256": _file_sha256(manifest_path),
    }
    _write_json(receipt_path, {**payload, "record_sha256": content_sha256(payload)})
    return KnowledgeLibrary(knowledge_path)


def _prepare_native_experiment(
    config: FullWorkflowConfig,
    *,
    run_root: Path,
    code_inspection: NativeCodeInspection | None = None,
    generated_code: GeneratedNativeCodeProposal | None = None,
) -> NativeExperimentDefinition | None:
    code_proposal_path = (
        generated_code.proposal_config_path
        if generated_code is not None
        else config.native_code_proposal_config
    )
    if code_proposal_path is not None:
        return prepare_native_code_experiment(
            code_proposal_path,
            run_root=run_root,
            inspection=code_inspection,
        )
    source_config = config.native_experiment_config
    if source_config is None:
        return None
    definition = load_native_experiment_definition(source_config)
    config_sha256 = _file_sha256(source_config)
    source_sha256 = _file_sha256(definition.source_path)
    context_root = run_root / "native_execution" / "context" / "experiment"
    receipt_path = context_root / "EXPERIMENT.json"
    if receipt_path.exists():
        receipt = _load_json_mapping(
            _owned_regular_file(run_root, _owned_locator(run_root, receipt_path))
        )
        record_sha256 = receipt.pop("record_sha256", None)
        if not isinstance(record_sha256, str) or record_sha256 != content_sha256(receipt):
            raise ValueError("native experiment context record hash mismatch")
        if receipt.get("source_config_sha256") != config_sha256:
            raise ValueError("native experiment config changed since the run was created")
        if receipt.get("source_file_sha256") != source_sha256:
            raise ValueError("native experiment source changed since the run was created")
        locator = receipt.get("source_locator")
        registered_definition = receipt.get("definition")
        if not isinstance(locator, str) or not isinstance(registered_definition, dict):
            raise ValueError("native experiment context record is incomplete")
        copied_source = _verified_file(run_root, locator, source_sha256)
        return NativeExperimentDefinition.model_validate(
            {**registered_definition, "source_path": copied_source}
        )
    if context_root.exists():
        raise ValueError("incomplete native experiment context requires manual inspection")
    context_root.mkdir(parents=True)
    copied_source = context_root / "experiment.py"
    with definition.source_path.open("rb") as source, copied_source.open("xb") as target:
        shutil.copyfileobj(source, target)
        target.flush()
        os.fsync(target.fileno())
    if _file_sha256(copied_source) != source_sha256:
        raise ValueError("native experiment source changed while it was materialized")
    registered_definition = definition.model_dump(mode="json", exclude={"source_path"})
    payload = {
        "schema_version": "1.0",
        "source_config_sha256": config_sha256,
        "source_file_sha256": source_sha256,
        "source_locator": _owned_locator(run_root, copied_source),
        "definition": registered_definition,
    }
    _write_json(receipt_path, {**payload, "record_sha256": content_sha256(payload)})
    return definition.model_copy(update={"source_path": copied_source})


def _native_execution_summary(
    executor: ResearchExecutor,
    *,
    run_root: Path,
) -> dict[str, object] | None:
    if not isinstance(executor, SciTasteNativeExecutor) or executor.store is None:
        return None
    verification = executor.store.verify()
    payload = verification.model_dump(mode="json")
    payload["experiment"] = (
        None
        if executor.experiment_runner is None
        else {
            "experiment_id": executor.experiment_runner.definition.experiment_id,
            "availability": executor.experiment_runner.availability().model_dump(mode="json"),
        }
    )
    code_context = load_native_code_context_record(run_root)
    code_generation = load_native_code_generation_record(run_root)
    code_generation_result = code_generation.typed_result if code_generation is not None else None
    payload["code_generation"] = (
        None
        if code_generation is None
        else {
            "generation_id": code_generation.generation_id,
            "proposal_id": code_generation.proposal_id,
            "provider": code_generation_result.response.backend,
            "model": code_generation_result.response.model,
            "outcome": code_generation.receipt.outcome.value,
            "input_tokens": code_generation.receipt.telemetry.input_tokens,
            "output_tokens": code_generation.receipt.telemetry.output_tokens,
            "cost_usd": code_generation.receipt.telemetry.cost_usd,
            "recovered_without_provider": (code_generation.receipt.recovered_without_provider),
            "record_sha256": code_generation.record_sha256,
            "proposal_only": True,
            "deterministic_admission_required": True,
        }
    )
    payload["code_admission"] = (
        None
        if code_context is None
        else {
            "decision": code_context.decision,
            "binding_sha256": code_context.binding_sha256,
            "record_sha256": code_context.record_sha256,
            "proposal": code_context.proposal_locator,
            "admission": code_context.admission_locator,
            "runtime_isolation_required": True,
        }
    )
    return payload


def load_full_workflow_config(path: str | Path) -> FullWorkflowConfig:
    config_path = Path(path).resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for field in (
        "discovery_scenario",
        "evidence_scenario",
        "communication_scenario",
        "figure_scenario",
        "native_knowledge_config",
        "native_experiment_config",
        "native_code_proposal_config",
        "native_code_generation_config",
        "model_node_advisory",
    ):
        if payload.get(field) is None:
            continue
        scenario = Path(payload[field])
        if not scenario.is_absolute():
            payload[field] = (config_path.parent / scenario).resolve()
    return FullWorkflowConfig.model_validate(payload)


def _discovery_for_project(config: FullWorkflowConfig) -> DiscoveryScenario:
    scenario = load_discovery_scenario(config.discovery_scenario)
    return DiscoveryScenario.model_validate(_identity_payload(scenario, config))


def _evidence_for_project(config: FullWorkflowConfig) -> EvidenceWorkflowScenario:
    scenario = load_evidence_scenario(config.evidence_scenario)
    return EvidenceWorkflowScenario.model_validate(_identity_payload(scenario, config))


def _communication_for_project(config: FullWorkflowConfig) -> CommunicationScenario:
    scenario = load_communication_scenario(config.communication_scenario)
    payload = _identity_payload(scenario, config)
    if payload["review_resolution"] is not None:
        payload["review_resolution"].update(
            {
                "project_id": config.project_id,
                "research_direction": config.research_direction,
                "target_domain": config.target_domain,
                "target_venue": config.target_venue,
            }
        )
    return CommunicationScenario.model_validate(payload)


def _figure_for_project(config: FullWorkflowConfig) -> FigureScenario:
    scenario = load_figure_scenario(config.figure_scenario)
    return FigureScenario.model_validate(_identity_payload(scenario, config))


def _identity_payload(scenario: BaseModel, config: FullWorkflowConfig) -> dict[str, object]:
    payload = scenario.model_dump(mode="json")
    payload.update(
        {
            "project_id": config.project_id,
            "research_direction": config.research_direction,
            "target_domain": config.target_domain,
            "target_venue": config.target_venue,
        }
    )
    return payload


def _stage_record(
    root: Path,
    name: StageName,
    summary: dict[str, object],
    *,
    run_root: Path,
    input_state: Path | None,
    extra_artifacts: tuple[str, ...] = (),
) -> FullStageRecord:
    output_state = root / "research_state.json"
    decision_log = root / "decisions.jsonl"
    artifact_paths = _required_stage_artifacts(root, name, extra_artifacts=extra_artifacts)
    payload = {
        "schema_version": "1.1",
        "stage": name,
        "status": "complete",
        "purpose": _STAGE_PURPOSES[name],
        "summary": summary,
        "input_state_sha256": _file_sha256(input_state) if input_state is not None else None,
        "output_state_locator": _owned_locator(run_root, output_state),
        "output_state_sha256": _file_sha256(output_state),
        "decision_log_locator": _owned_locator(run_root, decision_log),
        "decision_log_sha256": _file_sha256(decision_log),
        "artifact_sha256": {
            _owned_locator(run_root, path): _file_sha256(path) for path in artifact_paths
        },
    }
    record = FullStageRecord(
        **payload,
        record_sha256=content_sha256(payload),
    )
    _write_json(root / "STAGE.json", record.model_dump(mode="json"))
    return record


def _load_stage_record(
    root: Path,
    name: StageName,
    *,
    run_root: Path,
    project_id: str,
    expected_input_sha256: str | None,
    extra_artifacts: tuple[str, ...] = (),
) -> FullStageRecord | None:
    record_path = root / "STAGE.json"
    if not root.exists() or not record_path.exists():
        return None
    try:
        record = FullStageRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"invalid completed stage record for {name}: {exc}") from exc
    if record.stage != name:
        raise ValueError(f"stage record identity mismatch for {name}")
    if record.purpose != _STAGE_PURPOSES[name]:
        raise ValueError(f"stage record purpose mismatch for {name}")
    if record.input_state_sha256 != expected_input_sha256:
        raise ValueError(f"stage input state no longer matches its predecessor: {name}")
    expected_state = _owned_locator(run_root, root / "research_state.json")
    expected_log = _owned_locator(run_root, root / "decisions.jsonl")
    if record.output_state_locator != expected_state or record.decision_log_locator != expected_log:
        raise ValueError(f"stage record locators are not canonical: {name}")
    state_path = _verified_file(run_root, record.output_state_locator, record.output_state_sha256)
    decision_log_path = _verified_file(
        run_root, record.decision_log_locator, record.decision_log_sha256
    )
    _verify_native_execution_bindings(decision_log_path, run_root=run_root)
    expected_artifacts = {
        _owned_locator(run_root, path)
        for path in _required_stage_artifacts(root, name, extra_artifacts=extra_artifacts)
    }
    if set(record.artifact_sha256) != expected_artifacts:
        raise ValueError(f"stage artifact manifest is incomplete or unexpected: {name}")
    for locator, digest in record.artifact_sha256.items():
        _verified_file(run_root, locator, digest)
    state = ResearchState.model_validate_json(state_path.read_text(encoding="utf-8"))
    if state.project_id != project_id:
        raise ValueError(f"stage state belongs to another project: {name}")
    expected_stage = "PILOT" if name == "discovery" else "COMMUNICATION"
    if state.current_stage.value != expected_stage:
        raise ValueError(f"stage state has unexpected lifecycle position: {name}")
    if record.summary.get("project_id") != project_id:
        raise ValueError(f"stage summary belongs to another project: {name}")
    return record


def _required_stage_artifacts(
    root: Path,
    name: StageName,
    *,
    extra_artifacts: tuple[str, ...] = (),
) -> list[Path]:
    names: dict[StageName, tuple[str, ...]] = {
        "discovery": ("discovery_summary.json",),
        "evidence": ("evidence_summary.json",),
        "communication": (
            "communication_summary.json",
            "paper.md",
            "paper.publication.md",
        ),
        "figure": (
            "figure_summary.json",
            "figure.initial.svg",
            "figure.initial.drawio",
            "figure.svg",
            "figure.drawio",
        ),
    }
    if len(extra_artifacts) != len(set(extra_artifacts)):
        raise ValueError("stage extra artifact names must be unique")
    if any(Path(item).name != item or item in {"", ".", ".."} for item in extra_artifacts):
        raise ValueError("stage extra artifacts must be simple file names")
    paths = [root / item for item in (*names[name], *extra_artifacts)]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"stage {name} is missing required artifacts: {missing}")
    return paths


def _verified_file(run_root: Path, locator: str, expected_sha256: str) -> Path:
    root = run_root.resolve(strict=True)
    path = run_root / locator
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"stage locator is not a regular file: {locator}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"stage locator escapes its run: {locator}") from exc
    if _file_sha256(resolved) != expected_sha256:
        raise ValueError(f"stage artifact hash mismatch: {locator}")
    return resolved


def _verify_native_execution_bindings(decision_log: Path, *, run_root: Path) -> None:
    seen_records: set[str] = set()
    for line_number, line in enumerate(decision_log.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            decision = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid decision log line {line_number}") from exc
        if not isinstance(decision, dict):
            raise ValueError(f"invalid decision log line {line_number}")
        outcome = decision.get("actual_outcome")
        if not isinstance(outcome, dict) or outcome.get("executor") != SciTasteNativeExecutor.name:
            continue
        data = outcome.get("data")
        if not isinstance(data, dict):
            raise ValueError("native execution outcome is missing its evidence binding")
        locator = data.get("execution_record")
        digest = data.get("execution_record_sha256")
        if not isinstance(locator, str) or not isinstance(digest, str):
            raise ValueError("native execution outcome is missing its evidence binding")
        if locator in seen_records:
            raise ValueError("native execution record is bound by more than one decision")
        record_path = _owned_regular_file(run_root, locator)
        try:
            native_record = NativeExecutionRecord.model_validate_json(
                record_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError("invalid decision-bound native execution record") from exc
        if native_record.record_sha256 != digest:
            raise ValueError("native execution record hash does not match its decision")
        selected_action = decision.get("selected_action")
        if not isinstance(selected_action, dict):
            raise ValueError("native execution decision is missing its selected action")
        if native_record.action.model_dump(mode="json") != selected_action:
            raise ValueError("native execution record action does not match its decision")
        expected_result = native_record.result.model_copy(
            update={
                "data": {
                    **native_record.result.data,
                    "execution_record": locator,
                    "execution_record_sha256": digest,
                    "execution_sequence": native_record.sequence,
                }
            }
        ).model_dump(mode="json")
        if outcome != expected_result:
            raise ValueError("native execution record result does not match its decision")
        seen_records.add(locator)


def _owned_regular_file(run_root: Path, locator: str) -> Path:
    root = run_root.resolve(strict=True)
    path = run_root / locator
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"stage locator is not a regular file: {locator}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"stage locator escapes its run: {locator}") from exc
    return resolved


def _archive_stage(root: Path, run_root: Path, name: StageName) -> str:
    archive_root = run_root / "failed_attempts" / "stages" / name
    archive_root.mkdir(parents=True, exist_ok=True)
    index = 1
    while (archive_root / f"attempt-{index:03d}").exists():
        index += 1
    target = archive_root / f"attempt-{index:03d}"
    os.replace(root, target)
    return _owned_locator(run_root, target)


def _paper_file_label(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return {
        "main.md": "Markdown manuscript",
        "main.tex": "LaTeX manuscript",
        "main.pdf": "PDF manuscript",
        "ASSESSMENT.json": "Manuscript assessment",
        "build.json": "Build record",
        "README.md": "Bundle README",
        "figures/figure.svg": "Editable SVG figure",
        "figures/figure.drawio": "Draw.io figure source",
    }.get(relative, f"Artifact {relative}")


def _owned_locator(run_root: Path, path: Path) -> str:
    return path.relative_to(run_root).as_posix()


def _portable_summary(value: object, run_root: Path) -> object:
    if isinstance(value, dict):
        return {key: _portable_summary(item, run_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_summary(item, run_root) for item in value]
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute():
            try:
                return path.relative_to(run_root).as_posix()
            except ValueError:
                return value
    return value


def _portable_summary_dict(value: object, run_root: Path) -> dict[str, object]:
    portable = _portable_summary(value, run_root)
    if not isinstance(portable, dict):
        raise TypeError("workflow summaries must be mappings")
    return portable


def _load_json_mapping(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid workflow summary: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"workflow summary must be a mapping: {path}")
    return payload


def _model_advisory_summary(
    record: FullWorkflowModelAdvisoryRecord,
    *,
    run_root: Path,
    record_path: Path,
) -> dict[str, object]:
    return {
        "hook_id": record.hook_id,
        "node_name": record.node_name,
        "outcome": record.receipt.outcome.value,
        "proposal_available": record.proposal is not None,
        "recovered_without_provider": record.receipt.recovered_without_provider,
        "advisory_only": True,
        "executable": False,
        "record": _owned_locator(run_root, record_path),
    }


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workflow_config_sha256(
    config: FullWorkflowConfig,
    model_advisory: LoadedFullWorkflowModelAdvisory | None = None,
    *,
    code_inspection: NativeCodeInspection | None = None,
    code_generation: LoadedNativeCodeGeneration | None = None,
) -> str:
    payload = config.model_dump(mode="json")
    for field in (
        "discovery_scenario",
        "evidence_scenario",
        "communication_scenario",
        "figure_scenario",
    ):
        payload[field] = {"content_sha256": _file_sha256(Path(payload[field]))}
    if config.native_knowledge_config is None:
        payload.pop("native_knowledge_config", None)
    else:
        payload["native_knowledge_config"] = {
            "content_sha256": _file_sha256(config.native_knowledge_config)
        }
    if config.native_experiment_config is None:
        payload.pop("native_experiment_config", None)
    else:
        experiment = load_native_experiment_definition(config.native_experiment_config)
        payload["native_experiment_config"] = {
            "content_sha256": _file_sha256(config.native_experiment_config),
            "source_sha256": _file_sha256(experiment.source_path),
        }
    if config.native_code_proposal_config is None:
        payload.pop("native_code_proposal_config", None)
    else:
        inspection = code_inspection or inspect_native_code_proposal(
            config.native_code_proposal_config
        )
        if inspection.config_path != config.native_code_proposal_config.absolute():
            raise ValueError("native code inspection belongs to another full-workflow config")
        payload["native_code_proposal_config"] = {
            "binding_sha256": inspection.binding_sha256,
            "config_sha256": inspection.config_sha256,
            "source_sha256": inspection.proposal.source_sha256,
            "proposal_sha256": inspection.proposal.record_sha256,
            "policy_sha256": inspection.policy.record_sha256,
            "admission_sha256": inspection.admission.record_sha256,
            "decision": inspection.admission.decision,
        }
    if config.native_code_generation_config is None:
        payload.pop("native_code_generation_config", None)
    else:
        binding = code_generation or load_native_code_generation_config(
            config.native_code_generation_config
        )
        payload["native_code_generation_config"] = {
            "binding_sha256": binding.fingerprint,
            "generation_recovery_contract": _GENERATION_RECOVERY_CONTRACT,
        }
    if config.model_node_advisory is None:
        # Preserve hashes registered by pre-advisory v1.0 offline runs.
        payload.pop("model_node_advisory", None)
    else:
        binding = model_advisory or load_full_workflow_model_advisory(config.model_node_advisory)
        payload["model_node_advisory"] = {
            "binding_sha256": binding.fingerprint,
            "stage_recovery_contract": "2.0",
        }
    return content_sha256(payload)


def _native_experiment_is_configured(config: FullWorkflowConfig) -> bool:
    return (
        config.native_experiment_config is not None
        or config.native_code_proposal_config is not None
        or config.native_code_generation_config is not None
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

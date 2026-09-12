"""Project-owned offline composition of the Phase 4--7 workflows."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from scitaste.backends.base import CandidateGenerationBackend, PreferenceBackend
from scitaste.backends.local_transformers import (
    LocalTransformersBackend,
    LocalTransformersConfig,
    load_local_transformers_config,
)
from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.data.store import KnowledgeLibrary, TasteLibrary, build_libraries
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
    LoadedNativeCodeRepair,
    RepairedNativeCodeProposal,
    generate_native_code_proposal,
    load_native_code_generation_config,
    load_native_code_generation_record,
    load_native_code_repair_config,
    load_native_code_repair_record,
    native_code_generation_node_types,
    repair_native_code_proposal,
    validate_native_code_repair_binding,
)
from scitaste.executor.native_profile import (
    NativeExecutionProfileInspection,
    inspect_native_execution_profile,
    prepare_native_execution_profile,
)
from scitaste.executor.native_sandbox import (
    NativeExperimentDefinition,
    NativeExperimentRunner,
    load_native_experiment_definition,
)
from scitaste.executor.native_store import NativeExecutionRecord
from scitaste.generative_ui import ProjectSnapshotAdapter, SnapshotBinding
from scitaste.model_nodes.full_workflow_tool_intelligence import (
    FullWorkflowToolIntelligenceRecord,
    LoadedFullWorkflowToolIntelligence,
    execute_full_workflow_tool_intelligence,
    load_full_workflow_tool_intelligence,
    verify_full_workflow_tool_intelligence,
)
from scitaste.model_nodes.runtime import ModelNodeRegistration
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
from scitaste.taste.conditions import (
    NativeConditionMatrixInspection,
    NativeConditionRuntime,
    NativeTasteRetrievalMode,
    build_native_condition_runtime,
    load_native_condition_matrix,
)
from scitaste.visual.workflow import FigureScenario, FigureWorkflow, load_figure_scenario
from scitaste.workflow_intake import (
    LoadedScenarioBundleCatalog,
    WorkflowIntakeInspection,
    inspect_workflow_intake,
    load_scenario_bundle_catalog,
    materialize_workflow_intake,
    verify_workflow_intake,
)
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
    provider: str = Field(default="mock", min_length=1)
    model: str = "deterministic-controller"
    evidence_scope: str = "offline-integration-only"
    research_brief: Path | None = None
    discovery_scenario: Path | None = None
    evidence_scenario: Path | None = None
    communication_scenario: Path | None = None
    figure_scenario: Path | None = None
    scenario_catalog: Path | None = None
    native_knowledge_config: Path | None = None
    native_condition_config: Path | None = None
    native_preference_backend_config: Path | None = None
    native_candidate_generation_enabled: bool = False
    native_execution_profile: Path | None = None
    native_experiment_config: Path | None = None
    native_code_proposal_config: Path | None = None
    native_code_generation_config: Path | None = None
    native_code_repair_config: Path | None = None
    model_node_advisory: Path | None = None
    tool_intelligence_advisory: Path | None = None
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
        scenarios = (
            self.discovery_scenario,
            self.evidence_scenario,
            self.communication_scenario,
            self.figure_scenario,
        )
        if self.scenario_catalog is None and any(item is None for item in scenarios):
            raise ValueError("full workflow requires all registered stage scenarios")
        if self.scenario_catalog is not None and any(item is not None for item in scenarios):
            raise ValueError("scenario catalog and direct stage scenarios are mutually exclusive")
        if self.scenario_catalog is not None and self.research_brief is None:
            raise ValueError("automatic scenario selection requires a research brief")
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
        if (
            self.native_code_repair_config is not None
            and self.native_code_generation_config is None
        ):
            raise ValueError("native code repair requires native code generation")
        if self.native_execution_profile is not None and (
            self.execution_backend != "scitaste-native" or not configured
        ):
            raise ValueError(
                "a native execution profile requires a configured scitaste-native experiment"
            )
        if self.native_condition_config is not None and self.execution_backend != "scitaste-native":
            raise ValueError("native condition control requires the scitaste-native executor")
        if self.native_preference_backend_config is not None:
            if self.execution_backend != "scitaste-native":
                raise ValueError("native preference control requires the scitaste-native executor")
            if self.native_condition_config is None:
                raise ValueError("native preference control requires a native condition matrix")
        if (
            self.native_candidate_generation_enabled
            and self.native_preference_backend_config is None
        ):
            raise ValueError("native candidate generation requires a native preference backend")
        return self


StageName = Literal["discovery", "evidence", "communication", "figure"]

_STAGE_ORDER: tuple[StageName, ...] = (
    "discovery",
    "evidence",
    "communication",
    "figure",
)
_GENERATION_RECOVERY_CONTRACT = "1.0"
_REPAIR_RECOVERY_CONTRACT = "1.0"
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


class FullFinalizationPlan(BaseModel):
    """Write-once binding for restart-safe paper and summary finalization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    workflow_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    paper_id: str = Field(min_length=1)
    paper_directory: str = Field(min_length=1)
    paper_title: str = Field(min_length=1)
    paper_role: ManuscriptRole
    paper_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_sha256: dict[str, str]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("input_sha256")
    @classmethod
    def input_hashes_are_closed(cls, value: dict[str, str]) -> dict[str, str]:
        invalid = any(not locator or not _is_sha256(digest) for locator, digest in value.items())
        if not value or invalid:
            raise ValueError("finalization inputs require valid locators and SHA-256 values")
        return value

    @model_validator(mode="after")
    def self_hash_matches(self) -> FullFinalizationPlan:
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("finalization plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> FullFinalizationPlan:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


class FullWorkflow:
    """Run Discovery through Figure generation inside one managed project run."""

    def __init__(
        self,
        *,
        seed: int = 0,
        executor: ResearchExecutor | None = None,
        preference_backend: PreferenceBackend | None = None,
    ) -> None:
        self.seed = seed
        self.executor = executor
        self.preference_backend = preference_backend

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
        preference_config = (
            load_local_transformers_config(config.native_preference_backend_config)
            if config.native_preference_backend_config is not None
            else None
        )
        if preference_config is not None:
            validate_native_preference_identity(config, preference_config)
            if not allow_live_model_nodes:
                raise ValueError("model-backed native decisions require --allow-live-model-nodes")
        elif self.preference_backend is not None:
            raise ValueError("an injected preference backend requires a bound backend config")
        preference_backend = self.preference_backend or (
            LocalTransformersBackend(preference_config) if preference_config is not None else None
        )
        candidate_generation_backend: CandidateGenerationBackend | None = None
        if config.native_candidate_generation_enabled:
            if not isinstance(preference_backend, CandidateGenerationBackend):
                raise ValueError("native candidate generation requires a compatible bound backend")
            candidate_generation_backend = preference_backend
        model_advisory = (
            load_full_workflow_model_advisory(config.model_node_advisory)
            if config.model_node_advisory is not None
            else None
        )
        tool_intelligence = (
            load_full_workflow_tool_intelligence(config.tool_intelligence_advisory)
            if config.tool_intelligence_advisory is not None
            else None
        )
        scenario_catalog = (
            load_scenario_bundle_catalog(config.scenario_catalog)
            if config.scenario_catalog is not None
            else None
        )
        code_generation = (
            load_native_code_generation_config(config.native_code_generation_config)
            if config.native_code_generation_config is not None
            else None
        )
        code_repair = (
            load_native_code_repair_config(config.native_code_repair_config)
            if config.native_code_repair_config is not None
            else None
        )
        if code_repair is not None:
            assert code_generation is not None
            validate_native_code_repair_binding(code_repair, code_generation)
        model_node_extensions = (
            native_code_generation_node_types() if code_generation is not None else None
        )
        if (
            model_advisory is not None
            and model_advisory.config.live_enabled
            and not allow_live_model_nodes
        ):
            raise ValueError("live full-workflow model nodes require --allow-live-model-nodes")
        if (
            tool_intelligence is not None
            and tool_intelligence.config.live_enabled
            and not allow_live_model_nodes
        ):
            raise ValueError("live Tool Intelligence requires --allow-live-model-nodes")
        if (
            code_generation is not None
            and code_generation.config.live_enabled
            and not allow_live_model_nodes
        ):
            raise ValueError("live native source generation requires --allow-live-model-nodes")
        if (
            code_repair is not None
            and code_repair.config.live_enabled
            and not allow_live_model_nodes
        ):
            raise ValueError("live native source repair requires --allow-live-model-nodes")
        code_inspection = (
            inspect_native_code_proposal(config.native_code_proposal_config)
            if config.native_code_proposal_config is not None
            else None
        )
        execution_profile = (
            inspect_native_execution_profile(config.native_execution_profile)
            if config.native_execution_profile is not None
            else None
        )
        condition_inspection = (
            load_native_condition_matrix(config.native_condition_config)
            if config.native_condition_config is not None
            else None
        )
        if condition_inspection is not None:
            profile = condition_inspection.matrix.profile(config.condition)
            components = profile.components
            needs_library_source = (
                components.knowledge_retrieval_enabled
                or components.taste_retrieval is not NativeTasteRetrievalMode.DISABLED
            )
            if needs_library_source and config.native_knowledge_config is None:
                raise ValueError(
                    f"native condition {config.condition} requires native_knowledge_config"
                )
        workflow_config_sha256 = _workflow_config_sha256(
            config,
            model_advisory,
            tool_intelligence=tool_intelligence,
            scenario_catalog=scenario_catalog,
            code_inspection=code_inspection,
            code_generation=code_generation,
            code_repair=code_repair,
            execution_profile=execution_profile,
            condition_inspection=condition_inspection,
        )
        intake_inspection = inspect_full_workflow_intake(
            config,
            run_id=run_id,
            workflow_config_sha256=workflow_config_sha256,
        )
        snapshot = self._open_or_create_project(runtime, config, resume=resume)
        if resume:
            completed = next(
                (
                    item
                    for item in snapshot.manifest.runs
                    if item.run_id == run_id and item.status == "complete"
                ),
                None,
            )
            if completed is not None:
                return self._repair_completed_finalization(
                    runtime,
                    snapshot,
                    config,
                    completed,
                    workflow_config_sha256=workflow_config_sha256,
                    intake_inspection=intake_inspection,
                )
            snapshot, resume_attempt = self._resume_run(
                runtime,
                snapshot,
                config,
                run_id,
                workflow_config_sha256=workflow_config_sha256,
                intake_inspection=intake_inspection,
            )
        else:
            intake_metadata = (
                {}
                if intake_inspection is None
                else {
                    "research_brief_id": intake_inspection.brief.brief_id,
                    "research_question": intake_inspection.brief.question,
                    "launch_plan_locator": "intake/PLAN.json",
                    "launch_plan_sha256": intake_inspection.plan.record_sha256,
                }
            )
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
                    **intake_metadata,
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
            prepared_intake = (
                materialize_workflow_intake(intake_inspection, run_root=run_root)
                if intake_inspection is not None
                else None
            )
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
            repaired_code = (
                repair_native_code_proposal(
                    code_repair,
                    generated=generated_code,
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
                if code_repair is not None
                and generated_code is not None
                and generated_code.inspection.admission.decision == "rejected"
                else None
            )
            if repaired_code is not None:
                code_inspection = repaired_code.inspection
            native_libraries = (
                _prepare_native_libraries(config, run_root=run_root)
                if config.execution_backend == SciTasteNativeExecutor.name
                and config.native_knowledge_config is not None
                else None
            )
            condition_runtime = (
                build_native_condition_runtime(
                    condition_inspection.matrix.profile(config.condition),
                    seed=self.seed,
                    taste_library=(native_libraries[1] if native_libraries is not None else None),
                    preference_backend=preference_backend,
                    expected_preference_backend=(
                        preference_config.provider if preference_config is not None else None
                    ),
                    expected_preference_model=(
                        config.model if preference_config is not None else None
                    ),
                    candidate_generation_backend=candidate_generation_backend,
                    expected_candidate_generation_backend=(
                        preference_config.provider if preference_config is not None else None
                    ),
                    expected_candidate_generation_model=(
                        config.model if preference_config is not None else None
                    ),
                )
                if condition_inspection is not None
                else None
            )
            executor = self.executor or _build_full_workflow_executor(
                config,
                run_root=run_root,
                seed=self.seed,
                code_inspection=code_inspection,
                generated_code=generated_code,
                repaired_code=repaired_code,
                execution_profile=execution_profile,
                evidence_scenario_path=(
                    prepared_intake.scenario_paths["evidence"]
                    if prepared_intake is not None
                    else None
                ),
                native_libraries=native_libraries,
                condition_runtime=condition_runtime,
            )
            summaries, final_state, reused_stages, archived_attempts = self._run_stages(
                config,
                run_root,
                resume=resume,
                project_runtime=runtime,
                run_id=run_id,
                project_revision=snapshot.revision,
                model_advisory=model_advisory,
                tool_intelligence=tool_intelligence,
                model_node_extensions=model_node_extensions,
                allow_live_model_nodes=allow_live_model_nodes,
                executor=executor,
                condition_runtime=condition_runtime,
                scenario_paths=(
                    prepared_intake.scenario_paths if prepared_intake is not None else None
                ),
            )
            reloaded_advisory = (
                load_full_workflow_model_advisory(config.model_node_advisory)
                if config.model_node_advisory is not None
                else None
            )
            reloaded_tool_intelligence = (
                load_full_workflow_tool_intelligence(config.tool_intelligence_advisory)
                if config.tool_intelligence_advisory is not None
                else None
            )
            reloaded_scenario_catalog = (
                load_scenario_bundle_catalog(config.scenario_catalog)
                if config.scenario_catalog is not None
                else None
            )
            reloaded_generation = (
                load_native_code_generation_config(config.native_code_generation_config)
                if config.native_code_generation_config is not None
                else None
            )
            reloaded_repair = (
                load_native_code_repair_config(config.native_code_repair_config)
                if config.native_code_repair_config is not None
                else None
            )
            if reloaded_repair is not None:
                assert reloaded_generation is not None
                validate_native_code_repair_binding(reloaded_repair, reloaded_generation)
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
                repaired_code = (
                    repair_native_code_proposal(
                        reloaded_repair,
                        generated=generated_code,
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
                    if reloaded_repair is not None
                    and generated_code.inspection.admission.decision == "rejected"
                    else None
                )
            if (
                _workflow_config_sha256(
                    config,
                    reloaded_advisory,
                    tool_intelligence=reloaded_tool_intelligence,
                    scenario_catalog=reloaded_scenario_catalog,
                    code_inspection=(None if generated_code is not None else code_inspection),
                    code_generation=reloaded_generation,
                    code_repair=reloaded_repair,
                    execution_profile=(
                        inspect_native_execution_profile(config.native_execution_profile)
                        if config.native_execution_profile is not None
                        else None
                    ),
                    condition_inspection=(
                        load_native_condition_matrix(config.native_condition_config)
                        if config.native_condition_config is not None
                        else None
                    ),
                )
                != workflow_config_sha256
            ):
                raise ValueError("workflow configuration changed during execution")
            if intake_inspection is not None:
                prepared_intake = verify_workflow_intake(
                    intake_inspection,
                    run_root=run_root,
                )
            finalization_plan = _publish_or_verify_finalization_plan(
                config,
                run_id=run_id,
                run_root=run_root,
                final_state=final_state,
                workflow_config_sha256=workflow_config_sha256,
            )
            (
                paper_files,
                manuscript_assessment,
                artifact_sha256,
                existing_paper,
                finalization_archives,
            ) = self._materialize_or_reuse_paper(
                config,
                runtime,
                snapshot,
                run_root,
                run_id=run_id,
                resume=resume,
                finalization_plan=finalization_plan,
            )
            archived_attempts.extend(finalization_archives)
            paper = _build_paper_manifest(
                config,
                run_id=run_id,
                seed=self.seed,
                files=paper_files,
                assessment=manuscript_assessment,
                artifact_sha256=artifact_sha256,
                finalization_plan=finalization_plan,
            )
            if existing_paper is not None:
                if existing_paper.model_dump(mode="json") != paper.model_dump(mode="json"):
                    raise ValueError("registered paper does not match the finalization plan")
            else:
                snapshot = runtime.register_paper(
                    config.project_id,
                    paper,
                    directory_name=config.paper_directory,
                    expected_revision=snapshot.revision,
                )
            expected_paper_locator = f"papers/{config.paper_directory}"
            if (
                snapshot.manifest.current_paper != expected_paper_locator
                or snapshot.current_paper_locator is None
            ):
                snapshot = runtime.select_paper(
                    config.project_id,
                    config.paper_directory,
                    expected_revision=snapshot.revision,
                )
            project_status = (
                "research-working-draft"
                if config.paper_role == "research-working-draft"
                else "complete"
            )
            if snapshot.manifest.status != project_status:
                snapshot = runtime.update(
                    config.project_id,
                    expected_revision=snapshot.revision,
                    status=project_status,
                )

            summary_path = run_root / "full_run_summary.json"
            if summary_path.exists():
                if not resume:
                    raise FileExistsError(summary_path)
                archived_attempts.append(
                    _archive_finalization_path(summary_path, run_root, "summary")
                )

            # The summary must exist before the registered run can claim it as its
            # completion artifact. The final metadata update advances one revision.
            summary: dict[str, object] = {
                "schema_version": "1.1",
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
                "native_execution": _native_execution_summary(
                    executor,
                    run_root=run_root,
                    code_repair=code_repair,
                ),
                "native_condition": _native_condition_summary(
                    condition_inspection,
                    condition_runtime,
                ),
                "effectiveness_claim": False,
                "research_intake": (
                    prepared_intake.summary() if prepared_intake is not None else None
                ),
                "project_revision": snapshot.revision + 1,
                "current_paper": snapshot.current_paper_locator,
                "stages": summaries,
                "final_state": f"runs/{run_id}/{_owned_locator(run_root, final_state)}",
                "paper_files": paper_files,
                "manuscript_assessment": manuscript_assessment.model_dump(mode="json"),
                "finalization": {
                    "plan": "finalization/PLAN.json",
                    "plan_sha256": finalization_plan.record_sha256,
                    "recovered_after_all_stages": (resume and reused_stages == list(_STAGE_ORDER)),
                    "reused_registered_paper": existing_paper is not None,
                },
            }
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
                artifact_sha256=_file_sha256(summary_path),
                finalization_plan_locator="finalization/PLAN.json",
                finalization_plan_sha256=finalization_plan.record_sha256,
            )
        except BaseException as exc:
            self._mark_failed(runtime, config.project_id, run_id, exc)
            raise
        binding, binding_path = _publish_snapshot_binding(
            runtime,
            project_id=config.project_id,
            run_id=run_id,
            allow_existing=False,
        )
        return {
            **summary,
            "summary": str(summary_path),
            "snapshot_binding": str(binding_path),
            "snapshot_binding_sha256": binding.snapshot_sha256,
            "completion_repaired": False,
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
        intake_inspection: WorkflowIntakeInspection | None,
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
        if intake_inspection is not None and (
            extra.get("research_brief_id") != intake_inspection.brief.brief_id
            or extra.get("research_question") != intake_inspection.brief.question
            or extra.get("launch_plan_locator") != "intake/PLAN.json"
            or extra.get("launch_plan_sha256") != intake_inspection.plan.record_sha256
        ):
            raise ValueError("resume research intake does not match the registered run")
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
        if snapshot.manifest.status != "active":
            snapshot = runtime.update(
                config.project_id,
                expected_revision=snapshot.revision,
                status="active",
            )
        if snapshot.manifest.current_run != run_id or snapshot.current_stage_locator is None:
            snapshot = runtime.select_run(
                config.project_id,
                run_id,
                expected_revision=snapshot.revision,
            )
        return snapshot, resume_attempt

    def _repair_completed_finalization(
        self,
        runtime: ProjectRuntime,
        snapshot: ProjectSnapshot,
        config: FullWorkflowConfig,
        run: ProjectRun,
        *,
        workflow_config_sha256: str,
        intake_inspection: WorkflowIntakeInspection | None,
    ) -> dict[str, object]:
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
        expected_paper = f"papers/{config.paper_directory}"
        if (
            snapshot.manifest.current_run != run.run_id
            or snapshot.manifest.current_paper != expected_paper
        ):
            raise ValueError("only the current completed run can repair its finalization surface")
        run_root = runtime.outputs_root / "projects" / config.project_id / "runs" / run.run_id
        prepared_intake = (
            verify_workflow_intake(intake_inspection, run_root=run_root)
            if intake_inspection is not None
            else None
        )
        plan_path = run_root / "finalization" / "PLAN.json"
        plan = FullFinalizationPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        if (
            plan.project_id != config.project_id
            or plan.run_id != run.run_id
            or plan.workflow_config_sha256 != workflow_config_sha256
            or plan.paper_id != config.paper_id
            or plan.paper_directory != config.paper_directory
            or plan.paper_title != config.paper_title
            or plan.paper_role != config.paper_role
            or plan.paper_source_sha256
            != hashlib.sha256(_paper_source_text(config, run_root).encode("utf-8")).hexdigest()
        ):
            raise ValueError("completed finalization plan does not match the requested workflow")
        for locator, digest in plan.input_sha256.items():
            _verified_file(run_root, locator, digest)
        paper_entries = [
            item for item in snapshot.papers if item.directory_name == config.paper_directory
        ]
        if len(paper_entries) != 1:
            raise ValueError("completed run has no unique registered paper")
        paper = paper_entries[0].manifest
        paper_root = runtime.outputs_root / "projects" / config.project_id / expected_paper
        files, assessment, hashes = _verify_reusable_paper(
            config,
            run_root=run_root,
            paper_root=paper_root,
            paper=paper,
            finalization_plan=plan,
        )
        expected_manifest = _build_paper_manifest(
            config,
            run_id=run.run_id,
            seed=self.seed,
            files=files,
            assessment=assessment,
            artifact_sha256=hashes,
            finalization_plan=plan,
        )
        if paper.model_dump(mode="json") != expected_manifest.model_dump(mode="json"):
            raise ValueError("completed paper does not match its finalization plan")
        expected_artifact = f"runs/{run.run_id}/full_run_summary.json"
        if run.artifact != expected_artifact:
            raise ValueError("completed run has a noncanonical summary locator")
        summary_path = runtime.outputs_root / "projects" / config.project_id / expected_artifact
        expected_summary_sha256 = extra.get("artifact_sha256")
        if not isinstance(expected_summary_sha256, str) or not _is_sha256(expected_summary_sha256):
            raise ValueError("completed run has no summary content binding")
        if _file_sha256(summary_path) != expected_summary_sha256:
            raise ValueError("completed full-workflow summary hash mismatch")
        summary = _load_json_mapping(summary_path)
        finalization = summary.get("finalization")
        if (
            summary.get("schema_version") != "1.1"
            or summary.get("project_id") != config.project_id
            or summary.get("run_id") != run.run_id
            or summary.get("status") != "complete"
            or summary.get("workflow_config_sha256") != workflow_config_sha256
            or summary.get("research_intake")
            != (prepared_intake.summary() if prepared_intake is not None else None)
            or not isinstance(finalization, dict)
            or finalization.get("plan_sha256") != plan.record_sha256
            or summary.get("paper_files") != files
            or summary.get("manuscript_assessment") != assessment.model_dump(mode="json")
        ):
            raise ValueError("completed full-workflow summary is inconsistent")
        binding, binding_path = _publish_snapshot_binding(
            runtime,
            project_id=config.project_id,
            run_id=run.run_id,
            allow_existing=True,
        )
        return {
            **summary,
            "summary": str(summary_path),
            "snapshot_binding": str(binding_path),
            "snapshot_binding_sha256": binding.snapshot_sha256,
            "completion_repaired": True,
        }

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
        tool_intelligence: LoadedFullWorkflowToolIntelligence | None,
        model_node_extensions: Mapping[str, ModelNodeRegistration] | None,
        allow_live_model_nodes: bool,
        executor: ResearchExecutor,
        condition_runtime: NativeConditionRuntime | None,
        scenario_paths: Mapping[StageName, Path] | None,
    ) -> tuple[dict[str, object], Path, list[str], list[str]]:
        stages = run_root / "stages"
        summaries: dict[str, object] = {}
        reused_stages: list[str] = []
        archived_attempts: list[str] = []
        reuse_allowed = resume
        previous_state: Path | None = None
        owned_scenarios = scenario_paths or {}

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
            discovery_raw = DiscoveryLoop(
                seed=self.seed,
                executor=executor,
                controller=(
                    condition_runtime.controller if condition_runtime is not None else None
                ),
            ).run(
                _discovery_for_project(config, owned_scenarios.get("discovery")),
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
        advisory_artifacts: tuple[str, ...] = (
            ("model_advisory_input.json", "model_advisory.json")
            if model_advisory is not None
            else ()
        )
        if tool_intelligence is not None:
            advisory_artifacts += (
                "tool_intelligence_binding.json",
                "tool_intelligence_input.json",
                "tool_intelligence.json",
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
                    node_types=model_node_extensions,
                )
            if tool_intelligence is not None:
                verify_full_workflow_tool_intelligence(
                    tool_intelligence,
                    project_runtime=project_runtime,
                    project_id=config.project_id,
                    run_id=run_id,
                    run_root=run_root,
                    predecessor_state_path=previous_state,
                    state_path=evidence_state,
                    input_path=evidence_root / "tool_intelligence_input.json",
                    record_path=evidence_root / "tool_intelligence.json",
                    node_types=model_node_extensions,
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
                        node_types=model_node_extensions,
                    )
                else:
                    advisory_record = execute_full_workflow_model_advisory(
                        model_advisory,
                        project_runtime=project_runtime,
                        project_id=config.project_id,
                        run_id=run_id,
                        expected_project_revision=project_revision,
                        evidence_scenario=_evidence_for_project(
                            config, owned_scenarios.get("evidence")
                        ),
                        state_path=evidence_state,
                        record_path=advisory_record_path,
                        seed=self.seed,
                        resume=True,
                        allow_live=allow_live_model_nodes,
                        invocation_id=input_record.invocation_id,
                        invocation_project_revision=input_record.project_revision,
                        node_types=model_node_extensions,
                    )
                evidence["model_advisory"] = _model_advisory_summary(
                    advisory_record,
                    run_root=run_root,
                    record_path=advisory_record_path,
                )
                if tool_intelligence is not None:
                    tool_record_path = evidence_root / "tool_intelligence.json"
                    tool_record = execute_full_workflow_tool_intelligence(
                        tool_intelligence,
                        project_runtime=project_runtime,
                        project_id=config.project_id,
                        run_id=run_id,
                        expected_project_revision=project_revision,
                        run_root=run_root,
                        predecessor_state_path=previous_state,
                        state_path=evidence_state,
                        evidence_summary_path=evidence_root / "evidence_summary.json",
                        record_path=tool_record_path,
                        seed=self.seed,
                        resume=True,
                        allow_live=allow_live_model_nodes,
                        node_types=model_node_extensions,
                    )
                    evidence["tool_intelligence"] = _tool_intelligence_summary(
                        tool_record,
                        run_root=run_root,
                        record_path=tool_record_path,
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
                evidence_raw = EvidenceWorkflow(
                    seed=self.seed,
                    executor=executor,
                    controller=(
                        condition_runtime.controller if condition_runtime is not None else None
                    ),
                ).run(
                    _evidence_for_project(config, owned_scenarios.get("evidence")),
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
                        evidence_scenario=_evidence_for_project(
                            config, owned_scenarios.get("evidence")
                        ),
                        state_path=evidence_state,
                        record_path=advisory_record_path,
                        seed=self.seed,
                        allow_live=allow_live_model_nodes,
                        invocation_id=input_record.invocation_id,
                        invocation_project_revision=input_record.project_revision,
                        node_types=model_node_extensions,
                    )
                    evidence["model_advisory"] = _model_advisory_summary(
                        advisory_record,
                        run_root=run_root,
                        record_path=advisory_record_path,
                    )
                if tool_intelligence is not None:
                    tool_record_path = evidence_root / "tool_intelligence.json"
                    tool_record = execute_full_workflow_tool_intelligence(
                        tool_intelligence,
                        project_runtime=project_runtime,
                        project_id=config.project_id,
                        run_id=run_id,
                        expected_project_revision=project_revision,
                        run_root=run_root,
                        predecessor_state_path=previous_state,
                        state_path=evidence_state,
                        evidence_summary_path=evidence_root / "evidence_summary.json",
                        record_path=tool_record_path,
                        seed=self.seed,
                        allow_live=allow_live_model_nodes,
                        node_types=model_node_extensions,
                    )
                    evidence["tool_intelligence"] = _tool_intelligence_summary(
                        tool_record,
                        run_root=run_root,
                        record_path=tool_record_path,
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
            communication_scenario = _communication_for_project(
                config, owned_scenarios.get("communication")
            )
            evidence_projection = None
            if communication_artifacts:
                evidence_scenario = _evidence_for_project(config, owned_scenarios.get("evidence"))
                evidence_projection = build_writing_evidence_projection(
                    state_path=previous_state,
                    run_root=run_root,
                    expected_claim_id=evidence_scenario.claim.claim_id,
                    expected_experiment_id=evidence_scenario.result.experiment_id,
                )
            communication_raw = CommunicationWorkflow(
                seed=self.seed,
                executor=executor,
                controller=(
                    condition_runtime.controller if condition_runtime is not None else None
                ),
                taste_retriever=(
                    condition_runtime.taste_retriever if condition_runtime is not None else None
                ),
                retrieve_taste_context=(
                    condition_runtime.taste_context_enabled
                    if condition_runtime is not None
                    else True
                ),
            ).run(
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
            figure_raw = FigureWorkflow(
                seed=self.seed,
                executor=executor,
                controller=(
                    condition_runtime.controller if condition_runtime is not None else None
                ),
                taste_retriever=(
                    condition_runtime.taste_retriever if condition_runtime is not None else None
                ),
                retrieve_taste_context=(
                    condition_runtime.taste_context_enabled
                    if condition_runtime is not None
                    else True
                ),
            ).run(
                _figure_for_project(config, owned_scenarios.get("figure")),
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
    def _materialize_or_reuse_paper(
        config: FullWorkflowConfig,
        runtime: ProjectRuntime,
        snapshot: ProjectSnapshot,
        run_root: Path,
        *,
        run_id: str,
        resume: bool,
        finalization_plan: FullFinalizationPlan,
    ) -> tuple[
        dict[str, str],
        ManuscriptAssessment,
        dict[str, str],
        PaperManifest | None,
        list[str],
    ]:
        paper_root = (
            runtime.outputs_root
            / "projects"
            / config.project_id
            / "papers"
            / config.paper_directory
        )
        archives: list[str] = []
        manifest_path = paper_root / "MANIFEST.json"
        if os.path.lexists(paper_root):
            if paper_root.is_symlink() or not paper_root.is_dir():
                raise ValueError("paper finalization target must be a physical directory")
            if not resume:
                raise FileExistsError(f"paper directory already exists: {paper_root}")
            if manifest_path.is_file() and not manifest_path.is_symlink():
                matches = [
                    entry
                    for entry in snapshot.papers
                    if entry.directory_name == config.paper_directory
                ]
                if len(matches) != 1:
                    raise ValueError("registered paper cannot be loaded for finalization recovery")
                existing = matches[0].manifest
                files, assessment, hashes = _verify_reusable_paper(
                    config,
                    run_root=run_root,
                    paper_root=paper_root,
                    paper=existing,
                    finalization_plan=finalization_plan,
                )
                return files, assessment, hashes, existing, archives
            archives.append(_archive_finalization_path(paper_root, run_root, "paper"))
        files, assessment = FullWorkflow._materialize_paper(config, runtime, run_root)
        hashes = _paper_artifact_hashes(paper_root, files)
        return files, assessment, hashes, None, archives

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
        if os.path.lexists(paper_root):
            raise FileExistsError(f"paper directory already exists: {paper_root}")
        source = run_root / "stages" / "communication" / "paper_with_title.md"
        source_text = _paper_source_text(config, run_root)
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
    repaired_code: RepairedNativeCodeProposal | None = None,
    execution_profile: NativeExecutionProfileInspection | None = None,
    evidence_scenario_path: Path | None = None,
    native_libraries: tuple[KnowledgeLibrary, TasteLibrary] | None = None,
    condition_runtime: NativeConditionRuntime | None = None,
) -> ResearchExecutor:
    if config.execution_backend != SciTasteNativeExecutor.name:
        return build_builtin_executor(config.execution_backend, seed=seed)
    libraries = native_libraries or (
        _prepare_native_libraries(config, run_root=run_root)
        if config.native_knowledge_config is not None
        else None
    )
    knowledge = libraries[0] if libraries is not None else None
    if condition_runtime is not None and not condition_runtime.knowledge_retrieval_enabled:
        knowledge = None
    experiment = _prepare_native_experiment(
        config,
        run_root=run_root,
        code_inspection=code_inspection,
        generated_code=generated_code,
        repaired_code=repaired_code,
    )
    if experiment is not None:
        evidence_experiment_id = load_evidence_scenario(
            evidence_scenario_path or _required_scenario_path(config.evidence_scenario)
        ).result.experiment_id
        if experiment.experiment_id != evidence_experiment_id:
            raise ValueError(
                "native experiment identity does not match the primary evidence scenario"
            )
    profile_inspection = execution_profile or (
        inspect_native_execution_profile(config.native_execution_profile)
        if config.native_execution_profile is not None
        else None
    )
    prepared_profile = (
        prepare_native_execution_profile(profile_inspection, run_root=run_root)
        if profile_inspection is not None
        else None
    )
    return build_builtin_executor(
        config.execution_backend,
        seed=seed,
        workspace=run_root / "native_execution",
        artifact_root=run_root,
        knowledge_library=knowledge,
        experiment_runner=(
            NativeExperimentRunner(experiment, execution_profile=prepared_profile)
            if experiment is not None
            else None
        ),
    )


def _prepare_native_libraries(
    config: FullWorkflowConfig,
    *,
    run_root: Path,
) -> tuple[KnowledgeLibrary, TasteLibrary]:
    source = config.native_knowledge_config
    if source is None:
        raise ValueError("native library preparation requires native_knowledge_config")
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
        taste_path = _verified_file(run_root, taste_locator, taste_sha256)
        _verified_file(run_root, manifest_locator, manifest_sha256)
        return KnowledgeLibrary(knowledge_path), TasteLibrary(taste_path)
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
    return KnowledgeLibrary(knowledge_path), TasteLibrary(taste_path)


def _prepare_native_experiment(
    config: FullWorkflowConfig,
    *,
    run_root: Path,
    code_inspection: NativeCodeInspection | None = None,
    generated_code: GeneratedNativeCodeProposal | None = None,
    repaired_code: RepairedNativeCodeProposal | None = None,
) -> NativeExperimentDefinition | None:
    code_proposal_path = (
        repaired_code.proposal_config_path
        if repaired_code is not None
        else (
            generated_code.proposal_config_path
            if generated_code is not None
            else config.native_code_proposal_config
        )
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


def _native_condition_summary(
    inspection: NativeConditionMatrixInspection | None,
    runtime: NativeConditionRuntime | None,
) -> dict[str, object] | None:
    if inspection is None or runtime is None:
        return None
    return {
        "matrix_id": inspection.matrix.matrix_id,
        "matrix_file_sha256": inspection.file_sha256,
        "matrix_fingerprint": inspection.matrix.fingerprint,
        "condition_id": runtime.profile.condition_id.value,
        "role": runtime.profile.role.value,
        "components": runtime.profile.components.model_dump(mode="json"),
        "knowledge_retrieval_enabled": runtime.knowledge_retrieval_enabled,
        "taste_context_enabled": runtime.taste_context_enabled,
        "model_backed_action_selection": runtime.model_backed,
        "model_backed_candidate_generation": runtime.model_backed_candidate_generation,
        "integrity_gates_invariant": True,
    }


def _native_execution_summary(
    executor: ResearchExecutor,
    *,
    run_root: Path,
    code_repair: LoadedNativeCodeRepair | None = None,
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
            "execution_profile_id": executor.experiment_runner.profile.profile_id,
            "execution_profile_fingerprint": (
                executor.experiment_runner.execution_profile.fingerprint
                if executor.experiment_runner.execution_profile is not None
                else None
            ),
            "dataset_mounts": [
                item.mount_path for item in executor.experiment_runner.profile.datasets
            ],
            "gpu_authorized": executor.experiment_runner.profile.gpu.enabled,
            "availability": executor.experiment_runner.availability().model_dump(mode="json"),
        }
    )
    code_context = load_native_code_context_record(run_root)
    code_generation = load_native_code_generation_record(run_root)
    code_generation_result = code_generation.typed_result if code_generation is not None else None
    code_repair_record = load_native_code_repair_record(run_root)
    code_repair_result = code_repair_record.typed_result if code_repair_record is not None else None
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
    payload["code_repair"] = (
        None
        if code_repair is None
        else {
            "repair_id": code_repair.config.repair_id,
            "configured": True,
            "triggered": code_repair_record is not None,
            "status": (
                "not-triggered"
                if code_repair_record is None
                else (
                    "accepted-by-readmission"
                    if code_repair_record.admission_decision == "accepted"
                    else "rejected-by-readmission"
                )
            ),
            "initial_admission_decision": (
                code_generation.admission_decision if code_generation is not None else None
            ),
            "readmission_decision": (
                code_repair_record.admission_decision if code_repair_record is not None else None
            ),
            "provider": (
                code_repair_result.response.backend if code_repair_result is not None else None
            ),
            "model": (
                code_repair_result.response.model if code_repair_result is not None else None
            ),
            "input_tokens": (
                code_repair_record.receipt.telemetry.input_tokens
                if code_repair_record is not None
                else 0
            ),
            "output_tokens": (
                code_repair_record.receipt.telemetry.output_tokens
                if code_repair_record is not None
                else 0
            ),
            "cost_usd": (
                code_repair_record.receipt.telemetry.cost_usd
                if code_repair_record is not None
                else 0.0
            ),
            "recovered_without_provider": (
                code_repair_record.receipt.recovered_without_provider
                if code_repair_record is not None
                else False
            ),
            "record_sha256": (
                code_repair_record.record_sha256 if code_repair_record is not None else None
            ),
            "attempt_number": (
                code_repair_record.attempt_number if code_repair_record is not None else 0
            ),
            "max_attempts": code_repair.config.max_attempts,
            "repair_proposal_only": True,
            "deterministic_readmission_required": True,
            "runtime_isolation_required": True,
        }
    )
    return payload


def validate_native_preference_identity(
    workflow: FullWorkflowConfig,
    backend: LocalTransformersConfig,
) -> None:
    expected_model = f"{backend.model_id}@{backend.model_revision}"
    if workflow.provider != backend.provider:
        raise ValueError("workflow provider differs from native preference backend")
    if workflow.model != expected_model:
        raise ValueError("workflow model differs from native preference backend")
    if backend.checkpoint_sha256 is None:
        raise ValueError("native preference backend requires a checkpoint SHA-256")


def load_full_workflow_config(path: str | Path) -> FullWorkflowConfig:
    config_path = Path(path).resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for field in (
        "research_brief",
        "discovery_scenario",
        "evidence_scenario",
        "communication_scenario",
        "figure_scenario",
        "scenario_catalog",
        "native_knowledge_config",
        "native_condition_config",
        "native_preference_backend_config",
        "native_execution_profile",
        "native_experiment_config",
        "native_code_proposal_config",
        "native_code_generation_config",
        "native_code_repair_config",
        "model_node_advisory",
        "tool_intelligence_advisory",
    ):
        if payload.get(field) is None:
            continue
        scenario = Path(payload[field])
        if not scenario.is_absolute():
            payload[field] = (config_path.parent / scenario).resolve()
    return FullWorkflowConfig.model_validate(payload)


def inspect_full_workflow_intake(
    config: FullWorkflowConfig,
    *,
    run_id: str,
    workflow_config_sha256: str | None = None,
) -> WorkflowIntakeInspection | None:
    """Inspect an optional open-question intake without writing project state."""

    if config.research_brief is None:
        return None
    config_sha256 = workflow_config_sha256 or _workflow_config_sha256(config)
    return inspect_workflow_intake(
        config.research_brief,
        project_id=config.project_id,
        run_id=run_id,
        research_direction=config.research_direction,
        target_domain=config.target_domain,
        target_venue=config.target_venue,
        workflow_config_sha256=config_sha256,
        scenario_paths=(
            None
            if config.scenario_catalog is not None
            else {
                "discovery": _required_scenario_path(config.discovery_scenario),
                "evidence": _required_scenario_path(config.evidence_scenario),
                "communication": _required_scenario_path(config.communication_scenario),
                "figure": _required_scenario_path(config.figure_scenario),
            }
        ),
        scenario_catalog=config.scenario_catalog,
    )


def _discovery_for_project(
    config: FullWorkflowConfig, scenario_path: Path | None = None
) -> DiscoveryScenario:
    scenario = load_discovery_scenario(
        scenario_path or _required_scenario_path(config.discovery_scenario)
    )
    return DiscoveryScenario.model_validate(_identity_payload(scenario, config))


def _evidence_for_project(
    config: FullWorkflowConfig, scenario_path: Path | None = None
) -> EvidenceWorkflowScenario:
    scenario = load_evidence_scenario(
        scenario_path or _required_scenario_path(config.evidence_scenario)
    )
    return EvidenceWorkflowScenario.model_validate(_identity_payload(scenario, config))


def _communication_for_project(
    config: FullWorkflowConfig, scenario_path: Path | None = None
) -> CommunicationScenario:
    scenario = load_communication_scenario(
        scenario_path or _required_scenario_path(config.communication_scenario)
    )
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


def _figure_for_project(
    config: FullWorkflowConfig, scenario_path: Path | None = None
) -> FigureScenario:
    scenario = load_figure_scenario(
        scenario_path or _required_scenario_path(config.figure_scenario)
    )
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


def _required_scenario_path(path: Path | None) -> Path:
    if path is None:
        raise ValueError("full workflow has no admitted scenario path")
    return path


def _publish_or_verify_finalization_plan(
    config: FullWorkflowConfig,
    *,
    run_id: str,
    run_root: Path,
    final_state: Path,
    workflow_config_sha256: str,
) -> FullFinalizationPlan:
    input_paths = [
        *(run_root / "stages" / stage / "STAGE.json" for stage in _STAGE_ORDER),
        final_state,
        run_root / "stages" / "communication" / "paper.publication.md",
        run_root / "stages" / "figure" / "figure.svg",
        run_root / "stages" / "figure" / "figure.drawio",
    ]
    if config.research_brief is not None:
        input_paths.extend(
            [
                run_root / "intake" / "PLAN.json",
                run_root / "intake" / "BRIEF.yaml",
                *(run_root / "intake" / "scenarios" / f"{stage}.yaml" for stage in _STAGE_ORDER),
            ]
        )
        if config.scenario_catalog is not None:
            input_paths.append(run_root / "intake" / "SCENARIO_CATALOG.yaml")
    input_sha256 = {_owned_locator(run_root, path): _file_sha256(path) for path in input_paths}
    expected = FullFinalizationPlan.create(
        project_id=config.project_id,
        run_id=run_id,
        workflow_config_sha256=workflow_config_sha256,
        paper_id=config.paper_id,
        paper_directory=config.paper_directory,
        paper_title=config.paper_title,
        paper_role=config.paper_role,
        paper_source_sha256=hashlib.sha256(
            _paper_source_text(config, run_root).encode("utf-8")
        ).hexdigest(),
        input_sha256=input_sha256,
    )
    path = run_root / "finalization" / "PLAN.json"
    if path.is_symlink():
        raise ValueError("finalization plan must be a physical file")
    if path.exists():
        observed = FullFinalizationPlan.model_validate_json(path.read_text(encoding="utf-8"))
        if observed != expected:
            raise ValueError("finalization plan no longer matches its stage inputs")
        return observed
    if path.parent.exists() and any(path.parent.iterdir()):
        raise ValueError("incomplete finalization checkpoint requires manual inspection")
    _write_json(path, expected.model_dump(mode="json"))
    return expected


def _paper_source_text(config: FullWorkflowConfig, run_root: Path) -> str:
    communication_paper = run_root / "stages" / "communication" / "paper.publication.md"
    return f"## Title\n{config.paper_title}\n\n" + communication_paper.read_text(encoding="utf-8")


def _paper_artifact_hashes(paper_root: Path, files: dict[str, str]) -> dict[str, str]:
    if paper_root.is_symlink() or not paper_root.is_dir():
        raise ValueError("paper bundle must be a physical directory")
    hashes: dict[str, str] = {}
    for locator in files.values():
        path = paper_root / locator
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"paper artifact is not a regular file: {locator}")
        try:
            path.resolve(strict=True).relative_to(paper_root.resolve(strict=True))
        except ValueError as exc:
            raise ValueError(f"paper artifact escapes its bundle: {locator}") from exc
        hashes[locator] = _file_sha256(path)
    return hashes


def _build_paper_manifest(
    config: FullWorkflowConfig,
    *,
    run_id: str,
    seed: int,
    files: dict[str, str],
    assessment: ManuscriptAssessment,
    artifact_sha256: dict[str, str],
    finalization_plan: FullFinalizationPlan,
) -> PaperManifest:
    return PaperManifest(
        paper_id=config.paper_id,
        project_id=config.project_id,
        title=config.paper_title,
        date=config.paper_date,
        provider=config.provider,
        model=config.model,
        condition=config.condition,
        task="conflict-aware-research-control",
        seed=seed,
        stage=18,
        status=assessment.paper_status,
        evidence_scope=config.evidence_scope,
        publication_ready=False,
        source_run=run_id,
        files=files,
        stage_semantics=f"{config.execution_backend}-phase-4-to-7-integration",
        manuscript_role=config.paper_role,
        manuscript_assessment="ASSESSMENT.json",
        manuscript_assessment_sha256=assessment.record_sha256,
        manuscript_word_count=assessment.word_count,
        artifact_sha256=artifact_sha256,
        finalization_plan_locator=f"runs/{run_id}/finalization/PLAN.json",
        finalization_plan_sha256=finalization_plan.record_sha256,
        publication_source_sha256=finalization_plan.paper_source_sha256,
    )


def _verify_reusable_paper(
    config: FullWorkflowConfig,
    *,
    run_root: Path,
    paper_root: Path,
    paper: PaperManifest,
    finalization_plan: FullFinalizationPlan,
) -> tuple[dict[str, str], ManuscriptAssessment, dict[str, str]]:
    if paper.source_run != finalization_plan.run_id:
        raise ValueError("registered paper belongs to another workflow run")
    extra = paper.model_extra or {}
    raw_hashes = extra.get("artifact_sha256")
    if not isinstance(raw_hashes, dict) or set(raw_hashes) != set(paper.files.values()):
        raise ValueError("registered paper has no closed artifact hash manifest")
    hashes = {str(locator): str(digest) for locator, digest in raw_hashes.items()}
    if any(not _is_sha256(digest) for digest in hashes.values()):
        raise ValueError("registered paper artifact hash is invalid")
    observed_hashes = _paper_artifact_hashes(paper_root, paper.files)
    if hashes != observed_hashes:
        raise ValueError("registered paper artifact hash mismatch")
    if "main.md" not in paper.files.values():
        raise ValueError("registered paper has no canonical Markdown manuscript")
    main_path = paper_root / "main.md"
    if not main_path.is_file() or _file_sha256(main_path) != finalization_plan.paper_source_sha256:
        raise ValueError("registered paper source differs from the finalization plan")
    assessment_locator = extra.get("manuscript_assessment")
    if not isinstance(assessment_locator, str) or assessment_locator not in paper.files.values():
        raise ValueError("registered paper has no manuscript assessment locator")
    assessment = ManuscriptAssessment.model_validate_json(
        (paper_root / assessment_locator).read_text(encoding="utf-8")
    )
    if assessment.requested_role != config.paper_role:
        raise ValueError("registered paper role differs from the finalization plan")
    for name in ("figure.svg", "figure.drawio"):
        source = run_root / "stages" / "figure" / name
        copied = paper_root / "figures" / name
        if f"figures/{name}" not in paper.files.values():
            raise ValueError(f"registered paper has no declared figure artifact: {name}")
        if _file_sha256(source) != _file_sha256(copied):
            raise ValueError(f"registered paper figure differs from stage evidence: {name}")
    return dict(paper.files), assessment, hashes


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


def _archive_finalization_path(path: Path, run_root: Path, category: str) -> str:
    validate_entry_id(category, field_name="finalization archive category")
    archive_root = run_root / "failed_attempts" / "finalization" / category
    archive_root.mkdir(parents=True, exist_ok=True)
    index = 1
    while (archive_root / f"attempt-{index:03d}").exists():
        index += 1
    attempt = archive_root / f"attempt-{index:03d}"
    attempt.mkdir()
    target = attempt / path.name
    os.replace(path, target)
    return _owned_locator(run_root, target)


def _publish_snapshot_binding(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    run_id: str,
    allow_existing: bool,
) -> tuple[SnapshotBinding, Path]:
    binding = ProjectSnapshotAdapter(runtime).build_binding(project_id)
    binding_path = (
        runtime.outputs_root
        / "projects"
        / project_id
        / "surfaces"
        / f"{run_id}-snapshot-binding.json"
    )
    expected = binding.model_dump(mode="json")
    if binding_path.is_symlink():
        raise ValueError("snapshot binding must be a physical file")
    if binding_path.exists():
        if not allow_existing:
            raise FileExistsError(binding_path)
        observed = _load_json_mapping(binding_path)
        if observed != expected:
            raise ValueError("completed run snapshot binding differs from current project state")
        return binding, binding_path
    _write_json(binding_path, expected)
    return binding, binding_path


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


def _tool_intelligence_summary(
    record: FullWorkflowToolIntelligenceRecord,
    *,
    run_root: Path,
    record_path: Path,
) -> dict[str, object]:
    decision = record.decision
    return {
        "hook_id": record.hook_id,
        "status": record.status,
        "triggered": decision is not None,
        "decision": decision.decision.value if decision is not None else None,
        "selected_tool_step": (decision.selected_step_id if decision is not None else None),
        "resolved": decision.resolved if decision is not None else None,
        "recovered": record.recovered,
        "advisory_only": True,
        "canonical_evidence": False,
        "state_transition_authorized": False,
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
    tool_intelligence: LoadedFullWorkflowToolIntelligence | None = None,
    scenario_catalog: LoadedScenarioBundleCatalog | None = None,
    code_inspection: NativeCodeInspection | None = None,
    code_generation: LoadedNativeCodeGeneration | None = None,
    code_repair: LoadedNativeCodeRepair | None = None,
    execution_profile: NativeExecutionProfileInspection | None = None,
    condition_inspection: NativeConditionMatrixInspection | None = None,
) -> str:
    payload = config.model_dump(mode="json")
    if not config.native_candidate_generation_enabled:
        payload.pop("native_candidate_generation_enabled", None)
    if config.research_brief is None:
        payload.pop("research_brief", None)
    else:
        payload["research_brief"] = {"content_sha256": _file_sha256(config.research_brief)}
    for field in (
        "discovery_scenario",
        "evidence_scenario",
        "communication_scenario",
        "figure_scenario",
    ):
        configured_path = getattr(config, field)
        if configured_path is None:
            payload.pop(field, None)
        else:
            payload[field] = {"content_sha256": _file_sha256(configured_path)}
    if config.scenario_catalog is None:
        payload.pop("scenario_catalog", None)
    else:
        catalog = scenario_catalog or load_scenario_bundle_catalog(config.scenario_catalog)
        payload["scenario_catalog"] = {"binding_sha256": catalog.fingerprint}
    if config.native_knowledge_config is None:
        payload.pop("native_knowledge_config", None)
    else:
        payload["native_knowledge_config"] = {
            "content_sha256": _file_sha256(config.native_knowledge_config)
        }
    if config.native_condition_config is None:
        payload.pop("native_condition_config", None)
    else:
        condition_binding = condition_inspection or load_native_condition_matrix(
            config.native_condition_config
        )
        if condition_binding.path != config.native_condition_config.absolute():
            raise ValueError("native condition inspection belongs to another config")
        payload["native_condition_config"] = {
            "file_sha256": condition_binding.file_sha256,
            "matrix_fingerprint": condition_binding.matrix.fingerprint,
            "condition_id": condition_binding.matrix.profile(config.condition).condition_id.value,
        }
    if config.native_preference_backend_config is None:
        payload.pop("native_preference_backend_config", None)
    else:
        preference = load_local_transformers_config(config.native_preference_backend_config)
        validate_native_preference_identity(config, preference)
        payload["native_preference_backend_config"] = {
            "content_sha256": _file_sha256(config.native_preference_backend_config),
            "binding": preference.model_dump(mode="json"),
        }
    if config.native_execution_profile is None:
        payload.pop("native_execution_profile", None)
    else:
        profile = execution_profile or inspect_native_execution_profile(
            config.native_execution_profile
        )
        if profile.config_path != config.native_execution_profile.absolute():
            raise ValueError("native execution profile inspection belongs to another config")
        payload["native_execution_profile"] = {
            "fingerprint": profile.fingerprint,
            "config_sha256": profile.config_sha256,
            "datasets": [
                item.model_dump(mode="json", exclude={"source_path"}) for item in profile.datasets
            ],
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
    if config.native_code_repair_config is None:
        payload.pop("native_code_repair_config", None)
    else:
        repair_binding = code_repair or load_native_code_repair_config(
            config.native_code_repair_config
        )
        payload["native_code_repair_config"] = {
            "binding_sha256": repair_binding.fingerprint,
            "repair_recovery_contract": _REPAIR_RECOVERY_CONTRACT,
            "max_attempts": repair_binding.config.max_attempts,
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
    if config.tool_intelligence_advisory is None:
        payload.pop("tool_intelligence_advisory", None)
    else:
        binding = tool_intelligence or load_full_workflow_tool_intelligence(
            config.tool_intelligence_advisory
        )
        payload["tool_intelligence_advisory"] = {
            "binding_sha256": binding.fingerprint,
            "stage_recovery_contract": "1.0",
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

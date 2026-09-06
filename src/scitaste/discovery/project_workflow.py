"""Project-owned orchestration for composable native discovery commands."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.discovery.commands import (
    DiscoveryCommand,
    DiscoveryCommandReport,
    DiscoveryCommandRunner,
)
from scitaste.discovery.knowledge import (
    DiscoveryKnowledgeBinding,
    DiscoveryKnowledgePlan,
    DiscoveryKnowledgeReference,
    PreparedDiscoveryKnowledge,
    verify_discovery_knowledge_context,
)
from scitaste.discovery.landscape import LandscapeFinding, LiteratureLandscapeAgent
from scitaste.discovery.loop import DiscoveryScenario
from scitaste.discovery.semantic import (
    DISCOVERY_HYPOTHESIS_NODE,
    DISCOVERY_IDEATION_NODE,
    DISCOVERY_REFORMULATION_NODE,
    DiscoveryHypothesisInput,
    DiscoveryHypothesisProposal,
    DiscoveryIdeationInput,
    DiscoveryIdeationProposal,
    DiscoveryReformulationInput,
    DiscoveryReformulationProposal,
    DiscoverySemanticBinding,
    DiscoverySemanticReference,
    discovery_node_types,
    semantic_ideation_from_receipt,
    semantic_proposal_from_receipt,
    semantic_reference_from_receipt,
    semantic_reformulation_from_receipt,
)
from scitaste.executor.base import ResearchExecutor
from scitaste.executor.native import SciTasteNativeExecutor
from scitaste.executor.native_store import (
    NativeExecutionRecord,
    NativeExecutionStore,
    NativeExecutionVerification,
)
from scitaste.model_nodes.models import NodeContext
from scitaste.model_nodes.runtime import (
    ModelNodeRuntime,
    ModelNodeTrigger,
    RuntimeOutcome,
)
from scitaste.project.models import (
    ProjectRun,
    ProjectSnapshot,
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.project.runtime import ProjectRuntime
from scitaste.schema.actions import MetaAction
from scitaste.state.persistence import DecisionLogger, canonical_json, snapshot_id
from scitaste.state.research_state import ResearchStage, ResearchState
from scitaste.taste.controller import TasteController

_Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_StateId = Annotated[str, Field(pattern=r"^state-[0-9a-f]{64}$")]
_WORKFLOW_TYPE = "composable-native-discovery"
_PROVIDER = "scitaste-native"
_MODEL = "deterministic-taste-controller"
_CONDITION = "composable-discovery-commands-v1"
_STAGE_PATH = "discovery"
_MANIFEST_NAME = "DISCOVERY.json"
_SEMANTIC_COMMAND_NODES = {
    DiscoveryCommand.HYPOTHESIZE: DISCOVERY_HYPOTHESIS_NODE,
    DiscoveryCommand.REFORMULATE: DISCOVERY_REFORMULATION_NODE,
    DiscoveryCommand.IDEATE: DISCOVERY_IDEATION_NODE,
}
_SemanticProposal = (
    DiscoveryHypothesisProposal | DiscoveryReformulationProposal | DiscoveryIdeationProposal
)


class ProjectDiscoveryStep(BaseModel):
    """One immutable command output admitted into a project discovery run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int = Field(ge=1)
    command: DiscoveryCommand
    locator: str
    operation_token: _Digest
    project_revision_reserved: int = Field(ge=1)
    resumed: bool = False
    input_state_id: _StateId | None = None
    output_state_id: _StateId
    output_revision: int = Field(ge=1)
    final_stage: ResearchStage
    selected_actions: list[MetaAction] = Field(min_length=1)
    report_sha256: _Digest
    state_sha256: _Digest
    decision_log_sha256: _Digest
    semantic_proposal: DiscoverySemanticReference | None = None

    @field_validator("locator")
    @classmethod
    def locator_is_relative(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="discovery step locator")

    @model_validator(mode="after")
    def locator_matches_identity(self) -> ProjectDiscoveryStep:
        expected = f"steps/{self.ordinal:03d}-{self.command.value}"
        if self.locator != expected:
            raise ValueError(f"discovery step locator must be {expected!r}")
        expected_node = _SEMANTIC_COMMAND_NODES.get(self.command)
        if self.semantic_proposal is not None and self.semantic_proposal.node_name != expected_node:
            raise ValueError("discovery semantic reference does not match its command")
        return self


class ProjectDiscoveryManifest(BaseModel):
    """Self-hashed, mutable head over immutable project discovery steps."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    project_id: str
    run_id: str
    scenario_sha256: _Digest
    seed: int = Field(ge=0)
    status: Literal["active", "complete"]
    steps: list[ProjectDiscoveryStep] = Field(min_length=1)
    latest_state: str
    manifest_sha256: _Digest

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id")
    @classmethod
    def run_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="run_id")

    @field_validator("latest_state")
    @classmethod
    def latest_state_is_relative(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="latest discovery state")

    @classmethod
    def create(cls, **payload: Any) -> ProjectDiscoveryManifest:
        unsigned = dict(payload)
        unsigned.setdefault("schema_version", "1.0")
        unsigned.pop("manifest_sha256", None)
        serialized = _jsonable(unsigned)
        return cls.model_validate({**serialized, "manifest_sha256": content_sha256(serialized)})

    @model_validator(mode="after")
    def chain_and_hash_are_valid(self) -> ProjectDiscoveryManifest:
        unsigned = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if content_sha256(unsigned) != self.manifest_sha256:
            raise ValueError("discovery manifest self-hash mismatch")
        if self.steps[0].command != DiscoveryCommand.HYPOTHESIZE:
            raise ValueError("the first project discovery command must be hypothesize")
        for expected_ordinal, step in enumerate(self.steps, 1):
            if step.ordinal != expected_ordinal:
                raise ValueError("project discovery step ordinals must be contiguous")
            if expected_ordinal == 1:
                if step.input_state_id is not None:
                    raise ValueError("the first discovery step cannot have an input state")
            elif step.input_state_id != self.steps[expected_ordinal - 2].output_state_id:
                raise ValueError("project discovery state lineage is not contiguous")
            if (
                step.semantic_proposal is not None
                and step.semantic_proposal.node_name == DISCOVERY_HYPOTHESIS_NODE
                and expected_ordinal != 1
            ):
                raise ValueError("discovery semantic hypothesis must belong to the first step")
        invocation_ids = [
            step.semantic_proposal.invocation_id
            for step in self.steps
            if step.semantic_proposal is not None
        ]
        if len(invocation_ids) != len(set(invocation_ids)):
            raise ValueError("discovery semantic invocation identifiers must be unique")
        portfolio_positions = [
            index
            for index, step in enumerate(self.steps)
            if step.command == DiscoveryCommand.PORTFOLIO_SELECT
        ]
        if portfolio_positions and portfolio_positions != [len(self.steps) - 1]:
            raise ValueError("portfolio selection must be the final discovery step")
        expected_status = "complete" if portfolio_positions else "active"
        if self.status != expected_status:
            raise ValueError("discovery manifest status does not match its command chain")
        expected_latest = f"{self.steps[-1].locator}/research_state.json"
        if self.latest_state != expected_latest:
            raise ValueError("latest discovery state does not match the final step")
        return self


class ProjectDiscoveryPreview(BaseModel):
    """Mutation-free project admission result for one discovery operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["planned"] = "planned"
    project_id: str
    run_id: str
    project_revision: int = Field(ge=0)
    expected_final_revision: int = Field(ge=1)
    command: DiscoveryCommand
    ordinal: int = Field(ge=1)
    destination: str
    creates_run: bool
    resumes_run: bool
    recovers_completed_step: bool
    input_state_id: _StateId | None = None
    planned_actions: list[MetaAction] = Field(min_length=1)
    signal_number: int | None = Field(default=None, ge=1)
    reformulation_number: int | None = Field(default=None, ge=1)
    semantic_generation: bool = False
    knowledge_retrieval: bool = False


class ProjectDiscoveryVerification(BaseModel):
    """Independent verification result for a completed project metadata commit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["verified"] = "verified"
    project_id: str
    run_id: str
    run_status: Literal["active", "complete"]
    project_revision: int = Field(ge=1)
    project_snapshot_sha256: _Digest
    scenario_sha256: _Digest
    manifest_sha256: _Digest
    command_count: int = Field(ge=1)
    latest_state_id: _StateId
    latest_state: str
    final_stage: ResearchStage
    semantic_proposal_count: int = Field(default=0, ge=0)
    knowledge_retrieval: bool = False
    retrieved_document_count: int = Field(default=0, ge=0)
    native_execution_record_count: int = Field(default=0, ge=0)


class ProjectDiscoveryAdvanceReport(BaseModel):
    """Result of executing or interruption-safely recovering one project step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["active", "complete"]
    project_id: str
    run_id: str
    command: DiscoveryCommand
    ordinal: int = Field(ge=1)
    recovered_without_execution: bool
    project_revision: int = Field(ge=1)
    project_snapshot_sha256: _Digest
    discovery_manifest: str
    discovery_manifest_sha256: _Digest
    command_report: DiscoveryCommandReport
    verification: ProjectDiscoveryVerification


@dataclass(frozen=True)
class _Admission:
    snapshot: ProjectSnapshot
    registered_run: ProjectRun | None
    manifest: ProjectDiscoveryManifest | None
    state: ResearchState | None
    ordinal: int
    creates_run: bool
    resumes_run: bool
    recovers_completed_step: bool
    pending_token: str | None = None
    manifest_requires_publish: bool = False


class ProjectDiscoveryWorkflow:
    """Advance native Discovery through one revision-guarded project run."""

    def __init__(
        self,
        outputs_root: str | Path,
        *,
        seed: int = 0,
        controller: TasteController | None = None,
        executor: ResearchExecutor | None = None,
    ) -> None:
        self.runtime = ProjectRuntime(outputs_root)
        self.seed = seed
        self._controller = controller
        self._executor = executor
        self.runner = DiscoveryCommandRunner(
            seed=seed,
            controller=controller,
            executor=executor,
        )

    def preview(
        self,
        scenario: DiscoveryScenario,
        *,
        project_id: str,
        run_id: str,
        command: DiscoveryCommand,
        expected_revision: int,
        signal_number: int | None = None,
        reformulation_number: int | None = None,
        resume: bool = False,
        semantic: DiscoverySemanticBinding | None = None,
        knowledge: DiscoveryKnowledgeBinding | None = None,
    ) -> ProjectDiscoveryPreview:
        """Validate project/run/state identity without creating or changing files."""

        self._validate_semantic_request(scenario, command, semantic)
        admission = self._admit(
            scenario,
            project_id=project_id,
            run_id=run_id,
            command=command,
            expected_revision=expected_revision,
            resume=resume,
        )
        self._validate_semantic_state(command, admission.state, semantic)
        self._validate_semantic_budget(scenario, admission.state, semantic)
        self._require_semantic_identity(admission, command=command, semantic=semantic)
        self._validate_knowledge_request(scenario, admission, knowledge)
        if admission.recovers_completed_step:
            assert admission.manifest is not None
            completed = admission.manifest.steps[-1]
            completed_report = self._load_step_report(
                self._discovery_root(project_id, run_id),
                completed,
            )
            self._validate_recovery_options(
                completed_report,
                signal_number=signal_number,
                reformulation_number=reformulation_number,
            )
            planned_actions = completed.selected_actions
            resolved_signal = completed_report.details.get("signal_number")
            resolved_reformulation = completed_report.details.get("reformulation_number")
        else:
            command_preview = self.runner.preview(
                command,
                scenario,
                state=admission.state,
                signal_number=signal_number,
                reformulation_number=reformulation_number,
            )
            planned_actions = command_preview.planned_actions
            resolved_signal = command_preview.signal_number
            resolved_reformulation = command_preview.reformulation_number
        revision_increments = (
            3 if admission.creates_run else (1 if admission.recovers_completed_step else 2)
        )
        return ProjectDiscoveryPreview(
            project_id=project_id,
            run_id=run_id,
            project_revision=admission.snapshot.revision,
            expected_final_revision=admission.snapshot.revision + revision_increments,
            command=command,
            ordinal=admission.ordinal,
            destination=self._project_step_locator(run_id, admission.ordinal, command),
            creates_run=admission.creates_run,
            resumes_run=admission.resumes_run,
            recovers_completed_step=admission.recovers_completed_step,
            input_state_id=(snapshot_id(admission.state) if admission.state is not None else None),
            planned_actions=planned_actions,
            signal_number=resolved_signal,
            reformulation_number=resolved_reformulation,
            semantic_generation=semantic is not None,
            knowledge_retrieval=knowledge is not None,
        )

    def advance(
        self,
        scenario: DiscoveryScenario,
        *,
        project_id: str,
        run_id: str,
        command: DiscoveryCommand,
        expected_revision: int,
        evidence_scope: str = "native-discovery-engineering-evidence",
        signal_number: int | None = None,
        reformulation_number: int | None = None,
        resume: bool = False,
        semantic: DiscoverySemanticBinding | None = None,
        knowledge: DiscoveryKnowledgeBinding | None = None,
    ) -> ProjectDiscoveryAdvanceReport:
        """Reserve, execute, and commit exactly one project-owned discovery step."""

        validate_project_id(project_id)
        validate_entry_id(run_id, field_name="run_id")
        if not evidence_scope.strip():
            raise ValueError("evidence_scope must not be blank")
        # Reject deterministic identity, revision, stage, and operation errors
        # before even creating the per-run coordination lock file.
        self.preview(
            scenario,
            project_id=project_id,
            run_id=run_id,
            command=command,
            expected_revision=expected_revision,
            signal_number=signal_number,
            reformulation_number=reformulation_number,
            resume=resume,
            semantic=semantic,
            knowledge=knowledge,
        )
        lock_path = self._project_root(project_id) / f".discovery-{run_id}.lock"
        with _locked(lock_path):
            admission = self._admit(
                scenario,
                project_id=project_id,
                run_id=run_id,
                command=command,
                expected_revision=expected_revision,
                resume=resume,
            )
            self._validate_semantic_state(command, admission.state, semantic)
            self._validate_semantic_budget(scenario, admission.state, semantic)
            self._require_semantic_identity(admission, command=command, semantic=semantic)
            knowledge_plan = self._validate_knowledge_request(scenario, admission, knowledge)
            if admission.recovers_completed_step:
                assert admission.manifest is not None
                assert admission.pending_token is not None
                prepared_knowledge = self._prepare_knowledge(
                    project_id,
                    run_id,
                    knowledge,
                    knowledge_plan,
                )
                command_report = self._load_step_report(
                    self._discovery_root(project_id, run_id),
                    admission.manifest.steps[-1],
                )
                self._validate_recovery_options(
                    command_report,
                    signal_number=signal_number,
                    reformulation_number=reformulation_number,
                )
                if admission.manifest_requires_publish:
                    self._write_manifest(project_id, run_id, admission.manifest)
                snapshot = self._finalize(
                    project_id,
                    run_id,
                    admission.manifest,
                    pending_token=admission.pending_token,
                    recovered_without_execution=True,
                    knowledge=prepared_knowledge,
                )
                return self._report(
                    snapshot,
                    admission.manifest,
                    command_report,
                    recovered=True,
                )

            # Deterministic state and operation preconditions are admission checks;
            # they must fail before the project records a pending side effect.
            self.runner.preview(
                command,
                scenario,
                state=admission.state,
                signal_number=signal_number,
                reformulation_number=reformulation_number,
            )

            operation_token = self._operation_token(
                project_id=project_id,
                run_id=run_id,
                command=command,
                ordinal=admission.ordinal,
                expected_revision=expected_revision,
                input_state_id=(
                    snapshot_id(admission.state) if admission.state is not None else None
                ),
                resume_attempt=self._next_resume_attempt(admission),
                semantic_binding_sha256=(semantic.fingerprint if semantic is not None else None),
                knowledge_binding_sha256=(knowledge.fingerprint if knowledge is not None else None),
            )
            try:
                reserved = self._reserve(
                    admission,
                    scenario,
                    project_id=project_id,
                    run_id=run_id,
                    command=command,
                    operation_token=operation_token,
                    evidence_scope=evidence_scope,
                    semantic=semantic,
                    knowledge=knowledge,
                )
                expected_reserved_revision = admission.snapshot.revision + (
                    2 if admission.creates_run else 1
                )
                if reserved.revision != expected_reserved_revision:
                    raise ValueError("project discovery reservation revision is inconsistent")
                prepared_knowledge = self._prepare_knowledge(
                    project_id,
                    run_id,
                    knowledge,
                    knowledge_plan,
                )
                effective_findings = self._effective_landscape_findings(
                    scenario,
                    prepared_knowledge,
                )
                semantic_proposal: _SemanticProposal | None = None
                semantic_reference: DiscoverySemanticReference | None = None
                if semantic is not None:
                    semantic_proposal, semantic_reference = self._generate_semantic_proposal(
                        scenario,
                        project_id=project_id,
                        run_id=run_id,
                        command=command,
                        ordinal=admission.ordinal,
                        project_revision=reserved.revision,
                        state=admission.state,
                        resume=admission.resumes_run,
                        binding=semantic,
                        landscape_findings=effective_findings,
                    )
                step_root = self._step_root(
                    project_id,
                    run_id,
                    admission.ordinal,
                    command,
                )
                runner = self._runner_for_knowledge(
                    project_id,
                    run_id,
                    prepared_knowledge,
                    resume=admission.resumes_run,
                )
                command_report = runner.run(
                    command,
                    scenario,
                    output_dir=step_root,
                    state=admission.state,
                    signal_number=signal_number,
                    reformulation_number=reformulation_number,
                    receipt_paths="step-relative",
                    semantic_proposal=semantic_proposal,
                    semantic_reference=semantic_reference,
                    landscape_findings=(
                        effective_findings
                        if command is DiscoveryCommand.HYPOTHESIZE
                        and prepared_knowledge is not None
                        else None
                    ),
                    knowledge_reference=(
                        prepared_knowledge.reference
                        if command is DiscoveryCommand.HYPOTHESIZE
                        and prepared_knowledge is not None
                        else None
                    ),
                    expected_retrieved_document_ids=(
                        prepared_knowledge.plan.retrieved_document_ids
                        if command is DiscoveryCommand.HYPOTHESIZE
                        and prepared_knowledge is not None
                        else None
                    ),
                )
                command_report = self._make_report_portable(command_report, step_root)
                step = self._build_step(
                    command_report,
                    ordinal=admission.ordinal,
                    operation_token=operation_token,
                    project_revision_reserved=reserved.revision,
                    resumed=admission.resumes_run,
                    step_root=step_root,
                )
                manifest = ProjectDiscoveryManifest.create(
                    project_id=project_id,
                    run_id=run_id,
                    scenario_sha256=self._scenario_sha256(scenario),
                    seed=self.seed,
                    status=(
                        "complete" if command == DiscoveryCommand.PORTFOLIO_SELECT else "active"
                    ),
                    steps=[*(admission.manifest.steps if admission.manifest else []), step],
                    latest_state=f"{step.locator}/research_state.json",
                )
                self._write_manifest(project_id, run_id, manifest)
                snapshot = self._finalize(
                    project_id,
                    run_id,
                    manifest,
                    pending_token=operation_token,
                    recovered_without_execution=False,
                    knowledge=prepared_knowledge,
                )
            except BaseException as exc:
                self._mark_failed(
                    project_id,
                    run_id,
                    pending_token=operation_token,
                    error=exc,
                )
                raise
            return self._report(snapshot, manifest, command_report, recovered=False)

    def verify(self, project_id: str, run_id: str) -> ProjectDiscoveryVerification:
        """Verify project metadata, run head, immutable steps, and state lineage."""

        validate_project_id(project_id)
        validate_entry_id(run_id, field_name="run_id")
        snapshot = self.runtime.open(project_id)
        run = self._registered_run(snapshot, run_id)
        if run.status not in {"active", "complete"}:
            raise ValueError(f"project discovery run is not committed: {run.status!r}")
        extra = run.model_extra or {}
        if extra.get("workflow_type") != _WORKFLOW_TYPE:
            raise ValueError("registered run is not a project discovery workflow")
        if any(extra.get(name) is not None for name in self._pending_fields()):
            raise ValueError("committed discovery run retains a pending operation")
        manifest = self._load_manifest(project_id, run_id)
        knowledge_reference, native_verification = self._verify_manifest_tree(
            self._discovery_root(project_id, run_id),
            manifest,
        )
        self._require_committed_metadata(run, manifest)
        if run.status != manifest.status:
            raise ValueError("registered run status does not match discovery manifest")
        state = self._load_latest_state(project_id, run_id, manifest)
        return ProjectDiscoveryVerification(
            project_id=project_id,
            run_id=run_id,
            run_status=manifest.status,
            project_revision=snapshot.revision,
            project_snapshot_sha256=snapshot.snapshot_sha256,
            scenario_sha256=manifest.scenario_sha256,
            manifest_sha256=manifest.manifest_sha256,
            command_count=len(manifest.steps),
            latest_state_id=snapshot_id(state),
            latest_state=(
                f"projects/{project_id}/runs/{run_id}/{_STAGE_PATH}/{manifest.latest_state}"
            ),
            final_stage=state.current_stage,
            semantic_proposal_count=sum(
                step.semantic_proposal is not None for step in manifest.steps
            ),
            knowledge_retrieval=knowledge_reference is not None,
            retrieved_document_count=(
                len(knowledge_reference.retrieved_document_ids)
                if knowledge_reference is not None
                else 0
            ),
            native_execution_record_count=(
                native_verification.record_count if native_verification is not None else 0
            ),
        )

    def _admit(
        self,
        scenario: DiscoveryScenario,
        *,
        project_id: str,
        run_id: str,
        command: DiscoveryCommand,
        expected_revision: int,
        resume: bool,
    ) -> _Admission:
        validate_project_id(project_id)
        validate_entry_id(run_id, field_name="run_id")
        snapshot = self.runtime.open(project_id)
        if snapshot.revision != expected_revision:
            raise ValueError(
                f"stale project revision {expected_revision}; current is {snapshot.revision}"
            )
        self._require_project_identity(snapshot, scenario, project_id)
        matches = [item for item in snapshot.manifest.runs if item.run_id == run_id]
        if not matches:
            if resume:
                raise ValueError("cannot resume an unregistered project discovery run")
            if command != DiscoveryCommand.HYPOTHESIZE:
                raise ValueError("a new project discovery run must begin with hypothesize")
            return _Admission(
                snapshot=snapshot,
                registered_run=None,
                manifest=None,
                state=None,
                ordinal=1,
                creates_run=True,
                resumes_run=False,
                recovers_completed_step=False,
            )

        run = matches[0]
        self._require_run_identity(run, scenario)
        extra = run.model_extra or {}
        manifest_path = self._manifest_path(project_id, run_id)
        manifest = self._load_manifest(project_id, run_id) if manifest_path.is_file() else None
        if manifest is not None:
            if manifest.project_id != project_id or manifest.run_id != run_id:
                raise ValueError("discovery manifest identity does not match its project run")
            if manifest.seed != self.seed:
                raise ValueError("discovery manifest seed does not match the requested run")
            if manifest.scenario_sha256 != self._scenario_sha256(scenario):
                raise ValueError("discovery manifest is bound to a different scenario")

        if run.status == "complete":
            if manifest is not None:
                self._verify_manifest_tree(self._discovery_root(project_id, run_id), manifest)
            raise ValueError("a complete project discovery run cannot advance")
        if run.status == "active":
            if resume:
                raise ValueError("an active project discovery run does not require --resume")
            if manifest is None:
                raise ValueError("active project discovery run has no manifest")
            self._verify_manifest_tree(self._discovery_root(project_id, run_id), manifest)
            self._require_committed_metadata(run, manifest)
            if snapshot.manifest.current_run != run_id:
                raise ValueError("project discovery can advance only the current project run")
            state = self._load_latest_state(project_id, run_id, manifest)
            return _Admission(
                snapshot=snapshot,
                registered_run=run,
                manifest=manifest,
                state=state,
                ordinal=len(manifest.steps) + 1,
                creates_run=False,
                resumes_run=False,
                recovers_completed_step=False,
            )
        if run.status not in {"running", "failed"}:
            raise ValueError(f"unsupported project discovery run status {run.status!r}")
        if not resume:
            raise ValueError(f"{run.status} project discovery run requires --resume")
        pending_command = extra.get("pending_command")
        pending_ordinal = extra.get("pending_ordinal")
        pending_token = extra.get("pending_operation_token")
        pending_reserved_revision = extra.get("pending_project_revision_reserved")
        pending_resumed = extra.get("pending_resumed")
        if pending_command != command.value:
            raise ValueError(f"resume command must be {pending_command!r}, not {command.value!r}")
        if not isinstance(pending_ordinal, int) or isinstance(pending_ordinal, bool):
            raise ValueError("pending discovery ordinal is invalid")
        if not isinstance(pending_token, str) or not _is_digest(pending_token):
            raise ValueError("pending discovery operation token is invalid")
        if not isinstance(pending_reserved_revision, int) or isinstance(
            pending_reserved_revision, bool
        ):
            raise ValueError("pending discovery reserved revision is invalid")
        if not isinstance(pending_resumed, bool):
            raise ValueError("pending discovery resume marker is invalid")
        prior_count = len(manifest.steps) if manifest is not None else 0
        if prior_count not in {pending_ordinal - 1, pending_ordinal}:
            raise ValueError("pending discovery step does not align with the manifest")
        recoverable = prior_count == pending_ordinal
        manifest_requires_publish = False
        if recoverable:
            assert manifest is not None
            self._verify_manifest_tree(self._discovery_root(project_id, run_id), manifest)
            last = manifest.steps[-1]
            if (
                last.command != command
                or last.operation_token != pending_token
                or last.project_revision_reserved != pending_reserved_revision
                or last.resumed != pending_resumed
            ):
                raise ValueError("completed pending step does not match its reservation")
            state = (
                self._load_previous_state(project_id, run_id, manifest)
                if pending_ordinal > 1
                else None
            )
        else:
            if manifest is not None:
                self._require_committed_metadata(run, manifest)
                state = self._load_latest_state(project_id, run_id, manifest)
            else:
                if pending_ordinal != 1:
                    raise ValueError("missing discovery manifest before a later pending step")
                state = None
            pending_root = self._step_root(
                project_id,
                run_id,
                pending_ordinal,
                command,
            )
            if pending_root.exists():
                report = self._load_uncommitted_step_report(pending_root)
                step = self._build_step(
                    report,
                    ordinal=pending_ordinal,
                    operation_token=pending_token,
                    project_revision_reserved=pending_reserved_revision,
                    resumed=pending_resumed,
                    step_root=pending_root,
                )
                candidate = ProjectDiscoveryManifest.create(
                    project_id=project_id,
                    run_id=run_id,
                    scenario_sha256=self._scenario_sha256(scenario),
                    seed=self.seed,
                    status=(
                        "complete" if command == DiscoveryCommand.PORTFOLIO_SELECT else "active"
                    ),
                    steps=[*(manifest.steps if manifest is not None else []), step],
                    latest_state=f"{step.locator}/research_state.json",
                )
                self._verify_manifest_tree(
                    self._discovery_root(project_id, run_id),
                    candidate,
                )
                manifest = candidate
                recoverable = True
                manifest_requires_publish = True
            elif manifest is not None:
                self._verify_manifest_tree(
                    self._discovery_root(project_id, run_id),
                    manifest,
                )
            else:
                self._require_empty_steps(project_id, run_id)
        expected_input = snapshot_id(state) if state is not None else None
        if extra.get("pending_input_state_id") != expected_input:
            raise ValueError("pending discovery input state does not match the verified lineage")
        return _Admission(
            snapshot=snapshot,
            registered_run=run,
            manifest=manifest,
            state=state,
            ordinal=pending_ordinal,
            creates_run=False,
            resumes_run=True,
            recovers_completed_step=recoverable,
            pending_token=pending_token,
            manifest_requires_publish=manifest_requires_publish,
        )

    def _reserve(
        self,
        admission: _Admission,
        scenario: DiscoveryScenario,
        *,
        project_id: str,
        run_id: str,
        command: DiscoveryCommand,
        operation_token: str,
        evidence_scope: str,
        semantic: DiscoverySemanticBinding | None,
        knowledge: DiscoveryKnowledgeBinding | None,
    ) -> ProjectSnapshot:
        reserved_revision = admission.snapshot.revision + (2 if admission.creates_run else 1)
        semantic_bindings = self._registered_semantic_bindings(admission.registered_run)
        permanent_semantic: dict[str, Any] = {}
        if semantic is not None:
            invocation_id = self._semantic_invocation_id(command, admission.ordinal)
            existing_binding = semantic_bindings.get(invocation_id)
            if existing_binding is not None and existing_binding != semantic.fingerprint:
                raise ValueError("registered semantic invocation has a different binding")
            semantic_bindings[invocation_id] = semantic.fingerprint
            permanent_semantic["semantic_binding_sha256s"] = semantic_bindings
            if command is DiscoveryCommand.HYPOTHESIZE:
                permanent_semantic["semantic_binding_sha256"] = semantic.fingerprint
        permanent_knowledge: dict[str, Any] = {}
        if knowledge is not None:
            permanent_knowledge["knowledge_binding_sha256"] = knowledge.fingerprint
        pending = {
            "pending_command": command.value,
            "pending_ordinal": admission.ordinal,
            "pending_input_state_id": (
                snapshot_id(admission.state) if admission.state is not None else None
            ),
            "pending_operation_token": operation_token,
            "pending_project_revision_reserved": reserved_revision,
            "pending_resumed": admission.resumes_run,
            "pending_semantic_binding_sha256": (
                semantic.fingerprint if semantic is not None else None
            ),
            "pending_knowledge_binding_sha256": (
                knowledge.fingerprint if knowledge is not None else None
            ),
        }
        if admission.creates_run:
            snapshot = self.runtime.begin_run(
                project_id,
                ProjectRun(
                    run_id=run_id,
                    provider=_PROVIDER,
                    model=_MODEL,
                    condition=_CONDITION,
                    seed=self.seed,
                    status="running",
                    evidence_scope=evidence_scope,
                    stage_path=_STAGE_PATH,
                    workflow_type=_WORKFLOW_TYPE,
                    scenario_sha256=self._scenario_sha256(scenario),
                    resume_attempt=0,
                    effectiveness_claim=False,
                    **permanent_semantic,
                    **permanent_knowledge,
                    **pending,
                ),
                expected_revision=admission.snapshot.revision,
            )
            return self.runtime.select_run(
                project_id,
                run_id,
                expected_revision=snapshot.revision,
            )
        assert admission.registered_run is not None
        return self.runtime.update_run(
            project_id,
            run_id,
            expected_revision=admission.snapshot.revision,
            status="running",
            resume_attempt=self._next_resume_attempt(admission),
            failure=None,
            **permanent_semantic,
            **permanent_knowledge,
            **pending,
        )

    def _finalize(
        self,
        project_id: str,
        run_id: str,
        manifest: ProjectDiscoveryManifest,
        *,
        pending_token: str,
        recovered_without_execution: bool,
        knowledge: PreparedDiscoveryKnowledge | None,
    ) -> ProjectSnapshot:
        knowledge_reference, native_verification = self._verify_manifest_tree(
            self._discovery_root(project_id, run_id),
            manifest,
        )
        snapshot = self.runtime.open(project_id)
        run = self._registered_run(snapshot, run_id)
        extra = run.model_extra or {}
        if extra.get("pending_operation_token") != pending_token:
            raise ValueError("project run no longer owns the pending discovery operation")
        if extra.get("pending_command") != manifest.steps[-1].command.value:
            raise ValueError("pending command does not match the completed discovery step")
        recovery_updates: dict[str, Any] = {}
        if recovered_without_execution:
            prior_count = extra.get("recovered_without_execution_count", 0)
            if not isinstance(prior_count, int) or isinstance(prior_count, bool):
                raise ValueError("registered discovery recovery count is invalid")
            recovery_updates = {
                "recovered_without_execution_count": prior_count + 1,
                "last_recovery": {
                    "command": manifest.steps[-1].command.value,
                    "ordinal": manifest.steps[-1].ordinal,
                    "mode": "completed-step-without-execution",
                },
            }
        native_updates: dict[str, Any] = {}
        if knowledge is not None:
            if knowledge_reference != knowledge.reference or native_verification is None:
                raise ValueError("verified Discovery knowledge differs from the prepared context")
            native_updates = {
                "native_knowledge": knowledge.reference.model_dump(mode="json"),
                "native_execution": native_verification.model_dump(mode="json"),
            }
        elif knowledge_reference is not None:
            raise ValueError("project Discovery state has an unexpected native Knowledge context")
        return self.runtime.update_run(
            project_id,
            run_id,
            expected_revision=snapshot.revision,
            status=manifest.status,
            artifact=self._project_manifest_locator(run_id),
            discovery_manifest=self._project_manifest_locator(run_id),
            discovery_manifest_sha256=manifest.manifest_sha256,
            latest_state=(f"runs/{run_id}/{_STAGE_PATH}/{manifest.latest_state}"),
            command_count=len(manifest.steps),
            output_state_id=manifest.steps[-1].output_state_id,
            last_command=manifest.steps[-1].command.value,
            final_stage=manifest.steps[-1].final_stage.value,
            semantic_proposal_count=sum(
                step.semantic_proposal is not None for step in manifest.steps
            ),
            pending_command=None,
            pending_ordinal=None,
            pending_input_state_id=None,
            pending_operation_token=None,
            pending_project_revision_reserved=None,
            pending_resumed=None,
            pending_semantic_binding_sha256=None,
            pending_knowledge_binding_sha256=None,
            failure=None,
            effectiveness_claim=False,
            **recovery_updates,
            **native_updates,
        )

    def _mark_failed(
        self,
        project_id: str,
        run_id: str,
        *,
        pending_token: str,
        error: BaseException,
    ) -> None:
        try:
            snapshot = self.runtime.open(project_id)
            run = self._registered_run(snapshot, run_id)
            extra = run.model_extra or {}
            if extra.get("pending_operation_token") != pending_token:
                return
            self.runtime.update_run(
                project_id,
                run_id,
                expected_revision=snapshot.revision,
                status="failed",
                failure={
                    "type": type(error).__name__,
                    "message": str(error)[:1000],
                },
            )
        except (FileNotFoundError, ValueError):
            return

    def _report(
        self,
        snapshot: ProjectSnapshot,
        manifest: ProjectDiscoveryManifest,
        command_report: DiscoveryCommandReport,
        *,
        recovered: bool,
    ) -> ProjectDiscoveryAdvanceReport:
        verification = self.verify(manifest.project_id, manifest.run_id)
        return ProjectDiscoveryAdvanceReport(
            status=manifest.status,
            project_id=manifest.project_id,
            run_id=manifest.run_id,
            command=manifest.steps[-1].command,
            ordinal=manifest.steps[-1].ordinal,
            recovered_without_execution=recovered,
            project_revision=snapshot.revision,
            project_snapshot_sha256=snapshot.snapshot_sha256,
            discovery_manifest=(
                f"projects/{manifest.project_id}/{self._project_manifest_locator(manifest.run_id)}"
            ),
            discovery_manifest_sha256=manifest.manifest_sha256,
            command_report=command_report,
            verification=verification,
        )

    def _verify_manifest_tree(
        self,
        root: Path,
        manifest: ProjectDiscoveryManifest,
    ) -> tuple[DiscoveryKnowledgeReference | None, NativeExecutionVerification | None]:
        expected_directories = {step.locator for step in manifest.steps}
        steps_root = root / "steps"
        observed_directories = (
            {path.relative_to(root).as_posix() for path in steps_root.iterdir()}
            if steps_root.is_dir()
            else set()
        )
        if observed_directories != expected_directories:
            raise ValueError("discovery step directories do not match the manifest")
        previous_output: str | None = None
        previous_decision_ids: list[str] = []
        bound_semantic_references: list[DiscoverySemanticReference] = []
        bound_knowledge_reference: DiscoveryKnowledgeReference | None = None
        knowledge_presence: bool | None = None
        all_decisions: list[Any] = []
        initial_state: ResearchState | None = None
        for step in manifest.steps:
            step_root = root / step.locator
            if step_root.is_symlink() or not step_root.is_dir():
                raise ValueError(f"invalid discovery step directory: {step.locator}")
            report_path = step_root / "discovery_command.json"
            state_path = step_root / "research_state.json"
            decisions_path = step_root / "decisions.jsonl"
            for artifact in (report_path, state_path, decisions_path):
                self._require_owned_file(root, artifact)
            if {path.name for path in step_root.iterdir()} != {
                "decisions.jsonl",
                "discovery_command.json",
                "research_state.json",
                "state_snapshots",
            }:
                raise ValueError(f"discovery step contains unregistered artifacts: {step.locator}")
            if _file_sha256(report_path) != step.report_sha256:
                raise ValueError(f"discovery command report hash mismatch: {step.locator}")
            if _file_sha256(state_path) != step.state_sha256:
                raise ValueError(f"discovery state hash mismatch: {step.locator}")
            if _file_sha256(decisions_path) != step.decision_log_sha256:
                raise ValueError(f"discovery decision log hash mismatch: {step.locator}")
            report = DiscoveryCommandReport.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
            if (report.state, report.decision_log, report.report) != (
                "research_state.json",
                "decisions.jsonl",
                "discovery_command.json",
            ):
                raise ValueError("project discovery receipt paths must be step-relative")
            state = ResearchState.model_validate_json(state_path.read_text(encoding="utf-8"))
            if initial_state is None:
                initial_state = state
            if state.project_id != manifest.project_id:
                raise ValueError("discovery state belongs to a different project")
            raw_knowledge = state.executor_context.get("discovery_knowledge")
            observed_knowledge = (
                DiscoveryKnowledgeReference.model_validate_json(
                    json.dumps(raw_knowledge, ensure_ascii=False, allow_nan=False),
                    strict=True,
                )
                if raw_knowledge is not None
                else None
            )
            if knowledge_presence is None:
                knowledge_presence = observed_knowledge is not None
                bound_knowledge_reference = observed_knowledge
            elif (observed_knowledge is not None) != knowledge_presence:
                raise ValueError("discovery state Knowledge context appears mid-lineage")
            elif observed_knowledge != bound_knowledge_reference:
                raise ValueError("discovery state Knowledge context changes across its lineage")
            context = state.executor_context.get("discovery_command")
            if not isinstance(context, dict) or context.get("scenario_sha256") != (
                manifest.scenario_sha256
            ):
                raise ValueError("discovery state scenario binding is invalid")
            if report.command != step.command or report.project_id != manifest.project_id:
                raise ValueError("discovery command receipt identity mismatch")
            if report.scenario_sha256 != manifest.scenario_sha256 or report.seed != manifest.seed:
                raise ValueError("discovery command receipt configuration mismatch")
            if report.input_state_id != previous_output or step.input_state_id != previous_output:
                raise ValueError("discovery command input lineage mismatch")
            if report.output_state_id != snapshot_id(state):
                raise ValueError("discovery command output state identity mismatch")
            if report.output_state_id != step.output_state_id:
                raise ValueError("discovery step output state identity mismatch")
            if report.output_revision != state.revision or report.output_revision != (
                step.output_revision
            ):
                raise ValueError("discovery step state revision mismatch")
            if report.final_stage != state.current_stage or report.final_stage != step.final_stage:
                raise ValueError("discovery step stage mismatch")
            if report.selected_actions != step.selected_actions:
                raise ValueError("discovery step selected actions mismatch")
            if report.semantic_proposal != step.semantic_proposal:
                raise ValueError("discovery semantic reference differs from its manifest step")
            if report.semantic_proposal is not None:
                if any(
                    item.invocation_id == report.semantic_proposal.invocation_id
                    for item in bound_semantic_references
                ):
                    raise ValueError("discovery lineage repeats a semantic invocation")
                bound_semantic_references.append(report.semantic_proposal)
            if self._state_semantic_references(state) != bound_semantic_references:
                raise ValueError("discovery state semantic history is invalid")
            expected_semantic_cost = sum(item.cost_usd for item in bound_semantic_references)
            if not math.isclose(
                state.resource_usage.api_cost_usd,
                expected_semantic_cost,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("discovery state semantic cost differs from its ledger reference")
            if report.semantic_proposal is not None:
                self._verify_semantic_reference(manifest, report.semantic_proposal)
            decisions = DecisionLogger(decisions_path).read_all()
            all_decisions.extend(decisions)
            if [item.decision_id for item in decisions] != report.decision_ids:
                raise ValueError("discovery decision identifiers do not match the receipt")
            if [item.selected_action.type for item in decisions] != report.selected_actions:
                raise ValueError("discovery selected actions do not match the decision log")
            if [item.executor_result_id for item in decisions] != report.executor_result_ids:
                raise ValueError("discovery executor result lineage is invalid")
            current_decision_ids = [item.decision_id for item in state.decision_history]
            if current_decision_ids != [*previous_decision_ids, *report.decision_ids]:
                raise ValueError("discovery state decision history is not a contiguous extension")
            if [item.decision_id for item in state.transition_history] != current_decision_ids:
                raise ValueError("discovery transition history does not match its decisions")
            if [item.action_type for item in state.transition_history[-len(decisions) :]] != (
                report.selected_actions
            ):
                raise ValueError("discovery transition actions do not match the command receipt")
            snapshot_path = step_root / "state_snapshots" / f"{step.output_state_id}.json"
            self._require_owned_file(root, snapshot_path)
            if {path.name for path in snapshot_path.parent.iterdir()} != {snapshot_path.name}:
                raise ValueError("discovery step has an ambiguous immutable state snapshot")
            if snapshot_path.read_bytes() != state_path.read_bytes():
                raise ValueError("immutable discovery snapshot differs from latest step state")
            previous_output = step.output_state_id
            previous_decision_ids = current_decision_ids
        if bound_knowledge_reference is None:
            return None, None
        run_root = root.parent
        prepared_knowledge = verify_discovery_knowledge_context(
            run_root,
            bound_knowledge_reference,
        )
        assert initial_state is not None
        expected_landscape = LiteratureLandscapeAgent().build(
            list(prepared_knowledge.plan.findings)
        )
        actual_landscape = initial_state.literature_landscape.model_dump(mode="json")
        for field, expected_items in expected_landscape.model_dump(mode="json").items():
            if not set(expected_items).issubset(actual_landscape[field]):
                raise ValueError("Discovery state omits a planned Knowledge finding")
        self._verify_knowledge_semantic_scope(manifest, prepared_knowledge)
        native_store = self._native_store_for_verification(run_root)
        native_entries = native_store.entries()
        self._verify_native_execution_bindings(
            all_decisions,
            native_entries,
            knowledge=prepared_knowledge,
        )
        return bound_knowledge_reference, native_store.verify()

    def _verify_knowledge_semantic_scope(
        self,
        manifest: ProjectDiscoveryManifest,
        knowledge: PreparedDiscoveryKnowledge,
    ) -> None:
        reference = manifest.steps[0].semantic_proposal
        if reference is None:
            return
        if reference.node_name != DISCOVERY_HYPOTHESIS_NODE:
            raise ValueError("first Discovery semantic reference is not a hypothesis")
        entry = ModelNodeRuntime(
            self.runtime,
            node_types=discovery_node_types(),
        ).entry(
            project_id=manifest.project_id,
            run_id=manifest.run_id,
            invocation_id=reference.invocation_id,
        )
        try:
            semantic_input = DiscoveryHypothesisInput.model_validate_json(
                json.dumps(entry.intent.node_input, ensure_ascii=False, allow_nan=False),
                strict=True,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Knowledge-bound hypothesis input is invalid") from exc
        supplied = {
            content_sha256(finding.model_dump(mode="json"))
            for finding in semantic_input.landscape_findings
        }
        planned = {
            content_sha256(finding.model_dump(mode="json")) for finding in knowledge.plan.findings
        }
        if not planned.issubset(supplied):
            raise ValueError("semantic hypothesis input omits a planned Knowledge finding")

    @staticmethod
    def _native_store_for_verification(run_root: Path) -> NativeExecutionStore:
        workspace = run_root / "native_execution"
        for path in (workspace, workspace / "records", workspace / "artifacts"):
            if path.is_symlink() or not path.is_dir():
                raise ValueError("native Discovery execution storage is incomplete or unsafe")
        return NativeExecutionStore(workspace, artifact_root=run_root)

    @staticmethod
    def _verify_native_execution_bindings(
        decisions: list[Any],
        entries: tuple[tuple[str, NativeExecutionRecord], ...],
        *,
        knowledge: PreparedDiscoveryKnowledge,
    ) -> None:
        knowledge_reference = knowledge.reference
        records = dict(entries)
        seen: set[str] = set()
        search_count = 0
        for decision in decisions:
            outcome = decision.actual_outcome
            if not isinstance(outcome, dict) or outcome.get("executor") != (
                SciTasteNativeExecutor.name
            ):
                raise ValueError("Knowledge-bound Discovery decisions require native execution")
            data = outcome.get("data")
            if not isinstance(data, dict):
                raise ValueError("native Discovery outcome has no evidence binding")
            locator = data.get("execution_record")
            digest = data.get("execution_record_sha256")
            sequence = data.get("execution_sequence")
            if (
                not isinstance(locator, str)
                or not isinstance(digest, str)
                or isinstance(sequence, bool)
                or not isinstance(sequence, int)
            ):
                raise ValueError("native Discovery outcome has an invalid evidence binding")
            if locator in seen:
                raise ValueError("native Discovery record is bound by multiple decisions")
            try:
                record = records[locator]
            except KeyError as exc:
                raise ValueError("native Discovery decision references an unknown record") from exc
            if (
                record.record_sha256 != digest
                or record.sequence != sequence
                or record.action != decision.selected_action
                or record.state_sha256 != decision.state_snapshot_id.removeprefix("state-")
            ):
                raise ValueError("native Discovery record differs from its decision")
            expected_outcome = record.result.model_copy(
                update={
                    "data": {
                        **record.result.data,
                        "execution_record": locator,
                        "execution_record_sha256": record.record_sha256,
                        "execution_sequence": record.sequence,
                    }
                }
            ).model_dump(mode="json")
            if outcome != expected_outcome:
                raise ValueError("native Discovery result differs from its execution record")
            if decision.selected_action.type is MetaAction.SEARCH:
                search_count += 1
                if (
                    record.input_sha256.get(knowledge_reference.knowledge_records_locator)
                    != knowledge_reference.knowledge_records_sha256
                    or data.get("result_basis") != "knowledge-library-retrieval"
                    or data.get("retrieved_document_ids")
                    != list(knowledge_reference.retrieved_document_ids)
                    or data.get("retrieval_scores") != knowledge.plan.retrieval_scores
                ):
                    raise ValueError("native Discovery retrieval differs from its Knowledge plan")
            seen.add(locator)
        if search_count != 1:
            raise ValueError("Knowledge-bound Discovery must contain exactly one native retrieval")

    def _verify_semantic_reference(
        self,
        manifest: ProjectDiscoveryManifest,
        reference: DiscoverySemanticReference,
    ) -> None:
        runtime = ModelNodeRuntime(self.runtime, node_types=discovery_node_types())
        entry = runtime.entry(
            project_id=manifest.project_id,
            run_id=manifest.run_id,
            invocation_id=reference.invocation_id,
        )
        if entry.intent.node_name != reference.node_name:
            raise ValueError("discovery semantic reference points to another node type")
        if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
            raise ValueError("discovery semantic reference is not an accepted ledger entry")
        proposal = entry.result.get("proposal")
        if not isinstance(proposal, dict):
            raise ValueError("discovery semantic ledger entry has no typed proposal")
        expected_recording = (
            "projects/"
            f"{manifest.project_id}/runs/{manifest.run_id}/model_nodes/recordings/"
            f"{entry.intent.replay_source_invocation_id or entry.intent.invocation_id}.jsonl"
        )
        observed = (
            entry.entry_sha256,
            entry.request_fingerprint,
            content_sha256(proposal),
            expected_recording,
            entry.input_tokens,
            entry.output_tokens,
            entry.cost_effect_usd,
        )
        expected = (
            reference.ledger_entry_sha256,
            reference.request_fingerprint,
            reference.proposal_sha256,
            reference.recording_locator,
            reference.input_tokens,
            reference.output_tokens,
            reference.cost_usd,
        )
        if observed != expected:
            raise ValueError("discovery semantic receipt differs from its runtime ledger")
        registered = self._registered_run(
            self.runtime.open(manifest.project_id),
            manifest.run_id,
        )
        extra = registered.model_extra or {}
        semantic_bindings = self._registered_semantic_bindings(registered)
        run_binding = semantic_bindings.get(reference.invocation_id)
        if reference.node_name == DISCOVERY_HYPOTHESIS_NODE:
            legacy_binding = extra.get("semantic_binding_sha256")
            if legacy_binding is not None and legacy_binding != run_binding:
                raise ValueError("registered discovery semantic bindings are inconsistent")
        if not isinstance(run_binding, str) or not _is_digest(run_binding):
            raise ValueError("registered discovery semantic binding is missing or invalid")
        intent_binding = entry.intent.context.metadata.get("semantic_binding_sha256")
        if intent_binding is not None and intent_binding != run_binding:
            raise ValueError("discovery semantic binding differs from the runtime intent")

    def _require_committed_metadata(
        self,
        run: ProjectRun,
        manifest: ProjectDiscoveryManifest,
    ) -> None:
        extra = run.model_extra or {}
        expected = {
            "discovery_manifest": self._project_manifest_locator(run.run_id),
            "discovery_manifest_sha256": manifest.manifest_sha256,
            "latest_state": f"runs/{run.run_id}/{_STAGE_PATH}/{manifest.latest_state}",
            "command_count": len(manifest.steps),
            "output_state_id": manifest.steps[-1].output_state_id,
        }
        semantic_count = sum(step.semantic_proposal is not None for step in manifest.steps)
        if semantic_count or "semantic_proposal_count" in extra:
            expected["semantic_proposal_count"] = semantic_count
        mismatched = [name for name, value in expected.items() if extra.get(name) != value]
        if mismatched:
            raise ValueError(
                "registered discovery metadata does not match its manifest: "
                + ", ".join(mismatched)
            )
        if run.artifact != self._project_manifest_locator(run.run_id):
            raise ValueError("registered discovery artifact does not match its manifest")
        state = self._load_latest_state(manifest.project_id, manifest.run_id, manifest)
        raw_reference = state.executor_context.get("discovery_knowledge")
        knowledge_fields = (
            "knowledge_binding_sha256",
            "native_knowledge",
            "native_execution",
        )
        if raw_reference is None:
            if any(extra.get(name) is not None for name in knowledge_fields):
                raise ValueError("registered native Knowledge metadata has no state context")
            return
        try:
            reference = DiscoveryKnowledgeReference.model_validate_json(
                json.dumps(raw_reference, ensure_ascii=False, allow_nan=False),
                strict=True,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("discovery state Knowledge reference is invalid") from exc
        prepared = verify_discovery_knowledge_context(
            self._run_root(manifest.project_id, manifest.run_id),
            reference,
        )
        native_store = self._native_store_for_verification(
            self._run_root(manifest.project_id, manifest.run_id)
        )
        current_native = native_store.verify()
        observed = (
            extra.get("knowledge_binding_sha256"),
            extra.get("native_knowledge"),
        )
        expected_knowledge = (
            prepared.reference.binding_sha256,
            prepared.reference.model_dump(mode="json"),
        )
        if observed != expected_knowledge:
            raise ValueError("registered native Knowledge metadata differs from its context")
        try:
            committed_native = NativeExecutionVerification.model_validate(
                extra.get("native_execution"),
                strict=True,
            )
        except ValueError as exc:
            raise ValueError("registered native execution metadata is invalid") from exc
        if run.status in {"active", "complete"}:
            if committed_native != current_native:
                raise ValueError("registered native execution head differs from its record chain")
            return
        entries = native_store.entries()
        if committed_native.record_count > len(entries):
            raise ValueError("registered native execution prefix exceeds its record chain")
        if committed_native.record_count == 0:
            if (
                committed_native.head_record_sha256 is not None
                or committed_native.head_record_locator is not None
            ):
                raise ValueError("empty native execution prefix declares a record head")
            return
        locator, record = entries[committed_native.record_count - 1]
        if (
            committed_native.head_record_locator != locator
            or committed_native.head_record_sha256 != record.record_sha256
        ):
            raise ValueError("registered native execution prefix is not present in its chain")

    def _validate_knowledge_request(
        self,
        scenario: DiscoveryScenario,
        admission: _Admission,
        knowledge: DiscoveryKnowledgeBinding | None,
    ) -> DiscoveryKnowledgePlan | None:
        if knowledge is not None and self._executor is not None:
            raise ValueError("native Discovery knowledge cannot replace a caller-supplied executor")
        registered_binding: object | None = None
        if admission.registered_run is not None:
            registered_binding = (admission.registered_run.model_extra or {}).get(
                "knowledge_binding_sha256"
            )
        if registered_binding is None:
            if admission.registered_run is not None and knowledge is not None:
                raise ValueError("native Discovery knowledge cannot be added after run creation")
            if knowledge is None:
                return None
        elif (
            knowledge is None
            or not isinstance(registered_binding, str)
            or registered_binding != knowledge.fingerprint
        ):
            raise ValueError("native Discovery knowledge binding differs from the registered run")
        assert knowledge is not None
        if admission.resumes_run:
            pending = (admission.registered_run.model_extra or {}).get(
                "pending_knowledge_binding_sha256"
            )
            if pending != knowledge.fingerprint:
                raise ValueError("resume knowledge binding differs from the reserved operation")
        plan = knowledge.plan(
            scenario.research_direction,
            domain_tags=[scenario.target_domain],
            limit=5,
        )
        if len(scenario.landscape_findings) + len(plan.findings) > 40:
            raise ValueError("combined Discovery landscape exceeds the semantic evidence limit")
        return plan

    def _prepare_knowledge(
        self,
        project_id: str,
        run_id: str,
        knowledge: DiscoveryKnowledgeBinding | None,
        plan: DiscoveryKnowledgePlan | None,
    ) -> PreparedDiscoveryKnowledge | None:
        if knowledge is None or plan is None:
            if knowledge is not None or plan is not None:
                raise ValueError("Discovery knowledge binding and plan must be supplied together")
            return None
        return knowledge.prepare(self._run_root(project_id, run_id), plan)

    @staticmethod
    def _effective_landscape_findings(
        scenario: DiscoveryScenario,
        knowledge: PreparedDiscoveryKnowledge | None,
    ) -> list[LandscapeFinding]:
        return [
            *scenario.landscape_findings,
            *(knowledge.plan.findings if knowledge is not None else ()),
        ]

    def _runner_for_knowledge(
        self,
        project_id: str,
        run_id: str,
        knowledge: PreparedDiscoveryKnowledge | None,
        *,
        resume: bool,
    ) -> DiscoveryCommandRunner:
        if knowledge is None:
            return self.runner
        run_root = self._run_root(project_id, run_id)
        return DiscoveryCommandRunner(
            seed=self.seed,
            controller=self._controller,
            executor=SciTasteNativeExecutor(
                workspace=run_root / "native_execution",
                artifact_root=run_root,
                knowledge_library=knowledge.library,
                recover_completed_retrieval=resume,
            ),
        )

    def _validate_semantic_request(
        self,
        scenario: DiscoveryScenario,
        command: DiscoveryCommand,
        semantic: DiscoverySemanticBinding | None,
    ) -> None:
        if semantic is None:
            return
        expected_node = _SEMANTIC_COMMAND_NODES.get(command)
        if expected_node is None:
            raise ValueError("bounded semantic generation is not valid for this command")
        if semantic.node_name != expected_node:
            raise ValueError("semantic binding node does not match the discovery command")
        api_budget = scenario.resource_budget.max_api_cost_usd
        if api_budget is not None and semantic.profile.admission.max_response_cost_usd > api_budget:
            raise ValueError(
                "semantic response cost ceiling exceeds the discovery scenario API budget"
            )

    @staticmethod
    def _validate_semantic_state(
        command: DiscoveryCommand,
        state: ResearchState | None,
        semantic: DiscoverySemanticBinding | None,
    ) -> None:
        if semantic is None:
            return
        if command is DiscoveryCommand.IDEATE and (
            state is None or state.active_problem_id is not None
        ):
            raise ValueError("semantic ideation requires problem formation in the same command")

    @staticmethod
    def _validate_semantic_budget(
        scenario: DiscoveryScenario,
        state: ResearchState | None,
        semantic: DiscoverySemanticBinding | None,
    ) -> None:
        if semantic is None or scenario.resource_budget.max_api_cost_usd is None:
            return
        consumed = state.resource_usage.api_cost_usd if state is not None else 0.0
        if consumed + semantic.profile.admission.max_response_cost_usd > (
            scenario.resource_budget.max_api_cost_usd
        ):
            raise ValueError("cumulative semantic cost ceiling exceeds the discovery API budget")

    @staticmethod
    def _require_semantic_identity(
        admission: _Admission,
        *,
        command: DiscoveryCommand,
        semantic: DiscoverySemanticBinding | None,
    ) -> None:
        if admission.registered_run is None or not admission.resumes_run:
            return
        extra = admission.registered_run.model_extra or {}
        expected = semantic.fingerprint if semantic is not None else None
        if extra.get("pending_semantic_binding_sha256") != expected:
            raise ValueError("resume semantic binding differs from the reserved operation")
        if semantic is None:
            return
        invocation_id = ProjectDiscoveryWorkflow._semantic_invocation_id(
            command,
            admission.ordinal,
        )
        bindings = ProjectDiscoveryWorkflow._registered_semantic_bindings(admission.registered_run)
        if bindings.get(invocation_id) != expected:
            raise ValueError("registered discovery semantic identity is inconsistent")

    def _generate_semantic_proposal(
        self,
        scenario: DiscoveryScenario,
        *,
        project_id: str,
        run_id: str,
        command: DiscoveryCommand,
        ordinal: int,
        project_revision: int,
        state: ResearchState | None,
        resume: bool,
        binding: DiscoverySemanticBinding,
        landscape_findings: list[LandscapeFinding],
    ) -> tuple[_SemanticProposal, DiscoverySemanticReference]:
        invocation_id = self._semantic_invocation_id(command, ordinal)
        if command is DiscoveryCommand.HYPOTHESIZE:
            node_input: (
                DiscoveryHypothesisInput | DiscoveryReformulationInput | DiscoveryIdeationInput
            ) = DiscoveryHypothesisInput(
                research_direction=scenario.research_direction,
                target_domain=scenario.target_domain,
                target_venue=scenario.target_venue,
                landscape_findings=tuple(landscape_findings),
            )
            state_snapshot = f"scenario-{self._scenario_sha256(scenario)}"
            evidence_ids = list(node_input.source_ids)
            state_cost = 0.0
        elif command is DiscoveryCommand.REFORMULATE:
            if state is None:
                raise ValueError("semantic reformulation requires a predecessor state")
            node_input = DiscoveryReformulationInput(
                research_direction=state.research_direction,
                target_domain=state.target_domain,
                target_venue=state.target_venue,
                parent_hypothesis=self.runner._active_hypothesis(state),
                observations=tuple(state.observations),
            )
            state_snapshot = snapshot_id(state)
            evidence_ids = list(node_input.observation_ids)
            state_cost = state.resource_usage.api_cost_usd
        elif command is DiscoveryCommand.IDEATE:
            if state is None:
                raise ValueError("semantic ideation requires a predecessor state")
            node_input = DiscoveryIdeationInput(
                research_direction=state.research_direction,
                target_domain=state.target_domain,
                target_venue=state.target_venue,
                resource_budget=state.resource_budget,
                active_hypothesis=self.runner._active_hypothesis(state),
                observations=tuple(state.observations),
            )
            state_snapshot = snapshot_id(state)
            evidence_ids = list(node_input.observation_ids)
            state_cost = state.resource_usage.api_cost_usd
        else:
            raise ValueError("semantic proposal command is unsupported")
        receipt = ModelNodeRuntime(
            self.runtime,
            node_types=discovery_node_types(),
        ).execute(
            backend=binding.backend_for(invocation_id),
            resume=resume,
            allow_live=binding.allow_live,
            project_id=project_id,
            run_id=run_id,
            invocation_id=invocation_id,
            expected_project_revision=project_revision,
            state_revision=(state.revision if state is not None else 0),
            node_name=binding.node_name,
            node_input=node_input,
            context=NodeContext(
                project_id=project_id,
                stage=ResearchStage.DISCOVERY.value,
                state_snapshot_id=state_snapshot,
                cumulative_api_cost_usd=state_cost,
                evidence_ids=evidence_ids,
                metadata={
                    "run_id": run_id,
                    "authority": "proposal-only",
                    "command": command.value,
                    "semantic_binding_sha256": binding.fingerprint,
                },
            ),
            trigger=ModelNodeTrigger(
                trigger_id=f"project-discovery-{command.value}",
                reason=(
                    "A registered landscape requires bounded hypothesis semantics."
                    if command is DiscoveryCommand.HYPOTHESIZE
                    else (
                        "A registered contradiction requires bounded reformulation semantics."
                        if command is DiscoveryCommand.REFORMULATE
                        else "Registered observations require bounded problem and idea semantics."
                    )
                ),
            ),
            profile=binding.profile,
            policy=binding.policy,
            backend_mode=binding.backend_mode,
            replay_source_invocation_id=binding.replay_source_invocation_id,
            request_id=binding.request_id,
            seed=self.seed,
        )
        if command is DiscoveryCommand.HYPOTHESIZE:
            proposal = semantic_proposal_from_receipt(receipt)
        elif command is DiscoveryCommand.REFORMULATE:
            proposal = semantic_reformulation_from_receipt(receipt)
        else:
            proposal = semantic_ideation_from_receipt(receipt)
        api_budget = scenario.resource_budget.max_api_cost_usd
        observed_cost = receipt.telemetry.cost_usd
        if observed_cost is None or (
            api_budget is not None and state_cost + observed_cost > api_budget
        ):
            raise ValueError("semantic invocation exceeds the discovery scenario API budget")
        return proposal, semantic_reference_from_receipt(receipt, proposal)

    @staticmethod
    def _semantic_invocation_id(command: DiscoveryCommand, ordinal: int) -> str:
        if command is DiscoveryCommand.HYPOTHESIZE:
            if ordinal != 1:
                raise ValueError("semantic hypothesis invocation must be the first command")
            return "discovery-hypothesis-001"
        if command is DiscoveryCommand.REFORMULATE:
            return f"discovery-reformulation-{ordinal:03d}"
        if command is DiscoveryCommand.IDEATE:
            return f"discovery-ideation-{ordinal:03d}"
        raise ValueError("discovery command has no semantic invocation identity")

    @staticmethod
    def _registered_semantic_bindings(run: ProjectRun | None) -> dict[str, str]:
        if run is None:
            return {}
        extra = run.model_extra or {}
        raw = extra.get("semantic_binding_sha256s")
        if raw is None:
            bindings: dict[str, str] = {}
        elif isinstance(raw, dict) and all(
            isinstance(key, str) and isinstance(value, str) and _is_digest(value)
            for key, value in raw.items()
        ):
            bindings = dict(raw)
        else:
            raise ValueError("registered discovery semantic binding map is invalid")
        legacy = extra.get("semantic_binding_sha256")
        if legacy is not None:
            if not isinstance(legacy, str) or not _is_digest(legacy):
                raise ValueError("registered discovery semantic binding is invalid")
            existing = bindings.get("discovery-hypothesis-001")
            if existing is not None and existing != legacy:
                raise ValueError("registered discovery semantic bindings are inconsistent")
            bindings["discovery-hypothesis-001"] = legacy
        return bindings

    @staticmethod
    def _state_semantic_references(
        state: ResearchState,
    ) -> list[DiscoverySemanticReference]:
        legacy_raw = state.executor_context.get("discovery_semantic")
        legacy = (
            DiscoverySemanticReference.model_validate(legacy_raw, strict=True)
            if legacy_raw is not None
            else None
        )
        history_raw = state.executor_context.get("discovery_semantics")
        if history_raw is None:
            references = [] if legacy is None else [legacy]
        elif isinstance(history_raw, list):
            references = [
                DiscoverySemanticReference.model_validate(item, strict=True) for item in history_raw
            ]
        else:
            raise ValueError("discovery state semantic history is malformed")
        if legacy is not None and (not references or references[0] != legacy):
            raise ValueError("legacy discovery semantic reference differs from its history")
        invocation_ids = [item.invocation_id for item in references]
        if len(invocation_ids) != len(set(invocation_ids)):
            raise ValueError("discovery state semantic history repeats an invocation")
        return references

    def _require_project_identity(
        self,
        snapshot: ProjectSnapshot,
        scenario: DiscoveryScenario,
        project_id: str,
    ) -> None:
        if scenario.project_id != project_id:
            raise ValueError("scenario project_id must match the owning project")
        observed = (
            snapshot.manifest.research_direction,
            snapshot.manifest.target_domain,
            snapshot.manifest.target_venue,
        )
        expected = (
            scenario.research_direction,
            scenario.target_domain,
            scenario.target_venue,
        )
        if observed != expected:
            raise ValueError("project research identity does not match the discovery scenario")

    def _require_run_identity(self, run: ProjectRun, scenario: DiscoveryScenario) -> None:
        extra = run.model_extra or {}
        observed = (
            run.provider,
            run.model,
            run.condition,
            run.seed,
            run.stage_path,
            extra.get("workflow_type"),
            extra.get("scenario_sha256"),
        )
        expected = (
            _PROVIDER,
            _MODEL,
            _CONDITION,
            self.seed,
            _STAGE_PATH,
            _WORKFLOW_TYPE,
            self._scenario_sha256(scenario),
        )
        if observed != expected:
            raise ValueError("registered run identity does not match project discovery")

    def _build_step(
        self,
        report: DiscoveryCommandReport,
        *,
        ordinal: int,
        operation_token: str,
        project_revision_reserved: int,
        resumed: bool,
        step_root: Path,
    ) -> ProjectDiscoveryStep:
        return ProjectDiscoveryStep(
            ordinal=ordinal,
            command=report.command,
            locator=self._step_locator(ordinal, report.command),
            operation_token=operation_token,
            project_revision_reserved=project_revision_reserved,
            resumed=resumed,
            input_state_id=report.input_state_id,
            output_state_id=report.output_state_id,
            output_revision=report.output_revision,
            final_stage=report.final_stage,
            selected_actions=report.selected_actions,
            report_sha256=_file_sha256(step_root / "discovery_command.json"),
            state_sha256=_file_sha256(step_root / "research_state.json"),
            decision_log_sha256=report.decision_log_sha256,
            semantic_proposal=report.semantic_proposal,
        )

    @staticmethod
    def _make_report_portable(
        report: DiscoveryCommandReport,
        step_root: Path,
    ) -> DiscoveryCommandReport:
        local = {
            "state": "research_state.json",
            "decision_log": "decisions.jsonl",
            "report": "discovery_command.json",
        }
        if all(getattr(report, field) == value for field, value in local.items()):
            return report
        expected = {
            "state": step_root / "research_state.json",
            "decision_log": step_root / "decisions.jsonl",
            "report": step_root / "discovery_command.json",
        }
        for field, path in expected.items():
            if Path(getattr(report, field)).resolve() != path.resolve():
                raise ValueError(f"discovery command returned an unexpected {field} path")
        portable = report.model_copy(update=local)
        _atomic_json(
            step_root / "discovery_command.json",
            portable.model_dump(mode="json"),
        )
        return portable

    def _load_manifest(self, project_id: str, run_id: str) -> ProjectDiscoveryManifest:
        path = self._manifest_path(project_id, run_id)
        self._require_owned_file(self._discovery_root(project_id, run_id), path)
        return ProjectDiscoveryManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def _write_manifest(
        self,
        project_id: str,
        run_id: str,
        manifest: ProjectDiscoveryManifest,
    ) -> None:
        _atomic_json(
            self._manifest_path(project_id, run_id),
            manifest.model_dump(mode="json"),
        )

    def _load_latest_state(
        self,
        project_id: str,
        run_id: str,
        manifest: ProjectDiscoveryManifest,
    ) -> ResearchState:
        path = self._discovery_root(project_id, run_id) / manifest.latest_state
        self._require_owned_file(self._discovery_root(project_id, run_id), path)
        return ResearchState.model_validate_json(path.read_text(encoding="utf-8"))

    def _load_previous_state(
        self,
        project_id: str,
        run_id: str,
        manifest: ProjectDiscoveryManifest,
    ) -> ResearchState:
        if len(manifest.steps) < 2:
            raise ValueError("a recovered later step has no predecessor state")
        previous = manifest.steps[-2]
        path = self._discovery_root(project_id, run_id) / previous.locator / "research_state.json"
        self._require_owned_file(self._discovery_root(project_id, run_id), path)
        return ResearchState.model_validate_json(path.read_text(encoding="utf-8"))

    def _load_step_report(
        self,
        root: Path,
        step: ProjectDiscoveryStep,
    ) -> DiscoveryCommandReport:
        path = root / step.locator / "discovery_command.json"
        self._require_owned_file(root, path)
        return DiscoveryCommandReport.model_validate_json(path.read_text(encoding="utf-8"))

    def _load_uncommitted_step_report(self, step_root: Path) -> DiscoveryCommandReport:
        root = step_root.parent.parent
        if step_root.is_symlink() or not step_root.is_dir():
            raise ValueError("pending discovery step directory is invalid")
        report_path = step_root / "discovery_command.json"
        self._require_owned_file(root, report_path)
        report = DiscoveryCommandReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        if (report.state, report.decision_log, report.report) != (
            "research_state.json",
            "decisions.jsonl",
            "discovery_command.json",
        ):
            raise ValueError("pending project discovery receipt is not step-relative")
        return report

    def _require_empty_steps(self, project_id: str, run_id: str) -> None:
        steps_root = self._discovery_root(project_id, run_id) / "steps"
        if steps_root.exists() and any(steps_root.iterdir()):
            raise ValueError("unregistered discovery artifacts block safe resume")

    @staticmethod
    def _validate_recovery_options(
        report: DiscoveryCommandReport,
        *,
        signal_number: int | None,
        reformulation_number: int | None,
    ) -> None:
        if signal_number is not None and report.details.get("signal_number") != signal_number:
            raise ValueError("recovery signal number differs from the completed pending step")
        if (
            reformulation_number is not None
            and report.details.get("reformulation_number") != reformulation_number
        ):
            raise ValueError(
                "recovery reformulation number differs from the completed pending step"
            )

    @staticmethod
    def _registered_run(snapshot: ProjectSnapshot, run_id: str) -> ProjectRun:
        try:
            return next(item for item in snapshot.manifest.runs if item.run_id == run_id)
        except StopIteration as exc:
            raise ValueError(f"unknown project run {run_id!r}") from exc

    @staticmethod
    def _next_resume_attempt(admission: _Admission) -> int:
        if admission.registered_run is None:
            return 0
        raw = (admission.registered_run.model_extra or {}).get("resume_attempt", 0)
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            raise ValueError("registered discovery resume_attempt is invalid")
        return raw + 1 if admission.resumes_run else raw

    @staticmethod
    def _operation_token(
        *,
        project_id: str,
        run_id: str,
        command: DiscoveryCommand,
        ordinal: int,
        expected_revision: int,
        input_state_id: str | None,
        resume_attempt: int,
        semantic_binding_sha256: str | None,
        knowledge_binding_sha256: str | None,
    ) -> str:
        payload = {
            "project_id": project_id,
            "run_id": run_id,
            "command": command.value,
            "ordinal": ordinal,
            "expected_revision": expected_revision,
            "input_state_id": input_state_id,
            "resume_attempt": resume_attempt,
            "semantic_binding_sha256": semantic_binding_sha256,
        }
        if knowledge_binding_sha256 is not None:
            payload["knowledge_binding_sha256"] = knowledge_binding_sha256
        return content_sha256(payload)

    @staticmethod
    def _scenario_sha256(scenario: DiscoveryScenario) -> str:
        return hashlib.sha256(canonical_json(scenario).encode("utf-8")).hexdigest()

    def _project_root(self, project_id: str) -> Path:
        return self.runtime.projects_root / project_id

    def _run_root(self, project_id: str, run_id: str) -> Path:
        return self._project_root(project_id) / "runs" / run_id

    def _discovery_root(self, project_id: str, run_id: str) -> Path:
        return self._run_root(project_id, run_id) / _STAGE_PATH

    def _manifest_path(self, project_id: str, run_id: str) -> Path:
        return self._discovery_root(project_id, run_id) / _MANIFEST_NAME

    def _step_root(
        self,
        project_id: str,
        run_id: str,
        ordinal: int,
        command: DiscoveryCommand,
    ) -> Path:
        return self._discovery_root(project_id, run_id) / self._step_locator(ordinal, command)

    @staticmethod
    def _step_locator(ordinal: int, command: DiscoveryCommand) -> str:
        return f"steps/{ordinal:03d}-{command.value}"

    @classmethod
    def _project_step_locator(
        cls,
        run_id: str,
        ordinal: int,
        command: DiscoveryCommand,
    ) -> str:
        return f"runs/{run_id}/{_STAGE_PATH}/{cls._step_locator(ordinal, command)}"

    @staticmethod
    def _project_manifest_locator(run_id: str) -> str:
        return f"runs/{run_id}/{_STAGE_PATH}/{_MANIFEST_NAME}"

    @staticmethod
    def _pending_fields() -> tuple[str, ...]:
        return (
            "pending_command",
            "pending_ordinal",
            "pending_input_state_id",
            "pending_operation_token",
            "pending_project_revision_reserved",
            "pending_resumed",
            "pending_semantic_binding_sha256",
            "pending_knowledge_binding_sha256",
        )

    @staticmethod
    def _require_owned_file(root: Path, path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or linked project discovery artifact: {path.name}")
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError("project discovery artifact escapes its run") from exc


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

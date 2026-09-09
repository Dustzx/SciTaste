"""Project-owned Tool Intelligence hook for the native Full Workflow."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evidence.claim_graph import ClaimStatus
from scitaste.evidence.evidence_graph import EvidenceItem
from scitaste.model_nodes.facade import (
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
)
from scitaste.model_nodes.models import NodePolicy
from scitaste.model_nodes.profiles import (
    ModelNodeProfile,
    load_model_node_profile_set,
    validate_profile_binding,
)
from scitaste.model_nodes.runtime import (
    ModelNodeRegistration,
    ModelNodeRuntime,
    ModelNodeTrigger,
)
from scitaste.model_nodes.runtime_config import (
    LiveRuntimeBackend,
    RuntimeBackendBinding,
    ScriptedRuntimeBackend,
)
from scitaste.model_nodes.tool_bindings import (
    ContentAddressedRunFile,
    KnowledgeLibraryBinding,
    ProjectEvidenceRecord,
    ProjectToolBindingSet,
    load_project_tool_handlers,
)
from scitaste.model_nodes.tool_execution import (
    ControlledToolExecutor,
    SemanticGapKind,
    SemanticHotspotKind,
)
from scitaste.model_nodes.tool_execution_runtime import (
    DurableToolDecisionEnvelope,
    DurableToolExecutionRuntime,
)
from scitaste.model_nodes.tool_intelligence import (
    ControlledToolName,
    ControlledToolProfile,
    EvidenceInspectPermission,
    KnowledgeQueryPermission,
    RegisteredRunComparePermission,
    ToolPlanInput,
    ToolPlanOutput,
    ToolScopeProjection,
)
from scitaste.model_nodes.tool_workflow import (
    DeterministicSemanticHotspotSignal,
    ProjectToolIntelligenceBridge,
    SemanticHotspotDetector,
    ToolHotspotWorkflowBudget,
    ToolHotspotWorkflowDecisionRecord,
    ToolHotspotWorkflowRequest,
)
from scitaste.project import ProjectRuntime
from scitaste.project.models import content_sha256
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState

_HOOK_CONTRACT_VERSION = "1.0"
_MAX_CONFIG_BYTES = 1_000_000


class FullWorkflowToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class FullWorkflowToolIntelligenceConfig(FullWorkflowToolModel):
    """One explicit deterministic hotspot policy and bounded Tool Plan backend."""

    schema_version: Literal["1.0"] = "1.0"
    hook_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    trigger_claim_statuses: tuple[ClaimStatus, ...] = Field(min_length=1, max_length=5)
    objective: str = Field(min_length=1, max_length=4_000)
    hotspot_kind: SemanticHotspotKind
    semantic_gap: SemanticGapKind
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=16)
    candidate_tool_names: tuple[ControlledToolName, ...] = Field(min_length=1, max_length=2)
    profile_set: Path
    profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    policy: NodePolicy
    backend: RuntimeBackendBinding
    controlled_tool_profile: ControlledToolProfile
    budget: ToolHotspotWorkflowBudget = Field(default_factory=ToolHotspotWorkflowBudget)
    live_enabled: bool = False
    advisory_only: Literal[True] = True
    canonical_evidence_admission: Literal[False] = False
    state_transition_authorized: Literal[False] = False

    @model_validator(mode="after")
    def integration_boundary_is_closed(self) -> FullWorkflowToolIntelligenceConfig:
        if len(self.trigger_claim_statuses) != len(set(self.trigger_claim_statuses)):
            raise ValueError("Tool Intelligence trigger statuses must be unique")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("Tool Intelligence reason codes must be unique")
        if len(self.candidate_tool_names) != len(set(self.candidate_tool_names)):
            raise ValueError("Tool Intelligence candidate tools must be unique")
        allowed = set(self.controlled_tool_profile.allowed_tool_names)
        if set(item.value for item in self.candidate_tool_names) - allowed:
            raise ValueError("hotspot candidates exceed the controlled tool profile")
        if any(
            isinstance(item, RegisteredRunComparePermission)
            for item in self.controlled_tool_profile.permissions
        ):
            raise ValueError(
                "Full Workflow run comparison requires a separately registered metrics source"
            )
        knowledge_permissions = [
            item
            for item in self.controlled_tool_profile.permissions
            if isinstance(item, KnowledgeQueryPermission)
        ]
        if knowledge_permissions and len(knowledge_permissions[0].allowed_library_ids) != 1:
            raise ValueError("Full Workflow currently binds exactly one native Knowledge library")
        if self.policy.allowed_node_names != ["tool-plan"] or not self.policy.enabled:
            raise ValueError("Full Workflow Tool Intelligence policy must enable only tool-plan")
        identity = (
            (self.backend.provider, self.backend.model)
            if isinstance(self.backend, ScriptedRuntimeBackend)
            else (self.backend.config.provider, self.backend.config.model)
        )
        if identity != (self.policy.expected_backend, self.policy.expected_model):
            raise ValueError("Tool Intelligence backend identity differs from policy")
        if isinstance(self.backend, ScriptedRuntimeBackend):
            if self.live_enabled:
                raise ValueError("scripted Tool Intelligence cannot enable live execution")
            if self.backend.reply.tool_calls:
                raise ValueError("provider-native tool calls cannot authorize Tool Intelligence")
            if self.backend.reply.usage.cost_usd != 0:
                raise ValueError("scripted Tool Intelligence must have exactly zero API cost")
            proposal = ToolPlanOutput.model_validate(self.backend.reply.output_payload)
            if (
                proposal.tool_profile_id != self.controlled_tool_profile.profile_id
                or proposal.tool_profile_fingerprint != self.controlled_tool_profile.fingerprint
            ):
                raise ValueError("scripted Tool Plan differs from its controlled profile")
            proposed = {step.tool_name for step in proposal.steps}
            if proposed - set(self.candidate_tool_names):
                raise ValueError("scripted Tool Plan proposes a non-candidate tool")
        elif self.live_enabled != self.backend.config.live_enabled:
            raise ValueError("Tool Intelligence and backend live gates must agree")
        return self


@dataclass(frozen=True)
class LoadedFullWorkflowToolIntelligence:
    source_path: Path
    source_sha256: str
    profile_set_sha256: str
    config: FullWorkflowToolIntelligenceConfig
    profile: ModelNodeProfile

    @property
    def fingerprint(self) -> str:
        return content_sha256(
            {
                "hook_contract_version": _HOOK_CONTRACT_VERSION,
                "source_sha256": self.source_sha256,
                "profile_set_sha256": self.profile_set_sha256,
                "profile_fingerprint": self.profile.fingerprint,
            }
        )


class FullWorkflowToolIntelligenceInputRecord(FullWorkflowToolModel):
    """Pre-provider checkpoint for an exact automatic hotspot decision."""

    schema_version: Literal["1.0"] = "1.0"
    hook_id: str
    project_id: str
    run_id: str
    project_revision: int = Field(ge=0)
    predecessor_state_locator: str
    predecessor_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_locator: str
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_snapshot_id: str
    state_revision: int = Field(ge=0)
    evidence_summary_locator: str
    evidence_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_locator: str
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    controlled_tool_profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched_claim_ids: tuple[str, ...] = ()
    triggered: bool
    workflow_request: ToolHotspotWorkflowRequest | None = None
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: object) -> FullWorkflowToolIntelligenceInputRecord:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def input_identity_is_closed(self) -> FullWorkflowToolIntelligenceInputRecord:
        if self.triggered != bool(self.matched_claim_ids):
            raise ValueError("Tool Intelligence trigger must match its claim evidence")
        if self.triggered != (self.workflow_request is not None):
            raise ValueError("triggered Tool Intelligence input requires one workflow request")
        if self.workflow_request is not None and (
            self.workflow_request.project_id,
            self.workflow_request.run_id,
            self.workflow_request.hotspot.project_revision,
        ) != (self.project_id, self.run_id, self.project_revision):
            raise ValueError("Tool Intelligence request belongs to another project revision")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("Tool Intelligence input record hash mismatch")
        return self


class FullWorkflowToolIntelligenceRecord(FullWorkflowToolModel):
    """Stage bridge evidence that never promotes advice into canonical state."""

    schema_version: Literal["1.0"] = "1.0"
    hook_id: str
    project_id: str
    run_id: str
    project_revision: int = Field(ge=0)
    input_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["not_applicable", "resolved", "unresolved"]
    decision: ToolHotspotWorkflowDecisionRecord | None = None
    decision_locator: str | None = None
    decision_envelope_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    recovered: bool = False
    advisory_only: Literal[True] = True
    canonical_evidence: Literal[False] = False
    state_transition_authorized: Literal[False] = False
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: object) -> FullWorkflowToolIntelligenceRecord:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def result_identity_is_closed(self) -> FullWorkflowToolIntelligenceRecord:
        if self.input_state_sha256 != self.output_state_sha256:
            raise ValueError("Tool Intelligence changed canonical research state")
        decision_values = (self.decision, self.decision_locator, self.decision_envelope_sha256)
        if any(value is not None for value in decision_values) != all(
            value is not None for value in decision_values
        ):
            raise ValueError("Tool Intelligence decision evidence must be complete")
        if self.status == "not_applicable" and self.decision is not None:
            raise ValueError("not-applicable Tool Intelligence cannot have a decision")
        if self.status != "not_applicable" and self.decision is None:
            raise ValueError("triggered Tool Intelligence requires a decision")
        if self.decision is not None:
            expected_status = "resolved" if self.decision.resolved else "unresolved"
            if self.status != expected_status:
                raise ValueError("Tool Intelligence status differs from its durable decision")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("Tool Intelligence bridge record hash mismatch")
        return self


def load_full_workflow_tool_intelligence(
    path: str | Path,
) -> LoadedFullWorkflowToolIntelligence:
    """Load a strict secret-free Tool Intelligence hook and its pinned profile."""

    source = Path(path).expanduser().resolve(strict=True)
    raw = _read_regular(source, max_bytes=_MAX_CONFIG_BYTES)
    try:
        payload = yaml.load(raw, Loader=_UniqueKeyLoader)
        _reject_secret_fields(payload)
        if not isinstance(payload, dict):
            raise ValueError("Tool Intelligence config root must be a mapping")
        profile_set = Path(payload["profile_set"])
        if not profile_set.is_absolute():
            profile_set = (source.parent / profile_set).resolve(strict=True)
        payload["profile_set"] = profile_set
        config = FullWorkflowToolIntelligenceConfig.model_validate(payload)
        profiles = load_model_node_profile_set(profile_set)
        profile = profiles.profiles[config.profile_id]
        validate_profile_binding(profile, config.policy, node_name="tool-plan")
    except (KeyError, TypeError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("invalid Full Workflow Tool Intelligence configuration") from exc
    if config.live_enabled != profile.live_execution_permitted:
        raise ValueError("Tool Intelligence and profile live gates must agree")
    if config.live_enabled != profiles.profile_set.live_enabled:
        raise ValueError("Tool Intelligence and profile-set live gates must agree")
    if profile.unrestricted_code_generation:
        raise ValueError("Tool Intelligence profile cannot generate unrestricted code")
    if profile.admission.max_tool_call_proposals:
        raise ValueError("provider-native tool calls remain forbidden")
    if set(config.controlled_tool_profile.allowed_tool_names) - set(
        profile.admission.allowed_tool_names
    ):
        raise ValueError("controlled tools exceed the model profile")
    return LoadedFullWorkflowToolIntelligence(
        source_path=source,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        profile_set_sha256=profiles.source_sha256,
        config=config,
        profile=profile,
    )


def execute_full_workflow_tool_intelligence(
    loaded: LoadedFullWorkflowToolIntelligence,
    *,
    project_runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
    expected_project_revision: int,
    run_root: Path,
    predecessor_state_path: Path,
    state_path: Path,
    evidence_summary_path: Path,
    record_path: Path,
    seed: int,
    resume: bool = False,
    allow_live: bool = False,
    node_types: Mapping[str, ModelNodeRegistration] | None = None,
) -> FullWorkflowToolIntelligenceRecord:
    """Detect, execute, or verify one bounded evidence-stage semantic hotspot."""

    if isinstance(loaded.config.backend, LiveRuntimeBackend):
        if not loaded.config.live_enabled:
            raise ValueError("live Full Workflow Tool Intelligence is disabled")
        if not allow_live:
            raise ValueError("live Full Workflow Tool Intelligence requires caller opt-in")
    input_path = record_path.with_name("tool_intelligence_input.json")
    binding_path = record_path.with_name("tool_intelligence_binding.json")
    input_record = _prepare_input_record(
        loaded,
        project_runtime=project_runtime,
        project_id=project_id,
        run_id=run_id,
        expected_project_revision=expected_project_revision,
        run_root=run_root,
        predecessor_state_path=predecessor_state_path,
        state_path=state_path,
        evidence_summary_path=evidence_summary_path,
        input_path=input_path,
        binding_path=binding_path,
        seed=seed,
    )
    if record_path.exists():
        return verify_full_workflow_tool_intelligence(
            loaded,
            project_runtime=project_runtime,
            project_id=project_id,
            run_id=run_id,
            run_root=run_root,
            predecessor_state_path=predecessor_state_path,
            state_path=state_path,
            input_path=input_path,
            record_path=record_path,
            node_types=node_types,
        )
    before_sha256 = hashlib.sha256(state_path.read_bytes()).hexdigest()
    if input_record.workflow_request is None:
        record = FullWorkflowToolIntelligenceRecord.create(
            hook_id=loaded.config.hook_id,
            project_id=project_id,
            run_id=run_id,
            project_revision=input_record.project_revision,
            input_record_sha256=input_record.record_sha256,
            input_state_sha256=before_sha256,
            output_state_sha256=hashlib.sha256(state_path.read_bytes()).hexdigest(),
            status="not_applicable",
        )
        _write_model_exact(record_path, record)
        return record

    binding = ProjectToolBindingSet.model_validate_json(_read_regular(binding_path))

    def current_state_snapshot() -> str:
        state = ResearchState.model_validate_json(_read_regular(state_path))
        if state.project_id != project_id:
            raise ValueError("Tool Intelligence state changed project identity")
        return snapshot_id(state)

    tool_runtime = DurableToolExecutionRuntime(
        project_runtime,
        executor_factory=lambda: ControlledToolExecutor(
            project_runtime=project_runtime,
            state_snapshot_reader=current_state_snapshot,
            handlers=load_project_tool_handlers(
                project_runtime,
                binding,
                loaded.config.controlled_tool_profile,
            ).handlers,
        ),
    )
    bridge = ProjectToolIntelligenceBridge(
        ModelNodeFacade(ModelNodeRuntime(project_runtime, node_types=node_types)),
        tool_runtime,
    )
    request = input_record.workflow_request
    result = bridge.resolve(
        request,
        backend=loaded.config.backend.build(request.model_request.invocation_id),
        allow_live=allow_live,
    )
    after_sha256 = hashlib.sha256(state_path.read_bytes()).hexdigest()
    record = FullWorkflowToolIntelligenceRecord.create(
        hook_id=loaded.config.hook_id,
        project_id=project_id,
        run_id=run_id,
        project_revision=input_record.project_revision,
        input_record_sha256=input_record.record_sha256,
        input_state_sha256=before_sha256,
        output_state_sha256=after_sha256,
        status="resolved" if result.record.resolved else "unresolved",
        decision=result.record,
        decision_locator=result.decision_locator,
        decision_envelope_sha256=result.envelope_sha256,
        recovered=result.recovered,
    )
    _write_model_exact(record_path, record)
    return record


def verify_full_workflow_tool_intelligence(
    loaded: LoadedFullWorkflowToolIntelligence,
    *,
    project_runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
    run_root: Path,
    predecessor_state_path: Path,
    state_path: Path,
    input_path: Path,
    record_path: Path,
    node_types: Mapping[str, ModelNodeRegistration] | None = None,
) -> FullWorkflowToolIntelligenceRecord:
    """Verify the stage bridge plus the complete model and tool ledgers."""

    input_record = _load_and_verify_input(
        loaded,
        project_runtime=project_runtime,
        project_id=project_id,
        run_id=run_id,
        run_root=run_root,
        predecessor_state_path=predecessor_state_path,
        state_path=state_path,
        input_path=input_path,
    )
    try:
        record = FullWorkflowToolIntelligenceRecord.model_validate_json(_read_regular(record_path))
    except ValueError as exc:
        raise ValueError("invalid Full Workflow Tool Intelligence record") from exc
    state_sha256 = hashlib.sha256(_read_regular(state_path)).hexdigest()
    if (
        (record.project_id, record.run_id, record.hook_id)
        != (project_id, run_id, loaded.config.hook_id)
        or record.project_revision != input_record.project_revision
        or record.input_record_sha256 != input_record.record_sha256
        or record.input_state_sha256 != state_sha256
        or record.output_state_sha256 != state_sha256
    ):
        raise ValueError("Full Workflow Tool Intelligence result binding drift")
    if record.status == "not_applicable":
        if input_record.triggered:
            raise ValueError("triggered Tool Intelligence cannot be not-applicable")
        return record
    if record.decision is None or input_record.workflow_request is None:
        raise ValueError("Tool Intelligence decision evidence is incomplete")
    decision_path = _owned_outputs_path(project_runtime, record.decision_locator or "")
    envelope = DurableToolDecisionEnvelope.model_validate_json(_read_regular(decision_path))
    if (
        envelope.envelope_sha256 != record.decision_envelope_sha256
        or envelope.payload != record.decision.model_dump(mode="json", exclude_computed_fields=True)
        or record.decision.workflow_request_fingerprint != input_record.workflow_request.fingerprint
    ):
        raise ValueError("Tool Intelligence durable decision binding drift")
    model_runtime = ModelNodeRuntime(project_runtime, node_types=node_types)
    model_verification = model_runtime.verify(project_id=project_id, run_id=run_id)
    if model_verification.pending_count:
        raise ValueError("Tool Intelligence model ledger contains incomplete attempts")
    entry = model_runtime.entry(
        project_id=project_id,
        run_id=run_id,
        invocation_id=record.decision.model_invocation_id,
    )
    if (
        entry.entry_sha256 != record.decision.model_ledger_entry_sha256
        or entry.outcome != record.decision.model_outcome
        or entry.request_fingerprint != record.decision.model_request_fingerprint
    ):
        raise ValueError("Tool Intelligence decision differs from its model ledger")
    tool_verification = DurableToolExecutionRuntime(
        project_runtime,
        executor_factory=lambda: _unreachable_executor(),
    ).verify(project_id=project_id, run_id=run_id)
    if tool_verification.pending_attempt_count or tool_verification.incomplete_lease_count:
        raise ValueError("Tool Intelligence tool ledger is not closed")
    if tool_verification.decision_count < 1:
        raise ValueError("Tool Intelligence durable decision is absent")
    return record


def verify_full_workflow_tool_intelligence_input(
    loaded: LoadedFullWorkflowToolIntelligence,
    *,
    project_runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
    run_root: Path,
    predecessor_state_path: Path,
    state_path: Path,
    input_path: Path,
) -> FullWorkflowToolIntelligenceInputRecord:
    """Verify the pre-provider Tool Intelligence checkpoint without executing it."""

    return _load_and_verify_input(
        loaded,
        project_runtime=project_runtime,
        project_id=project_id,
        run_id=run_id,
        run_root=run_root,
        predecessor_state_path=predecessor_state_path,
        state_path=state_path,
        input_path=input_path,
    )


def _prepare_input_record(
    loaded: LoadedFullWorkflowToolIntelligence,
    *,
    project_runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
    expected_project_revision: int,
    run_root: Path,
    predecessor_state_path: Path,
    state_path: Path,
    evidence_summary_path: Path,
    input_path: Path,
    binding_path: Path,
    seed: int,
) -> FullWorkflowToolIntelligenceInputRecord:
    if input_path.exists():
        return _load_and_verify_input(
            loaded,
            project_runtime=project_runtime,
            project_id=project_id,
            run_id=run_id,
            run_root=run_root,
            predecessor_state_path=predecessor_state_path,
            state_path=state_path,
            input_path=input_path,
        )
    snapshot = project_runtime.open(project_id)
    if snapshot.revision != expected_project_revision:
        raise ValueError("Tool Intelligence project revision changed before checkpointing")
    state_raw = _read_regular(state_path)
    state = ResearchState.model_validate_json(state_raw)
    if state.project_id != project_id:
        raise ValueError("Tool Intelligence state belongs to another project")
    state_sha256 = hashlib.sha256(state_raw).hexdigest()
    state_snapshot = snapshot_id(state)
    summary_raw = _read_regular(evidence_summary_path)
    predecessor_raw = _read_regular(predecessor_state_path)
    matched_claim_ids = tuple(
        sorted(
            claim.claim_id
            for claim in state.claims
            if claim.status in loaded.config.trigger_claim_statuses
        )
    )
    binding = _materialize_binding(
        loaded,
        project_id=project_id,
        run_id=run_id,
        project_revision=expected_project_revision,
        run_root=run_root,
        state=state,
        state_locator=_owned_locator(run_root, state_path),
        state_sha256=state_sha256,
        state_snapshot=state_snapshot,
    )
    _write_model_exact(binding_path, binding)
    binding_raw = _read_regular(binding_path)
    load_project_tool_handlers(
        project_runtime,
        binding,
        loaded.config.controlled_tool_profile,
    )
    workflow_request = (
        _workflow_request(
            loaded,
            project_runtime=project_runtime,
            project_id=project_id,
            run_id=run_id,
            project_revision=expected_project_revision,
            state=state,
            state_snapshot=state_snapshot,
            matched_claim_ids=matched_claim_ids,
            seed=seed,
        )
        if matched_claim_ids
        else None
    )
    record = FullWorkflowToolIntelligenceInputRecord.create(
        hook_id=loaded.config.hook_id,
        project_id=project_id,
        run_id=run_id,
        project_revision=expected_project_revision,
        predecessor_state_locator=_owned_locator(run_root, predecessor_state_path),
        predecessor_state_sha256=hashlib.sha256(predecessor_raw).hexdigest(),
        state_locator=_owned_locator(run_root, state_path),
        state_sha256=state_sha256,
        state_snapshot_id=state_snapshot,
        state_revision=state.revision,
        evidence_summary_locator=_owned_locator(run_root, evidence_summary_path),
        evidence_summary_sha256=hashlib.sha256(summary_raw).hexdigest(),
        binding_locator=_owned_locator(run_root, binding_path),
        binding_sha256=hashlib.sha256(binding_raw).hexdigest(),
        binding_fingerprint=binding.fingerprint,
        config_binding_sha256=loaded.fingerprint,
        profile_fingerprint=loaded.profile.fingerprint,
        policy_fingerprint=loaded.config.policy.fingerprint,
        controlled_tool_profile_fingerprint=(loaded.config.controlled_tool_profile.fingerprint),
        matched_claim_ids=matched_claim_ids,
        triggered=bool(matched_claim_ids),
        workflow_request=workflow_request,
    )
    _write_model_exact(input_path, record)
    return record


def _load_and_verify_input(
    loaded: LoadedFullWorkflowToolIntelligence,
    *,
    project_runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
    run_root: Path,
    predecessor_state_path: Path,
    state_path: Path,
    input_path: Path,
) -> FullWorkflowToolIntelligenceInputRecord:
    try:
        record = FullWorkflowToolIntelligenceInputRecord.model_validate_json(
            _read_regular(input_path)
        )
    except ValueError as exc:
        raise ValueError("invalid Full Workflow Tool Intelligence input") from exc
    if (
        (record.project_id, record.run_id, record.hook_id)
        != (project_id, run_id, loaded.config.hook_id)
        or record.config_binding_sha256 != loaded.fingerprint
        or record.profile_fingerprint != loaded.profile.fingerprint
        or record.policy_fingerprint != loaded.config.policy.fingerprint
        or record.controlled_tool_profile_fingerprint
        != loaded.config.controlled_tool_profile.fingerprint
    ):
        raise ValueError("Full Workflow Tool Intelligence input configuration drift")
    state_raw = _read_regular(state_path)
    predecessor_raw = _read_regular(predecessor_state_path)
    state = ResearchState.model_validate_json(state_raw)
    if (
        state.project_id != project_id
        or record.predecessor_state_locator != _owned_locator(run_root, predecessor_state_path)
        or record.predecessor_state_sha256 != hashlib.sha256(predecessor_raw).hexdigest()
        or record.state_locator != _owned_locator(run_root, state_path)
        or record.state_sha256 != hashlib.sha256(state_raw).hexdigest()
        or record.state_snapshot_id != snapshot_id(state)
        or record.state_revision != state.revision
    ):
        raise ValueError("Full Workflow Tool Intelligence input state drift")
    summary_path = _owned_run_path(run_root, record.evidence_summary_locator)
    if hashlib.sha256(_read_regular(summary_path)).hexdigest() != record.evidence_summary_sha256:
        raise ValueError("Tool Intelligence evidence summary drift")
    binding_path = _owned_run_path(run_root, record.binding_locator)
    binding_raw = _read_regular(binding_path)
    if hashlib.sha256(binding_raw).hexdigest() != record.binding_sha256:
        raise ValueError("Tool Intelligence binding file drift")
    binding = ProjectToolBindingSet.model_validate_json(binding_raw)
    if binding.fingerprint != record.binding_fingerprint:
        raise ValueError("Tool Intelligence binding fingerprint drift")
    _verify_binding_sources(run_root, binding)
    current_revision = project_runtime.open(project_id).revision
    if current_revision < record.project_revision:
        raise ValueError("Tool Intelligence input references a future project revision")
    return record


def _materialize_binding(
    loaded: LoadedFullWorkflowToolIntelligence,
    *,
    project_id: str,
    run_id: str,
    project_revision: int,
    run_root: Path,
    state: ResearchState,
    state_locator: str,
    state_sha256: str,
    state_snapshot: str,
) -> ProjectToolBindingSet:
    evidence_source = None
    knowledge_bindings: list[KnowledgeLibraryBinding] = []
    for permission in loaded.config.controlled_tool_profile.permissions:
        if isinstance(permission, EvidenceInspectPermission):
            by_id = {item.evidence_id: item for item in state.evidence_graph.items}
            missing = set(permission.allowed_evidence_ids) - set(by_id)
            if missing:
                raise ValueError(
                    f"Tool Intelligence evidence IDs are absent from state: {sorted(missing)}"
                )
            records = tuple(
                ProjectEvidenceRecord(
                    evidence=EvidenceItem.model_validate(by_id[evidence_id].model_dump()),
                    provenance={
                        "source": "ResearchState.evidence_graph",
                        "state_locator": state_locator,
                        "state_sha256": state_sha256,
                        "state_snapshot_id": state_snapshot,
                    },
                )
                for evidence_id in permission.allowed_evidence_ids
            )
            raw = _jsonl(records)
            path = run_root / "stages/evidence/tool_intelligence_sources/evidence.jsonl"
            _write_bytes_exact(path, raw)
            evidence_source = ContentAddressedRunFile(
                locator=_owned_locator(run_root, path),
                sha256=hashlib.sha256(raw).hexdigest(),
                max_bytes=max(1, len(raw)),
            )
        elif isinstance(permission, KnowledgeQueryPermission):
            source = run_root / "native_execution/context/libraries/knowledge/records.jsonl"
            raw = _read_regular(source)
            knowledge_bindings.append(
                KnowledgeLibraryBinding(
                    library_id=permission.allowed_library_ids[0],
                    source=ContentAddressedRunFile(
                        locator=_owned_locator(run_root, source),
                        sha256=hashlib.sha256(raw).hexdigest(),
                        max_bytes=max(1, len(raw)),
                    ),
                )
            )
    return ProjectToolBindingSet(
        binding_id=loaded.config.hook_id,
        project_id=project_id,
        run_id=run_id,
        project_revision=project_revision,
        knowledge_libraries=tuple(knowledge_bindings),
        evidence_source=evidence_source,
    )


def _workflow_request(
    loaded: LoadedFullWorkflowToolIntelligence,
    *,
    project_runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
    project_revision: int,
    state: ResearchState,
    state_snapshot: str,
    matched_claim_ids: tuple[str, ...],
    seed: int,
) -> ToolHotspotWorkflowRequest:
    controlled = loaded.config.controlled_tool_profile
    library_ids: list[str] = []
    evidence_ids: list[str] = []
    for permission in controlled.permissions:
        if isinstance(permission, KnowledgeQueryPermission):
            library_ids.extend(permission.allowed_library_ids)
        elif isinstance(permission, EvidenceInspectPermission):
            evidence_ids.extend(permission.allowed_evidence_ids)
    scope = ToolScopeProjection(
        project_id=project_id,
        state_snapshot_id=state_snapshot,
        library_ids=tuple(library_ids),
        evidence_ids=tuple(evidence_ids),
    )
    projection = ImmutableStateProjection(
        project_id=project_id,
        state_snapshot_id=state_snapshot,
        state_revision=state.revision,
        stage=state.current_stage.value,
        claim_ids=tuple(sorted(item.claim_id for item in state.claims)),
        evidence_ids=tuple(evidence_ids),
        metadata={
            "hook_id": loaded.config.hook_id,
            "matched_claim_ids": list(matched_claim_ids),
            "proposal_only": True,
        },
    )
    signal = DeterministicSemanticHotspotSignal(
        signal_id=f"{loaded.config.hook_id}-trigger",
        hotspot_kind=loaded.config.hotspot_kind,
        semantic_gap=loaded.config.semantic_gap,
        objective=loaded.config.objective,
        candidate_tool_names=loaded.config.candidate_tool_names,
        evidence_ids=tuple(evidence_ids),
        reason_codes=loaded.config.reason_codes,
    )
    hotspot = SemanticHotspotDetector(project_runtime).detect(
        project_id=project_id,
        state_projection=projection,
        controlled_profile=controlled,
        signal=signal,
    )
    if hotspot.project_revision != project_revision:
        raise ValueError("Tool Intelligence hotspot observed another project revision")
    invocation_id = f"{loaded.config.hook_id}-p{project_revision}-s{state.revision}"
    node_input = ToolPlanInput(
        objective=loaded.config.objective,
        scope=scope,
        tool_profile=controlled,
    )
    model_request = ModelNodeFacadeRequest(
        project_id=project_id,
        run_id=run_id,
        invocation_id=invocation_id,
        request_id=invocation_id,
        expected_project_revision=project_revision,
        node_name="tool-plan",
        node_input=node_input.model_dump(mode="json"),
        state_projection=projection,
        trigger=ModelNodeTrigger(
            trigger_id=f"{loaded.config.hook_id}-model",
            reason=(
                "Deterministic claim-status policy found an unresolved evidence-stage hotspot."
            ),
        ),
        profile=loaded.profile,
        policy=loaded.config.policy,
        backend_mode=loaded.config.backend.mode,
        seed=seed,
    )
    return ToolHotspotWorkflowRequest(
        workflow_id=loaded.config.hook_id,
        project_id=project_id,
        run_id=run_id,
        hotspot=hotspot,
        model_request=model_request,
        budget=loaded.config.budget,
    )


def _verify_binding_sources(run_root: Path, binding: ProjectToolBindingSet) -> None:
    sources = [item.source for item in binding.knowledge_libraries]
    if binding.evidence_source is not None:
        sources.append(binding.evidence_source)
    if binding.run_metrics_source is not None:
        sources.append(binding.run_metrics_source)
    for source in sources:
        path = _owned_run_path(run_root, source.locator)
        try:
            raw = _read_regular(path, max_bytes=source.max_bytes)
        except ValueError as exc:
            raise ValueError("Tool Intelligence bound source is unsafe or oversized") from exc
        if hashlib.sha256(raw).hexdigest() != source.sha256:
            raise ValueError("Tool Intelligence bound source hash drift")


def _jsonl(records: tuple[ProjectEvidenceRecord, ...]) -> bytes:
    return b"".join(
        json.dumps(
            item.model_dump(mode="json", exclude_computed_fields=True),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
        for item in records
    )


def _write_model_exact(path: Path, model: BaseModel) -> None:
    raw = (
        json.dumps(
            model.model_dump(mode="json", exclude_computed_fields=True),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode()
    _write_bytes_exact(path, raw)


def _write_bytes_exact(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Tool Intelligence artifact cannot be a symlink")
    if path.exists():
        if _read_regular(path) != raw:
            raise ValueError(f"Tool Intelligence artifact identity drift: {path.name}")
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            if _read_regular(path) != raw:
                raise ValueError(f"Tool Intelligence publication conflict: {path.name}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _read_regular(path: Path, *, max_bytes: int = 10_000_000) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"Tool Intelligence path is not a safe file: {path}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            raise ValueError("Tool Intelligence file is unsafe or oversized")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(max_bytes + 1)
    finally:
        os.close(descriptor)
    if len(raw) > max_bytes:
        raise ValueError("Tool Intelligence file exceeds its byte ceiling")
    return raw


def _owned_locator(run_root: Path, path: Path) -> str:
    root = run_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("Tool Intelligence artifact escapes its owning run") from exc


def _owned_run_path(run_root: Path, locator: str) -> Path:
    root = run_root.resolve(strict=True)
    candidate = run_root / locator
    if candidate.is_symlink():
        raise ValueError("Tool Intelligence locator resolves through a symlink")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Tool Intelligence locator escapes its owning run") from exc
    return resolved


def _owned_outputs_path(runtime: ProjectRuntime, locator: str) -> Path:
    root = runtime.outputs_root.resolve(strict=True)
    candidate = runtime.outputs_root / locator
    if candidate.is_symlink():
        raise ValueError("Tool Intelligence decision locator is a symlink")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Tool Intelligence decision escapes outputs") from exc
    return resolved


def _unreachable_executor() -> ControlledToolExecutor:
    raise AssertionError("verification must not construct a tool executor")


def _reject_secret_fields(value: object) -> None:
    if isinstance(value, dict):
        forbidden = {"api_key", "authorization", "bearer_token", "password", "secret"}
        if any(str(key).casefold().replace("-", "_") in forbidden for key in value):
            raise ValueError("credential fields are forbidden")
        for nested in value.values():
            _reject_secret_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_fields(nested)


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


__all__ = [
    "FullWorkflowToolIntelligenceConfig",
    "FullWorkflowToolIntelligenceInputRecord",
    "FullWorkflowToolIntelligenceRecord",
    "LoadedFullWorkflowToolIntelligence",
    "execute_full_workflow_tool_intelligence",
    "load_full_workflow_tool_intelligence",
    "verify_full_workflow_tool_intelligence",
    "verify_full_workflow_tool_intelligence_input",
]

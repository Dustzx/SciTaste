"""Offline, proposal-only model advice bound to a full-workflow evidence stage."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.evidence.workflow import EvidenceWorkflowScenario
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
    ModelNodeRuntime,
    ModelNodeTrigger,
    RuntimeBackendMode,
    RuntimeInvocationReceipt,
    RuntimeOutcome,
)
from scitaste.model_nodes.runtime_config import ScriptedRuntimeBackend
from scitaste.project import ProjectRuntime
from scitaste.project.models import content_sha256
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState


class WorkflowAdvisoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class FullWorkflowModelAdvisoryConfig(WorkflowAdvisoryModel):
    """One deliberately narrow, network-free evidence-stage model hook."""

    schema_version: Literal["1.0"] = "1.0"
    hook_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    node_name: Literal["interpretation-threat"] = "interpretation-threat"
    trigger_reason: str = Field(min_length=1)
    profile_set: Path
    profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    policy: NodePolicy
    backend: ScriptedRuntimeBackend
    advisory_only: Literal[True] = True
    executable: Literal[False] = False
    effectiveness_claim: Literal[False] = False

    @model_validator(mode="after")
    def authority_is_narrow_and_offline(self) -> FullWorkflowModelAdvisoryConfig:
        if not self.policy.enabled:
            raise ValueError("full-workflow model advisory policy must be enabled")
        if self.policy.allowed_node_names != [self.node_name]:
            raise ValueError("full-workflow model advisory policy must allow only its node")
        if self.policy.allowed_tool_names or self.backend.reply.tool_calls:
            raise ValueError("full-workflow model advisories cannot expose tool calls")
        if self.backend.reply.usage.cost_usd != 0:
            raise ValueError("offline scripted advisory cost must be exactly zero")
        observed = (self.backend.provider, self.backend.model)
        expected = (self.policy.expected_backend, self.policy.expected_model)
        if observed != expected:
            raise ValueError("advisory backend identity differs from the policy")
        response_identity = (
            self.backend.reply.response_backend or self.backend.provider,
            self.backend.reply.response_model or self.backend.model,
        )
        if response_identity != expected:
            raise ValueError("scripted response identity differs from the policy")
        return self


@dataclass(frozen=True)
class LoadedFullWorkflowModelAdvisory:
    source_path: Path
    source_sha256: str
    profile_set_sha256: str
    config: FullWorkflowModelAdvisoryConfig
    profile: ModelNodeProfile

    @property
    def fingerprint(self) -> str:
        return content_sha256(
            {
                "source_sha256": self.source_sha256,
                "profile_set_sha256": self.profile_set_sha256,
                "profile_fingerprint": self.profile.fingerprint,
            }
        )


class FullWorkflowModelAdvisoryRecord(WorkflowAdvisoryModel):
    """Self-hashed bridge evidence; the underlying ledger remains authoritative."""

    schema_version: Literal["1.0"] = "1.0"
    hook_id: str
    node_name: Literal["interpretation-threat"]
    project_id: str
    run_id: str
    project_revision: int = Field(ge=0)
    state_locator: str = Field(min_length=1)
    state_snapshot_id: str = Field(min_length=1)
    state_revision: int = Field(ge=0)
    input_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt: RuntimeInvocationReceipt
    proposal: dict[str, JsonValue] | None = None
    proposal_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    state_mutated: Literal[False] = False
    advisory_only: Literal[True] = True
    executable: Literal[False] = False
    effectiveness_claim: Literal[False] = False
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: object) -> FullWorkflowModelAdvisoryRecord:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def evidence_is_closed(self) -> FullWorkflowModelAdvisoryRecord:
        if self.input_state_sha256 != self.output_state_sha256:
            raise ValueError("model advisory mutated its input state")
        if (self.proposal is None) != (self.proposal_sha256 is None):
            raise ValueError("proposal and proposal hash must be present together")
        if self.proposal is not None and content_sha256(self.proposal) != self.proposal_sha256:
            raise ValueError("proposal hash mismatch")
        if self.receipt.outcome is RuntimeOutcome.ACCEPTED and self.proposal is None:
            raise ValueError("accepted advisory receipt requires a trusted proposal")
        if self.receipt.outcome is not RuntimeOutcome.ACCEPTED and self.proposal is not None:
            raise ValueError("non-accepted advisory receipt cannot expose a trusted proposal")
        if (self.receipt.project_id, self.receipt.run_id) != (self.project_id, self.run_id):
            raise ValueError("advisory receipt belongs to another project run")
        if self.receipt.entry_sha256 != self.receipt.totals.chain_head_sha256:
            raise ValueError("advisory receipt is not the recorded ledger head")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("model advisory record hash mismatch")
        return self


def load_full_workflow_model_advisory(
    path: str | Path,
) -> LoadedFullWorkflowModelAdvisory:
    """Load and content-bind an offline full-workflow model hook."""

    source = Path(path).expanduser().resolve(strict=True)
    raw = source.read_bytes()
    try:
        payload = yaml.load(raw, Loader=_UniqueKeyLoader)
        _reject_secret_fields(payload)
        if not isinstance(payload, dict):
            raise ValueError("advisory config root must be a mapping")
        profile_set = Path(payload["profile_set"])
        if not profile_set.is_absolute():
            profile_set = (source.parent / profile_set).resolve(strict=True)
        payload["profile_set"] = profile_set
        config = FullWorkflowModelAdvisoryConfig.model_validate(payload)
        profiles = load_model_node_profile_set(profile_set)
        profile = profiles.profiles[config.profile_id]
        validate_profile_binding(profile, config.policy, node_name=config.node_name)
    except (KeyError, TypeError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("invalid full-workflow model advisory configuration") from exc
    if profile.live_execution_permitted or profiles.profile_set.live_enabled:
        raise ValueError("full-workflow advisory profile set must remain offline")
    if profile.unrestricted_code_generation:
        raise ValueError("full-workflow advisory cannot generate unrestricted code")
    if profile.admission.allowed_tool_names or profile.admission.max_tool_call_proposals:
        raise ValueError("full-workflow advisory profile cannot propose tools")
    return LoadedFullWorkflowModelAdvisory(
        source_path=source,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        profile_set_sha256=profiles.source_sha256,
        config=config,
        profile=profile,
    )


def execute_full_workflow_model_advisory(
    loaded: LoadedFullWorkflowModelAdvisory,
    *,
    project_runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
    expected_project_revision: int,
    evidence_scenario: EvidenceWorkflowScenario,
    state_path: Path,
    record_path: Path,
    seed: int,
) -> FullWorkflowModelAdvisoryRecord:
    """Run one bounded interpretation hook without changing ``ResearchState``."""

    if record_path.exists():
        raise FileExistsError(record_path)
    if state_path.is_symlink() or not state_path.is_file():
        raise ValueError("model advisory state input must be a regular file")
    before = state_path.read_bytes()
    before_sha256 = hashlib.sha256(before).hexdigest()
    state = ResearchState.model_validate_json(before)
    if state.project_id != project_id or evidence_scenario.project_id != project_id:
        raise ValueError("model advisory inputs belong to another project")
    invocation_id = f"{loaded.config.hook_id}-p{expected_project_revision}-s{state.revision}"
    projection = ImmutableStateProjection(
        project_id=project_id,
        state_snapshot_id=snapshot_id(state),
        state_revision=state.revision,
        stage=state.current_stage.value,
        claim_ids=tuple(sorted(item.claim_id for item in state.claims)),
        evidence_ids=tuple(sorted(item.evidence_id for item in state.evidence_graph.items)),
        metadata={
            "hook_id": loaded.config.hook_id,
            "input_state_sha256": before_sha256,
            "proposal_only": True,
        },
    )
    request = ModelNodeFacadeRequest(
        project_id=project_id,
        run_id=run_id,
        invocation_id=invocation_id,
        expected_project_revision=expected_project_revision,
        node_name=loaded.config.node_name,
        node_input={
            "result": evidence_scenario.result.model_dump(mode="json"),
            "interpretation_context": evidence_scenario.interpretation.model_dump(mode="json"),
        },
        state_projection=projection,
        trigger=ModelNodeTrigger(
            trigger_id=loaded.config.hook_id,
            reason=loaded.config.trigger_reason,
        ),
        profile=loaded.profile,
        policy=loaded.config.policy,
        backend_mode=RuntimeBackendMode.SCRIPTED,
        seed=seed,
    )
    result = ModelNodeFacade(ModelNodeRuntime(project_runtime)).execute(
        request,
        backend=loaded.config.backend.build(invocation_id),
    )
    after_sha256 = hashlib.sha256(state_path.read_bytes()).hexdigest()
    proposal = (
        result.result.proposal.model_dump(mode="json")
        if result.result is not None and result.result.proposal is not None
        else None
    )
    record = FullWorkflowModelAdvisoryRecord.create(
        hook_id=loaded.config.hook_id,
        node_name=loaded.config.node_name,
        project_id=project_id,
        run_id=run_id,
        project_revision=expected_project_revision,
        state_locator=state_path.relative_to(record_path.parents[2]).as_posix(),
        state_snapshot_id=projection.state_snapshot_id,
        state_revision=state.revision,
        input_state_sha256=before_sha256,
        output_state_sha256=after_sha256,
        config_binding_sha256=loaded.fingerprint,
        source_config_sha256=loaded.source_sha256,
        profile_set_sha256=loaded.profile_set_sha256,
        profile_fingerprint=loaded.profile.fingerprint,
        policy_fingerprint=loaded.config.policy.fingerprint,
        receipt=result.receipt,
        proposal=proposal,
        proposal_sha256=content_sha256(proposal) if proposal is not None else None,
    )
    _write_json(record_path, record.model_dump(mode="json"))
    return record


def verify_full_workflow_model_advisory(
    loaded: LoadedFullWorkflowModelAdvisory,
    *,
    project_runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
    state_path: Path,
    record_path: Path,
) -> FullWorkflowModelAdvisoryRecord:
    """Verify the bridge record, immutable state binding, and complete ledger head."""

    if record_path.is_symlink() or not record_path.is_file():
        raise ValueError("model advisory record must be a regular file")
    if state_path.is_symlink() or not state_path.is_file():
        raise ValueError("model advisory state must be a regular file")
    try:
        record = FullWorkflowModelAdvisoryRecord.model_validate_json(
            record_path.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        raise ValueError("invalid full-workflow model advisory record") from exc
    if (record.project_id, record.run_id) != (project_id, run_id):
        raise ValueError("model advisory record belongs to another project run")
    expected_binding = (
        loaded.fingerprint,
        loaded.source_sha256,
        loaded.profile_set_sha256,
        loaded.profile.fingerprint,
        loaded.config.policy.fingerprint,
    )
    observed_binding = (
        record.config_binding_sha256,
        record.source_config_sha256,
        record.profile_set_sha256,
        record.profile_fingerprint,
        record.policy_fingerprint,
    )
    if observed_binding != expected_binding:
        raise ValueError("model advisory configuration binding drift")
    state_raw = state_path.read_bytes()
    state_sha256 = hashlib.sha256(state_raw).hexdigest()
    state = ResearchState.model_validate_json(state_raw)
    if (
        record.state_locator != state_path.relative_to(record_path.parents[2]).as_posix()
        or record.state_snapshot_id != snapshot_id(state)
        or record.state_revision != state.revision
        or record.input_state_sha256 != state_sha256
        or record.output_state_sha256 != state_sha256
    ):
        raise ValueError("model advisory state binding drift")
    verification = ModelNodeRuntime(project_runtime).verify(
        project_id=project_id,
        run_id=run_id,
    )
    if verification.pending_count:
        raise ValueError("model advisory ledger contains incomplete attempts")
    if verification.ledger_locator != record.receipt.ledger_locator:
        raise ValueError("model advisory ledger locator drift")
    if verification.totals != record.receipt.totals:
        raise ValueError("model advisory ledger totals drift")
    return record


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


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
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


__all__ = [
    "FullWorkflowModelAdvisoryConfig",
    "FullWorkflowModelAdvisoryRecord",
    "LoadedFullWorkflowModelAdvisory",
    "execute_full_workflow_model_advisory",
    "load_full_workflow_model_advisory",
    "verify_full_workflow_model_advisory",
]

"""Provider-backed native-source proposals with deterministic admission handoff."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scitaste.executor.native_code import (
    NativeCodeAdmissionPolicy,
    NativeCodeExperimentProposal,
    NativeCodeInspection,
    NativeCodeProducer,
    NativeCodeProposalConfig,
    NativeCodeViolation,
    inspect_native_code_proposal,
)
from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResult
from scitaste.model_nodes.nodes import ModelNode
from scitaste.model_nodes.profiles import (
    ModelNodeProfile,
    load_model_node_profile_set,
    validate_profile_binding,
)
from scitaste.model_nodes.runtime import (
    ModelNodeRegistration,
    ModelNodeRuntime,
    ModelNodeTrigger,
    RuntimeInvocationReceipt,
    RuntimeOutcome,
    RuntimeVerification,
)
from scitaste.model_nodes.runtime_config import (
    LiveRuntimeBackend,
    RuntimeBackendBinding,
    ScriptedRuntimeBackend,
)
from scitaste.project import ProjectRuntime
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_GENERATION_CONTRACT_VERSION = "1.0"
_REPAIR_CONTRACT_VERSION = "1.0"
_NODE_NAME = "native-code-proposal"
_REPAIR_NODE_NAME = "native-code-repair"
_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONFIG_BYTES = 1_048_576
_MAX_GENERATED_SOURCE_BYTES = 262_144
_MEASUREMENT_MARKER = "SCITASTE_MEASUREMENTS_JSON="


class NativeCodeGenerationError(ValueError):
    """Raised when generation evidence cannot produce an admitted source proposal."""


class GenerationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class NativeCodeGenerationInput(GenerationModel):
    """Trusted source-generation brief; authority-bearing fields are not model outputs."""

    schema_version: Literal["1.0"] = "1.0"
    objective: str = Field(min_length=1, max_length=12_000)
    constraints: tuple[str, ...] = Field(min_length=1, max_length=64)
    expected_metrics: tuple[str, ...] = Field(min_length=1, max_length=64)
    experiment: NativeCodeExperimentProposal
    admission_policy: NativeCodeAdmissionPolicy
    output_contract: Literal["one-utf8-python-module-emitting-scitaste-measurements-json"] = (
        "one-utf8-python-module-emitting-scitaste-measurements-json"
    )

    @field_validator("constraints", "expected_metrics")
    @classmethod
    def tuple_values_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("generation input tuple values must be unique")
        return value

    @model_validator(mode="after")
    def metric_contract_is_closed(self) -> NativeCodeGenerationInput:
        if self.experiment.primary_metric not in self.expected_metrics:
            raise ValueError("generation primary metric must appear in expected_metrics")
        return self


class NativeCodeGenerationOutput(GenerationModel):
    """Proposal-only model output; it cannot select policy, paths, limits, or actions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    source_code: str = Field(min_length=1, max_length=_MAX_GENERATED_SOURCE_BYTES)
    rationale: str = Field(min_length=1, max_length=4_000)
    assumptions: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("assumptions")
    @classmethod
    def assumptions_are_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("generation assumptions must be unique")
        if any(not item or len(item) > 1_000 for item in value):
            raise ValueError("generation assumptions must be non-empty and bounded")
        return value


class NativeCodeGenerationNode(ModelNode[NativeCodeGenerationInput, NativeCodeGenerationOutput]):
    """Generate one bounded candidate without granting execution authority."""

    node_name = _NODE_NAME
    prompt_version = "native-code-proposal-v1"
    system_instruction = (
        "Produce exactly one JSON object matching the supplied output schema. The source_code "
        "field must contain a complete UTF-8 Python module, without Markdown fences. The module "
        "must use only the trusted admission_policy imports, perform a deterministic bounded CPU "
        "experiment, and print exactly one line beginning SCITASTE_MEASUREMENTS_JSON= whose JSON "
        "payload reports every expected metric for explicit replicates. Do not propose commands, "
        "paths, tools, dependencies, policy changes, resource limits, experiment identity, metric "
        "identity, or execution. This response is only an untrusted source proposal and will be "
        "subjected to deterministic static admission and an isolated runtime."
    )
    input_model = NativeCodeGenerationInput
    output_model = NativeCodeGenerationOutput

    def _proposal_rejections(
        self,
        proposal: NativeCodeGenerationOutput,
        *,
        input_data: NativeCodeGenerationInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del context, policy
        source = proposal.source_code
        reasons: list[str] = []
        if "```" in source:
            reasons.append("source_code contains a Markdown fence")
        if "\x00" in source:
            reasons.append("source_code contains a NUL byte")
        if len(source.encode("utf-8")) > input_data.admission_policy.max_source_bytes:
            reasons.append("source_code exceeds the trusted admission-policy byte limit")
        return reasons


class NativeCodeRuntimeFailure(GenerationModel):
    """Bounded diagnostic evidence from one failed isolated execution."""

    schema_version: Literal["1.0"] = "1.0"
    experiment_id: str = Field(pattern=_SAFE_ID)
    action_id: str = Field(min_length=1, max_length=1_000)
    result_id: str = Field(pattern=_SAFE_ID)
    execution_record_locator: str = Field(min_length=1, max_length=1_000)
    execution_record_sha256: str = Field(pattern=_SHA256)
    source_sha256: str = Field(pattern=_SHA256)
    failure_code: Literal[
        "nonzero-exit",
        "timeout",
        "measurement-contract",
    ]
    error_message: str = Field(min_length=1, max_length=4_000)
    stderr_sha256: str = Field(pattern=_SHA256)
    stderr_excerpt: str = Field(max_length=4_000)
    runtime_repairable: Literal[True] = True
    verification_route: Literal["direct_path", "owner_approval"]
    verification_reason_codes: tuple[str, ...] = Field(min_length=1, max_length=12)
    authorization_basis: Literal[
        "tool-intelligence-direct-path",
        "workflow-config-and-caller-opt-in",
    ]
    standalone_preflight_performed: Literal[False] = False

    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


class NativeCodeRepairInput(GenerationModel):
    """Hash-bound failed proposal and exact issues supplied to one repair call."""

    schema_version: Literal["1.0"] = "1.0"
    generation_input: NativeCodeGenerationInput
    rejected_output: NativeCodeGenerationOutput
    rejected_binding_sha256: str = Field(pattern=_SHA256)
    rejected_source_sha256: str = Field(pattern=_SHA256)
    trigger: Literal["static-admission", "isolated-runtime"] = "static-admission"
    validation_issues: tuple[NativeCodeViolation, ...] = Field(max_length=32)
    runtime_failure: NativeCodeRuntimeFailure | None = None
    repair_contract: Literal[
        "replace-source-only-then-repeat-identical-deterministic-admission",
        "replace-source-only-then-readmit-and-rerun-identical-isolated-experiment",
    ] = "replace-source-only-then-repeat-identical-deterministic-admission"

    @model_validator(mode="after")
    def rejected_source_is_hash_bound(self) -> NativeCodeRepairInput:
        observed = hashlib.sha256(self.rejected_output.source_code.encode("utf-8")).hexdigest()
        if observed != self.rejected_source_sha256:
            raise ValueError("rejected source hash does not match rejected_output")
        runtime = self.trigger == "isolated-runtime"
        if runtime != (self.runtime_failure is not None):
            raise ValueError("native repair trigger differs from its runtime evidence")
        if not runtime and not self.validation_issues:
            raise ValueError("static native repair requires deterministic validation issues")
        expected_contract = (
            "replace-source-only-then-readmit-and-rerun-identical-isolated-experiment"
            if runtime
            else "replace-source-only-then-repeat-identical-deterministic-admission"
        )
        if self.repair_contract != expected_contract:
            raise ValueError("native repair contract differs from its trigger")
        return self


class NativeCodeRepairOutput(GenerationModel):
    """One replacement proposal; deterministic admission remains the authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    source_code: str = Field(min_length=1, max_length=_MAX_GENERATED_SOURCE_BYTES)
    rationale: str = Field(min_length=1, max_length=4_000)
    assumptions: tuple[str, ...] = Field(default=(), max_length=32)
    change_summary: tuple[str, ...] = Field(min_length=1, max_length=32)
    repair_proposal_only: Literal[True] = True
    advisory_only: Literal[True] = True
    executable: Literal[False] = False

    @field_validator("assumptions", "change_summary")
    @classmethod
    def repair_text_is_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("repair tuple values must be unique")
        if any(not item or len(item) > 1_000 for item in value):
            raise ValueError("repair tuple values must be non-empty and bounded")
        return value


class NativeCodeRepairNode(ModelNode[NativeCodeRepairInput, NativeCodeRepairOutput]):
    """Propose one source replacement without changing trusted experiment authority."""

    node_name = _REPAIR_NODE_NAME
    prompt_version = "native-code-repair-v1"
    system_instruction = (
        "Return exactly one JSON object matching the supplied output schema. Repair only the "
        "source_code in response to the deterministic validation_issues or the exact bounded "
        "isolated-runtime failure. Preserve the supplied "
        "experiment identity, metrics, policy, limits, and output contract. The source must be a "
        "complete UTF-8 Python module without Markdown fences and must print exactly one "
        "SCITASTE_MEASUREMENTS_JSON line. Do not propose commands, paths, dependencies, tools, "
        "policy changes, retries, execution, or claims of acceptance. This is a single untrusted "
        "replacement proposal that will face the identical deterministic admission policy."
    )
    input_model = NativeCodeRepairInput
    output_model = NativeCodeRepairOutput

    def _proposal_rejections(
        self,
        proposal: NativeCodeRepairOutput,
        *,
        input_data: NativeCodeRepairInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del context, policy
        source = proposal.source_code
        reasons: list[str] = []
        if "```" in source:
            reasons.append("source_code contains a Markdown fence")
        if "\x00" in source:
            reasons.append("source_code contains a NUL byte")
        if (
            len(source.encode("utf-8"))
            > input_data.generation_input.admission_policy.max_source_bytes
        ):
            reasons.append("source_code exceeds the trusted admission-policy byte limit")
        return reasons


class NativeCodeGenerationConfig(GenerationModel):
    """Non-secret binding for one project-controlled source generation request."""

    schema_version: Literal["1.0"] = "1.0"
    generation_id: str = Field(pattern=_SAFE_ID)
    proposal_id: str = Field(pattern=_SAFE_ID)
    trigger_reason: str = Field(min_length=1, max_length=2_000)
    objective: str = Field(min_length=1, max_length=12_000)
    constraints: tuple[str, ...] = Field(min_length=1, max_length=64)
    expected_metrics: tuple[str, ...] = Field(min_length=1, max_length=64)
    experiment: NativeCodeExperimentProposal
    admission_policy: NativeCodeAdmissionPolicy = Field(default_factory=NativeCodeAdmissionPolicy)
    profile_set: Path
    profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    policy: NodePolicy
    backend: RuntimeBackendBinding
    live_enabled: bool = False
    proposal_only: Literal[True] = True
    deterministic_admission_required: Literal[True] = True
    runtime_isolation_required: Literal[True] = True
    effectiveness_claim: Literal[False] = False

    @field_validator("constraints", "expected_metrics")
    @classmethod
    def values_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("native code generation tuple values must be unique")
        return value

    @model_validator(mode="after")
    def authority_and_backend_are_closed(self) -> NativeCodeGenerationConfig:
        if self.experiment.primary_metric not in self.expected_metrics:
            raise ValueError("generation primary metric must appear in expected_metrics")
        if not self.policy.enabled or self.policy.allowed_node_names != [_NODE_NAME]:
            raise ValueError("generation policy must enable only native-code-proposal")
        if self.policy.allowed_tool_names or self.policy.allowed_action_types:
            raise ValueError("source generation cannot expose tools or action types")
        observed = (
            (self.backend.provider, self.backend.model)
            if isinstance(self.backend, ScriptedRuntimeBackend)
            else (self.backend.config.provider, self.backend.config.model)
        )
        expected = (self.policy.expected_backend, self.policy.expected_model)
        if observed != expected:
            raise ValueError("generation backend identity differs from the pinned policy")
        if isinstance(self.backend, ScriptedRuntimeBackend):
            if self.live_enabled:
                raise ValueError("scripted source generation cannot enable live execution")
            if self.backend.reply.tool_calls:
                raise ValueError("source generation cannot expose tool calls")
            if self.backend.reply.usage.cost_usd != 0:
                raise ValueError("scripted source generation cost must be exactly zero")
            response_identity = (
                self.backend.reply.response_backend or self.backend.provider,
                self.backend.reply.response_model or self.backend.model,
            )
            if response_identity != expected:
                raise ValueError("scripted generation response identity differs from policy")
        elif self.live_enabled != self.backend.config.live_enabled:
            raise ValueError("generation and backend live gates must agree")
        return self

    @property
    def node_input(self) -> NativeCodeGenerationInput:
        return NativeCodeGenerationInput(
            objective=self.objective,
            constraints=self.constraints,
            expected_metrics=self.expected_metrics,
            experiment=self.experiment,
            admission_policy=self.admission_policy,
        )


class NativeCodeRepairConfig(GenerationModel):
    """Non-secret binding for exactly one conditional repair proposal."""

    schema_version: Literal["1.0"] = "1.0"
    repair_id: str = Field(pattern=_SAFE_ID)
    generation_id: str = Field(pattern=_SAFE_ID)
    rejected_proposal_id: str = Field(pattern=_SAFE_ID)
    repaired_proposal_id: str = Field(pattern=_SAFE_ID)
    trigger_reason: str = Field(min_length=1, max_length=2_000)
    max_attempts: Literal[1] = 1
    profile_set: Path
    profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    policy: NodePolicy
    backend: RuntimeBackendBinding
    live_enabled: bool = False
    conditional_on_static_rejection: bool = True
    conditional_on_runtime_failure: bool = False
    repair_proposal_only: Literal[True] = True
    deterministic_readmission_required: Literal[True] = True
    runtime_isolation_required: Literal[True] = True
    effectiveness_claim: Literal[False] = False

    @model_validator(mode="after")
    def authority_and_backend_are_closed(self) -> NativeCodeRepairConfig:
        if self.conditional_on_static_rejection == self.conditional_on_runtime_failure:
            raise ValueError("native code repair must bind exactly one failure trigger")
        if self.rejected_proposal_id == self.repaired_proposal_id:
            raise ValueError("repaired proposal identity must differ from the rejected proposal")
        if not self.policy.enabled or self.policy.allowed_node_names != [_REPAIR_NODE_NAME]:
            raise ValueError("repair policy must enable only native-code-repair")
        if self.policy.allowed_tool_names or self.policy.allowed_action_types:
            raise ValueError("native code repair cannot expose tools or action types")
        observed = (
            (self.backend.provider, self.backend.model)
            if isinstance(self.backend, ScriptedRuntimeBackend)
            else (self.backend.config.provider, self.backend.config.model)
        )
        expected = (self.policy.expected_backend, self.policy.expected_model)
        if observed != expected:
            raise ValueError("repair backend identity differs from the pinned policy")
        if isinstance(self.backend, ScriptedRuntimeBackend):
            if self.live_enabled:
                raise ValueError("scripted native code repair cannot enable live execution")
            if self.backend.reply.tool_calls:
                raise ValueError("native code repair cannot expose tool calls")
            if self.backend.reply.usage.cost_usd != 0:
                raise ValueError("scripted native code repair cost must be exactly zero")
            response_identity = (
                self.backend.reply.response_backend or self.backend.provider,
                self.backend.reply.response_model or self.backend.model,
            )
            if response_identity != expected:
                raise ValueError("scripted repair response identity differs from policy")
        elif self.live_enabled != self.backend.config.live_enabled:
            raise ValueError("repair and backend live gates must agree")
        return self


@dataclass(frozen=True)
class LoadedNativeCodeGeneration:
    source_path: Path
    source_sha256: str
    profile_set_sha256: str
    config: NativeCodeGenerationConfig
    profile: ModelNodeProfile

    @property
    def fingerprint(self) -> str:
        return content_sha256(
            {
                "generation_contract_version": _GENERATION_CONTRACT_VERSION,
                "source_sha256": self.source_sha256,
                "profile_set_sha256": self.profile_set_sha256,
                "profile_fingerprint": self.profile.fingerprint,
            }
        )


@dataclass(frozen=True)
class LoadedNativeCodeRepair:
    source_path: Path
    source_sha256: str
    profile_set_sha256: str
    config: NativeCodeRepairConfig
    profile: ModelNodeProfile

    @property
    def fingerprint(self) -> str:
        return content_sha256(
            {
                "repair_contract_version": _REPAIR_CONTRACT_VERSION,
                "source_sha256": self.source_sha256,
                "profile_set_sha256": self.profile_set_sha256,
                "profile_fingerprint": self.profile.fingerprint,
            }
        )


class NativeCodeGenerationInputRecord(GenerationModel):
    """Pre-call checkpoint used to preserve one invocation across workflow recovery."""

    schema_version: Literal["1.0"] = "1.0"
    generation_id: str = Field(pattern=_SAFE_ID)
    project_id: str
    run_id: str = Field(pattern=_SAFE_ID)
    project_revision: int = Field(ge=0)
    invocation_id: str = Field(pattern=_SAFE_ID)
    workflow_config_sha256: str = Field(pattern=_SHA256)
    config_binding_sha256: str = Field(pattern=_SHA256)
    profile_fingerprint: str = Field(pattern=_SHA256)
    policy_fingerprint: str = Field(pattern=_SHA256)
    node_input: NativeCodeGenerationInput
    record_sha256: str = Field(pattern=_SHA256)

    @classmethod
    def create(cls, **values: object) -> NativeCodeGenerationInputRecord:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def evidence_is_closed(self) -> NativeCodeGenerationInputRecord:
        validate_project_id(self.project_id)
        validate_entry_id(self.run_id, field_name="run_id")
        expected_invocation = f"{self.generation_id}-p{self.project_revision}"
        if self.invocation_id != expected_invocation:
            raise ValueError("native code generation invocation identity drift")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("native code generation input record hash mismatch")
        return self


class NativeCodeGenerationRecord(GenerationModel):
    """Derived proposal bridge; the model-node ledger remains authoritative."""

    schema_version: Literal["1.0"] = "1.0"
    generation_id: str = Field(pattern=_SAFE_ID)
    proposal_id: str = Field(pattern=_SAFE_ID)
    project_id: str
    run_id: str = Field(pattern=_SAFE_ID)
    project_revision: int = Field(ge=0)
    invocation_id: str = Field(pattern=_SAFE_ID)
    config_binding_sha256: str = Field(pattern=_SHA256)
    input_record_sha256: str = Field(pattern=_SHA256)
    profile_fingerprint: str = Field(pattern=_SHA256)
    policy_fingerprint: str = Field(pattern=_SHA256)
    receipt: RuntimeInvocationReceipt
    request_sha256: str = Field(pattern=_SHA256)
    response_sha256: str = Field(pattern=_SHA256)
    generated_source_locator: str
    generated_source_sha256: str = Field(pattern=_SHA256)
    generated_source_bytes: int = Field(ge=1)
    proposal_config_locator: str
    proposal_config_sha256: str = Field(pattern=_SHA256)
    proposal_binding_sha256: str = Field(pattern=_SHA256)
    admission_decision: Literal["accepted", "rejected"]
    rationale_sha256: str = Field(pattern=_SHA256)
    assumptions_sha256: str = Field(pattern=_SHA256)
    proposal_only: Literal[True] = True
    executable: Literal[False] = False
    deterministic_admission_required: Literal[True] = True
    runtime_isolation_required: Literal[True] = True
    effectiveness_claim: Literal[False] = False
    record_sha256: str = Field(pattern=_SHA256)

    @classmethod
    def create(cls, **values: object) -> NativeCodeGenerationRecord:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def evidence_is_closed(self) -> NativeCodeGenerationRecord:
        if (self.receipt.project_id, self.receipt.run_id, self.receipt.invocation_id) != (
            self.project_id,
            self.run_id,
            self.invocation_id,
        ):
            raise ValueError("generation receipt belongs to another invocation")
        if self.receipt.outcome is not RuntimeOutcome.ACCEPTED:
            raise ValueError("generation record requires an accepted model proposal")
        if self.receipt.result is None:
            raise ValueError("generation record requires a typed model result")
        if self.receipt.entry_sha256 != self.receipt.totals.chain_head_sha256:
            raise ValueError("generation receipt was not the ledger head when recorded")
        result = NodeResult[NativeCodeGenerationOutput].model_validate(self.receipt.result)
        if result.proposal is None:
            raise ValueError("generation record requires an accepted typed proposal")
        if (
            self.request_sha256 != result.request.fingerprint
            or self.response_sha256 != result.response.raw_response_sha256
            or self.rationale_sha256 != content_sha256(result.proposal.rationale)
            or self.assumptions_sha256 != content_sha256(list(result.proposal.assumptions))
        ):
            raise ValueError("generation record differs from its typed model result")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("native code generation record hash mismatch")
        return self

    @property
    def typed_result(self) -> NodeResult[NativeCodeGenerationOutput]:
        assert self.receipt.result is not None
        return NodeResult[NativeCodeGenerationOutput].model_validate(self.receipt.result)


class NativeCodeRepairInputRecord(GenerationModel):
    """Pre-call repair checkpoint bound to the rejected generation evidence."""

    schema_version: Literal["1.0"] = "1.0"
    repair_id: str = Field(pattern=_SAFE_ID)
    project_id: str
    run_id: str = Field(pattern=_SAFE_ID)
    project_revision: int = Field(ge=0)
    invocation_id: str = Field(pattern=_SAFE_ID)
    workflow_config_sha256: str = Field(pattern=_SHA256)
    config_binding_sha256: str = Field(pattern=_SHA256)
    original_generation_record_sha256: str = Field(pattern=_SHA256)
    profile_fingerprint: str = Field(pattern=_SHA256)
    policy_fingerprint: str = Field(pattern=_SHA256)
    node_input: NativeCodeRepairInput
    record_sha256: str = Field(pattern=_SHA256)

    @classmethod
    def create(cls, **values: object) -> NativeCodeRepairInputRecord:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def evidence_is_closed(self) -> NativeCodeRepairInputRecord:
        validate_project_id(self.project_id)
        validate_entry_id(self.run_id, field_name="run_id")
        if self.invocation_id != f"{self.repair_id}-p{self.project_revision}":
            raise ValueError("native code repair invocation identity drift")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("native code repair input record hash mismatch")
        return self


class NativeCodeRepairRecord(GenerationModel):
    """Durable bridge from one repair ledger entry to deterministic readmission."""

    schema_version: Literal["1.0"] = "1.0"
    repair_id: str = Field(pattern=_SAFE_ID)
    generation_id: str = Field(pattern=_SAFE_ID)
    rejected_proposal_id: str = Field(pattern=_SAFE_ID)
    repaired_proposal_id: str = Field(pattern=_SAFE_ID)
    project_id: str
    run_id: str = Field(pattern=_SAFE_ID)
    project_revision: int = Field(ge=0)
    invocation_id: str = Field(pattern=_SAFE_ID)
    attempt_number: Literal[1] = 1
    max_attempts: Literal[1] = 1
    config_binding_sha256: str = Field(pattern=_SHA256)
    input_record_sha256: str = Field(pattern=_SHA256)
    original_generation_record_sha256: str = Field(pattern=_SHA256)
    rejected_binding_sha256: str = Field(pattern=_SHA256)
    rejected_source_sha256: str = Field(pattern=_SHA256)
    profile_fingerprint: str = Field(pattern=_SHA256)
    policy_fingerprint: str = Field(pattern=_SHA256)
    receipt: RuntimeInvocationReceipt
    request_sha256: str = Field(pattern=_SHA256)
    response_sha256: str = Field(pattern=_SHA256)
    repaired_source_locator: str
    repaired_source_sha256: str = Field(pattern=_SHA256)
    repaired_source_bytes: int = Field(ge=1)
    proposal_config_locator: str
    proposal_config_sha256: str = Field(pattern=_SHA256)
    proposal_binding_sha256: str = Field(pattern=_SHA256)
    admission_decision: Literal["accepted", "rejected"]
    rationale_sha256: str = Field(pattern=_SHA256)
    assumptions_sha256: str = Field(pattern=_SHA256)
    change_summary_sha256: str = Field(pattern=_SHA256)
    repair_proposal_only: Literal[True] = True
    executable: Literal[False] = False
    deterministic_readmission_required: Literal[True] = True
    runtime_isolation_required: Literal[True] = True
    effectiveness_claim: Literal[False] = False
    record_sha256: str = Field(pattern=_SHA256)

    @classmethod
    def create(cls, **values: object) -> NativeCodeRepairRecord:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def evidence_is_closed(self) -> NativeCodeRepairRecord:
        if (self.receipt.project_id, self.receipt.run_id, self.receipt.invocation_id) != (
            self.project_id,
            self.run_id,
            self.invocation_id,
        ):
            raise ValueError("repair receipt belongs to another invocation")
        if self.receipt.outcome is not RuntimeOutcome.ACCEPTED or self.receipt.result is None:
            raise ValueError("repair record requires an accepted model proposal")
        if self.receipt.entry_sha256 != self.receipt.totals.chain_head_sha256:
            raise ValueError("repair receipt was not the ledger head when recorded")
        result = NodeResult[NativeCodeRepairOutput].model_validate(self.receipt.result)
        if result.proposal is None:
            raise ValueError("repair record requires an accepted typed proposal")
        if (
            self.request_sha256 != result.request.fingerprint
            or self.response_sha256 != result.response.raw_response_sha256
            or self.rationale_sha256 != content_sha256(result.proposal.rationale)
            or self.assumptions_sha256 != content_sha256(list(result.proposal.assumptions))
            or self.change_summary_sha256 != content_sha256(list(result.proposal.change_summary))
        ):
            raise ValueError("repair record differs from its typed model result")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("native code repair record hash mismatch")
        return self

    @property
    def typed_result(self) -> NodeResult[NativeCodeRepairOutput]:
        assert self.receipt.result is not None
        return NodeResult[NativeCodeRepairOutput].model_validate(self.receipt.result)


@dataclass(frozen=True)
class GeneratedNativeCodeProposal:
    loaded: LoadedNativeCodeGeneration
    input_record: NativeCodeGenerationInputRecord
    record: NativeCodeGenerationRecord
    proposal_config_path: Path
    inspection: NativeCodeInspection


@dataclass(frozen=True)
class RepairedNativeCodeProposal:
    loaded: LoadedNativeCodeRepair
    input_record: NativeCodeRepairInputRecord
    record: NativeCodeRepairRecord
    proposal_config_path: Path
    inspection: NativeCodeInspection


def load_native_code_generation_config(path: str | Path) -> LoadedNativeCodeGeneration:
    """Load one strict, content-bound, credential-free generation configuration."""

    source = Path(path).expanduser().resolve(strict=True)
    raw = _read_bounded_regular(source, _MAX_CONFIG_BYTES, "native code generation config")
    try:
        payload = yaml.load(raw, Loader=_UniqueKeyLoader)
        _reject_secret_fields(payload)
        if not isinstance(payload, dict):
            raise ValueError("native code generation config root must be a mapping")
        profile_set = Path(payload["profile_set"])
        if not profile_set.is_absolute():
            profile_set = (source.parent / profile_set).resolve(strict=True)
        payload["profile_set"] = profile_set
        config = NativeCodeGenerationConfig.model_validate(payload)
        profiles = load_model_node_profile_set(profile_set)
        profile = profiles.profiles[config.profile_id]
        validate_profile_binding(profile, config.policy, node_name=_NODE_NAME)
    except (KeyError, TypeError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("invalid native code generation configuration") from exc
    if config.live_enabled != profile.live_execution_permitted:
        raise ValueError("generation and profile live gates must agree")
    if config.live_enabled != profiles.profile_set.live_enabled:
        raise ValueError("generation and profile-set live gates must agree")
    if profile.unrestricted_code_generation:
        raise ValueError("native source generation must remain bounded")
    if profile.admission.allowed_tool_names or profile.admission.max_tool_call_proposals:
        raise ValueError("native source generation profile cannot propose tools")
    return LoadedNativeCodeGeneration(
        source_path=source,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        profile_set_sha256=profiles.source_sha256,
        config=config,
        profile=profile,
    )


def load_native_code_repair_config(path: str | Path) -> LoadedNativeCodeRepair:
    """Load one strict, one-attempt, credential-free repair configuration."""

    source = Path(path).expanduser().resolve(strict=True)
    raw = _read_bounded_regular(source, _MAX_CONFIG_BYTES, "native code repair config")
    try:
        payload = yaml.load(raw, Loader=_UniqueKeyLoader)
        _reject_secret_fields(payload)
        if not isinstance(payload, dict):
            raise ValueError("native code repair config root must be a mapping")
        profile_set = Path(payload["profile_set"])
        if not profile_set.is_absolute():
            profile_set = (source.parent / profile_set).resolve(strict=True)
        payload["profile_set"] = profile_set
        config = NativeCodeRepairConfig.model_validate(payload)
        profiles = load_model_node_profile_set(profile_set)
        profile = profiles.profiles[config.profile_id]
        validate_profile_binding(profile, config.policy, node_name=_REPAIR_NODE_NAME)
    except (KeyError, TypeError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("invalid native code repair configuration") from exc
    if config.live_enabled != profile.live_execution_permitted:
        raise ValueError("repair and profile live gates must agree")
    if config.live_enabled != profiles.profile_set.live_enabled:
        raise ValueError("repair and profile-set live gates must agree")
    if profile.unrestricted_code_generation:
        raise ValueError("native source repair must remain bounded")
    if profile.admission.allowed_tool_names or profile.admission.max_tool_call_proposals:
        raise ValueError("native source repair profile cannot propose tools")
    return LoadedNativeCodeRepair(
        source_path=source,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        profile_set_sha256=profiles.source_sha256,
        config=config,
        profile=profile,
    )


def validate_native_code_repair_binding(
    repair: LoadedNativeCodeRepair,
    generation: LoadedNativeCodeGeneration,
) -> None:
    """Require repair identity and cumulative limits to match its generating node."""

    observed = (
        repair.config.generation_id,
        repair.config.rejected_proposal_id,
    )
    expected = (
        generation.config.generation_id,
        generation.config.proposal_id,
    )
    if observed != expected:
        raise NativeCodeGenerationError("native code repair belongs to another generation config")
    if repair.profile.cumulative_project != generation.profile.cumulative_project:
        raise NativeCodeGenerationError(
            "native code repair and generation must share one cumulative project budget"
        )


def generate_native_code_proposal(
    loaded: LoadedNativeCodeGeneration,
    *,
    project_runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
    run_root: Path,
    expected_project_revision: int,
    workflow_config_sha256: str,
    seed: int,
    resume: bool = False,
    allow_live: bool = False,
) -> GeneratedNativeCodeProposal:
    """Generate/recover one proposal and bind it to deterministic static admission."""

    if isinstance(loaded.config.backend, LiveRuntimeBackend):
        if not loaded.config.live_enabled:
            raise NativeCodeGenerationError("live native source generation is disabled")
        if not allow_live:
            raise NativeCodeGenerationError(
                "live native source generation requires explicit caller opt-in"
            )
    root = run_root.resolve(strict=True)
    expected_root = (
        project_runtime.outputs_root / "projects" / project_id / "runs" / run_id
    ).resolve(strict=True)
    if root != expected_root or run_root.is_symlink():
        raise NativeCodeGenerationError("native source generation run root is not project-owned")
    native_root = run_root / "native_execution"
    context_root = native_root / "context"
    generation_root = context_root / "code_generation"
    for directory in (native_root, context_root, generation_root):
        directory.mkdir(exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise NativeCodeGenerationError(
                "native source generation root must be an owned directory"
            )
        try:
            directory.resolve(strict=True).relative_to(root)
        except ValueError as exc:
            raise NativeCodeGenerationError(
                "native source generation directory escapes its owning run"
            ) from exc
    input_path = generation_root / "GENERATION_INPUT.json"
    if input_path.exists():
        if not resume:
            raise FileExistsError(input_path)
        input_record = _verify_input_record(
            loaded,
            input_path=input_path,
            project_id=project_id,
            run_id=run_id,
            workflow_config_sha256=workflow_config_sha256,
        )
    else:
        input_record = NativeCodeGenerationInputRecord.create(
            generation_id=loaded.config.generation_id,
            project_id=project_id,
            run_id=run_id,
            project_revision=expected_project_revision,
            invocation_id=(f"{loaded.config.generation_id}-p{expected_project_revision}"),
            workflow_config_sha256=workflow_config_sha256,
            config_binding_sha256=loaded.fingerprint,
            profile_fingerprint=loaded.profile.fingerprint,
            policy_fingerprint=loaded.config.policy.fingerprint,
            node_input=loaded.config.node_input,
        )
        _write_json_exclusive(input_path, input_record.model_dump(mode="json"))

    result_root = generation_root / "result"
    record_path = result_root / "GENERATION.json"
    runtime = _generation_runtime(project_runtime)
    if record_path.exists():
        return _verify_generation_result(
            loaded,
            runtime=runtime,
            run_root=run_root,
            input_record=input_record,
            result_root=result_root,
        )

    context = NodeContext(
        project_id=project_id,
        stage="EXPERIMENT",
        state_snapshot_id=workflow_config_sha256,
        cumulative_api_cost_usd=0.0,
        metadata={
            "generation_id": loaded.config.generation_id,
            "proposal_only": True,
            "deterministic_admission_required": True,
            "runtime_isolation_required": True,
        },
    )
    receipt = runtime.execute(
        backend=loaded.config.backend.build(input_record.invocation_id),
        resume=resume,
        allow_live=allow_live,
        project_id=project_id,
        run_id=run_id,
        invocation_id=input_record.invocation_id,
        expected_project_revision=expected_project_revision,
        state_revision=0,
        node_name=_NODE_NAME,
        node_input=input_record.node_input,
        context=context,
        trigger=ModelNodeTrigger(
            trigger_id=loaded.config.generation_id,
            reason=loaded.config.trigger_reason,
        ),
        profile=loaded.profile,
        policy=loaded.config.policy,
        backend_mode=loaded.config.backend.mode,
        seed=seed,
    )
    if receipt.outcome is not RuntimeOutcome.ACCEPTED or receipt.result is None:
        blockers = "; ".join(receipt.blockers) or receipt.outcome.value
        raise NativeCodeGenerationError(
            "native source model proposal was not accepted: " + blockers
        )
    result = NodeResult[NativeCodeGenerationOutput].model_validate(receipt.result)
    if result.proposal is None:
        raise NativeCodeGenerationError("accepted native source generation has no proposal")
    _publish_generated_files(loaded, result, result_root=result_root)
    inspection = inspect_native_code_proposal(result_root / "proposal.json")
    record = _build_generation_record(
        loaded,
        input_record=input_record,
        receipt=receipt,
        result=result,
        result_root=result_root,
        inspection=inspection,
        run_root=run_root,
    )
    _write_json_exclusive(record_path, record.model_dump(mode="json"))
    return _verify_generation_result(
        loaded,
        runtime=runtime,
        run_root=run_root,
        input_record=input_record,
        result_root=result_root,
    )


def repair_native_code_proposal(
    loaded: LoadedNativeCodeRepair,
    *,
    generated: GeneratedNativeCodeProposal,
    project_runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
    run_root: Path,
    expected_project_revision: int,
    workflow_config_sha256: str,
    seed: int,
    resume: bool = False,
    allow_live: bool = False,
    runtime_failure: NativeCodeRuntimeFailure | None = None,
) -> RepairedNativeCodeProposal:
    """Run or recover one repair after static rejection or isolated runtime failure."""

    validate_native_code_repair_binding(loaded, generated.loaded)
    runtime_trigger = runtime_failure is not None
    if runtime_trigger:
        if not loaded.config.conditional_on_runtime_failure:
            raise NativeCodeGenerationError("native code repair is not bound to runtime failure")
        if generated.inspection.admission.decision != "accepted":
            raise NativeCodeGenerationError(
                "runtime repair requires an admitted generated proposal"
            )
        if runtime_failure.source_sha256 != generated.record.generated_source_sha256:
            raise NativeCodeGenerationError("runtime failure belongs to another generated source")
        validation_issues = (
            NativeCodeViolation(
                code=f"runtime-{runtime_failure.failure_code}",
                message=runtime_failure.error_message,
            ),
        )
    else:
        if not loaded.config.conditional_on_static_rejection:
            raise NativeCodeGenerationError("native code repair is not bound to static rejection")
        if generated.inspection.admission.decision != "rejected":
            raise NativeCodeGenerationError(
                "native code repair requires a rejected generated proposal"
            )
        validation_issues = generated.inspection.admission.violations
    if isinstance(loaded.config.backend, LiveRuntimeBackend):
        if not loaded.config.live_enabled:
            raise NativeCodeGenerationError("live native source repair is disabled")
        if not allow_live:
            raise NativeCodeGenerationError(
                "live native source repair requires explicit caller opt-in"
            )
    root = run_root.resolve(strict=True)
    expected_root = (
        project_runtime.outputs_root / "projects" / project_id / "runs" / run_id
    ).resolve(strict=True)
    if root != expected_root or run_root.is_symlink():
        raise NativeCodeGenerationError("native source repair run root is not project-owned")
    expected_generated_root = run_root / "native_execution" / "context" / "code_generation"
    if generated.proposal_config_path.parent.parent.resolve(strict=True) != (
        expected_generated_root.resolve(strict=True)
    ):
        raise NativeCodeGenerationError("native source repair input is not project-owned")
    repair_root = expected_generated_root / "repair"
    repair_root.mkdir(exist_ok=True)
    if repair_root.is_symlink() or not repair_root.is_dir():
        raise NativeCodeGenerationError("native source repair root must be an owned directory")
    try:
        repair_root.resolve(strict=True).relative_to(root)
    except ValueError as exc:
        raise NativeCodeGenerationError(
            "native source repair directory escapes its owning run"
        ) from exc

    generation_result = generated.record.typed_result
    rejected_output = generation_result.proposal
    assert rejected_output is not None
    node_input = NativeCodeRepairInput(
        generation_input=generated.input_record.node_input,
        rejected_output=rejected_output,
        rejected_binding_sha256=generated.inspection.binding_sha256,
        rejected_source_sha256=generated.record.generated_source_sha256,
        trigger="isolated-runtime" if runtime_trigger else "static-admission",
        validation_issues=validation_issues,
        runtime_failure=runtime_failure,
        repair_contract=(
            "replace-source-only-then-readmit-and-rerun-identical-isolated-experiment"
            if runtime_trigger
            else "replace-source-only-then-repeat-identical-deterministic-admission"
        ),
    )
    input_path = repair_root / "REPAIR_INPUT.json"
    if input_path.exists():
        if not resume:
            raise FileExistsError(input_path)
        input_record = _verify_repair_input_record(
            loaded,
            generated=generated,
            input_path=input_path,
            project_id=project_id,
            run_id=run_id,
            workflow_config_sha256=workflow_config_sha256,
            node_input=node_input,
        )
    else:
        input_record = NativeCodeRepairInputRecord.create(
            repair_id=loaded.config.repair_id,
            project_id=project_id,
            run_id=run_id,
            project_revision=expected_project_revision,
            invocation_id=f"{loaded.config.repair_id}-p{expected_project_revision}",
            workflow_config_sha256=workflow_config_sha256,
            config_binding_sha256=loaded.fingerprint,
            original_generation_record_sha256=generated.record.record_sha256,
            profile_fingerprint=loaded.profile.fingerprint,
            policy_fingerprint=loaded.config.policy.fingerprint,
            node_input=node_input,
        )
        _write_json_exclusive(input_path, input_record.model_dump(mode="json"))

    result_root = repair_root / "result"
    record_path = result_root / "REPAIR.json"
    runtime = _generation_runtime(project_runtime)
    if record_path.exists():
        return _verify_repair_result(
            loaded,
            generated=generated,
            runtime=runtime,
            run_root=run_root,
            input_record=input_record,
            result_root=result_root,
        )

    context = NodeContext(
        project_id=project_id,
        stage="EXPERIMENT",
        state_snapshot_id=workflow_config_sha256,
        cumulative_api_cost_usd=generated.record.receipt.totals.cost_usd,
        metadata={
            "repair_id": loaded.config.repair_id,
            "repair_trigger": node_input.trigger,
            "runtime_failure_sha256": (
                runtime_failure.fingerprint if runtime_failure is not None else None
            ),
            "attempt_number": 1,
            "max_attempts": loaded.config.max_attempts,
            "repair_proposal_only": True,
            "deterministic_readmission_required": True,
            "runtime_isolation_required": True,
        },
    )
    receipt = runtime.execute(
        backend=loaded.config.backend.build(input_record.invocation_id),
        resume=resume,
        allow_live=allow_live,
        project_id=project_id,
        run_id=run_id,
        invocation_id=input_record.invocation_id,
        expected_project_revision=expected_project_revision,
        state_revision=0,
        node_name=_REPAIR_NODE_NAME,
        node_input=input_record.node_input,
        context=context,
        trigger=ModelNodeTrigger(
            trigger_id=loaded.config.repair_id,
            reason=loaded.config.trigger_reason,
        ),
        profile=loaded.profile,
        policy=loaded.config.policy,
        backend_mode=loaded.config.backend.mode,
        seed=seed,
    )
    if receipt.outcome is not RuntimeOutcome.ACCEPTED or receipt.result is None:
        blockers = "; ".join(receipt.blockers) or receipt.outcome.value
        raise NativeCodeGenerationError(
            "native source repair proposal was not accepted: " + blockers
        )
    result = NodeResult[NativeCodeRepairOutput].model_validate(receipt.result)
    if result.proposal is None:
        raise NativeCodeGenerationError("accepted native source repair has no proposal")
    _publish_repaired_files(
        loaded,
        generated=generated,
        result=result,
        result_root=result_root,
    )
    inspection = inspect_native_code_proposal(result_root / "proposal.json")
    record = _build_repair_record(
        loaded,
        generated=generated,
        input_record=input_record,
        receipt=receipt,
        result=result,
        result_root=result_root,
        inspection=inspection,
        run_root=run_root,
    )
    _write_json_exclusive(record_path, record.model_dump(mode="json"))
    return _verify_repair_result(
        loaded,
        generated=generated,
        runtime=runtime,
        run_root=run_root,
        input_record=input_record,
        result_root=result_root,
    )


def load_native_code_generation_record(
    run_root: str | Path,
) -> NativeCodeGenerationRecord | None:
    path = (
        Path(run_root)
        / "native_execution"
        / "context"
        / "code_generation"
        / "result"
        / "GENERATION.json"
    )
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise NativeCodeGenerationError("native source generation record must be a regular file")
    try:
        return NativeCodeGenerationRecord.model_validate_json(path.read_bytes())
    except ValueError as exc:
        raise NativeCodeGenerationError("invalid native source generation record") from exc


def load_native_code_repair_record(run_root: str | Path) -> NativeCodeRepairRecord | None:
    path = (
        Path(run_root)
        / "native_execution"
        / "context"
        / "code_generation"
        / "repair"
        / "result"
        / "REPAIR.json"
    )
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise NativeCodeGenerationError("native source repair record must be a regular file")
    try:
        return NativeCodeRepairRecord.model_validate_json(path.read_bytes())
    except ValueError as exc:
        raise NativeCodeGenerationError("invalid native source repair record") from exc


def verify_native_code_generation_ledger(
    project_runtime: ProjectRuntime,
    *,
    project_id: str,
    run_id: str,
) -> RuntimeVerification:
    """Verify a mixed built-in/extension ledger with the generation type registered."""

    return _generation_runtime(project_runtime).verify(project_id=project_id, run_id=run_id)


def native_code_generation_node_types() -> dict[str, ModelNodeRegistration]:
    """Return extension types required to verify generation and repair ledger entries."""

    return {
        _NODE_NAME: ModelNodeRegistration(
            NativeCodeGenerationNode,
            NativeCodeGenerationInput,
            NativeCodeGenerationOutput,
        ),
        _REPAIR_NODE_NAME: ModelNodeRegistration(
            NativeCodeRepairNode,
            NativeCodeRepairInput,
            NativeCodeRepairOutput,
        ),
    }


def _generation_runtime(project_runtime: ProjectRuntime) -> ModelNodeRuntime:
    return ModelNodeRuntime(
        project_runtime,
        node_types=native_code_generation_node_types(),
    )


def _verify_input_record(
    loaded: LoadedNativeCodeGeneration,
    *,
    input_path: Path,
    project_id: str,
    run_id: str,
    workflow_config_sha256: str,
) -> NativeCodeGenerationInputRecord:
    if input_path.is_symlink() or not input_path.is_file():
        raise NativeCodeGenerationError("generation input record must be a regular file")
    try:
        record = NativeCodeGenerationInputRecord.model_validate_json(input_path.read_bytes())
    except ValueError as exc:
        raise NativeCodeGenerationError("invalid generation input record") from exc
    if (record.project_id, record.run_id) != (project_id, run_id):
        raise NativeCodeGenerationError("generation input belongs to another project run")
    expected = (
        loaded.config.generation_id,
        workflow_config_sha256,
        loaded.fingerprint,
        loaded.profile.fingerprint,
        loaded.config.policy.fingerprint,
        loaded.config.node_input.model_dump(mode="json"),
    )
    observed = (
        record.generation_id,
        record.workflow_config_sha256,
        record.config_binding_sha256,
        record.profile_fingerprint,
        record.policy_fingerprint,
        record.node_input.model_dump(mode="json"),
    )
    if observed != expected:
        raise NativeCodeGenerationError("generation input configuration binding drift")
    return record


def _verify_repair_input_record(
    loaded: LoadedNativeCodeRepair,
    *,
    generated: GeneratedNativeCodeProposal,
    input_path: Path,
    project_id: str,
    run_id: str,
    workflow_config_sha256: str,
    node_input: NativeCodeRepairInput,
) -> NativeCodeRepairInputRecord:
    if input_path.is_symlink() or not input_path.is_file():
        raise NativeCodeGenerationError("repair input record must be a regular file")
    try:
        record = NativeCodeRepairInputRecord.model_validate_json(input_path.read_bytes())
    except ValueError as exc:
        raise NativeCodeGenerationError("invalid repair input record") from exc
    expected = (
        project_id,
        run_id,
        loaded.config.repair_id,
        workflow_config_sha256,
        loaded.fingerprint,
        generated.record.record_sha256,
        loaded.profile.fingerprint,
        loaded.config.policy.fingerprint,
        node_input.model_dump(mode="json"),
    )
    observed = (
        record.project_id,
        record.run_id,
        record.repair_id,
        record.workflow_config_sha256,
        record.config_binding_sha256,
        record.original_generation_record_sha256,
        record.profile_fingerprint,
        record.policy_fingerprint,
        record.node_input.model_dump(mode="json"),
    )
    if observed != expected:
        raise NativeCodeGenerationError("repair input configuration binding drift")
    return record


def _publish_generated_files(
    loaded: LoadedNativeCodeGeneration,
    result: NodeResult[NativeCodeGenerationOutput],
    *,
    result_root: Path,
) -> None:
    proposal = result.proposal
    assert proposal is not None
    source = proposal.source_code.encode("utf-8")
    source_name = "generated.py"
    proposal_payload = _proposal_payload(
        loaded,
        proposal,
        request_sha256=result.request.fingerprint,
        response_sha256=result.response.raw_response_sha256,
    )
    expected_proposal = _json_bytes(proposal_payload)
    if result_root.exists():
        if result_root.is_symlink() or not result_root.is_dir():
            raise NativeCodeGenerationError("generated result root is not an owned directory")
        allowed = {"generated.py", "proposal.json", "GENERATION.json"}
        if {item.name for item in result_root.iterdir()} - allowed:
            raise NativeCodeGenerationError("generated result root contains unknown artifacts")
        source_path = result_root / source_name
        proposal_path = result_root / "proposal.json"
        if (
            source_path.is_symlink()
            or not source_path.is_file()
            or source_path.read_bytes() != source
            or proposal_path.is_symlink()
            or not proposal_path.is_file()
            or proposal_path.read_bytes() != expected_proposal
        ):
            raise NativeCodeGenerationError("incomplete generated result differs from ledger")
        return
    temporary = Path(tempfile.mkdtemp(prefix=".result.", dir=result_root.parent))
    try:
        _write_bytes_exclusive(temporary / source_name, source)
        _write_json_exclusive(temporary / "proposal.json", proposal_payload)
        _fsync_directory(temporary)
        os.replace(temporary, result_root)
        _fsync_directory(result_root.parent)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _publish_repaired_files(
    loaded: LoadedNativeCodeRepair,
    *,
    generated: GeneratedNativeCodeProposal,
    result: NodeResult[NativeCodeRepairOutput],
    result_root: Path,
) -> None:
    proposal = result.proposal
    assert proposal is not None
    source = proposal.source_code.encode("utf-8")
    proposal_payload = _repair_proposal_payload(
        loaded,
        generated=generated,
        proposal=proposal,
        request_sha256=result.request.fingerprint,
        response_sha256=result.response.raw_response_sha256,
    )
    expected_proposal = _json_bytes(proposal_payload)
    if result_root.exists():
        if result_root.is_symlink() or not result_root.is_dir():
            raise NativeCodeGenerationError("repaired result root is not an owned directory")
        allowed = {"repaired.py", "proposal.json", "REPAIR.json"}
        if {item.name for item in result_root.iterdir()} - allowed:
            raise NativeCodeGenerationError("repaired result root contains unknown artifacts")
        source_path = result_root / "repaired.py"
        proposal_path = result_root / "proposal.json"
        if (
            source_path.is_symlink()
            or not source_path.is_file()
            or source_path.read_bytes() != source
            or proposal_path.is_symlink()
            or not proposal_path.is_file()
            or proposal_path.read_bytes() != expected_proposal
        ):
            raise NativeCodeGenerationError("incomplete repaired result differs from ledger")
        return
    temporary = Path(tempfile.mkdtemp(prefix=".result.", dir=result_root.parent))
    try:
        _write_bytes_exclusive(temporary / "repaired.py", source)
        _write_json_exclusive(temporary / "proposal.json", proposal_payload)
        _fsync_directory(temporary)
        os.replace(temporary, result_root)
        _fsync_directory(result_root.parent)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _proposal_payload(
    loaded: LoadedNativeCodeGeneration,
    proposal: NativeCodeGenerationOutput,
    *,
    request_sha256: str,
    response_sha256: str,
) -> dict[str, JsonValue]:
    config = NativeCodeProposalConfig(
        proposal_id=loaded.config.proposal_id,
        source_path=Path("generated.py"),
        rationale=proposal.rationale,
        expected_metrics=loaded.config.expected_metrics,
        producer=NativeCodeProducer(
            mode="model",
            producer_id=loaded.config.generation_id,
            provider=loaded.profile.provider,
            model=loaded.profile.model,
            request_sha256=request_sha256,
            response_sha256=response_sha256,
        ),
        experiment=loaded.config.experiment,
        policy=loaded.config.admission_policy,
    )
    return config.model_dump(mode="json")


def _repair_proposal_payload(
    loaded: LoadedNativeCodeRepair,
    *,
    generated: GeneratedNativeCodeProposal,
    proposal: NativeCodeRepairOutput,
    request_sha256: str,
    response_sha256: str,
) -> dict[str, JsonValue]:
    generation = generated.loaded.config
    config = NativeCodeProposalConfig(
        proposal_id=loaded.config.repaired_proposal_id,
        source_path=Path("repaired.py"),
        rationale=proposal.rationale,
        expected_metrics=generation.expected_metrics,
        producer=NativeCodeProducer(
            mode="model",
            producer_id=loaded.config.repair_id,
            provider=loaded.profile.provider,
            model=loaded.profile.model,
            request_sha256=request_sha256,
            response_sha256=response_sha256,
        ),
        experiment=generation.experiment,
        policy=generation.admission_policy,
    )
    return config.model_dump(mode="json")


def _build_generation_record(
    loaded: LoadedNativeCodeGeneration,
    *,
    input_record: NativeCodeGenerationInputRecord,
    receipt: RuntimeInvocationReceipt,
    result: NodeResult[NativeCodeGenerationOutput],
    result_root: Path,
    inspection: NativeCodeInspection,
    run_root: Path,
) -> NativeCodeGenerationRecord:
    assert result.proposal is not None
    source_path = result_root / "generated.py"
    proposal_path = result_root / "proposal.json"
    return NativeCodeGenerationRecord.create(
        generation_id=loaded.config.generation_id,
        proposal_id=loaded.config.proposal_id,
        project_id=input_record.project_id,
        run_id=input_record.run_id,
        project_revision=input_record.project_revision,
        invocation_id=input_record.invocation_id,
        config_binding_sha256=loaded.fingerprint,
        input_record_sha256=input_record.record_sha256,
        profile_fingerprint=loaded.profile.fingerprint,
        policy_fingerprint=loaded.config.policy.fingerprint,
        receipt=receipt,
        request_sha256=result.request.fingerprint,
        response_sha256=result.response.raw_response_sha256,
        generated_source_locator=_owned_locator(run_root, source_path),
        generated_source_sha256=_file_sha256(source_path),
        generated_source_bytes=source_path.stat().st_size,
        proposal_config_locator=_owned_locator(run_root, proposal_path),
        proposal_config_sha256=_file_sha256(proposal_path),
        proposal_binding_sha256=inspection.binding_sha256,
        admission_decision=inspection.admission.decision,
        rationale_sha256=content_sha256(result.proposal.rationale),
        assumptions_sha256=content_sha256(list(result.proposal.assumptions)),
    )


def _build_repair_record(
    loaded: LoadedNativeCodeRepair,
    *,
    generated: GeneratedNativeCodeProposal,
    input_record: NativeCodeRepairInputRecord,
    receipt: RuntimeInvocationReceipt,
    result: NodeResult[NativeCodeRepairOutput],
    result_root: Path,
    inspection: NativeCodeInspection,
    run_root: Path,
) -> NativeCodeRepairRecord:
    assert result.proposal is not None
    source_path = result_root / "repaired.py"
    proposal_path = result_root / "proposal.json"
    return NativeCodeRepairRecord.create(
        repair_id=loaded.config.repair_id,
        generation_id=generated.record.generation_id,
        rejected_proposal_id=generated.record.proposal_id,
        repaired_proposal_id=loaded.config.repaired_proposal_id,
        project_id=input_record.project_id,
        run_id=input_record.run_id,
        project_revision=input_record.project_revision,
        invocation_id=input_record.invocation_id,
        attempt_number=1,
        max_attempts=loaded.config.max_attempts,
        config_binding_sha256=loaded.fingerprint,
        input_record_sha256=input_record.record_sha256,
        original_generation_record_sha256=generated.record.record_sha256,
        rejected_binding_sha256=generated.inspection.binding_sha256,
        rejected_source_sha256=generated.record.generated_source_sha256,
        profile_fingerprint=loaded.profile.fingerprint,
        policy_fingerprint=loaded.config.policy.fingerprint,
        receipt=receipt,
        request_sha256=result.request.fingerprint,
        response_sha256=result.response.raw_response_sha256,
        repaired_source_locator=_owned_locator(run_root, source_path),
        repaired_source_sha256=_file_sha256(source_path),
        repaired_source_bytes=source_path.stat().st_size,
        proposal_config_locator=_owned_locator(run_root, proposal_path),
        proposal_config_sha256=_file_sha256(proposal_path),
        proposal_binding_sha256=inspection.binding_sha256,
        admission_decision=inspection.admission.decision,
        rationale_sha256=content_sha256(result.proposal.rationale),
        assumptions_sha256=content_sha256(list(result.proposal.assumptions)),
        change_summary_sha256=content_sha256(list(result.proposal.change_summary)),
    )


def _verify_generation_result(
    loaded: LoadedNativeCodeGeneration,
    *,
    runtime: ModelNodeRuntime,
    run_root: Path,
    input_record: NativeCodeGenerationInputRecord,
    result_root: Path,
) -> GeneratedNativeCodeProposal:
    record_path = result_root / "GENERATION.json"
    if record_path.is_symlink() or not record_path.is_file():
        raise NativeCodeGenerationError("native source generation result is incomplete")
    try:
        record = NativeCodeGenerationRecord.model_validate_json(record_path.read_bytes())
    except ValueError as exc:
        raise NativeCodeGenerationError("invalid native source generation result") from exc
    entry = runtime.entry(
        project_id=input_record.project_id,
        run_id=input_record.run_id,
        invocation_id=input_record.invocation_id,
    )
    if entry.entry_sha256 != record.receipt.entry_sha256 or entry.result is None:
        raise NativeCodeGenerationError("generation record differs from its model-node ledger")
    result = NodeResult[NativeCodeGenerationOutput].model_validate(entry.result)
    if result.proposal is None or entry.outcome is not RuntimeOutcome.ACCEPTED:
        raise NativeCodeGenerationError("generation ledger has no accepted source proposal")
    expected_bindings = (
        loaded.config.generation_id,
        loaded.config.proposal_id,
        input_record.project_id,
        input_record.run_id,
        input_record.project_revision,
        input_record.invocation_id,
        loaded.fingerprint,
        input_record.record_sha256,
        loaded.profile.fingerprint,
        loaded.config.policy.fingerprint,
        result.request.fingerprint,
        result.response.raw_response_sha256,
        content_sha256(result.proposal.rationale),
        content_sha256(list(result.proposal.assumptions)),
    )
    observed_bindings = (
        record.generation_id,
        record.proposal_id,
        record.project_id,
        record.run_id,
        record.project_revision,
        record.invocation_id,
        record.config_binding_sha256,
        record.input_record_sha256,
        record.profile_fingerprint,
        record.policy_fingerprint,
        record.request_sha256,
        record.response_sha256,
        record.rationale_sha256,
        record.assumptions_sha256,
    )
    if observed_bindings != expected_bindings:
        raise NativeCodeGenerationError("generation result binding drift")
    source_path = _owned_regular_file(
        run_root,
        record.generated_source_locator,
        expected_sha256=record.generated_source_sha256,
    )
    proposal_path = _owned_regular_file(
        run_root,
        record.proposal_config_locator,
        expected_sha256=record.proposal_config_sha256,
    )
    if source_path.parent != result_root.resolve(strict=True) or source_path.name != "generated.py":
        raise NativeCodeGenerationError("generated source locator is not canonical")
    if (
        proposal_path.parent != result_root.resolve(strict=True)
        or proposal_path.name != "proposal.json"
    ):
        raise NativeCodeGenerationError("generated proposal locator is not canonical")
    if source_path.read_bytes() != result.proposal.source_code.encode("utf-8"):
        raise NativeCodeGenerationError("generated source differs from the model-node ledger")
    expected_proposal = _proposal_payload(
        loaded,
        result.proposal,
        request_sha256=result.request.fingerprint,
        response_sha256=result.response.raw_response_sha256,
    )
    try:
        observed_proposal = json.loads(proposal_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeCodeGenerationError("generated proposal config is invalid") from exc
    if observed_proposal != expected_proposal:
        raise NativeCodeGenerationError("generated proposal config differs from its ledger")
    inspection = inspect_native_code_proposal(proposal_path)
    if (
        inspection.binding_sha256 != record.proposal_binding_sha256
        or inspection.admission.decision != record.admission_decision
        or source_path.stat().st_size != record.generated_source_bytes
    ):
        raise NativeCodeGenerationError("generated proposal admission binding drift")
    return GeneratedNativeCodeProposal(
        loaded=loaded,
        input_record=input_record,
        record=record,
        proposal_config_path=proposal_path,
        inspection=inspection,
    )


def _verify_repair_result(
    loaded: LoadedNativeCodeRepair,
    *,
    generated: GeneratedNativeCodeProposal,
    runtime: ModelNodeRuntime,
    run_root: Path,
    input_record: NativeCodeRepairInputRecord,
    result_root: Path,
) -> RepairedNativeCodeProposal:
    record_path = result_root / "REPAIR.json"
    if record_path.is_symlink() or not record_path.is_file():
        raise NativeCodeGenerationError("native source repair result is incomplete")
    try:
        record = NativeCodeRepairRecord.model_validate_json(record_path.read_bytes())
    except ValueError as exc:
        raise NativeCodeGenerationError("invalid native source repair result") from exc
    entry = runtime.entry(
        project_id=input_record.project_id,
        run_id=input_record.run_id,
        invocation_id=input_record.invocation_id,
    )
    if (
        entry.entry_sha256 != record.receipt.entry_sha256
        or entry.result is None
        or record.receipt.result != entry.result
        or record.receipt.outcome is not entry.outcome
        or record.receipt.request_fingerprint != entry.request_fingerprint
    ):
        raise NativeCodeGenerationError("repair record differs from its model-node ledger")
    prefix_totals = runtime.totals_through_entry(
        project_id=input_record.project_id,
        run_id=input_record.run_id,
        invocation_id=input_record.invocation_id,
    )
    if record.receipt.totals != prefix_totals:
        raise NativeCodeGenerationError("repair receipt totals differ from its ledger prefix")
    telemetry = record.receipt.telemetry
    expected_telemetry = (
        entry.input_tokens,
        entry.output_tokens,
        entry.token_effect,
        entry.cost_effect_usd,
        entry.latency_ms,
        entry.cached,
        entry.replayed,
    )
    observed_telemetry = (
        telemetry.input_tokens,
        telemetry.output_tokens,
        telemetry.total_tokens,
        telemetry.cost_usd,
        telemetry.latency_ms,
        telemetry.cached,
        telemetry.replayed,
    )
    if observed_telemetry != expected_telemetry:
        raise NativeCodeGenerationError("repair receipt telemetry differs from its ledger entry")
    result = NodeResult[NativeCodeRepairOutput].model_validate(entry.result)
    if result.proposal is None or entry.outcome is not RuntimeOutcome.ACCEPTED:
        raise NativeCodeGenerationError("repair ledger has no accepted source proposal")
    expected_bindings = (
        loaded.config.repair_id,
        generated.record.generation_id,
        generated.record.proposal_id,
        loaded.config.repaired_proposal_id,
        input_record.project_id,
        input_record.run_id,
        input_record.project_revision,
        input_record.invocation_id,
        loaded.fingerprint,
        input_record.record_sha256,
        generated.record.record_sha256,
        generated.inspection.binding_sha256,
        generated.record.generated_source_sha256,
        loaded.profile.fingerprint,
        loaded.config.policy.fingerprint,
        result.request.fingerprint,
        result.response.raw_response_sha256,
        content_sha256(result.proposal.rationale),
        content_sha256(list(result.proposal.assumptions)),
        content_sha256(list(result.proposal.change_summary)),
    )
    observed_bindings = (
        record.repair_id,
        record.generation_id,
        record.rejected_proposal_id,
        record.repaired_proposal_id,
        record.project_id,
        record.run_id,
        record.project_revision,
        record.invocation_id,
        record.config_binding_sha256,
        record.input_record_sha256,
        record.original_generation_record_sha256,
        record.rejected_binding_sha256,
        record.rejected_source_sha256,
        record.profile_fingerprint,
        record.policy_fingerprint,
        record.request_sha256,
        record.response_sha256,
        record.rationale_sha256,
        record.assumptions_sha256,
        record.change_summary_sha256,
    )
    if observed_bindings != expected_bindings:
        raise NativeCodeGenerationError("repair result binding drift")
    source_path = _owned_regular_file(
        run_root,
        record.repaired_source_locator,
        expected_sha256=record.repaired_source_sha256,
    )
    proposal_path = _owned_regular_file(
        run_root,
        record.proposal_config_locator,
        expected_sha256=record.proposal_config_sha256,
    )
    if source_path.parent != result_root.resolve(strict=True) or source_path.name != "repaired.py":
        raise NativeCodeGenerationError("repaired source locator is not canonical")
    if (
        proposal_path.parent != result_root.resolve(strict=True)
        or proposal_path.name != "proposal.json"
    ):
        raise NativeCodeGenerationError("repaired proposal locator is not canonical")
    if source_path.read_bytes() != result.proposal.source_code.encode("utf-8"):
        raise NativeCodeGenerationError("repaired source differs from the model-node ledger")
    expected_proposal = _repair_proposal_payload(
        loaded,
        generated=generated,
        proposal=result.proposal,
        request_sha256=result.request.fingerprint,
        response_sha256=result.response.raw_response_sha256,
    )
    try:
        observed_proposal = json.loads(proposal_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeCodeGenerationError("repaired proposal config is invalid") from exc
    if observed_proposal != expected_proposal:
        raise NativeCodeGenerationError("repaired proposal config differs from its ledger")
    inspection = inspect_native_code_proposal(proposal_path)
    if (
        inspection.binding_sha256 != record.proposal_binding_sha256
        or inspection.admission.decision != record.admission_decision
        or source_path.stat().st_size != record.repaired_source_bytes
    ):
        raise NativeCodeGenerationError("repaired proposal admission binding drift")
    return RepairedNativeCodeProposal(
        loaded=loaded,
        input_record=input_record,
        record=record,
        proposal_config_path=proposal_path,
        inspection=inspection,
    )


def _owned_locator(run_root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(run_root.resolve(strict=True)).as_posix()
    except ValueError as exc:
        raise NativeCodeGenerationError("generation artifact escapes its owning run") from exc


def _owned_regular_file(
    run_root: Path,
    locator: str,
    *,
    expected_sha256: str,
) -> Path:
    candidate = PurePosixPath(locator)
    if (
        not locator
        or candidate.is_absolute()
        or candidate.as_posix() != locator
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise NativeCodeGenerationError("generation artifact locator is not canonical")
    path = run_root / candidate
    if path.is_symlink() or not path.is_file():
        raise NativeCodeGenerationError("generation artifact is not a regular file")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(run_root.resolve(strict=True))
    except ValueError as exc:
        raise NativeCodeGenerationError("generation artifact escapes its run") from exc
    if _file_sha256(resolved) != expected_sha256:
        raise NativeCodeGenerationError("generation artifact hash drift")
    return resolved


def _read_bounded_regular(path: Path, max_bytes: int, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{label} must be a regular non-symlink file") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"{label} must be a regular non-symlink file")
        payload = bytearray()
        while len(payload) <= max_bytes:
            chunk = os.read(descriptor, min(65_536, max_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > max_bytes:
            raise ValueError(f"{label} exceeds {max_bytes} bytes")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _write_json_exclusive(path: Path, payload: object) -> None:
    _write_bytes_exclusive(path, _json_bytes(payload))


def _json_bytes(payload: object) -> bytes:
    rendered = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    return rendered.encode("utf-8")


def _write_bytes_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _reject_secret_fields(value: JsonValue) -> None:
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
            raise ValueError(f"duplicate YAML key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


__all__ = [
    "GeneratedNativeCodeProposal",
    "LoadedNativeCodeGeneration",
    "LoadedNativeCodeRepair",
    "NativeCodeGenerationConfig",
    "NativeCodeGenerationError",
    "NativeCodeGenerationInput",
    "NativeCodeGenerationInputRecord",
    "NativeCodeGenerationNode",
    "NativeCodeGenerationOutput",
    "NativeCodeGenerationRecord",
    "NativeCodeRepairConfig",
    "NativeCodeRepairInput",
    "NativeCodeRepairInputRecord",
    "NativeCodeRepairNode",
    "NativeCodeRepairOutput",
    "NativeCodeRepairRecord",
    "NativeCodeRuntimeFailure",
    "RepairedNativeCodeProposal",
    "generate_native_code_proposal",
    "load_native_code_generation_config",
    "load_native_code_generation_record",
    "load_native_code_repair_config",
    "load_native_code_repair_record",
    "repair_native_code_proposal",
    "validate_native_code_repair_binding",
    "verify_native_code_generation_ledger",
]

"""Strict contracts for proposal-only Tool Intelligence nodes."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
ScopedIdentifier: TypeAlias = Annotated[
    str,
    Field(pattern=_IDENTIFIER_PATTERN, max_length=128),
]


class ToolIntelligenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ControlledToolName(StrEnum):
    """First-party capabilities admitted by the initial read-only catalog."""

    KNOWLEDGE_QUERY = "knowledge.query"
    EVIDENCE_INSPECT = "evidence.inspect"
    REGISTERED_RUN_COMPARE = "registered-run.compare"


class ToolAuthorityBoundary(ToolIntelligenceModel):
    """Capabilities that a v1 controlled tool profile can never grant."""

    schema_version: Literal["1.0"] = "1.0"
    read_only: Literal[True] = True
    network_access: Literal[False] = False
    filesystem_write: Literal[False] = False
    process_launch: Literal[False] = False
    state_mutation: Literal[False] = False
    direct_execution: Literal[False] = False


class _PermissionBase(ToolIntelligenceModel):
    @staticmethod
    def _unique(values: tuple[str, ...], label: str) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError(f"{label} must not contain duplicates")
        return tuple(sorted(values))


class KnowledgeQueryPermission(_PermissionBase):
    tool_name: Literal[ControlledToolName.KNOWLEDGE_QUERY] = ControlledToolName.KNOWLEDGE_QUERY
    allowed_library_ids: tuple[ScopedIdentifier, ...] = Field(
        min_length=1,
        max_length=32,
    )
    max_library_ids: int = Field(ge=1, le=32)
    max_query_chars: int = Field(default=500, ge=1, le=4_000)
    max_top_k: int = Field(default=10, ge=1, le=100)

    @field_validator("allowed_library_ids")
    @classmethod
    def library_ids_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return cls._unique(values, "allowed library IDs")

    @model_validator(mode="after")
    def library_limit_is_reachable(self) -> KnowledgeQueryPermission:
        if self.max_library_ids > len(self.allowed_library_ids):
            raise ValueError("max_library_ids exceeds the allowed library scope")
        return self


class EvidenceInspectPermission(_PermissionBase):
    tool_name: Literal[ControlledToolName.EVIDENCE_INSPECT] = ControlledToolName.EVIDENCE_INSPECT
    allowed_evidence_ids: tuple[ScopedIdentifier, ...] = Field(
        min_length=1,
        max_length=256,
    )
    max_evidence_items: int = Field(ge=1, le=64)

    @field_validator("allowed_evidence_ids")
    @classmethod
    def evidence_ids_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return cls._unique(values, "allowed evidence IDs")

    @model_validator(mode="after")
    def evidence_limit_is_reachable(self) -> EvidenceInspectPermission:
        if self.max_evidence_items > len(self.allowed_evidence_ids):
            raise ValueError("max_evidence_items exceeds the allowed evidence scope")
        return self


class RegisteredRunComparePermission(_PermissionBase):
    tool_name: Literal[ControlledToolName.REGISTERED_RUN_COMPARE] = (
        ControlledToolName.REGISTERED_RUN_COMPARE
    )
    allowed_run_ids: tuple[ScopedIdentifier, ...] = Field(min_length=2, max_length=64)
    allowed_metric_names: tuple[ScopedIdentifier, ...] = Field(min_length=1, max_length=64)
    max_runs: int = Field(ge=2, le=16)
    max_metrics: int = Field(ge=1, le=32)

    @field_validator("allowed_run_ids")
    @classmethod
    def run_ids_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return cls._unique(values, "allowed run IDs")

    @field_validator("allowed_metric_names")
    @classmethod
    def metric_names_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return cls._unique(values, "allowed metric names")

    @model_validator(mode="after")
    def comparison_limits_are_reachable(self) -> RegisteredRunComparePermission:
        if self.max_runs > len(self.allowed_run_ids):
            raise ValueError("max_runs exceeds the allowed run scope")
        if self.max_metrics > len(self.allowed_metric_names):
            raise ValueError("max_metrics exceeds the allowed metric scope")
        return self


ControlledToolPermission: TypeAlias = Annotated[
    KnowledgeQueryPermission | EvidenceInspectPermission | RegisteredRunComparePermission,
    Field(discriminator="tool_name"),
]


class ControlledToolProfile(ToolIntelligenceModel):
    """Content-addressed authority and resource limits for one tool plan."""

    schema_version: Literal["1.0"] = "1.0"
    profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    profile_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    permissions: tuple[ControlledToolPermission, ...] = Field(
        min_length=1,
        max_length=3,
    )
    max_plan_steps: int = Field(default=6, ge=1, le=32)
    max_dependency_edges: int = Field(default=8, ge=0, le=64)
    authority: ToolAuthorityBoundary = Field(default_factory=ToolAuthorityBoundary)
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def tool_permissions_are_unique(self) -> ControlledToolProfile:
        names = [item.tool_name.value for item in self.permissions]
        if len(names) != len(set(names)):
            raise ValueError("controlled tool permissions must be unique")
        return self

    @property
    def allowed_tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(item.tool_name.value for item in self.permissions))

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))

    def permission_for(self, name: ControlledToolName) -> ControlledToolPermission | None:
        return next((item for item in self.permissions if item.tool_name == name), None)


class ToolScopeProjection(ToolIntelligenceModel):
    """Caller-owned identifiers visible to one proposal; it grants no capability."""

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(min_length=1, max_length=128)
    state_snapshot_id: str = Field(min_length=1, max_length=256)
    library_ids: tuple[ScopedIdentifier, ...] = Field(default=(), max_length=32)
    evidence_ids: tuple[ScopedIdentifier, ...] = Field(default=(), max_length=256)
    run_ids: tuple[ScopedIdentifier, ...] = Field(default=(), max_length=64)
    metric_names: tuple[ScopedIdentifier, ...] = Field(default=(), max_length=64)

    @field_validator("library_ids", "evidence_ids", "run_ids", "metric_names")
    @classmethod
    def scope_values_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("tool scope identifiers must not contain duplicates")
        return tuple(sorted(values))

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class KnowledgeQueryArguments(ToolIntelligenceModel):
    query: str = Field(min_length=1, max_length=4_000)
    library_ids: tuple[ScopedIdentifier, ...] = Field(min_length=1, max_length=32)
    top_k: int = Field(ge=1, le=100)

    @field_validator("library_ids")
    @classmethod
    def library_ids_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("query library IDs must not contain duplicates")
        return tuple(sorted(values))


class EvidenceInspectArguments(ToolIntelligenceModel):
    evidence_ids: tuple[ScopedIdentifier, ...] = Field(min_length=1, max_length=64)
    include_provenance: bool = True

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("inspection evidence IDs must not contain duplicates")
        return tuple(sorted(values))


class RegisteredRunCompareArguments(ToolIntelligenceModel):
    run_ids: tuple[ScopedIdentifier, ...] = Field(min_length=2, max_length=16)
    metric_names: tuple[ScopedIdentifier, ...] = Field(min_length=1, max_length=32)

    @field_validator("run_ids", "metric_names")
    @classmethod
    def comparison_values_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("comparison identifiers must not contain duplicates")
        return tuple(sorted(values))


class _ToolPlanStepBase(ToolIntelligenceModel):
    step_id: ScopedIdentifier
    depends_on: tuple[ScopedIdentifier, ...] = Field(default=(), max_length=16)
    purpose: str = Field(min_length=1, max_length=1_000)
    advisory_only: Literal[True] = True
    executable: Literal[False] = False

    @field_validator("depends_on")
    @classmethod
    def dependencies_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("step dependencies must not contain duplicates")
        return values


class KnowledgeQueryStep(_ToolPlanStepBase):
    tool_name: Literal[ControlledToolName.KNOWLEDGE_QUERY] = ControlledToolName.KNOWLEDGE_QUERY
    arguments: KnowledgeQueryArguments


class EvidenceInspectStep(_ToolPlanStepBase):
    tool_name: Literal[ControlledToolName.EVIDENCE_INSPECT] = ControlledToolName.EVIDENCE_INSPECT
    arguments: EvidenceInspectArguments


class RegisteredRunCompareStep(_ToolPlanStepBase):
    tool_name: Literal[ControlledToolName.REGISTERED_RUN_COMPARE] = (
        ControlledToolName.REGISTERED_RUN_COMPARE
    )
    arguments: RegisteredRunCompareArguments


ToolPlanStep: TypeAlias = Annotated[
    KnowledgeQueryStep | EvidenceInspectStep | RegisteredRunCompareStep,
    Field(discriminator="tool_name"),
]


class ToolPlanInput(ToolIntelligenceModel):
    objective: str = Field(min_length=1, max_length=4_000)
    scope: ToolScopeProjection
    tool_profile: ControlledToolProfile


class ToolPlanOutput(ToolIntelligenceModel):
    tool_profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    tool_profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    steps: tuple[ToolPlanStep, ...] = Field(min_length=1, max_length=32)
    rationale: str = Field(min_length=1, max_length=4_000)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    advisory_only: Literal[True] = True
    executable: Literal[False] = False

    @model_validator(mode="after")
    def step_ids_are_unique(self) -> ToolPlanOutput:
        identifiers = [item.step_id for item in self.steps]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("tool plan step IDs must be unique")
        return self


RepairTargetNodeName: TypeAlias = Literal[
    "review-semantic",
    "interpretation-threat",
    "ambiguous-action",
    "tool-plan",
]


class SanitizedValidationIssue(ToolIntelligenceModel):
    location: str = Field(pattern=r"^[A-Za-z0-9_.\[\]-]+$", max_length=256)
    error_type: str = Field(pattern=r"^[a-z0-9_.-]+$", max_length=128)


class StructuredRepairInput(ToolIntelligenceModel):
    target_node_name: RepairTargetNodeName
    target_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    invalid_payload: JsonValue
    invalid_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_issues: tuple[SanitizedValidationIssue, ...] = Field(
        min_length=1,
        max_length=32,
    )

    @model_validator(mode="after")
    def invalid_payload_is_hash_bound_and_bounded(self) -> StructuredRepairInput:
        encoded = canonical_json(self.invalid_payload)
        if len(encoded) > 32_768:
            raise ValueError("invalid structured payload exceeds 32768 bytes")
        if hashlib.sha256(encoded).hexdigest() != self.invalid_payload_sha256:
            raise ValueError("invalid_payload_sha256 does not match invalid_payload")
        return self


class StructuredRepairOutput(ToolIntelligenceModel):
    target_node_name: RepairTargetNodeName
    target_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    repaired_payload: JsonValue
    change_summary: tuple[str, ...] = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    repair_proposal_only: Literal[True] = True
    advisory_only: Literal[True] = True
    executable: Literal[False] = False

    @field_validator("change_summary")
    @classmethod
    def summaries_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or len(value) > 1_000 for value in values):
            raise ValueError("repair change summaries must contain 1-1000 characters")
        return values

    @model_validator(mode="after")
    def repaired_payload_is_bounded(self) -> StructuredRepairOutput:
        if len(canonical_json(self.repaired_payload)) > 32_768:
            raise ValueError("repaired structured payload exceeds 32768 bytes")
        return self


def canonical_json(value: JsonValue | dict[str, object]) -> bytes:
    """Encode hash-bound JSON without accepting non-finite extensions."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def canonical_sha256(value: JsonValue | dict[str, object]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def output_schema_sha256(model_type: type[BaseModel]) -> str:
    return canonical_sha256(model_type.model_json_schema(mode="validation"))


__all__ = [
    "ControlledToolName",
    "ControlledToolPermission",
    "ControlledToolProfile",
    "EvidenceInspectArguments",
    "EvidenceInspectPermission",
    "EvidenceInspectStep",
    "KnowledgeQueryArguments",
    "KnowledgeQueryPermission",
    "KnowledgeQueryStep",
    "RegisteredRunCompareArguments",
    "RegisteredRunComparePermission",
    "RegisteredRunCompareStep",
    "RepairTargetNodeName",
    "SanitizedValidationIssue",
    "StructuredRepairInput",
    "StructuredRepairOutput",
    "ToolAuthorityBoundary",
    "ToolPlanInput",
    "ToolPlanOutput",
    "ToolPlanStep",
    "ToolScopeProjection",
    "canonical_json",
    "canonical_sha256",
    "output_schema_sha256",
]

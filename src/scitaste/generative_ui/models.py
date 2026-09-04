"""Evidence-grounded, non-executable generative UI contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from scitaste.generative_ui.registry import (
    COMPONENT_REGISTRY,
    ApprovalSubject,
    EvidenceKind,
    ProposalKind,
    SurfacePurpose,
    TrustedComponent,
)
from scitaste.generative_ui.safety import (
    ProjectIdentifier,
    SafeIdentifier,
    SafeLocator,
    SafeText,
    Sha256,
    contains_key,
    declarative_dict,
)
from scitaste.schema.actions import MetaAction

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvidenceRef(BaseModel):
    """Content-addressed evidence available in one project snapshot."""

    model_config = _MODEL_CONFIG

    evidence_id: SafeIdentifier
    project_id: ProjectIdentifier
    kind: EvidenceKind
    locator: SafeLocator
    sha256: Sha256
    label: SafeText


class SnapshotBinding(BaseModel):
    """Immutable identity of the project state used to generate a surface."""

    model_config = _MODEL_CONFIG

    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    evidence_refs: list[EvidenceRef] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_belongs_to_one_snapshot(self) -> SnapshotBinding:
        ids = [item.evidence_id for item in self.evidence_refs]
        if len(ids) != len(set(ids)):
            raise ValueError("snapshot evidence IDs must be unique")
        foreign = [
            item.evidence_id for item in self.evidence_refs if item.project_id != self.project_id
        ]
        if foreign:
            raise ValueError(f"snapshot evidence belongs to another project: {sorted(foreign)}")
        return self


class ComponentSpec(BaseModel):
    """One trusted native component with data-only, evidence-linked content."""

    model_config = _MODEL_CONFIG

    component_id: SafeIdentifier
    component: TrustedComponent
    title: SafeText
    evidence_ref_ids: list[SafeIdentifier] = Field(min_length=1)
    data: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def content_is_declarative(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return declarative_dict(value)

    @model_validator(mode="after")
    def evidence_ids_are_unique(self) -> ComponentSpec:
        if len(self.evidence_ref_ids) != len(set(self.evidence_ref_ids)):
            raise ValueError("component evidence references must be unique")
        return self


class InspectArtifactPayload(BaseModel):
    model_config = _MODEL_CONFIG

    kind: Literal[ProposalKind.INSPECT_ARTIFACT]
    artifact_ref_id: SafeIdentifier
    view: Literal["metadata", "preview", "source"] = "preview"


class CompareRunsPayload(BaseModel):
    model_config = _MODEL_CONFIG

    kind: Literal[ProposalKind.COMPARE_RUNS]
    baseline_run_ref_id: SafeIdentifier
    candidate_run_ref_id: SafeIdentifier
    metric_names: list[SafeIdentifier] = Field(min_length=1)

    @model_validator(mode="after")
    def comparison_is_well_formed(self) -> CompareRunsPayload:
        if self.baseline_run_ref_id == self.candidate_run_ref_id:
            raise ValueError("run comparison requires two distinct run evidence references")
        if len(self.metric_names) != len(set(self.metric_names)):
            raise ValueError("comparison metric names must be unique")
        return self


class ProposeTransitionPayload(BaseModel):
    model_config = _MODEL_CONFIG

    kind: Literal[ProposalKind.PROPOSE_TRANSITION]
    from_stage: SafeIdentifier
    proposed_action: MetaAction
    decision_ref_id: SafeIdentifier


class RequestApprovalPayload(BaseModel):
    model_config = _MODEL_CONFIG

    kind: Literal[ProposalKind.REQUEST_APPROVAL]
    subject: ApprovalSubject
    subject_ref_ids: list[SafeIdentifier] = Field(min_length=1)
    question: SafeText

    @model_validator(mode="after")
    def subject_refs_are_unique(self) -> RequestApprovalPayload:
        if len(self.subject_ref_ids) != len(set(self.subject_ref_ids)):
            raise ValueError("approval subject references must be unique")
        return self


ProposalPayload = Annotated[
    InspectArtifactPayload | CompareRunsPayload | ProposeTransitionPayload | RequestApprovalPayload,
    Field(discriminator="kind"),
]


class ActionProposal(BaseModel):
    """Typed advice with an explicit absence of execution authority."""

    model_config = _MODEL_CONFIG

    payload: ProposalPayload
    rationale: SafeText
    evidence_ref_ids: list[SafeIdentifier] = Field(min_length=1)
    requires_approval: bool = False
    authority: Literal["proposal_only"] = "proposal_only"

    @model_validator(mode="after")
    def proposal_is_bounded(self) -> ActionProposal:
        if len(self.evidence_ref_ids) != len(set(self.evidence_ref_ids)):
            raise ValueError("proposal evidence references must be unique")
        payload_refs = _payload_ref_ids(self.payload)
        missing = payload_refs - set(self.evidence_ref_ids)
        if missing:
            raise ValueError(f"proposal payload references undeclared evidence: {sorted(missing)}")
        if (
            self.payload.kind
            in {
                ProposalKind.PROPOSE_TRANSITION,
                ProposalKind.REQUEST_APPROVAL,
            }
            and not self.requires_approval
        ):
            raise ValueError(f"{self.payload.kind.value} proposals require human approval")
        return self


class ActionBinding(BaseModel):
    """Bind a proposal to a visible component without adding an executable callback."""

    model_config = _MODEL_CONFIG

    action_id: SafeIdentifier
    component_id: SafeIdentifier
    label: SafeText
    proposal: ActionProposal
    presentation: Literal["button", "menu_item", "inline"] = "button"


class SurfaceSpec(BaseModel):
    """Complete declarative workspace generated from one immutable snapshot."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    surface_id: SafeIdentifier
    revision: int = Field(default=0, ge=0)
    purpose: SurfacePurpose
    title: SafeText
    project_id: ProjectIdentifier
    snapshot: SnapshotBinding
    components: list[ComponentSpec] = Field(min_length=1)
    actions: list[ActionBinding] = Field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @model_validator(mode="after")
    def surface_has_closed_references(self) -> SurfaceSpec:
        if self.project_id != self.snapshot.project_id:
            raise ValueError("surface project_id must match its snapshot binding")
        component_ids = [item.component_id for item in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("surface component IDs must be unique")
        action_ids = [item.action_id for item in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("surface action IDs must be unique")

        evidence = {item.evidence_id: item for item in self.snapshot.evidence_refs}
        components = {item.component_id: item for item in self.components}
        for component in self.components:
            _validate_component_evidence(component, evidence)
        for action in self.actions:
            if action.component_id not in components:
                raise ValueError(
                    f"action {action.action_id!r} references unknown component "
                    f"{action.component_id!r}"
                )
            unknown = set(action.proposal.evidence_ref_ids) - evidence.keys()
            if unknown:
                raise ValueError(
                    f"action {action.action_id!r} references missing evidence: {sorted(unknown)}"
                )
            component_refs = set(components[action.component_id].evidence_ref_ids)
            outside_component = set(action.proposal.evidence_ref_ids) - component_refs
            if outside_component:
                raise ValueError(
                    f"action {action.action_id!r} is not grounded by its component: "
                    f"{sorted(outside_component)}"
                )
            _validate_proposal_evidence(action.proposal.payload, evidence)
        return self


class SurfaceRevision(BaseModel):
    """Auditable replacement of a prior surface; never a patch to executable state."""

    model_config = _MODEL_CONFIG

    revision_id: SafeIdentifier
    surface_id: SafeIdentifier
    previous_revision: int = Field(ge=0)
    previous_fingerprint: Sha256
    surface: SurfaceSpec
    changed_component_ids: list[SafeIdentifier] = Field(default_factory=list)
    removed_component_ids: list[SafeIdentifier] = Field(default_factory=list)
    evidence_ref_ids: list[SafeIdentifier] = Field(min_length=1)
    reason: SafeText

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def revision_is_consistent(self) -> SurfaceRevision:
        if self.surface_id != self.surface.surface_id:
            raise ValueError("revision surface_id must match the replacement surface")
        if self.surface.revision <= self.previous_revision:
            raise ValueError("replacement surface revision must increase")
        changed = self.changed_component_ids
        removed = self.removed_component_ids
        if len(changed) != len(set(changed)) or len(removed) != len(set(removed)):
            raise ValueError("revision component IDs must be unique")
        if set(changed) & set(removed):
            raise ValueError("a component cannot be both changed and removed")
        current_ids = {item.component_id for item in self.surface.components}
        unknown_changed = set(changed) - current_ids
        retained_removed = set(removed) & current_ids
        if unknown_changed:
            raise ValueError(f"changed components are absent: {sorted(unknown_changed)}")
        if retained_removed:
            raise ValueError(f"removed components remain present: {sorted(retained_removed)}")
        if len(self.evidence_ref_ids) != len(set(self.evidence_ref_ids)):
            raise ValueError("revision evidence references must be unique")
        available = {item.evidence_id for item in self.surface.snapshot.evidence_refs}
        missing = set(self.evidence_ref_ids) - available
        if missing:
            raise ValueError(f"revision references missing evidence: {sorted(missing)}")
        return self


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _payload_ref_ids(payload: ProposalPayload) -> set[str]:
    if isinstance(payload, InspectArtifactPayload):
        return {payload.artifact_ref_id}
    if isinstance(payload, CompareRunsPayload):
        return {payload.baseline_run_ref_id, payload.candidate_run_ref_id}
    if isinstance(payload, ProposeTransitionPayload):
        return {payload.decision_ref_id}
    return set(payload.subject_ref_ids)


def _validate_component_evidence(
    component: ComponentSpec,
    evidence: dict[str, EvidenceRef],
) -> None:
    unknown = set(component.evidence_ref_ids) - evidence.keys()
    if unknown:
        raise ValueError(
            f"component {component.component_id!r} references missing evidence: {sorted(unknown)}"
        )
    kinds = {evidence[item].kind for item in component.evidence_ref_ids}
    required = COMPONENT_REGISTRY[component.component].required_kinds
    missing_kinds = required - kinds
    if missing_kinds:
        values = sorted(item.value for item in missing_kinds)
        raise ValueError(
            f"component {component.component_id!r} lacks required evidence kinds: {values}"
        )
    if contains_key(component.data, {"paper_path", "paper_status", "paper_title"}) and (
        EvidenceKind.PAPER not in kinds
    ):
        raise ValueError(f"component {component.component_id!r} has an ungrounded paper claim")
    if contains_key(
        component.data,
        {"health_status", "project_status", "publication_ready", "run_status", "status"},
    ) and not kinds.intersection(
        {
            EvidenceKind.PROJECT_MANIFEST,
            EvidenceKind.STAGE_RECORD,
            EvidenceKind.BLOCKER,
            EvidenceKind.RUN_RECORD,
            EvidenceKind.DECISION,
            EvidenceKind.REVIEW,
            EvidenceKind.PAPER,
        }
    ):
        raise ValueError(f"component {component.component_id!r} has an ungrounded status claim")


def _validate_proposal_evidence(
    payload: ProposalPayload,
    evidence: dict[str, EvidenceRef],
) -> None:
    if isinstance(payload, InspectArtifactPayload):
        if evidence[payload.artifact_ref_id].kind not in {
            EvidenceKind.ARTIFACT,
            EvidenceKind.PAPER,
        }:
            raise ValueError("inspect_artifact must target artifact or paper evidence")
    elif isinstance(payload, CompareRunsPayload):
        refs = [payload.baseline_run_ref_id, payload.candidate_run_ref_id]
        if any(evidence[item].kind != EvidenceKind.RUN_RECORD for item in refs):
            raise ValueError("compare_runs must target two run records")
    elif isinstance(payload, ProposeTransitionPayload):
        if evidence[payload.decision_ref_id].kind != EvidenceKind.DECISION:
            raise ValueError("propose_transition must cite decision evidence")

"""Project validated surfaces into a fixed-shell renderer document."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from scitaste.generative_ui.models import (
    ComponentSpec,
    SnapshotBinding,
    SurfaceSpec,
    _validate_component_evidence,
    validate_component_data,
)
from scitaste.generative_ui.registry import ProposalKind, TrustedComponent
from scitaste.generative_ui.safety import (
    ProjectIdentifier,
    SafeIdentifier,
    SafeText,
    Sha256,
    declarative_dict,
)

_MODEL_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class FixedApplicationShell(BaseModel):
    """Receiver-owned shell; generated content can populate only ``workspace``."""

    model_config = _MODEL_CONFIG

    shell_id: Literal["scitaste-research-shell"] = "scitaste-research-shell"
    shell_version: Literal["1.0"] = "1.0"
    fixed_regions: tuple[
        Literal["header"],
        Literal["project_nav"],
        Literal["workspace"],
        Literal["inspector"],
    ] = (
        "header",
        "project_nav",
        "workspace",
        "inspector",
    )
    generated_region: Literal["workspace"] = "workspace"


class RendererComponent(BaseModel):
    """A native component instance; ``renderer`` is selected from the trusted catalog."""

    model_config = _MODEL_CONFIG

    component_id: SafeIdentifier
    renderer: TrustedComponent
    region: Literal["workspace"] = "workspace"
    title: SafeText
    evidence_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    data: dict[str, JsonValue]

    @field_validator("data")
    @classmethod
    def content_is_declarative(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return declarative_dict(value)

    @model_validator(mode="after")
    def data_and_evidence_ids_are_valid(self) -> RendererComponent:
        if len(self.evidence_ref_ids) != len(set(self.evidence_ref_ids)):
            raise ValueError("renderer component evidence references must be unique")
        object.__setattr__(self, "data", validate_component_data(self.renderer, self.data))
        return self


class RendererAction(BaseModel):
    """Client-visible event metadata without the server-owned proposal payload."""

    model_config = _MODEL_CONFIG

    action_id: SafeIdentifier
    component_id: SafeIdentifier
    label: SafeText
    presentation: Literal["button", "menu_item", "inline"]
    event_type: Literal["surface_action_requested"] = "surface_action_requested"
    proposal_kind: ProposalKind
    requires_approval: bool


class RendererDocument(BaseModel):
    """Framework-neutral document consumed by a trusted native renderer."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    catalog_version: Literal[
        "scitaste-trusted-components-v1",
        "scitaste-trusted-components-v2",
        "scitaste-trusted-components-v3",
    ] = "scitaste-trusted-components-v1"
    shell: FixedApplicationShell
    project_id: ProjectIdentifier
    surface_id: SafeIdentifier
    surface_revision: int = Field(ge=0)
    surface_fingerprint: Sha256
    title: SafeText
    snapshot: SnapshotBinding
    components: tuple[RendererComponent, ...] = Field(min_length=1)
    actions: tuple[RendererAction, ...]
    execution_authority: Literal["none"] = "none"

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @model_validator(mode="after")
    def bindings_are_closed(self) -> RendererDocument:
        if self.project_id != self.snapshot.project_id:
            raise ValueError("renderer project_id must match the snapshot binding")
        component_ids = [item.component_id for item in self.components]
        action_ids = [item.action_id for item in self.actions]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("renderer component IDs must be unique")
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("renderer action IDs must be unique")
        unknown = {item.component_id for item in self.actions} - set(component_ids)
        if unknown:
            raise ValueError(f"renderer actions reference unknown components: {sorted(unknown)}")
        evidence = {item.evidence_id: item for item in self.snapshot.evidence_refs}
        for item in self.components:
            component = ComponentSpec(
                component_id=item.component_id,
                component=item.renderer,
                title=item.title,
                evidence_ref_ids=list(item.evidence_ref_ids),
                data=item.data,
            )
            _validate_component_evidence(component, evidence)
        return self


def project_surface(surface: SurfaceSpec) -> RendererDocument:
    """Create a data-only renderer document from an already validated surface."""

    surface = SurfaceSpec.model_validate(surface.model_dump(mode="json"))
    component_kinds = {component.component for component in surface.components}
    if TrustedComponent.RESEARCH_LANDSCAPE_MAP in component_kinds:
        catalog_version = "scitaste-trusted-components-v3"
    elif TrustedComponent.PROJECT_PROGRESS_BOARD in component_kinds:
        catalog_version = "scitaste-trusted-components-v2"
    else:
        catalog_version = "scitaste-trusted-components-v1"
    return RendererDocument(
        catalog_version=catalog_version,
        shell=FixedApplicationShell(),
        project_id=surface.project_id,
        surface_id=surface.surface_id,
        surface_revision=surface.revision,
        surface_fingerprint=surface.fingerprint,
        title=surface.title,
        snapshot=surface.snapshot,
        components=tuple(
            RendererComponent(
                component_id=component.component_id,
                renderer=component.component,
                title=component.title,
                evidence_ref_ids=tuple(component.evidence_ref_ids),
                data=component.data,
            )
            for component in surface.components
        ),
        actions=tuple(
            RendererAction(
                action_id=action.action_id,
                component_id=action.component_id,
                label=action.label,
                presentation=action.presentation,
                proposal_kind=action.proposal.payload.kind,
                requires_approval=action.proposal.requires_approval,
            )
            for action in surface.actions
        ),
    )

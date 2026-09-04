"""Safe declarative contracts for evidence-grounded generative interfaces."""

from scitaste.generative_ui.fixtures import (
    build_blocked_run_fixture,
    build_fixture_surfaces,
    build_next_step_fixture,
    build_paper_status_fixture,
    build_project_overview_fixture,
    build_run_comparison_fixture,
    fixture_snapshot_binding,
)
from scitaste.generative_ui.models import (
    ActionBinding,
    ActionProposal,
    CompareRunsPayload,
    ComponentSpec,
    EvidenceRef,
    InspectArtifactPayload,
    ProposeTransitionPayload,
    RequestApprovalPayload,
    SnapshotBinding,
    SurfaceRevision,
    SurfaceSpec,
)
from scitaste.generative_ui.registry import (
    COMPONENT_REGISTRY,
    ApprovalSubject,
    EvidenceKind,
    ProposalKind,
    SurfacePurpose,
    TrustedComponent,
)

__all__ = [
    "COMPONENT_REGISTRY",
    "ActionBinding",
    "ActionProposal",
    "ApprovalSubject",
    "CompareRunsPayload",
    "ComponentSpec",
    "EvidenceKind",
    "EvidenceRef",
    "InspectArtifactPayload",
    "ProposalKind",
    "ProposeTransitionPayload",
    "RequestApprovalPayload",
    "SnapshotBinding",
    "SurfacePurpose",
    "SurfaceRevision",
    "SurfaceSpec",
    "TrustedComponent",
    "build_blocked_run_fixture",
    "build_fixture_surfaces",
    "build_next_step_fixture",
    "build_paper_status_fixture",
    "build_project_overview_fixture",
    "build_run_comparison_fixture",
    "fixture_snapshot_binding",
]

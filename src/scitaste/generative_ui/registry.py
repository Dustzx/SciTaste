"""Closed registries for declarative generative-research surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EvidenceKind(StrEnum):
    """Evidence identities accepted by the UI contract."""

    PROJECT_MANIFEST = "project_manifest"
    STAGE_RECORD = "stage_record"
    BLOCKER = "blocker"
    RUN_RECORD = "run_record"
    RESOURCE_USAGE = "resource_usage"
    DECISION = "decision"
    EVIDENCE_RECORD = "evidence_record"
    CLAIM = "claim"
    REVIEW = "review"
    ARTIFACT = "artifact"
    PAPER = "paper"
    AUDIT_RECORD = "audit_record"


class TrustedComponent(StrEnum):
    """Components a trusted renderer may map to native UI widgets."""

    PROJECT_SUMMARY_CARD = "ProjectSummaryCard"
    STAGE_TIMELINE = "StageTimeline"
    BLOCKER_LIST = "BlockerList"
    RUN_HEALTH = "RunHealth"
    BUDGET_METER = "BudgetMeter"
    DECISION_COMPARISON = "DecisionComparison"
    EVIDENCE_GRAPH = "EvidenceGraph"
    CLAIM_MATRIX = "ClaimMatrix"
    REVIEWER_QUEUE = "ReviewerQueue"
    ARTIFACT_VIEWER = "ArtifactViewer"
    PAPER_PREVIEW = "PaperPreview"
    AVAILABILITY_NOTICE = "AvailabilityNotice"
    RUN_STAGE_EXPLORER = "RunStageExplorer"
    EVIDENCE_INVENTORY = "EvidenceInventory"
    RUN_COMPARISON_PANEL = "RunComparisonPanel"
    RUN_BLOCKER_PANEL = "RunBlockerPanel"
    PENDING_PROPOSAL_LIST = "PendingProposalList"


class SurfacePurpose(StrEnum):
    PROJECT_OVERVIEW = "project_overview"
    PAPER_STATUS = "paper_status"
    BLOCKED_RUN = "blocked_run"
    NEXT_STEP = "next_step"
    RUN_COMPARISON = "run_comparison"
    RUN_STAGE_EXPLORER = "run_stage_explorer"
    PAPER_EVIDENCE = "paper_evidence"
    WORKSPACE_RUN_COMPARISON = "workspace_run_comparison"
    BLOCKER_VIEW = "blocker_view"
    PENDING_PROPOSALS = "pending_proposals"


class ProposalKind(StrEnum):
    INSPECT_ARTIFACT = "inspect_artifact"
    COMPARE_RUNS = "compare_runs"
    PROPOSE_TRANSITION = "propose_transition"
    REQUEST_APPROVAL = "request_approval"


class ApprovalSubject(StrEnum):
    TRANSITION = "transition"
    ARTIFACT_RELEASE = "artifact_release"
    PAPER_SELECTION = "paper_selection"
    RUN_SELECTION = "run_selection"
    BLOCKER_DISPOSITION = "blocker_disposition"


APPROVAL_EVIDENCE_KINDS: dict[ApprovalSubject, frozenset[EvidenceKind]] = {
    ApprovalSubject.TRANSITION: frozenset({EvidenceKind.DECISION}),
    ApprovalSubject.ARTIFACT_RELEASE: frozenset({EvidenceKind.ARTIFACT, EvidenceKind.PAPER}),
    ApprovalSubject.PAPER_SELECTION: frozenset({EvidenceKind.PAPER}),
    ApprovalSubject.RUN_SELECTION: frozenset({EvidenceKind.RUN_RECORD}),
    ApprovalSubject.BLOCKER_DISPOSITION: frozenset({EvidenceKind.BLOCKER}),
}


@dataclass(frozen=True)
class ComponentPolicy:
    """Evidence kinds that must ground one trusted component."""

    required_kinds: frozenset[EvidenceKind]


COMPONENT_REGISTRY: dict[TrustedComponent, ComponentPolicy] = {
    TrustedComponent.PROJECT_SUMMARY_CARD: ComponentPolicy(
        frozenset({EvidenceKind.PROJECT_MANIFEST})
    ),
    TrustedComponent.STAGE_TIMELINE: ComponentPolicy(frozenset({EvidenceKind.STAGE_RECORD})),
    TrustedComponent.BLOCKER_LIST: ComponentPolicy(frozenset({EvidenceKind.BLOCKER})),
    TrustedComponent.RUN_HEALTH: ComponentPolicy(frozenset({EvidenceKind.RUN_RECORD})),
    TrustedComponent.BUDGET_METER: ComponentPolicy(frozenset({EvidenceKind.RESOURCE_USAGE})),
    TrustedComponent.DECISION_COMPARISON: ComponentPolicy(
        frozenset({EvidenceKind.DECISION, EvidenceKind.RUN_RECORD})
    ),
    TrustedComponent.EVIDENCE_GRAPH: ComponentPolicy(frozenset({EvidenceKind.EVIDENCE_RECORD})),
    TrustedComponent.CLAIM_MATRIX: ComponentPolicy(
        frozenset({EvidenceKind.CLAIM, EvidenceKind.EVIDENCE_RECORD})
    ),
    TrustedComponent.REVIEWER_QUEUE: ComponentPolicy(frozenset({EvidenceKind.REVIEW})),
    TrustedComponent.ARTIFACT_VIEWER: ComponentPolicy(frozenset({EvidenceKind.ARTIFACT})),
    TrustedComponent.PAPER_PREVIEW: ComponentPolicy(frozenset({EvidenceKind.PAPER})),
    TrustedComponent.AVAILABILITY_NOTICE: ComponentPolicy(
        frozenset({EvidenceKind.PROJECT_MANIFEST})
    ),
    TrustedComponent.RUN_STAGE_EXPLORER: ComponentPolicy(
        frozenset({EvidenceKind.PROJECT_MANIFEST, EvidenceKind.RUN_RECORD})
    ),
    TrustedComponent.EVIDENCE_INVENTORY: ComponentPolicy(
        frozenset({EvidenceKind.PROJECT_MANIFEST})
    ),
    TrustedComponent.RUN_COMPARISON_PANEL: ComponentPolicy(frozenset({EvidenceKind.RUN_RECORD})),
    TrustedComponent.RUN_BLOCKER_PANEL: ComponentPolicy(frozenset({EvidenceKind.RUN_RECORD})),
    TrustedComponent.PENDING_PROPOSAL_LIST: ComponentPolicy(frozenset({EvidenceKind.AUDIT_RECORD})),
}

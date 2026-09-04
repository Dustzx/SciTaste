"""Deterministic contract fixtures for renderer and integration development."""

from __future__ import annotations

import hashlib

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
    SurfaceSpec,
)
from scitaste.generative_ui.registry import (
    ApprovalSubject,
    EvidenceKind,
    ProposalKind,
    SurfacePurpose,
    TrustedComponent,
)
from scitaste.schema.actions import MetaAction

_PROJECT_ID = "scitaste-fixture-project"


def fixture_snapshot_binding() -> SnapshotBinding:
    """Return a content-addressed sample snapshot; never use it as research evidence."""

    specifications = [
        ("project-manifest", EvidenceKind.PROJECT_MANIFEST, "PROJECT.json"),
        ("stage-analysis", EvidenceKind.STAGE_RECORD, "stages/current/stage-14/analysis.md"),
        ("blocker-record", EvidenceKind.BLOCKER, "runs/run-a/blockers.json"),
        ("run-a", EvidenceKind.RUN_RECORD, "runs/run-a/execution_record.json"),
        ("run-b", EvidenceKind.RUN_RECORD, "runs/run-b/execution_record.json"),
        ("resource-usage", EvidenceKind.RESOURCE_USAGE, "runs/run-b/usage.json"),
        ("decision-record", EvidenceKind.DECISION, "runs/run-b/decisions.jsonl"),
        ("evidence-record", EvidenceKind.EVIDENCE_RECORD, "runs/run-b/evidence.json"),
        ("claim-record", EvidenceKind.CLAIM, "runs/run-b/claims.json"),
        ("review-record", EvidenceKind.REVIEW, "papers/paper-a/peer_review.md"),
        ("paper-artifact", EvidenceKind.ARTIFACT, "papers/paper-a/paper.pdf"),
        ("paper-record", EvidenceKind.PAPER, "papers/paper-a/MANIFEST.json"),
    ]
    refs = [
        EvidenceRef(
            evidence_id=evidence_id,
            project_id=_PROJECT_ID,
            kind=kind,
            locator=locator,
            sha256=_digest(f"fixture:{evidence_id}:{locator}"),
            label=evidence_id.replace("-", " ").title(),
        )
        for evidence_id, kind, locator in specifications
    ]
    return SnapshotBinding.from_trusted_evidence(
        project_id=_PROJECT_ID,
        snapshot_revision=7,
        evidence_refs=refs,
    )


def build_project_overview_fixture(
    snapshot: SnapshotBinding | None = None,
) -> SurfaceSpec:
    binding = snapshot or fixture_snapshot_binding()
    return SurfaceSpec(
        surface_id="project-overview",
        revision=1,
        purpose=SurfacePurpose.PROJECT_OVERVIEW,
        title="Project overview",
        project_id=binding.project_id,
        snapshot=binding,
        components=[
            ComponentSpec(
                component_id="project-summary",
                component=TrustedComponent.PROJECT_SUMMARY_CARD,
                title="SciTaste fixture project",
                evidence_ref_ids=["project-manifest"],
                data={
                    "project_ref_id": "project-manifest",
                    "project_status": "active",
                    "publication_ready": False,
                    "current_focus": "Evidence-grounded interface contracts",
                },
            ),
            ComponentSpec(
                component_id="stage-timeline",
                component=TrustedComponent.STAGE_TIMELINE,
                title="Current stage",
                evidence_ref_ids=["stage-analysis"],
                data={
                    "stages": [
                        {
                            "stage_ref_id": "stage-analysis",
                            "stage": 13,
                            "status": "completed",
                        },
                        {
                            "stage_ref_id": "stage-analysis",
                            "stage": 14,
                            "status": "active",
                        },
                    ]
                },
            ),
            ComponentSpec(
                component_id="budget-meter",
                component=TrustedComponent.BUDGET_METER,
                title="Resource budget",
                evidence_ref_ids=["resource-usage"],
                data={
                    "usage_ref_id": "resource-usage",
                    "resources": [
                        {
                            "resource": "model-tokens",
                            "used": 2400,
                            "limit": 10000,
                            "unit": "tokens",
                        }
                    ],
                },
            ),
            ComponentSpec(
                component_id="evidence-graph",
                component=TrustedComponent.EVIDENCE_GRAPH,
                title="Evidence graph",
                evidence_ref_ids=["evidence-record", "claim-record"],
                data={
                    "nodes": [
                        {
                            "evidence_ref_id": "evidence-record",
                            "kind": "evidence_record",
                            "label": "Registered evidence",
                        },
                        {
                            "evidence_ref_id": "claim-record",
                            "kind": "claim",
                            "label": "Registered claim",
                        },
                    ],
                    "edges": [
                        {
                            "source_ref_id": "evidence-record",
                            "target_ref_id": "claim-record",
                            "relation": "supports",
                        }
                    ],
                },
            ),
            ComponentSpec(
                component_id="claim-matrix",
                component=TrustedComponent.CLAIM_MATRIX,
                title="Claim coverage",
                evidence_ref_ids=["claim-record", "evidence-record"],
                data={
                    "claims": [
                        {
                            "claim_ref_id": "claim-record",
                            "statement": "The registered claim has supporting evidence.",
                            "status": "supported",
                            "evidence_ref_ids": ["evidence-record"],
                        }
                    ]
                },
            ),
            ComponentSpec(
                component_id="reviewer-queue",
                component=TrustedComponent.REVIEWER_QUEUE,
                title="Reviewer queue",
                evidence_ref_ids=["review-record"],
                data={
                    "reviews": [
                        {
                            "review_ref_id": "review-record",
                            "status": "open",
                            "summary": "One registered review remains open.",
                        }
                    ]
                },
            ),
        ],
    )


def build_paper_status_fixture(snapshot: SnapshotBinding | None = None) -> SurfaceSpec:
    binding = snapshot or fixture_snapshot_binding()
    return SurfaceSpec(
        surface_id="paper-status",
        revision=1,
        purpose=SurfacePurpose.PAPER_STATUS,
        title="Paper status",
        project_id=binding.project_id,
        snapshot=binding,
        components=[
            ComponentSpec(
                component_id="paper-preview",
                component=TrustedComponent.PAPER_PREVIEW,
                title="Current manuscript",
                evidence_ref_ids=["paper-record"],
                data={
                    "paper_ref_id": "paper-record",
                    "paper_title": "Evidence-Grounded Research Interface",
                    "paper_status": "peer_reviewed_draft",
                    "publication_ready": False,
                    "excerpt": "The current manuscript remains a reviewed draft.",
                },
            ),
            ComponentSpec(
                component_id="artifact-viewer",
                component=TrustedComponent.ARTIFACT_VIEWER,
                title="Paper artifact",
                evidence_ref_ids=["paper-artifact"],
                data={
                    "artifact_ref_id": "paper-artifact",
                    "artifact_path": "papers/paper-a/paper.pdf",
                    "media_type": "application/pdf",
                },
            ),
        ],
        actions=[
            ActionBinding(
                action_id="inspect-paper",
                component_id="artifact-viewer",
                label="Inspect paper",
                proposal=ActionProposal(
                    payload=InspectArtifactPayload(
                        kind=ProposalKind.INSPECT_ARTIFACT,
                        artifact_ref_id="paper-artifact",
                    ),
                    rationale="Inspect the selected content-addressed artifact.",
                    evidence_ref_ids=["paper-artifact"],
                ),
            )
        ],
    )


def build_blocked_run_fixture(snapshot: SnapshotBinding | None = None) -> SurfaceSpec:
    binding = snapshot or fixture_snapshot_binding()
    return SurfaceSpec(
        surface_id="blocked-run",
        revision=1,
        purpose=SurfacePurpose.BLOCKED_RUN,
        title="Blocked run",
        project_id=binding.project_id,
        snapshot=binding,
        components=[
            ComponentSpec(
                component_id="blocker-list",
                component=TrustedComponent.BLOCKER_LIST,
                title="Open blockers",
                evidence_ref_ids=["blocker-record"],
                data={
                    "blockers": [
                        {
                            "blocker_ref_id": "blocker-record",
                            "blocker_id": "provider-format",
                            "severity": "high",
                            "status": "open",
                            "summary": "Provider output failed the registered schema.",
                        }
                    ]
                },
            ),
            ComponentSpec(
                component_id="failed-run-health",
                component=TrustedComponent.RUN_HEALTH,
                title="Run health",
                evidence_ref_ids=["run-a"],
                data={
                    "run_ref_id": "run-a",
                    "run_status": "failed",
                    "failure_stage": 14,
                    "retry_safe": True,
                },
            ),
        ],
        actions=[
            ActionBinding(
                action_id="request-blocker-disposition",
                component_id="blocker-list",
                label="Request disposition",
                proposal=ActionProposal(
                    payload=RequestApprovalPayload(
                        kind=ProposalKind.REQUEST_APPROVAL,
                        subject=ApprovalSubject.BLOCKER_DISPOSITION,
                        subject_ref_ids=["blocker-record"],
                        question="Approve a new run after the deterministic schema gate is fixed?",
                    ),
                    rationale="The blocked run cannot be resumed without an explicit disposition.",
                    evidence_ref_ids=["blocker-record"],
                    requires_approval=True,
                ),
            )
        ],
    )


def build_next_step_fixture(snapshot: SnapshotBinding | None = None) -> SurfaceSpec:
    binding = snapshot or fixture_snapshot_binding()
    return SurfaceSpec(
        surface_id="next-step",
        revision=1,
        purpose=SurfacePurpose.NEXT_STEP,
        title="Evidence-grounded next step",
        project_id=binding.project_id,
        snapshot=binding,
        components=[
            ComponentSpec(
                component_id="next-decision",
                component=TrustedComponent.DECISION_COMPARISON,
                title="Candidate transition",
                evidence_ref_ids=["decision-record", "run-b"],
                data={
                    "view": "transition",
                    "decision_ref_id": "decision-record",
                    "run_ref_id": "run-b",
                    "status": "proposed",
                    "current_stage": "evidence",
                    "recommended_action": "COLLECT_EVIDENCE",
                    "alternative_action": "WRITE",
                },
            )
        ],
        actions=[
            ActionBinding(
                action_id="propose-evidence-transition",
                component_id="next-decision",
                label="Propose transition",
                proposal=ActionProposal(
                    payload=ProposeTransitionPayload(
                        kind=ProposalKind.PROPOSE_TRANSITION,
                        from_stage="evidence",
                        proposed_action=MetaAction.COLLECT_EVIDENCE,
                        decision_ref_id="decision-record",
                    ),
                    rationale="The recorded decision prefers resolving the evidence gap first.",
                    evidence_ref_ids=["decision-record"],
                    requires_approval=True,
                ),
            )
        ],
    )


def build_run_comparison_fixture(snapshot: SnapshotBinding | None = None) -> SurfaceSpec:
    binding = snapshot or fixture_snapshot_binding()
    return SurfaceSpec(
        surface_id="run-comparison",
        revision=1,
        purpose=SurfacePurpose.RUN_COMPARISON,
        title="Run comparison",
        project_id=binding.project_id,
        snapshot=binding,
        components=[
            ComponentSpec(
                component_id="run-comparison-card",
                component=TrustedComponent.DECISION_COMPARISON,
                title="Baseline and candidate",
                evidence_ref_ids=["decision-record", "run-a", "run-b"],
                data={
                    "view": "run_comparison",
                    "decision_ref_id": "decision-record",
                    "baseline_run_ref_id": "run-a",
                    "candidate_run_ref_id": "run-b",
                    "baseline_score": 0.71,
                    "candidate_score": 0.82,
                    "metric": "balanced_accuracy",
                },
            ),
            ComponentSpec(
                component_id="baseline-health",
                component=TrustedComponent.RUN_HEALTH,
                title="Baseline health",
                evidence_ref_ids=["run-a"],
                data={"run_ref_id": "run-a", "run_status": "succeeded", "schema_valid": True},
            ),
            ComponentSpec(
                component_id="candidate-health",
                component=TrustedComponent.RUN_HEALTH,
                title="Candidate health",
                evidence_ref_ids=["run-b"],
                data={"run_ref_id": "run-b", "run_status": "succeeded", "schema_valid": True},
            ),
        ],
        actions=[
            ActionBinding(
                action_id="compare-selected-runs",
                component_id="run-comparison-card",
                label="Compare runs",
                proposal=ActionProposal(
                    payload=CompareRunsPayload(
                        kind=ProposalKind.COMPARE_RUNS,
                        baseline_run_ref_id="run-a",
                        candidate_run_ref_id="run-b",
                        metric_names=["balanced_accuracy"],
                    ),
                    rationale="Compare only the two registered run records.",
                    evidence_ref_ids=["run-a", "run-b"],
                ),
            )
        ],
    )


def build_fixture_surfaces() -> dict[SurfacePurpose, SurfaceSpec]:
    binding = fixture_snapshot_binding()
    return {
        SurfacePurpose.PROJECT_OVERVIEW: build_project_overview_fixture(binding),
        SurfacePurpose.PAPER_STATUS: build_paper_status_fixture(binding),
        SurfacePurpose.BLOCKED_RUN: build_blocked_run_fixture(binding),
        SurfacePurpose.NEXT_STEP: build_next_step_fixture(binding),
        SurfacePurpose.RUN_COMPARISON: build_run_comparison_fixture(binding),
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

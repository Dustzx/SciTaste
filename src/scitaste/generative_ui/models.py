"""Evidence-grounded, non-executable generative UI contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
    model_validator,
)

from scitaste.generative_ui.registry import (
    APPROVAL_EVIDENCE_KINDS,
    COMPONENT_REGISTRY,
    ApprovalSubject,
    EvidenceKind,
    ProposalKind,
    SurfacePurpose,
    TrustedComponent,
)
from scitaste.generative_ui.research_landscape import ResearchLandscapeData
from scitaste.generative_ui.safety import (
    ProjectIdentifier,
    SafeIdentifier,
    SafeLocator,
    SafeText,
    Sha256,
    declarative_dict,
)
from scitaste.schema.actions import MetaAction

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_DATA_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    allow_inf_nan=False,
    revalidate_instances="always",
)


class EvidenceRef(BaseModel):
    """Content-addressed evidence available in one project snapshot."""

    model_config = _MODEL_CONFIG

    evidence_id: SafeIdentifier
    project_id: ProjectIdentifier
    kind: EvidenceKind
    locator: SafeLocator
    sha256: Sha256
    label: SafeText


def compute_snapshot_sha256(
    *,
    project_id: str,
    snapshot_revision: int,
    evidence_refs: Iterable[EvidenceRef],
) -> str:
    """Hash the canonical trusted-evidence manifest for a project snapshot."""

    refs = sorted(
        (item.model_dump(mode="json") for item in evidence_refs),
        key=lambda item: item["evidence_id"],
    )
    return _fingerprint(
        {
            "schema_version": "1.0",
            "project_id": project_id,
            "snapshot_revision": snapshot_revision,
            "evidence_refs": refs,
        }
    )


class SnapshotBinding(BaseModel):
    """Immutable identity of the project state used to generate a surface."""

    model_config = _MODEL_CONFIG

    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    evidence_refs: list[EvidenceRef] = Field(min_length=1)

    @classmethod
    def from_trusted_evidence(
        cls,
        *,
        project_id: str,
        snapshot_revision: int,
        evidence_refs: Iterable[EvidenceRef],
    ) -> SnapshotBinding:
        """Build a binding only after a trusted adapter resolves and hashes evidence."""

        refs = [EvidenceRef.model_validate(item.model_dump(mode="json")) for item in evidence_refs]
        return cls(
            project_id=project_id,
            snapshot_revision=snapshot_revision,
            snapshot_sha256=compute_snapshot_sha256(
                project_id=project_id,
                snapshot_revision=snapshot_revision,
                evidence_refs=refs,
            ),
            evidence_refs=refs,
        )

    @model_validator(mode="after")
    def evidence_belongs_to_one_snapshot(self) -> SnapshotBinding:
        ids = [item.evidence_id for item in self.evidence_refs]
        if len(ids) != len(set(ids)):
            raise ValueError("snapshot evidence IDs must be unique")
        locators = [item.locator for item in self.evidence_refs]
        if len(locators) != len(set(locators)):
            raise ValueError("snapshot evidence locators must be unique")
        foreign = [
            item.evidence_id for item in self.evidence_refs if item.project_id != self.project_id
        ]
        if foreign:
            raise ValueError(f"snapshot evidence belongs to another project: {sorted(foreign)}")
        expected_hash = compute_snapshot_sha256(
            project_id=self.project_id,
            snapshot_revision=self.snapshot_revision,
            evidence_refs=self.evidence_refs,
        )
        if self.snapshot_sha256 != expected_hash:
            raise ValueError("snapshot hash does not match its canonical evidence manifest")
        object.__setattr__(
            self,
            "evidence_refs",
            sorted(self.evidence_refs, key=lambda item: item.evidence_id),
        )
        return self


class ProjectSummaryData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    project_ref_id: SafeIdentifier
    project_status: SafeIdentifier
    publication_ready: bool
    current_focus: SafeText


class StageTimelineItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    stage_ref_id: SafeIdentifier
    stage: int = Field(ge=0)
    status: SafeIdentifier


class StageTimelineData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    stages: tuple[StageTimelineItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def stage_rows_are_unique(self) -> StageTimelineData:
        identities = [(item.stage_ref_id, item.stage) for item in self.stages]
        if len(identities) != len(set(identities)):
            raise ValueError("stage timeline rows must be unique")
        return self


class BlockerItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    blocker_ref_id: SafeIdentifier
    blocker_id: SafeIdentifier
    severity: Literal["low", "medium", "high", "critical"]
    status: SafeIdentifier
    summary: SafeText


class BlockerListData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    blockers: tuple[BlockerItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def blocker_rows_are_unique(self) -> BlockerListData:
        ids = [item.blocker_id for item in self.blockers]
        if len(ids) != len(set(ids)):
            raise ValueError("blocker IDs must be unique")
        return self


class RunHealthData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_status: SafeIdentifier
    failure_stage: int | None = Field(default=None, ge=0)
    retry_safe: bool | None = None
    schema_valid: bool | None = None


class BudgetResourceItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    resource: SafeIdentifier
    used: float = Field(ge=0)
    limit: float = Field(gt=0)
    unit: SafeIdentifier


class BudgetMeterData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    usage_ref_id: SafeIdentifier
    resources: tuple[BudgetResourceItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def resource_rows_are_unique(self) -> BudgetMeterData:
        resources = [item.resource for item in self.resources]
        if len(resources) != len(set(resources)):
            raise ValueError("budget resources must be unique")
        return self


class TransitionDecisionData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    view: Literal["transition"]
    decision_ref_id: SafeIdentifier
    run_ref_id: SafeIdentifier
    status: SafeIdentifier
    current_stage: SafeIdentifier
    recommended_action: MetaAction
    alternative_action: MetaAction

    @model_validator(mode="after")
    def actions_are_distinct(self) -> TransitionDecisionData:
        if self.recommended_action == self.alternative_action:
            raise ValueError("decision comparison actions must be distinct")
        return self


class RunComparisonData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    view: Literal["run_comparison"]
    decision_ref_id: SafeIdentifier
    baseline_run_ref_id: SafeIdentifier
    candidate_run_ref_id: SafeIdentifier
    baseline_score: float
    candidate_score: float
    metric: SafeIdentifier

    @model_validator(mode="after")
    def runs_are_distinct(self) -> RunComparisonData:
        if self.baseline_run_ref_id == self.candidate_run_ref_id:
            raise ValueError("run comparison data requires two distinct run references")
        return self


DecisionComparisonData = Annotated[
    TransitionDecisionData | RunComparisonData,
    Field(discriminator="view"),
]


class EvidenceGraphNode(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    evidence_ref_id: SafeIdentifier
    kind: EvidenceKind
    label: SafeText


class EvidenceGraphEdge(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    source_ref_id: SafeIdentifier
    target_ref_id: SafeIdentifier
    relation: SafeIdentifier


class EvidenceGraphData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    nodes: tuple[EvidenceGraphNode, ...] = Field(min_length=1, max_length=24)
    edges: tuple[EvidenceGraphEdge, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def graph_is_closed(self) -> EvidenceGraphData:
        node_ids = [item.evidence_ref_id for item in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("evidence graph node IDs must be unique")
        unknown = {
            ref_id
            for edge in self.edges
            for ref_id in (edge.source_ref_id, edge.target_ref_id)
            if ref_id not in node_ids
        }
        if unknown:
            raise ValueError(f"evidence graph edges reference missing nodes: {sorted(unknown)}")
        return self


class ClaimMatrixRow(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    claim_ref_id: SafeIdentifier
    statement: SafeText
    status: SafeIdentifier
    evidence_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_ids_are_unique(self) -> ClaimMatrixRow:
        if len(self.evidence_ref_ids) != len(set(self.evidence_ref_ids)):
            raise ValueError("claim evidence references must be unique")
        return self


class ClaimMatrixData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    claims: tuple[ClaimMatrixRow, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def claim_rows_are_unique(self) -> ClaimMatrixData:
        refs = [item.claim_ref_id for item in self.claims]
        if len(refs) != len(set(refs)):
            raise ValueError("claim matrix references must be unique")
        return self


class ReviewerQueueItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    review_ref_id: SafeIdentifier
    status: SafeIdentifier
    summary: SafeText


class ReviewerQueueData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    reviews: tuple[ReviewerQueueItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def review_rows_are_unique(self) -> ReviewerQueueData:
        refs = [item.review_ref_id for item in self.reviews]
        if len(refs) != len(set(refs)):
            raise ValueError("review queue references must be unique")
        return self


class ArtifactViewerData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    artifact_ref_id: SafeIdentifier
    artifact_path: SafeLocator
    media_type: str = Field(pattern=r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$")


class PaperPreviewData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    paper_ref_id: SafeIdentifier
    paper_title: SafeText
    paper_status: SafeIdentifier
    publication_ready: bool
    excerpt: SafeText | None = None


class AvailabilityNoticeData(BaseModel):
    """Explicit absence state backed by the project manifest."""

    model_config = _DATA_MODEL_CONFIG

    project_ref_id: SafeIdentifier
    subject: Literal[
        "runs",
        "stages",
        "papers",
        "evidence",
        "comparison",
        "blockers",
        "proposals",
        "research_landscape",
    ]
    state: Literal["empty", "unavailable"]
    reason_code: SafeIdentifier


class WorkspaceRunItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    provider: SafeText
    model_name: SafeText
    condition: SafeText
    seed: int = Field(ge=0)
    status: SafeText
    evidence_scope: SafeText
    selected: bool
    outcome: Literal["succeeded", "failed", "blocked", "active", "registered", "unknown"]
    summary_code: SafeIdentifier


class WorkspaceStageItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    stage_ref_id: SafeIdentifier
    stage: int = Field(ge=1, le=23)
    name: SafeIdentifier
    label_en: SafeText
    label_zh: SafeText
    status: Literal["completed"]
    artifact_count: int = Field(ge=0)
    output_locator: SafeLocator
    summary_code: SafeIdentifier


class RunStageExplorerData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    project_ref_id: SafeIdentifier
    selected_run_id: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    stage_state: Literal["available", "empty", "unavailable"]
    runs: tuple[WorkspaceRunItem, ...] = Field(min_length=1)
    stages: tuple[WorkspaceStageItem, ...] = ()

    @model_validator(mode="after")
    def explorer_rows_are_consistent(self) -> RunStageExplorerData:
        run_ids = [item.run_id for item in self.runs]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("workspace run IDs must be unique")
        selected = [item.run_id for item in self.runs if item.selected]
        if selected != ([self.selected_run_id] if self.selected_run_id is not None else []):
            raise ValueError("workspace selected run must match exactly one run row")
        stages = [item.stage for item in self.stages]
        if stages != sorted(set(stages)):
            raise ValueError("workspace stages must be sorted and unique")
        if self.stage_state == "available" and not self.stages:
            raise ValueError("available stage state requires stage rows")
        if self.stage_state != "available" and self.stages:
            raise ValueError("empty or unavailable stage state cannot contain stage rows")
        return self


class EvidenceInventoryItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    evidence_ref_id: SafeIdentifier
    kind: EvidenceKind
    locator: SafeLocator
    sha256: Sha256
    label: SafeText


class EvidenceInventoryData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    project_ref_id: SafeIdentifier
    scope: Literal["project", "paper"]
    selected_paper_id: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    items: tuple[EvidenceInventoryItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_rows_are_unique(self) -> EvidenceInventoryData:
        refs = [item.evidence_ref_id for item in self.items]
        if len(refs) != len(set(refs)):
            raise ValueError("evidence inventory references must be unique")
        if self.scope == "paper" and self.selected_paper_id is None:
            raise ValueError("paper evidence scope requires a selected paper")
        if self.scope == "project" and self.selected_paper_id is not None:
            raise ValueError("project evidence scope cannot select a paper")
        return self


class ComparedRunItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    status: SafeText
    provider: SafeText
    model_name: SafeText
    condition: SafeText
    seed: int = Field(ge=0)
    evidence_scope: SafeText


class RunComparisonPanelData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    baseline: ComparedRunItem
    candidate: ComparedRunItem
    metrics_state: Literal["available", "unavailable"]
    metrics_reason_code: SafeIdentifier
    metrics: dict[SafeIdentifier, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def comparison_is_consistent(self) -> RunComparisonPanelData:
        if self.baseline.run_id == self.candidate.run_id:
            raise ValueError("workspace run comparison requires distinct runs")
        if self.metrics_state == "unavailable" and self.metrics:
            raise ValueError("unavailable comparison metrics must remain empty")
        if self.metrics_state == "available" and not self.metrics:
            raise ValueError("available comparison metrics require values")
        return self


class RunBlockerItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    run_status: SafeText
    classification: Literal["blocked", "failed"]
    reason_code: SafeIdentifier
    source_locator: SafeLocator
    detail_state: Literal["recorded", "unavailable"] = "unavailable"
    recorded_reasons: tuple[SafeText, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def detail_matches_recorded_reasons(self) -> RunBlockerItem:
        if self.detail_state == "recorded" and not self.recorded_reasons:
            raise ValueError("recorded blocker detail requires at least one reason")
        if self.detail_state == "unavailable" and self.recorded_reasons:
            raise ValueError("unavailable blocker detail cannot contain reasons")
        return self


class RunBlockerPanelData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    blockers: tuple[RunBlockerItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def blocker_runs_are_unique(self) -> RunBlockerPanelData:
        run_ids = [item.run_id for item in self.blockers]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("workspace blocker run IDs must be unique")
        return self


class PendingProposalItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    audit_ref_id: SafeIdentifier
    event_id: SafeIdentifier
    action_id: SafeIdentifier
    surface_id: SafeIdentifier
    surface_revision: int = Field(ge=0)
    snapshot_revision: int = Field(ge=0)
    status: Literal["proposal_pending"]
    next_boundary: Literal["deterministic_controller"]
    execution_authority: Literal["none"]


class PendingProposalListData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    proposals: tuple[PendingProposalItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def proposal_events_are_unique(self) -> PendingProposalListData:
        event_ids = [item.event_id for item in self.proposals]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("pending proposal event IDs must be unique")
        return self


ObservedProgressState = Literal[
    "observed_completed",
    "current_work",
    "blocked",
    "failed",
    "candidate",
    "unavailable",
    "unknown",
]


class ProjectProgressCounts(BaseModel):
    """Observed project records, never an inferred completion percentage."""

    model_config = _DATA_MODEL_CONFIG

    runs_registered: int = Field(ge=0)
    runs_completed: int = Field(ge=0)
    runs_failed: int = Field(ge=0)
    runs_blocked: int = Field(ge=0)
    runs_active: int = Field(ge=0)
    runs_candidates: int = Field(ge=0)
    runs_unavailable: int = Field(ge=0)
    runs_unknown: int = Field(ge=0)
    completed_stages: int = Field(ge=0)
    papers_registered: int = Field(ge=0)
    evaluations_registered: int = Field(ge=0)
    evaluation_results_registered: int = Field(ge=0)
    acquisition_requests: int = Field(default=0, ge=0)
    acquisition_receipts: int = Field(default=0, ge=0)
    metadata_audit_plans: int = Field(default=0, ge=0)
    benchmark_metadata_populations: int = Field(default=0, ge=0)
    benchmark_metadata_screenings: int = Field(default=0, ge=0)
    benchmark_metadata_allocation_plans: int = Field(default=0, ge=0)
    benchmark_metadata_allocations: int = Field(default=0, ge=0)
    reference_selection_comparisons: int = Field(default=0, ge=0)
    taste_candidate_populations: int = Field(default=0, ge=0)
    taste_domain_expansions: int = Field(default=0, ge=0)
    taste_source_review_campaigns: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def run_states_cover_registered_runs(self) -> ProjectProgressCounts:
        classified = (
            self.runs_completed
            + self.runs_failed
            + self.runs_blocked
            + self.runs_active
            + self.runs_candidates
            + self.runs_unavailable
            + self.runs_unknown
        )
        if classified != self.runs_registered:
            raise ValueError("project progress run counts must cover every registered run")
        return self


class ProjectProgressActivityItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    reported_status: SafeText
    observed_state: ObservedProgressState
    provider: SafeText
    model_name: SafeText
    condition: SafeText
    evidence_scope: SafeText
    selected: bool
    superseded: bool
    source_locator: SafeLocator
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def activity_support_is_closed(self) -> ProjectProgressActivityItem:
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("project progress activity evidence references must be unique")
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("project progress activity must cite its run record")
        return self


class ProjectProgressStageItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    stage_ref_id: SafeIdentifier
    stage: int = Field(ge=1, le=23)
    name: SafeIdentifier
    label_en: SafeText
    label_zh: SafeText
    observed_state: Literal["observed_completed"] = "observed_completed"
    artifact_count: int = Field(ge=0)
    output_locator: SafeLocator
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def stage_support_is_closed(self) -> ProjectProgressStageItem:
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("project progress stage evidence references must be unique")
        if self.stage_ref_id not in self.support_ref_ids:
            raise ValueError("project progress stage must cite its stage record")
        return self


class ProjectProgressPaperItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    paper_ref_id: SafeIdentifier
    paper_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    title: SafeText
    reported_status: SafeText
    observed_state: ObservedProgressState
    publication_ready: bool
    selected: bool
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def paper_support_is_closed(self) -> ProjectProgressPaperItem:
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("project progress paper evidence references must be unique")
        if self.paper_ref_id not in self.support_ref_ids:
            raise ValueError("project progress paper must cite its paper record")
        return self


class ProjectProgressEvaluationGateItem(BaseModel):
    """One compact decision gate; detailed diagnostics remain in evidence."""

    model_config = _DATA_MODEL_CONFIG

    gate_id: Literal[
        "task_scope",
        "comparator_adapters",
        "statistical_design",
        "temporal_integrity",
        "independent_review",
        "runtime_resources",
        "owner_approval",
    ]
    state: Literal["satisfied", "blocked", "awaiting_approval"]
    issue_count: int = Field(ge=0)
    affected_count: int = Field(ge=0)
    next_action_code: SafeIdentifier

    @model_validator(mode="after")
    def gate_state_matches_issues(self) -> ProjectProgressEvaluationGateItem:
        if self.state == "satisfied" and self.issue_count:
            raise ValueError("a satisfied evaluation gate cannot retain issues")
        if self.state == "blocked" and not self.issue_count:
            raise ValueError("a blocked evaluation gate requires an issue")
        return self


class ProjectProgressEvaluationItem(BaseModel):
    """One exact no-run experiment proposal displayed on its project home."""

    model_config = _DATA_MODEL_CONFIG

    evaluation_ref_id: SafeIdentifier
    evaluation_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    protocol_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    study_scope: Literal["pilot", "formal", "robustness"]
    status: Literal["blocked", "awaiting_author_approval", "execution_authorized"]
    planned_cells: int = Field(gt=0)
    api_resources: tuple[SafeText, ...] = ()
    gpu_resources: tuple[SafeText, ...] = ()
    ready_for_author_review: bool
    execution_authorized: bool
    blocker_count: int = Field(ge=0)
    decision_blocker_count: int = Field(ge=0, le=7)
    next_gate_id: (
        Literal[
            "task_scope",
            "comparator_adapters",
            "statistical_design",
            "temporal_integrity",
            "independent_review",
            "runtime_resources",
            "owner_approval",
        ]
        | None
    ) = None
    gate_map_sha256: Sha256
    gates: tuple[ProjectProgressEvaluationGateItem, ...] = Field(min_length=7, max_length=7)
    selected: bool
    no_execution_performed: Literal[True] = True
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def evaluation_support_is_closed(self) -> ProjectProgressEvaluationItem:
        if self.evaluation_ref_id not in self.support_ref_ids:
            raise ValueError("project evaluation must cite its registered record")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("project evaluation evidence references must be unique")
        if not self.api_resources and not self.gpu_resources:
            raise ValueError("project evaluation must name an API or GPU resource")
        if self.execution_authorized and not self.ready_for_author_review:
            raise ValueError("project evaluation authority requires readiness")
        expected_order = (
            "task_scope",
            "comparator_adapters",
            "statistical_design",
            "temporal_integrity",
            "independent_review",
            "runtime_resources",
            "owner_approval",
        )
        if tuple(item.gate_id for item in self.gates) != expected_order:
            raise ValueError("project evaluation gates must use the decision order")
        open_gates = [item for item in self.gates if item.state != "satisfied"]
        if self.decision_blocker_count != len(open_gates):
            raise ValueError("project evaluation decision count must match its gates")
        expected_next = open_gates[0].gate_id if open_gates else None
        if self.next_gate_id != expected_next:
            raise ValueError("project evaluation next gate must be the first unresolved gate")
        return self


class ProjectProgressEvaluationResultItem(BaseModel):
    """One reverified project result, separate from its immutable proposal."""

    model_config = _DATA_MODEL_CONFIG

    result_ref_id: SafeIdentifier
    result_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    evaluation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    status: Literal["incomplete", "complete"]
    planned_cells: int = Field(ge=0)
    verified_records: int = Field(ge=0)
    succeeded_cells: int = Field(ge=0)
    failed_cells: int = Field(ge=0)
    missing_cells: int = Field(ge=0)
    invalid_cells: int = Field(ge=0)
    valid_external_reviews: int = Field(ge=0)
    scientific_evidence_complete: bool
    headline_eligible: bool
    scientific_effectiveness_established: bool
    selected: bool
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def result_summary_is_closed(self) -> ProjectProgressEvaluationResultItem:
        if self.verified_records + self.missing_cells + self.invalid_cells != self.planned_cells:
            raise ValueError("project evaluation-result cells do not close")
        if self.succeeded_cells + self.failed_cells != self.verified_records:
            raise ValueError("project evaluation-result verified records do not close")
        if self.headline_eligible != self.scientific_evidence_complete:
            raise ValueError("project evaluation-result headline state is inconsistent")
        if self.scientific_effectiveness_established and not self.headline_eligible:
            raise ValueError("project result effectiveness requires headline evidence")
        if self.result_ref_id not in self.support_ref_ids:
            raise ValueError("project evaluation result must cite its result record")
        return self


class ProjectProgressMilestoneItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    milestone_id: SafeIdentifier
    recorded_on: date
    reported_status: SafeText
    observed_state: ObservedProgressState
    decision: SafeText
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    evidence_locator: SafeLocator | None = None
    evidence_binding: Literal["content_addressed", "manifest_declared"]

    @model_validator(mode="after")
    def milestone_support_is_closed(self) -> ProjectProgressMilestoneItem:
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("project progress milestone evidence references must be unique")
        return self


class ProjectProgressAttentionItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    reported_status: SafeText
    classification: Literal["blocked", "failed"]
    reason_code: SafeIdentifier
    source_locator: SafeLocator
    detail_state: Literal["recorded", "unavailable"]
    recorded_reasons: tuple[SafeText, ...] = ()
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def attention_support_is_closed(self) -> ProjectProgressAttentionItem:
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("project progress attention evidence references must be unique")
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("project progress attention must cite its run record")
        if self.detail_state == "recorded" and not self.recorded_reasons:
            raise ValueError("recorded project progress attention requires reasons")
        if self.detail_state == "unavailable" and self.recorded_reasons:
            raise ValueError("unavailable project progress attention cannot include reasons")
        return self


class ProjectProgressAcquisitionItem(BaseModel):
    """One inspected, project-owned acquisition decision with no implied execution."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    request_sha256: Sha256
    report_sha256: Sha256
    status: Literal["blocked", "awaiting_owner_approval", "download_authorized"]
    purpose: SafeText
    claim_boundary: SafeText
    item_count: int = Field(gt=0)
    maximum_total_bytes: int = Field(gt=0)
    source_hosts: tuple[SafeText, ...] = Field(min_length=1, max_length=20)
    ready_for_owner_approval: bool
    download_authorized: bool
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False
    no_network_access_performed: Literal[True] = True
    no_download_performed: Literal[True] = True
    no_dataset_file_created: Literal[True] = True
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def acquisition_state_is_closed(self) -> ProjectProgressAcquisitionItem:
        expected = (
            "download_authorized"
            if self.download_authorized
            else "awaiting_owner_approval"
            if self.ready_for_owner_approval
            else "blocked"
        )
        if self.status != expected:
            raise ValueError("project acquisition status differs from its gate report")
        if self.download_authorized and not self.ready_for_owner_approval:
            raise ValueError("project acquisition authorization requires review readiness")
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("project acquisition must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("project acquisition evidence references must be unique")
        return self


class ProjectProgressAcquisitionQualificationItem(BaseModel):
    """One content-bound statement about an acquired cohort's valid uses."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    selection_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    request_sha256: Sha256
    receipt_sha256: Sha256
    report_sha256: Sha256
    report_file_sha256: Sha256
    scientific_disposition: Literal[
        "invalid-acquisition",
        "brief-only-pilot-candidate",
        "formal-empirical-task-candidate",
    ]
    task_count: int = Field(gt=0)
    observed_total_bytes: int = Field(ge=0)
    exact_task_set_verified: bool
    exact_bytes_verified: bool
    ready_for_stagewise_pilot: bool
    ready_for_brief_only_package_prepilot: bool
    ready_for_formal_empirical_task_binding: bool
    ready_for_objective_progress_binding: bool
    formal_task_blocker_codes: tuple[SafeIdentifier, ...] = ()
    objective_progress_blocker_codes: tuple[SafeIdentifier, ...] = ()
    authorizes_ingestion: Literal[False] = False
    authorizes_execution: Literal[False] = False
    provider_call_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def qualification_state_is_closed(self) -> ProjectProgressAcquisitionQualificationItem:
        if self.scientific_disposition == "invalid-acquisition" and self.exact_bytes_verified:
            raise ValueError("invalid acquisition qualification cannot claim exact bytes")
        if self.scientific_disposition == "formal-empirical-task-candidate" and not (
            self.ready_for_formal_empirical_task_binding
        ):
            raise ValueError("formal acquisition disposition requires formal task readiness")
        if self.ready_for_formal_empirical_task_binding and not (
            self.ready_for_brief_only_package_prepilot
        ):
            raise ValueError("formal task readiness requires brief-package readiness")
        if self.ready_for_objective_progress_binding and not (
            self.ready_for_formal_empirical_task_binding
        ):
            raise ValueError("objective readiness requires formal empirical readiness")
        if self.ready_for_formal_empirical_task_binding and self.formal_task_blocker_codes:
            raise ValueError("formally ready acquisition cannot retain formal blockers")
        if self.ready_for_objective_progress_binding and self.objective_progress_blocker_codes:
            raise ValueError("objective-ready acquisition cannot retain objective blockers")
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("project acquisition qualification must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("project acquisition qualification references must be unique")
        return self


class ProjectProgressAcquisitionReceiptItem(BaseModel):
    """One acquired byte set that still grants no content or execution authority."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    request_sha256: Sha256
    bundle_file_sha256: Sha256
    receipt_sha256: Sha256
    receipt_file_sha256: Sha256
    status: Literal["acquired_download_only"]
    purpose: SafeText
    claim_boundary: SafeText
    item_count: int = Field(gt=0)
    total_bytes: int = Field(gt=0)
    maximum_total_bytes: int = Field(gt=0)
    source_hosts: tuple[SafeText, ...] = Field(min_length=1, max_length=20)
    acquired_at: SafeText
    acquisition_complete: Literal[True]
    content_access_performed: Literal[False]
    content_audit_required: Literal[True]
    authorizes_ingestion: Literal[False]
    authorizes_execution: Literal[False]
    next_gate: SafeText
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def receipt_state_is_closed(self) -> ProjectProgressAcquisitionReceiptItem:
        if self.total_bytes > self.maximum_total_bytes:
            raise ValueError("project acquisition receipt exceeds its approved ceiling")
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("project acquisition receipt must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("project acquisition receipt references must be unique")
        return self


class ProjectProgressTasteCandidatePopulationItem(BaseModel):
    """One natural reference population awaiting Taste abstraction and review."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    artifact_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    population_id: SafeIdentifier
    report_file_sha256: Sha256
    report_sha256: Sha256
    compiler_implementation_sha256: Sha256
    candidate_count: int = Field(gt=0)
    source_group_count: int = Field(gt=0)
    target_population_floor: int = Field(gt=0)
    target_population_floor_met: bool
    domain_count_observed: int = Field(gt=0)
    target_domain_count: int = Field(gt=0)
    target_domain_floor_met: bool
    alignment_agreement_count: int = Field(ge=0)
    alignment_disagreement_count: int = Field(ge=0)
    no_aligned_edit_count: int = Field(ge=0)
    synthetic_review_row_count_excluded: int = Field(ge=0)
    ready_for_taste_abstraction_review: bool
    ready_for_benchmark_admission: bool
    blocker_codes: tuple[SafeIdentifier, ...] = Field(min_length=1)
    verification_route: Literal["direct_path"]
    standalone_preflight_performed: Literal[False]
    inline_integrity_guards_performed: Literal[True]
    model_calls_performed: Literal[False]
    gpu_work_performed: Literal[False]
    experiment_performed: Literal[False]
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def candidate_population_is_closed(
        self,
    ) -> ProjectProgressTasteCandidatePopulationItem:
        if self.target_population_floor_met != (
            self.candidate_count >= self.target_population_floor
        ):
            raise ValueError("Taste candidate population floor is inconsistent")
        if self.target_domain_floor_met != (
            self.domain_count_observed >= self.target_domain_count
        ):
            raise ValueError("Taste candidate domain floor is inconsistent")
        if self.candidate_count != (
            self.alignment_agreement_count + self.alignment_disagreement_count
        ):
            raise ValueError("Taste alignment counts do not cover the population")
        if self.ready_for_benchmark_admission:
            raise ValueError("candidate population cannot claim benchmark admission")
        if {self.run_ref_id, self.artifact_ref_id} - set(self.support_ref_ids):
            raise ValueError("Taste candidate population lacks registered evidence")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("Taste candidate population evidence must be unique")
        return self


class ProjectProgressTasteDomainExpansionItem(BaseModel):
    """One publisher-stratified multidisciplinary population awaiting human gates."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    artifact_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    population_id: SafeIdentifier
    report_file_sha256: Sha256
    report_sha256: Sha256
    acquisition_receipt_sha256: Sha256
    compiler_implementation_sha256: Sha256
    selected_source_group_count: int = Field(gt=0)
    candidate_source_group_count: int = Field(gt=0)
    candidate_count: int = Field(gt=0)
    response_observed_count: int = Field(ge=0)
    domain_source_group_counts: dict[SafeIdentifier, int] = Field(min_length=2)
    recommendation_counts: dict[SafeIdentifier, int] = Field(min_length=1)
    observed_domain_count: int = Field(gt=0)
    target_domain_count: int = Field(gt=0)
    observed_domain_floor_met: bool
    minimum_groups_per_added_domain: int = Field(gt=0)
    added_domain_group_floor_met: bool
    independent_domain_review_complete: bool
    independent_quality_review_complete: bool
    decision_family_stratification_complete: bool
    privacy_review_complete: bool
    ready_for_taste_abstraction_review: bool
    ready_for_benchmark_admission: bool
    blocker_codes: tuple[SafeIdentifier, ...] = Field(min_length=1)
    verification_route: Literal["direct_path"]
    standalone_preflight_performed: Literal[False]
    inline_integrity_guards_performed: Literal[True]
    model_calls_performed: Literal[False]
    gpu_work_performed: Literal[False]
    experiment_performed: Literal[False]
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def domain_expansion_is_closed(self) -> ProjectProgressTasteDomainExpansionItem:
        if self.candidate_source_group_count != sum(self.domain_source_group_counts.values()):
            raise ValueError("Taste domain-expansion group counts are inconsistent")
        if self.candidate_source_group_count > self.selected_source_group_count:
            raise ValueError("Taste domain-expansion candidate groups exceed selection")
        if self.candidate_count != sum(self.recommendation_counts.values()):
            raise ValueError("Taste domain-expansion recommendations do not cover candidates")
        if self.response_observed_count > self.candidate_count:
            raise ValueError("Taste domain-expansion responses exceed candidates")
        if self.observed_domain_floor_met != (
            self.observed_domain_count >= self.target_domain_count
        ):
            raise ValueError("Taste domain-expansion domain floor is inconsistent")
        expected_group_floor = all(
            count >= self.minimum_groups_per_added_domain
            for count in self.domain_source_group_counts.values()
        )
        if self.added_domain_group_floor_met != expected_group_floor:
            raise ValueError("Taste domain-expansion group floor is inconsistent")
        if self.ready_for_taste_abstraction_review or self.ready_for_benchmark_admission:
            raise ValueError("unreviewed domain expansion cannot claim downstream admission")
        if {self.run_ref_id, self.artifact_ref_id} - set(self.support_ref_ids):
            raise ValueError("Taste domain expansion lacks registered evidence")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("Taste domain-expansion evidence must be unique")
        return self


class ProjectProgressTasteSourceReviewCampaignItem(BaseModel):
    """Independent natural-source review workload and its two Tool routes."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    artifact_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    campaign_id: SafeIdentifier
    population_id: SafeIdentifier
    campaign_file_sha256: Sha256
    campaign_sha256: Sha256
    candidate_count: int = Field(gt=0)
    source_group_count: int = Field(gt=0)
    publisher_subject_group_counts: dict[SafeIdentifier, int] = Field(min_length=2)
    scientific_reviewer_count: Literal[2]
    privacy_reviewer_count: Literal[1]
    scientific_assessment_count: int = Field(gt=0)
    privacy_assessment_count: int = Field(gt=0)
    reviewer_sessions_prepared: int = Field(ge=0, le=3)
    reviewer_submissions_collected: int = Field(ge=0, le=3)
    review_collection_status: Literal[
        "awaiting_owner_approval",
        "authorized_sessions_ready",
        "collecting_reviews",
        "review_locked",
    ]
    recruitment_status: Literal[
        "owner-and-ethics-approval-required",
        "authorized-sessions-prepared-no-contact",
    ]
    owner_approval_required: bool
    review_sessions_ready: bool
    activation_id: SafeIdentifier | None = None
    activation_sha256: Sha256 | None = None
    control_id: SafeIdentifier | None = None
    control_sha256: Sha256 | None = None
    session_locators: tuple[SafeLocator, ...] = Field(default=(), max_length=3)
    collected_submission_locators: tuple[SafeLocator, ...] = Field(default=(), max_length=3)
    result_locator: SafeLocator | None = None
    result_file_sha256: Sha256 | None = None
    result_sha256: Sha256 | None = None
    eligible_candidate_count: int | None = Field(default=None, ge=0)
    adjudication_required_count: int | None = Field(default=None, ge=0)
    abstraction_plan_locator: SafeLocator | None = None
    abstraction_plan_file_sha256: Sha256 | None = None
    abstraction_plan_sha256: Sha256 | None = None
    abstraction_input_count: int = Field(default=0, ge=0)
    abstraction_candidate_ceiling: int = Field(gt=0)
    abstraction_capacity_basis: Literal["campaign-ceiling", "locked-eligible-inputs"]
    abstraction_profile_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=12)
    abstraction_profile_capacity: int = Field(gt=0)
    abstraction_profile_capacity_gap: int = Field(default=0, ge=0)
    ready_for_abstraction_model_authorization: bool = False
    abstraction_preparation_route: Literal["direct_path"] | None = None
    abstraction_model_execution_route: Literal["owner_approval"] | None = None
    abstraction_human_review_route: Literal["owner_approval"] | None = None
    next_action: SafeIdentifier
    preparation_verification_route: Literal["direct_path"]
    recruitment_verification_route: Literal["owner_approval"]
    preparation_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1)
    recruitment_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1)
    submission_verification_route: Literal["direct_path"]
    submission_verification_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1)
    source_outcomes_hidden_from_scientific_review: Literal[True]
    ready_for_taste_abstraction_review: bool
    ready_for_benchmark_admission: Literal[False]
    standalone_preflight_performed: Literal[False]
    model_calls_performed: Literal[False]
    api_spend_performed: Literal[False]
    gpu_work_performed: Literal[False]
    human_recruitment_performed: Literal[False]
    experiment_performed: Literal[False]
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def review_campaign_is_closed(
        self,
    ) -> ProjectProgressTasteSourceReviewCampaignItem:
        if self.source_group_count != sum(self.publisher_subject_group_counts.values()):
            raise ValueError("Taste source-review domain counts are inconsistent")
        if self.scientific_assessment_count != 2 * self.candidate_count:
            raise ValueError("Taste source-review scientific workload is inconsistent")
        if self.privacy_assessment_count != self.candidate_count:
            raise ValueError("Taste source-review privacy workload is inconsistent")
        ready = self.recruitment_status == "authorized-sessions-prepared-no-contact"
        if self.review_sessions_ready != ready or self.owner_approval_required == ready:
            raise ValueError("Taste source-review control state is inconsistent")
        if self.reviewer_sessions_prepared != (3 if ready else 0):
            raise ValueError("Taste source-review session count is inconsistent")
        control_fields = (
            self.activation_id,
            self.activation_sha256,
            self.control_id,
            self.control_sha256,
        )
        if ready != all(control_fields) or (not ready and any(control_fields)):
            raise ValueError("Taste source-review control lineage is inconsistent")
        if len(self.session_locators) != (3 if ready else 0):
            raise ValueError("Taste source-review session locators differ from readiness")
        if len(self.session_locators) != len(set(self.session_locators)):
            raise ValueError("Taste source-review session locators must be unique")
        if self.reviewer_submissions_collected != len(self.collected_submission_locators):
            raise ValueError("Taste source-review submission count is inconsistent")
        if len(self.collected_submission_locators) != len(
            set(self.collected_submission_locators)
        ):
            raise ValueError("Taste source-review submission locators must be unique")
        locked = self.review_collection_status == "review_locked"
        result_fields = (
            self.result_locator,
            self.result_file_sha256,
            self.result_sha256,
            self.eligible_candidate_count,
            self.adjudication_required_count,
        )
        if locked != all(value is not None for value in result_fields):
            raise ValueError("Taste source-review result lineage is inconsistent")
        expected_collection_status = (
            "awaiting_owner_approval"
            if not ready
            else "authorized_sessions_ready"
            if self.reviewer_submissions_collected == 0
            else "collecting_reviews"
            if self.reviewer_submissions_collected < 3
            else "review_locked"
        )
        if self.review_collection_status != expected_collection_status:
            raise ValueError("Taste source-review collection status is inconsistent")
        if locked != (self.reviewer_submissions_collected == 3):
            raise ValueError("Taste source-review locked result requires three submissions")
        if self.ready_for_taste_abstraction_review and not locked:
            raise ValueError("Taste source-review abstraction readiness requires a result")
        planned = self.abstraction_plan_sha256 is not None
        plan_fields = (
            self.abstraction_plan_locator,
            self.abstraction_plan_file_sha256,
            self.abstraction_plan_sha256,
            self.abstraction_preparation_route,
            self.abstraction_model_execution_route,
            self.abstraction_human_review_route,
        )
        if planned != all(value is not None for value in plan_fields):
            raise ValueError("Taste abstraction plan lineage is inconsistent")
        if planned != bool(self.abstraction_input_count):
            raise ValueError("Taste abstraction input count is inconsistent")
        if self.abstraction_candidate_ceiling < self.abstraction_input_count:
            raise ValueError("Taste abstraction inputs exceed the campaign ceiling")
        expected_basis = "locked-eligible-inputs" if planned else "campaign-ceiling"
        if self.abstraction_capacity_basis != expected_basis:
            raise ValueError("Taste abstraction capacity basis differs from plan state")
        capacity_demand = (
            self.abstraction_input_count if planned else self.abstraction_candidate_ceiling
        )
        if self.abstraction_profile_capacity_gap != max(
            0, capacity_demand - self.abstraction_profile_capacity
        ):
            raise ValueError("Taste abstraction profile capacity gap is inconsistent")
        if not planned and self.ready_for_abstraction_model_authorization:
            raise ValueError("unplanned Taste abstraction cannot be authorized")
        if planned and self.ready_for_abstraction_model_authorization != (
            self.abstraction_profile_capacity_gap == 0
        ):
            raise ValueError("Taste abstraction readiness differs from profile capacity")
        if {self.run_ref_id, self.artifact_ref_id} - set(self.support_ref_ids):
            raise ValueError("Taste source-review campaign lacks registered evidence")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("Taste source-review evidence must be unique")
        return self


class ProjectProgressMetadataAuditPlanItem(BaseModel):
    """One no-read metadata plan whose next action is explicit owner approval."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    bundle_file_sha256: Sha256
    bundle_sha256: Sha256
    plan_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    plan_locator: SafeLocator
    plan_file_sha256: Sha256
    plan_sha256: Sha256
    receipt_sha256: Sha256
    receipt_locator: SafeLocator
    receipt_file_sha256: Sha256
    auditor_implementation_sha256: Sha256
    auditor_implementation_current: bool
    expected_item_count: int = Field(gt=0)
    formats: tuple[Literal["application/x-yaml", "text/csv"], ...] = Field(
        min_length=1,
        max_length=2,
    )
    maximum_total_source_bytes: int = Field(gt=0)
    status: Literal["awaiting_content_read_approval", "implementation_drift"]
    next_gate: Literal[
        "approve_exact_local_structured_metadata_read",
        "regenerate_plans_against_current_auditor",
    ]
    ready_for_owner_approval: bool
    source_content_read: Literal[False]
    owner_approval_recorded: Literal[False]
    authorizes_local_content_read: Literal[False]
    authorizes_projection: Literal[False]
    authorizes_ingestion: Literal[False]
    authorizes_execution: Literal[False]
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def plan_state_is_closed(self) -> ProjectProgressMetadataAuditPlanItem:
        if self.ready_for_owner_approval != self.auditor_implementation_current:
            raise ValueError("metadata audit plan readiness differs from implementation")
        expected_status = (
            "awaiting_content_read_approval"
            if self.ready_for_owner_approval
            else "implementation_drift"
        )
        if self.status != expected_status:
            raise ValueError("metadata audit plan status differs from readiness")
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("metadata audit plan must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("metadata audit plan evidence references must be unique")
        return self


class ProjectProgressBenchmarkMetadataPopulationItem(BaseModel):
    """One complete, result/model/compute-blind population before task screening."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    request_id: SafeIdentifier
    scope_id: SafeIdentifier
    population_file_sha256: Sha256
    population_sha256: Sha256
    plan_sha256: Sha256
    approval_sha256: Sha256
    audit_report_sha256: Sha256
    projection_implementation_current: bool
    media_type: Literal["application/x-yaml", "text/csv"]
    record_unit: Literal["one-record-per-acquired-item", "one-record-per-csv-row"]
    record_count: int = Field(gt=0)
    required_screen_fields: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=50)
    missing_source_field_observation_count: int = Field(ge=0)
    complete_population_projected: Literal[True]
    ready_for_screen_decision_proposal: Literal[True]
    selection_performed: Literal[False]
    formal_outcomes_consulted: Literal[False]
    model_inventory_consulted: Literal[False]
    compute_inventory_consulted: Literal[False]
    source_content_read: Literal[True]
    network_access_performed: Literal[False]
    linked_assets_resolved: Literal[False]
    ingestion_performed: Literal[False]
    model_calls_performed: Literal[False]
    gpu_work_performed: Literal[False]
    experiment_performed: Literal[False]
    authorizes_task_selection: Literal[False]
    authorizes_ingestion: Literal[False]
    authorizes_execution: Literal[False]
    next_gate: Literal["review_complete_population_and_freeze_screen_decisions"]
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def population_state_is_closed(self) -> ProjectProgressBenchmarkMetadataPopulationItem:
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("benchmark metadata population must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("benchmark metadata population evidence references must be unique")
        if tuple(sorted(set(self.required_screen_fields))) != self.required_screen_fields:
            raise ValueError("benchmark metadata population fields must be sorted and unique")
        return self


class ProjectProgressBenchmarkMetadataScreeningItem(BaseModel):
    """One complete eligibility ledger before powered allocation or task selection."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    scope_id: SafeIdentifier
    report_file_sha256: Sha256
    report_sha256: Sha256
    population_sha256: Sha256
    rulebook_sha256: Sha256
    decision_package_sha256: Sha256
    screening_implementation_current: bool
    record_count: int = Field(gt=0)
    eligibility_rule_count: int = Field(gt=0)
    allocation_rule_codes: tuple[SafeIdentifier, ...]
    eligible_record_count: int = Field(ge=0)
    excluded_record_count: int = Field(ge=0)
    blocked_record_count: int = Field(ge=0)
    ready_for_allocation_proposal: bool
    complete_population_screened: Literal[True]
    projected_metadata_read: Literal[True]
    raw_source_content_read: Literal[False]
    formal_outcomes_consulted: Literal[False]
    model_inventory_consulted: Literal[False]
    compute_inventory_consulted: Literal[False]
    current_host_inventory_consulted: Literal[False]
    model_calls_performed: Literal[False]
    selection_performed: Literal[False]
    allocation_performed: Literal[False]
    asset_download_performed: Literal[False]
    ingestion_performed: Literal[False]
    gpu_work_performed: Literal[False]
    experiment_performed: Literal[False]
    authorizes_allocation: Literal[False]
    authorizes_task_selection: Literal[False]
    authorizes_execution: Literal[False]
    next_gate: Literal["resolve_screen_evidence", "propose_powered_allocation"]
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def screening_state_is_closed(self) -> ProjectProgressBenchmarkMetadataScreeningItem:
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("benchmark metadata screening must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("benchmark metadata screening evidence references must be unique")
        if self.record_count != (
            self.eligible_record_count + self.excluded_record_count + self.blocked_record_count
        ):
            raise ValueError("benchmark metadata screening counts must cover every record")
        expected_ready = self.eligible_record_count > 0 and self.blocked_record_count == 0
        if self.ready_for_allocation_proposal != expected_ready:
            raise ValueError("benchmark metadata screening readiness differs from counts")
        expected_gate = (
            "propose_powered_allocation" if expected_ready else "resolve_screen_evidence"
        )
        if self.next_gate != expected_gate:
            raise ValueError("benchmark metadata screening next gate differs from readiness")
        return self


class ProjectProgressBenchmarkMetadataAllocationPlanItem(BaseModel):
    """One powered, outcome-blind allocation awaiting an exact owner decision."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    plan_id: SafeIdentifier
    scope_id: SafeIdentifier
    formal_study_id: SafeIdentifier
    plan_file_sha256: Sha256
    plan_sha256: Sha256
    screening_report_sha256: Sha256
    population_sha256: Sha256
    power_report_sha256: Sha256
    allocation_implementation_current: bool
    eligible_record_count: int = Field(ge=0)
    allocatable_record_count: int = Field(ge=0)
    excluded_record_count: int = Field(ge=0)
    blocked_record_count: int = Field(ge=0)
    available_independent_units: int = Field(ge=0)
    powered_independent_units: int = Field(gt=0)
    stratum_count: int = Field(ge=0)
    blocker_codes: tuple[SafeIdentifier, ...] = ()
    scientific_controls_ready: bool
    ready_for_owner_approval: bool
    status: Literal["blocked", "implementation_drift", "awaiting_owner_approval"]
    next_gate: Literal[
        "resolve_allocation_controls",
        "regenerate_allocation_plan",
        "approve_exact_powered_allocation",
    ]
    selected_identity_count: Literal[0] = 0
    allocation_performed: Literal[False]
    task_selection_performed: Literal[False]
    authorizes_allocation: Literal[False]
    authorizes_execution: Literal[False]
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def allocation_plan_state_is_closed(
        self,
    ) -> ProjectProgressBenchmarkMetadataAllocationPlanItem:
        expected_ready = self.scientific_controls_ready and self.allocation_implementation_current
        if self.ready_for_owner_approval != expected_ready:
            raise ValueError("allocation plan owner readiness differs from its controls")
        expected_status = (
            "implementation_drift"
            if not self.allocation_implementation_current
            else "awaiting_owner_approval"
            if self.scientific_controls_ready
            else "blocked"
        )
        if self.status != expected_status:
            raise ValueError("allocation plan status differs from its controls")
        expected_gate = {
            "implementation_drift": "regenerate_allocation_plan",
            "awaiting_owner_approval": "approve_exact_powered_allocation",
            "blocked": "resolve_allocation_controls",
        }[self.status]
        if self.next_gate != expected_gate:
            raise ValueError("allocation plan next gate differs from its status")
        if self.allocatable_record_count > self.eligible_record_count:
            raise ValueError("allocation plan usable records exceed eligibility")
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("allocation plan must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("allocation plan evidence references must be unique")
        return self


class ProjectProgressBenchmarkMetadataAllocationItem(BaseModel):
    """One approved, powered task-set freeze that still grants no execution authority."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    plan_id: SafeIdentifier
    scope_id: SafeIdentifier
    formal_study_id: SafeIdentifier
    report_file_sha256: Sha256
    report_sha256: Sha256
    plan_sha256: Sha256
    approval_sha256: Sha256
    screening_report_sha256: Sha256
    population_sha256: Sha256
    power_report_sha256: Sha256
    formal_task_set_sha256: Sha256
    allocation_implementation_current: bool
    screened_record_count: int = Field(gt=0)
    available_independent_units: int = Field(gt=0)
    powered_independent_units: int = Field(gt=0)
    selected_record_count: int = Field(gt=0)
    unsampled_eligible_record_count: int = Field(ge=0)
    excluded_record_count: int = Field(ge=0)
    blocked_record_count: int = Field(ge=0)
    stratum_count: int = Field(gt=0)
    status: Literal["task_set_frozen", "implementation_drift"]
    next_gate: Literal[
        "qualify_assets_and_freeze_prelaunch",
        "replay_allocation_against_current_implementation",
    ]
    owner_approval_recorded: Literal[True]
    source_groups_unique: Literal[True]
    powered_sample_size_satisfied: Literal[True]
    task_selection_frozen: Literal[True]
    experiment_performed: Literal[False]
    authorizes_execution: Literal[False]
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def allocation_state_is_closed(self) -> ProjectProgressBenchmarkMetadataAllocationItem:
        expected_status = (
            "task_set_frozen" if self.allocation_implementation_current else "implementation_drift"
        )
        if self.status != expected_status:
            raise ValueError("benchmark allocation status differs from implementation")
        expected_gate = (
            "qualify_assets_and_freeze_prelaunch"
            if self.allocation_implementation_current
            else "replay_allocation_against_current_implementation"
        )
        if self.next_gate != expected_gate:
            raise ValueError("benchmark allocation next gate differs from implementation")
        if self.selected_record_count != self.powered_independent_units:
            raise ValueError("benchmark allocation selected count differs from power")
        if (
            self.selected_record_count
            + self.unsampled_eligible_record_count
            + self.excluded_record_count
            + self.blocked_record_count
            != self.screened_record_count
        ):
            raise ValueError("benchmark allocation counts do not preserve its screen")
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("benchmark allocation must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("benchmark allocation evidence references must be unique")
        return self


class ProjectProgressReferenceSelectionComparisonItem(BaseModel):
    """One outcome-blind H0 quality-versus-prestige source-selection state."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    comparison_id: SafeIdentifier
    plan_file_sha256: Sha256
    plan_sha256: Sha256
    report_file_sha256: Sha256 | None = None
    report_sha256: Sha256 | None = None
    approval_sha256: Sha256 | None = None
    selection_implementation_current: bool
    candidate_count: int = Field(gt=0)
    target_source_count: int = Field(gt=0)
    content_grounded_admitted_count: int = Field(ge=0)
    downstream_eligible_count: int = Field(ge=0)
    matched_stratum_count: int | None = Field(default=None, gt=0)
    cross_arm_overlap_count: int | None = Field(default=None, ge=0)
    blocker_codes: tuple[SafeText, ...] = ()
    selection_performed: bool
    status: Literal[
        "blocked",
        "implementation_drift",
        "awaiting_owner_approval",
        "selection_frozen",
    ]
    next_gate: Literal[
        "resolve_source_selection_controls",
        "regenerate_source_selection_plan",
        "approve_exact_source_selection",
        "plan_h0_bound_source_projection",
    ]
    raw_source_content_read: Literal[False]
    model_calls_performed: Literal[False]
    experiment_performed: Literal[False]
    authorizes_experiment: Literal[False]
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def reference_selection_state_is_closed(
        self,
    ) -> ProjectProgressReferenceSelectionComparisonItem:
        expected_status = (
            "implementation_drift"
            if not self.selection_implementation_current
            else "selection_frozen"
            if self.selection_performed
            else "blocked"
            if self.blocker_codes
            else "awaiting_owner_approval"
        )
        if self.status != expected_status:
            raise ValueError("reference-selection status differs from its evidence")
        expected_gate = {
            "implementation_drift": "regenerate_source_selection_plan",
            "selection_frozen": "plan_h0_bound_source_projection",
            "blocked": "resolve_source_selection_controls",
            "awaiting_owner_approval": "approve_exact_source_selection",
        }[self.status]
        if self.next_gate != expected_gate:
            raise ValueError("reference-selection next gate differs from its status")
        report_values = (
            self.report_file_sha256,
            self.report_sha256,
            self.approval_sha256,
            self.matched_stratum_count,
            self.cross_arm_overlap_count,
        )
        if self.selection_performed != all(value is not None for value in report_values):
            raise ValueError("reference-selection frozen evidence is incomplete")
        if self.target_source_count > self.candidate_count:
            raise ValueError("reference-selection target exceeds the broad pool")
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("reference-selection state must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("reference-selection evidence references must be unique")
        return self


class ProjectProgressDatasetPackageTaskItem(BaseModel):
    """One task-level large-asset acquisition qualification."""

    model_config = _DATA_MODEL_CONFIG

    task_id: SafeIdentifier
    asset_count: int = Field(gt=0)
    observed_compressed_bytes: int = Field(gt=0)
    maximum_unpacked_bytes: int = Field(gt=0)
    license_disposition: Literal["verified", "review_required", "blocked"]
    exact_source_metadata_ready: bool
    ready_for_owner_approval: bool
    blocker_codes: tuple[SafeText, ...] = ()

    @model_validator(mode="after")
    def dataset_package_task_is_consistent(self) -> ProjectProgressDatasetPackageTaskItem:
        if self.maximum_unpacked_bytes < self.observed_compressed_bytes:
            raise ValueError("dataset package task unpacked ceiling is below compressed bytes")
        if self.ready_for_owner_approval and (
            not self.exact_source_metadata_ready
            or self.license_disposition != "verified"
            or self.blocker_codes
        ):
            raise ValueError("approval-ready dataset task retains unresolved evidence")
        return self


class ProjectProgressDatasetPackageItem(BaseModel):
    """One exact, no-download large benchmark asset decision."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    proposal_sha256: Sha256
    report_sha256: Sha256
    report_file_sha256: Sha256
    selected_task_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    source_hosts: tuple[SafeText, ...] = Field(min_length=1, max_length=20)
    asset_count: int = Field(gt=0)
    observed_download_bytes: int = Field(gt=0)
    maximum_unpacked_bytes: int = Field(gt=0)
    minimum_free_storage_bytes: int = Field(gt=0)
    task_qualifications: tuple[ProjectProgressDatasetPackageTaskItem, ...] = Field(min_length=1)
    metadata_review_ready: bool
    ready_for_owner_approval: bool
    pending_content_hash_count: int = Field(ge=0)
    integrity_blocker_codes: tuple[SafeText, ...] = ()
    approval_blocker_codes: tuple[SafeText, ...] = ()
    pending_qualification_codes: tuple[SafeText, ...] = ()
    authorization_blocker_codes: tuple[SafeText, ...] = ()
    post_approval_streaming_available: Literal[True] = True
    archive_safety_check_available: Literal[True] = True
    archive_safety_status: Literal["pending", "qualified", "blocked"] = "pending"
    archive_qualification_run_ref_id: SafeIdentifier | None = None
    archive_qualification_run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    archive_qualification_report_sha256: Sha256 | None = None
    archive_qualification_file_sha256: Sha256 | None = None
    archive_member_count: int | None = Field(default=None, ge=0)
    archive_expanded_bytes: int | None = Field(default=None, ge=0)
    all_receipt_hashes_reverified: bool | None = None
    license_coverage_status: Literal["pending", "qualified", "blocked"] = "pending"
    license_coverage_run_ref_id: SafeIdentifier | None = None
    license_coverage_run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    license_coverage_report_sha256: Sha256 | None = None
    license_coverage_file_sha256: Sha256 | None = None
    license_policy_sha256: Sha256 | None = None
    license_verification_route: Literal["targeted_check"] | None = None
    license_image_count: int | None = Field(default=None, ge=0)
    license_record_count: int | None = Field(default=None, ge=0)
    license_ingestion_ready: bool | None = None
    license_blocker_codes: tuple[SafeText, ...] = ()
    extraction_performed: Literal[False] = False
    authorizes_network_preflight: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False
    no_network_access_performed: Literal[True] = True
    no_download_performed: Literal[True] = True
    no_dataset_file_created: Literal[True] = True
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def dataset_package_is_consistent(self) -> ProjectProgressDatasetPackageItem:
        if self.asset_count != sum(item.asset_count for item in self.task_qualifications):
            raise ValueError("dataset package asset count differs from its tasks")
        if self.observed_download_bytes != sum(
            item.observed_compressed_bytes for item in self.task_qualifications
        ):
            raise ValueError("dataset package compressed bytes differ from its tasks")
        if self.maximum_unpacked_bytes != sum(
            item.maximum_unpacked_bytes for item in self.task_qualifications
        ):
            raise ValueError("dataset package unpacked ceiling differs from its tasks")
        if self.minimum_free_storage_bytes < self.maximum_unpacked_bytes:
            raise ValueError("dataset package free-storage floor is below its unpacked ceiling")
        if tuple(item.task_id for item in self.task_qualifications) != self.selected_task_ids:
            raise ValueError("dataset package task order differs from its selected tasks")
        if self.metadata_review_ready and self.integrity_blocker_codes:
            raise ValueError("metadata-ready dataset package retains integrity blockers")
        if self.ready_for_owner_approval and (
            not self.metadata_review_ready or self.approval_blocker_codes
        ):
            raise ValueError("approval-ready dataset package retains approval blockers")
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("dataset package must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("dataset package evidence references must be unique")
        qualification_fields = (
            self.archive_qualification_run_ref_id,
            self.archive_qualification_run_id,
            self.archive_qualification_report_sha256,
            self.archive_qualification_file_sha256,
            self.archive_member_count,
            self.archive_expanded_bytes,
            self.all_receipt_hashes_reverified,
        )
        if self.archive_safety_status == "pending" and any(
            value is not None for value in qualification_fields
        ):
            raise ValueError("pending archive qualification cannot expose result evidence")
        if self.archive_safety_status != "pending" and not all(
            value is not None for value in qualification_fields
        ):
            raise ValueError("observed archive qualification requires complete evidence")
        if (
            self.archive_safety_status == "qualified"
            and self.all_receipt_hashes_reverified is not True
        ):
            raise ValueError("qualified archives require reverified receipt hashes")
        if (
            self.archive_qualification_run_ref_id is not None
            and self.archive_qualification_run_ref_id not in self.support_ref_ids
        ):
            raise ValueError("archive qualification must cite its registered run")
        license_fields = (
            self.license_coverage_run_ref_id,
            self.license_coverage_run_id,
            self.license_coverage_report_sha256,
            self.license_coverage_file_sha256,
            self.license_policy_sha256,
            self.license_verification_route,
            self.license_image_count,
            self.license_record_count,
            self.license_ingestion_ready,
        )
        if self.license_coverage_status == "pending" and (
            any(value is not None for value in license_fields) or self.license_blocker_codes
        ):
            raise ValueError("pending license coverage cannot expose result evidence")
        if self.license_coverage_status != "pending" and not all(
            value is not None for value in license_fields
        ):
            raise ValueError("observed license coverage requires complete evidence")
        if self.license_coverage_status == "qualified" and (
            self.license_ingestion_ready is not True or self.license_blocker_codes
        ):
            raise ValueError("qualified license coverage differs from its evidence")
        if self.license_coverage_status == "blocked" and (
            self.license_ingestion_ready is not False or not self.license_blocker_codes
        ):
            raise ValueError("blocked license coverage differs from its evidence")
        if (
            self.license_coverage_run_ref_id is not None
            and self.license_coverage_run_ref_id not in self.support_ref_ids
        ):
            raise ValueError("license coverage must cite its registered run")
        return self


class ProjectProgressBenchmarkQualificationItem(BaseModel):
    """One no-run benchmark/compute compatibility decision."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    candidate_id: SafeIdentifier
    proposal_sha256: Sha256
    report_sha256: Sha256
    report_file_sha256: Sha256
    accepted_task_count: int = Field(gt=0)
    selected_task_count: int = Field(gt=0)
    excluded_task_count: int = Field(ge=0)
    selected_task_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    excluded_task_ids: tuple[SafeIdentifier, ...] = ()
    first_preflight_candidate_ids: tuple[SafeIdentifier, ...] = ()
    planned_cells: int = Field(gt=0)
    planned_gpu_hours: float = Field(gt=0)
    formal_gpu_hour_cap: float = Field(gt=0)
    metadata_review_ready: bool
    acquisition_request_ready: bool
    local_preflight_ready: bool
    experiment_ready: bool
    requires_additional_48gb_single_device_resource: bool
    integrity_blocker_codes: tuple[SafeIdentifier, ...] = ()
    qualification_blocker_codes: tuple[SafeIdentifier, ...] = ()
    pending_qualification_codes: tuple[SafeIdentifier, ...] = ()
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False
    external_action_performed: Literal[False] = False
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def benchmark_qualification_is_consistent(
        self,
    ) -> ProjectProgressBenchmarkQualificationItem:
        if self.selected_task_count != len(self.selected_task_ids):
            raise ValueError("benchmark selected-task count differs from its inventory")
        if self.excluded_task_count != len(self.excluded_task_ids):
            raise ValueError("benchmark excluded-task count differs from its inventory")
        if self.accepted_task_count != self.selected_task_count + self.excluded_task_count:
            raise ValueError("benchmark accepted tasks must equal selected plus excluded")
        task_ids = (*self.selected_task_ids, *self.excluded_task_ids)
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("benchmark qualification task IDs must be unique")
        if not set(self.first_preflight_candidate_ids) <= set(self.selected_task_ids):
            raise ValueError("first-preflight tasks must belong to the selected task set")
        if self.planned_gpu_hours > self.formal_gpu_hour_cap:
            raise ValueError("benchmark qualification exceeds its GPU-hour cap")
        if self.metadata_review_ready and self.integrity_blocker_codes:
            raise ValueError(
                "metadata-ready benchmark qualification cannot retain integrity blockers"
            )
        if self.experiment_ready and (
            not self.local_preflight_ready
            or self.qualification_blocker_codes
            or self.pending_qualification_codes
        ):
            raise ValueError("experiment-ready benchmark qualification retains unresolved gates")
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("benchmark qualification must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("benchmark qualification references must be unique")
        return self


class ProjectProgressReviewIterationStepItem(BaseModel):
    """One compact node from a project-owned reviewer iteration plan."""

    model_config = _DATA_MODEL_CONFIG

    step_id: str = Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    kind: Literal[
        "prose_revision",
        "claim_revision",
        "evidence_analysis",
        "experiment_design",
        "experiment_execution",
        "method_revision_proposal",
        "method_validation",
        "revision_input",
        "paper_revision",
        "author_response",
        "reviewer_verification",
    ]
    stage: Literal["research", "evidence", "method", "writing", "review"]
    objective: SafeText
    depends_on: tuple[
        Annotated[str, Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")],
        ...,
    ] = ()
    state: Literal[
        "ready",
        "blocked_by_dependency",
        "owner_approval_required",
        "independent_review_required",
    ]
    requires_owner_approval: bool
    project_interface: SafeText
    study_ids: tuple[SafeIdentifier, ...] = ()
    hypothesis_ids: tuple[
        Annotated[str, Field(max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")],
        ...,
    ] = ()

    @model_validator(mode="after")
    def evidence_bindings_are_unique(self) -> ProjectProgressReviewIterationStepItem:
        if len(self.study_ids) != len(set(self.study_ids)):
            raise ValueError("review iteration UI study IDs must be unique")
        if len(self.hypothesis_ids) != len(set(self.hypothesis_ids)):
            raise ValueError("review iteration UI hypothesis IDs must be unique")
        return self


class ProjectProgressReviewIterationLaneItem(BaseModel):
    """Aggregated lane used to render a large review DAG without a long page."""

    model_config = _DATA_MODEL_CONFIG

    stage: Literal["research", "method", "evidence", "writing", "review"]
    step_ids: tuple[
        Annotated[str, Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")],
        ...,
    ] = Field(min_length=1, max_length=1_000)
    ready_count: int = Field(ge=0)
    approval_count: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_fit_lane(self) -> ProjectProgressReviewIterationLaneItem:
        if len(self.step_ids) != len(set(self.step_ids)):
            raise ValueError("review iteration lane step IDs must be unique")
        if self.ready_count > len(self.step_ids) or self.approval_count > len(self.step_ids):
            raise ValueError("review iteration lane counts exceed its step inventory")
        return self


class ProjectProgressReviewIterationEdgeItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    source_stage: Literal["research", "method", "evidence", "writing", "review"]
    target_stage: Literal["research", "method", "evidence", "writing", "review"]
    dependency_count: int = Field(gt=0)


class ProjectProgressReviewActivationItem(BaseModel):
    """Horizontal no-run launch gate projected from a project activation record."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    activation_sha256: Sha256
    study_count: int = Field(gt=0, le=30)
    metadata_item_count: int = Field(gt=0)
    metadata_byte_ceiling: int = Field(gt=0)
    metadata_source_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=30)
    metadata_decision_ready: Literal[True]
    primary_model_candidate_count: int = Field(ge=2, le=10)
    pilot_ready_model_count: int = Field(ge=0, le=10)
    model_identity_protocol_id: SafeIdentifier | None = None
    identity_protocol_model_count: int = Field(default=0, ge=0, le=10)
    pilot_proposal_ready_model_count: int = Field(default=0, ge=0, le=10)
    external_system_count: int = Field(ge=0, le=30)
    adapter_ready_system_count: int = Field(ge=0, le=30)
    minimum_reviewer_count: int = Field(ge=2)
    recruited_reviewer_count: int = Field(ge=0)
    next_owner_decision_id: Literal["review-exact-metadata-acquisition"]
    blocker_count: int = Field(gt=0)
    ready_for_experiment: Literal[False]
    authorizes_execution: Literal[False]
    no_external_action_performed: Literal[True]

    @model_validator(mode="after")
    def counts_and_sources_are_closed(self) -> ProjectProgressReviewActivationItem:
        if len(self.metadata_source_ids) != len(set(self.metadata_source_ids)):
            raise ValueError("review activation metadata sources must be unique")
        if self.pilot_ready_model_count > self.primary_model_candidate_count:
            raise ValueError("pilot-ready model count exceeds candidate count")
        if self.identity_protocol_model_count > self.primary_model_candidate_count:
            raise ValueError("identity-protocol model count exceeds candidate count")
        if self.pilot_proposal_ready_model_count > self.primary_model_candidate_count:
            raise ValueError("pilot-proposal model count exceeds candidate count")
        if (self.model_identity_protocol_id is None) != (self.identity_protocol_model_count == 0):
            raise ValueError("identity protocol ID and candidate count must agree")
        if self.adapter_ready_system_count > self.external_system_count:
            raise ValueError("adapter-ready system count exceeds system count")
        return self


class ProjectProgressReviewFollowupDesignItem(BaseModel):
    """Compact projection of the exact no-run evidence response to a review."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    design_sha256: Sha256
    evidence_program_id: SafeIdentifier
    treatment_count: int = Field(gt=0)
    study_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=30)
    hypothesis_ids: tuple[
        Annotated[str, Field(max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")],
        ...,
    ] = Field(min_length=1, max_length=30)
    confirmatory_study_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=30)
    supporting_study_ids: tuple[SafeIdentifier, ...] = Field(max_length=30)
    diagnostic_study_ids: tuple[SafeIdentifier, ...] = Field(max_length=30)
    task_source_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=30)
    system_candidate_ids: tuple[SafeIdentifier, ...] = Field(max_length=30)
    primary_model_state: Literal["unselected"]
    task_data_state: Literal["pending", "verified", "blocked"]
    sample_size_state: Literal["pilot_then_power_analysis"]
    compute_state: Literal["unallocated"]
    title_claim_status: Literal["submission_blocked_pending_title_critical_evidence"]
    authorizes_execution: Literal[False] = False
    no_execution_performed: Literal[True] = True
    activation: ProjectProgressReviewActivationItem | None = None

    @model_validator(mode="after")
    def inventories_are_unique_and_partitioned(
        self,
    ) -> ProjectProgressReviewFollowupDesignItem:
        inventories = (
            self.study_ids,
            self.hypothesis_ids,
            self.task_source_ids,
            self.system_candidate_ids,
        )
        if any(len(items) != len(set(items)) for items in inventories):
            raise ValueError("review follow-up design inventories must be unique")
        roles = (
            *self.confirmatory_study_ids,
            *self.supporting_study_ids,
            *self.diagnostic_study_ids,
        )
        if len(roles) != len(set(roles)) or set(roles) != set(self.study_ids):
            raise ValueError("review follow-up inference roles must partition its studies")
        if self.activation is not None and self.activation.study_count != len(self.study_ids):
            raise ValueError("review activation study count differs from its evidence design")
        return self


class ProjectProgressReviewIterationItem(BaseModel):
    """Condensed, evidence-bound review-to-research workflow for the project home."""

    model_config = _DATA_MODEL_CONFIG

    run_ref_id: SafeIdentifier
    run_id: str = Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    review_id: str = Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    plan_sha256: Sha256
    concern_count: int = Field(gt=0)
    obligation_count: int = Field(gt=0)
    step_count: int = Field(ge=5)
    next_step_ids: tuple[
        Annotated[str, Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")],
        ...,
    ] = Field(min_length=1, max_length=320)
    owner_approval_step_ids: tuple[
        Annotated[str, Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")],
        ...,
    ] = Field(max_length=320)
    terminal_step_id: str = Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    steps: tuple[ProjectProgressReviewIterationStepItem, ...] = Field(
        min_length=5, max_length=1_000
    )
    lanes: tuple[ProjectProgressReviewIterationLaneItem, ...] = Field(min_length=1, max_length=5)
    lane_edges: tuple[ProjectProgressReviewIterationEdgeItem, ...] = Field(max_length=25)
    execution_approval_required: bool
    authorizes_execution: Literal[False] = False
    no_execution_performed: Literal[True] = True
    followup_design: ProjectProgressReviewFollowupDesignItem | None = None
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def graph_summary_is_closed(self) -> ProjectProgressReviewIterationItem:
        if self.run_ref_id not in self.support_ref_ids:
            raise ValueError("review iteration must cite its registered run")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("review iteration evidence references must be unique")
        if (
            self.followup_design is not None
            and self.followup_design.run_ref_id not in self.support_ref_ids
        ):
            raise ValueError("review iteration must cite its follow-up evidence design")
        if (
            self.followup_design is not None
            and self.followup_design.activation is not None
            and self.followup_design.activation.run_ref_id not in self.support_ref_ids
        ):
            raise ValueError("review iteration must cite its follow-up activation dossier")
        step_ids = [item.step_id for item in self.steps]
        if len(step_ids) != self.step_count or len(step_ids) != len(set(step_ids)):
            raise ValueError("review iteration step count differs from its unique inventory")
        known: set[str] = set()
        for item in self.steps:
            if any(dependency not in known for dependency in item.depends_on):
                raise ValueError("review iteration UI steps must remain topologically ordered")
            known.add(item.step_id)
        roots = tuple(item.step_id for item in self.steps if not item.depends_on)
        if roots != self.next_step_ids:
            raise ValueError("review iteration UI roots differ from next steps")
        approvals = tuple(item.step_id for item in self.steps if item.requires_owner_approval)
        if approvals != self.owner_approval_step_ids:
            raise ValueError("review iteration UI approval steps differ")
        if self.execution_approval_required != bool(approvals):
            raise ValueError("review iteration UI approval summary differs")
        if self.terminal_step_id not in known:
            raise ValueError("review iteration UI terminal step is missing")
        lane_steps = [step_id for lane in self.lanes for step_id in lane.step_ids]
        if len(lane_steps) != len(set(lane_steps)) or set(lane_steps) != set(step_ids):
            raise ValueError("review iteration lanes must partition every step")
        stage_by_id = {item.step_id: item.stage for item in self.steps}
        expected_edges: dict[tuple[str, str], int] = {}
        for item in self.steps:
            for dependency in item.depends_on:
                edge = (stage_by_id[dependency], item.stage)
                if edge[0] != edge[1]:
                    expected_edges[edge] = expected_edges.get(edge, 0) + 1
        observed_edges = {
            (item.source_stage, item.target_stage): item.dependency_count
            for item in self.lane_edges
        }
        if len(observed_edges) != len(self.lane_edges):
            raise ValueError("review iteration lane edges must be unique")
        if observed_edges != expected_edges:
            raise ValueError("review iteration lane edges differ from its dependency graph")
        return self


class ProjectProgressCandidateItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    candidate_id: SafeIdentifier
    kind: Literal[
        "review_progress",
        "diagnose_blockers",
        "compare_runs",
        "review_paper_evidence",
        "review_next_gate",
        "review_research_landscape",
        "review_data_acquisition",
        "approve_metadata_audit",
        "review_metadata_population",
        "review_metadata_screening",
        "approve_metadata_allocation",
        "review_metadata_allocation",
        "approve_reference_selection",
        "review_reference_selection",
        "review_benchmark_qualification",
        "review_iteration",
        "review_taste_population",
        "plan_taste_abstraction",
    ]
    label_code: SafeIdentifier
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    target_ids: tuple[str, ...] = ()

    @field_validator("target_ids")
    @classmethod
    def targets_are_safe_entry_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        pattern = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
        if any(not re.fullmatch(pattern, value) for value in values):
            raise ValueError("project progress candidate targets must be safe entry IDs")
        if len(values) != len(set(values)):
            raise ValueError("project progress candidate targets must be unique")
        return values

    @model_validator(mode="after")
    def candidate_support_is_unique(self) -> ProjectProgressCandidateItem:
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("project progress candidate evidence references must be unique")
        return self


class ProjectLifecycleGateItem(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    gate_id: Literal[
        "idea",
        "evidence",
        "lineage",
        "paper",
        "submission",
        "review",
        "response_verification",
        "independent_review",
    ]
    state: Literal["satisfied", "blocked", "unavailable"]
    reason_code: SafeIdentifier
    support_ref_ids: tuple[SafeIdentifier, ...] = ()

    @model_validator(mode="after")
    def evidence_matches_gate(self) -> ProjectLifecycleGateItem:
        if self.state == "satisfied" and not self.support_ref_ids:
            raise ValueError("a satisfied project lifecycle gate requires evidence")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("project lifecycle evidence references must be unique")
        return self


class ProjectLifecycleSummaryData(BaseModel):
    model_config = _DATA_MODEL_CONFIG

    lifecycle_state: Literal[
        "discovery",
        "evidence",
        "paper",
        "review",
        "revision",
        "internally_closed",
        "independently_reviewed",
    ]
    current_paper_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    current_review_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    current_evaluation_result_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    )
    idea_to_paper_complete: bool
    internal_review_cycle_complete: bool
    independent_pre_submission_review_complete: bool
    scientific_evidence_complete: bool
    paper_scientific_evidence_bound: bool
    top_venue_evidence_loop_complete: bool
    official_decision_authority: Literal[False] = False
    scientific_effectiveness_established: bool = False
    gates: tuple[ProjectLifecycleGateItem, ...] = Field(min_length=8, max_length=8)
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def lifecycle_summary_is_closed(self) -> ProjectLifecycleSummaryData:
        expected = (
            "idea",
            "evidence",
            "lineage",
            "paper",
            "submission",
            "review",
            "response_verification",
            "independent_review",
        )
        if tuple(item.gate_id for item in self.gates) != expected:
            raise ValueError("project lifecycle gates must remain in canonical order")
        cited = {ref for item in self.gates for ref in item.support_ref_ids}
        if cited - set(self.support_ref_ids):
            raise ValueError("project lifecycle gate cites evidence outside its support set")
        expected_loop = (
            self.independent_pre_submission_review_complete
            and self.scientific_evidence_complete
            and self.paper_scientific_evidence_bound
        )
        if self.top_venue_evidence_loop_complete != expected_loop:
            raise ValueError("project top-venue loop does not match its evidence states")
        if self.paper_scientific_evidence_bound and not self.scientific_evidence_complete:
            raise ValueError("project paper cannot bind incomplete scientific evidence")
        if self.scientific_effectiveness_established and not self.scientific_evidence_complete:
            raise ValueError("project effectiveness requires complete scientific evidence")
        return self


class ProjectEvidenceProgramPhaseItem(BaseModel):
    """One collapsed phase in a project-owned scientific evidence program."""

    model_config = _DATA_MODEL_CONFIG

    phase_id: Literal[
        "research-basis",
        "taste-instrument",
        "method-readiness",
        "independent-review",
        "prepilot-evidence",
        "formal-evidence",
        "paper-review-loop",
    ]
    label_code: SafeIdentifier
    state: Literal["complete", "current", "blocked", "future"]
    stage_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    decision_stage_ids: tuple[SafeIdentifier, ...] = ()
    completed_stage_count: int = Field(ge=0)
    stage_count: int = Field(gt=0)
    blocker_count: int = Field(ge=0)
    owner_approval_required: bool
    external_actions: tuple[SafeIdentifier, ...] = ()
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def phase_counts_and_references_are_closed(self) -> ProjectEvidenceProgramPhaseItem:
        if self.completed_stage_count > self.stage_count:
            raise ValueError("evidence-program completed stages cannot exceed all stages")
        if len(self.stage_ids) != self.stage_count or len(self.stage_ids) != len(
            set(self.stage_ids)
        ):
            raise ValueError("evidence-program phase stage IDs must be complete and unique")
        if set(self.decision_stage_ids) - set(self.stage_ids):
            raise ValueError("evidence-program decision stages must belong to their phase")
        for values in (
            self.decision_stage_ids,
            self.external_actions,
            self.support_ref_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("evidence-program phase values must be unique")
        if self.state == "complete" and self.completed_stage_count != self.stage_count:
            raise ValueError("a complete evidence-program phase requires every stage")
        if self.state == "current" and not self.decision_stage_ids:
            raise ValueError("a current evidence-program phase requires a next decision")
        return self


class ProjectEvidenceProgramTrackItem(BaseModel):
    """One scientific claim track without implying that its experiment has run."""

    model_config = _DATA_MODEL_CONFIG

    track_id: SafeIdentifier
    role: Literal[
        "scientific_taste_mechanism",
        "native_taste_causal",
        "end_to_end_external_systems",
        "small_model_robustness",
    ]
    state: Literal["design_only", "blocked", "ready_for_decision"]
    resource_kind: Literal["unselected", "api", "gpu"]
    planned_cells: int | None = Field(default=None, gt=0)
    population_floor: int | None = Field(default=None, gt=0)
    blocker_count: int = Field(ge=0)
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def track_state_is_truthful(self) -> ProjectEvidenceProgramTrackItem:
        if self.state == "ready_for_decision" and self.blocker_count:
            raise ValueError("a decision-ready evidence track cannot retain blockers")
        if self.state != "ready_for_decision" and not self.blocker_count:
            raise ValueError("a non-ready evidence track requires blockers")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("evidence-program track references must be unique")
        return self


class ProjectPlanningDirectiveData(BaseModel):
    """Published user-approved planning overlay; it grants no execution authority."""

    model_config = _DATA_MODEL_CONFIG

    publication_id: SafeIdentifier
    publication_sha256: Sha256
    run_id: str = Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    run_ref_id: SafeIdentifier
    artifact_ref_id: SafeIdentifier
    source_dossier_sha256: Sha256
    proposal_id: SafeIdentifier
    proposal_record_sha256: Sha256
    decision_id: SafeIdentifier
    decision_sha256: Sha256
    change_kind: Literal[
        "reprioritize_next_gates",
        "clarify_stage_decision",
        "request_resource_revision",
        "add_risk_note",
    ]
    target_stage_id: SafeIdentifier
    target_track_ids: tuple[SafeIdentifier, ...] = ()
    proposed_next_stage_order: tuple[SafeIdentifier, ...] = ()
    summary: SafeText
    required_evidence: tuple[SafeText, ...] = Field(default=(), max_length=12)
    requested_resource_roles: tuple[SafeIdentifier, ...] = Field(default=(), max_length=12)
    requested_resource_ids: tuple[SafeIdentifier, ...] = Field(default=(), max_length=12)
    predecessor_publication_id: SafeIdentifier | None = None
    predecessor_publication_sha256: Sha256 | None = None
    source_dossier_unchanged: Literal[True] = True
    source_resource_binding_unchanged: Literal[True] = True
    authorizes_external_action: Literal[False] = False
    authorizes_execution: Literal[False] = False
    verification_route: Literal["direct_path"] = "direct_path"
    verification_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1)
    controller_consumed: bool = False
    effective_program_sha256: Sha256 | None = None
    control_effect: (
        Literal[
            "stage_order",
            "decision_guidance",
            "risk_note",
            "resource_preference",
        ]
        | None
    ) = None
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def planning_directive_is_closed(self) -> ProjectPlanningDirectiveData:
        if (self.predecessor_publication_id is None) != (
            self.predecessor_publication_sha256 is None
        ):
            raise ValueError("planning-directive predecessor identity must be complete")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("planning-directive support references must be unique")
        if {self.run_ref_id, self.artifact_ref_id} - set(self.support_ref_ids):
            raise ValueError("planning-directive evidence is outside its support set")
        if self.controller_consumed != (self.effective_program_sha256 is not None):
            raise ValueError("planning-directive controller status requires an effective program")
        if self.controller_consumed != (self.control_effect is not None):
            raise ValueError("planning-directive controller effect must be atomic")
        return self


class ProjectProgramActionRouteData(BaseModel):
    """Tool Intelligence route for the current effective gate, without authority."""

    model_config = _DATA_MODEL_CONFIG

    route_sha256: Sha256
    effective_program_sha256: Sha256
    stage_id: SafeIdentifier
    stage_state: Literal["ready_for_decision", "blocked", "future"]
    blocker_codes: tuple[SafeText, ...] = Field(default=(), max_length=100)
    external_actions: tuple[SafeIdentifier, ...] = Field(default=(), max_length=10)
    routing_basis: Literal["declared-policy-priors"]
    next_action_kind: Literal[
        "request_owner_decision",
        "run_targeted_check",
        "run_full_preflight",
        "resolve_registered_blockers",
        "continue_directly",
    ]
    verification_route: Literal[
        "direct_path",
        "targeted_check",
        "full_preflight",
        "owner_approval",
    ]
    verification_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=12)
    action_effects: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=8)
    expected_loss_units: float = Field(ge=0)
    targeted_net_gain_units: float
    full_preflight_net_gain_units: float
    owner_approval_required: bool
    model_advisory_eligible: bool
    decision_source: Literal["deterministic", "model_assisted"]
    advisory_fingerprint: Sha256 | None = None
    selected_by_tool_intelligence: Literal[True] = True
    authorizes_external_action: Literal[False] = False
    authorizes_execution: Literal[False] = False
    execution_authority: Literal["none"] = "none"
    no_external_action_performed: Literal[True] = True

    @model_validator(mode="after")
    def action_route_is_closed(self) -> ProjectProgramActionRouteData:
        if len(self.blocker_codes) != len(set(self.blocker_codes)):
            raise ValueError("program action blockers must be unique")
        if len(self.external_actions) != len(set(self.external_actions)):
            raise ValueError("program external actions must be unique")
        if len(self.action_effects) != len(set(self.action_effects)):
            raise ValueError("program action effects must be unique")
        expected_actions = {
            "owner_approval": {"request_owner_decision"},
            "targeted_check": {"run_targeted_check"},
            "full_preflight": {"run_full_preflight"},
            "direct_path": {"resolve_registered_blockers", "continue_directly"},
        }
        if self.next_action_kind not in expected_actions[self.verification_route]:
            raise ValueError("program next action differs from its verification route")
        if self.owner_approval_required != (
            self.verification_route in {"owner_approval", "full_preflight"}
            and (
                "declared_owner_boundary" in self.action_effects
                or "external_mutation" in self.action_effects
                or "secret_access" in self.action_effects
                or "paid_compute" in self.action_effects
                or "untrusted_code" in self.action_effects
            )
        ):
            raise ValueError("program action owner boundary differs from its effects")
        if (self.decision_source == "model_assisted") != (self.advisory_fingerprint is not None):
            raise ValueError("model-assisted program action requires its advisory fingerprint")
        return self


class ProjectEvidenceProgramData(BaseModel):
    """Compact, content-bound ICLR evidence roadmap projected from one run artifact."""

    model_config = _DATA_MODEL_CONFIG

    run_id: str = Field(max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    run_ref_id: SafeIdentifier
    artifact_ref_id: SafeIdentifier
    dossier_id: SafeIdentifier
    dossier_sha256: Sha256
    dossier_report_sha256: Sha256
    paper_title: SafeText
    target_venue: SafeText
    central_question: SafeText
    claim_boundary: SafeText
    artifact_bindings_verified: bool
    exact_cell_count: int = Field(ge=0)
    total_stage_count: int = Field(gt=0)
    completed_stage_count: int = Field(ge=0)
    next_stage_count: int = Field(ge=0)
    planning_authority: Literal["dossier_only", "user_published_control"]
    control_effect: Literal[
        "none",
        "stage_order",
        "decision_guidance",
        "risk_note",
        "resource_preference",
    ]
    source_publication_id: SafeIdentifier | None = None
    source_publication_sha256: Sha256 | None = None
    effective_program_sha256: Sha256
    planning_verification_route: Literal["direct_path"] = "direct_path"
    planning_verification_reason_codes: tuple[SafeIdentifier, ...] = Field(min_length=1)
    baseline_next_stage_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    effective_next_stage_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    current_phase_id: SafeIdentifier
    current_stage_id: SafeIdentifier
    current_decision: SafeText
    current_blocker_count: int = Field(ge=0)
    current_owner_approval_required: bool
    current_external_actions: tuple[SafeIdentifier, ...] = ()
    gate_action_route: ProjectProgramActionRouteData
    next_gate_action_routes: tuple[ProjectProgramActionRouteData, ...] = Field(
        default=(),
        max_length=50,
    )
    current_action_run_id: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    current_action_run_ref_id: SafeIdentifier | None = None
    phases: tuple[ProjectEvidenceProgramPhaseItem, ...] = Field(min_length=7, max_length=7)
    tracks: tuple[ProjectEvidenceProgramTrackItem, ...] = Field(min_length=1, max_length=4)
    planning_directive: ProjectPlanningDirectiveData | None = None
    scientific_effectiveness_established: Literal[False] = False
    no_external_action_performed: Literal[True] = True
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def evidence_program_is_closed(self) -> ProjectEvidenceProgramData:
        expected_phases = (
            "research-basis",
            "taste-instrument",
            "method-readiness",
            "independent-review",
            "prepilot-evidence",
            "formal-evidence",
            "paper-review-loop",
        )
        if tuple(item.phase_id for item in self.phases) != expected_phases:
            raise ValueError("evidence-program phases must remain in canonical order")
        if self.current_phase_id not in expected_phases:
            raise ValueError("evidence-program current phase must be registered")
        if self.current_stage_id not in {
            stage_id for phase in self.phases for stage_id in phase.stage_ids
        }:
            raise ValueError("evidence-program current stage must be registered")
        if self.completed_stage_count > self.total_stage_count:
            raise ValueError("completed evidence-program stages cannot exceed all stages")
        if self.next_stage_count != len(self.effective_next_stage_ids):
            raise ValueError("evidence-program next-stage count must use its effective order")
        if self.current_stage_id != self.effective_next_stage_ids[0]:
            raise ValueError("evidence-program current stage must lead its effective order")
        if self.next_gate_action_routes:
            route_stage_ids = tuple(item.stage_id for item in self.next_gate_action_routes)
            if route_stage_ids != self.effective_next_stage_ids:
                raise ValueError("next-gate Tool Intelligence routes must follow effective order")
            if self.next_gate_action_routes[0] != self.gate_action_route:
                raise ValueError("current gate route must lead next-gate Tool Intelligence routes")
            if any(
                item.effective_program_sha256 != self.effective_program_sha256
                for item in self.next_gate_action_routes
            ):
                raise ValueError("next-gate Tool Intelligence routes target another program")
        for values in (self.baseline_next_stage_ids, self.effective_next_stage_ids):
            if len(values) != len(set(values)):
                raise ValueError("evidence-program next-stage order must be unique")
        if set(self.baseline_next_stage_ids) != set(self.effective_next_stage_ids):
            raise ValueError("planning controls cannot add or remove eligible next stages")
        if self.planning_authority == "dossier_only" and self.control_effect != "none":
            raise ValueError("dossier-only evidence program cannot claim a control effect")
        publication_identity = (
            self.source_publication_id,
            self.source_publication_sha256,
        )
        if self.planning_authority == "dossier_only" and any(
            value is not None for value in publication_identity
        ):
            raise ValueError("dossier-only evidence program cannot claim a publication")
        if self.planning_authority == "user_published_control" and self.control_effect == "none":
            raise ValueError("published evidence program requires a typed control effect")
        if self.planning_authority == "user_published_control" and not all(
            value is not None for value in publication_identity
        ):
            raise ValueError("published evidence program requires source publication identity")
        if sum(item.stage_count for item in self.phases) != self.total_stage_count:
            raise ValueError("evidence-program phases must cover every dossier stage")
        if sum(item.completed_stage_count for item in self.phases) != self.completed_stage_count:
            raise ValueError("evidence-program completed-stage counts must agree")
        if len(self.support_ref_ids) != len(set(self.support_ref_ids)):
            raise ValueError("evidence-program references must be unique")
        required_refs = {self.run_ref_id, self.artifact_ref_id}
        if self.current_action_run_ref_id is not None:
            required_refs.add(self.current_action_run_ref_id)
        if required_refs - set(self.support_ref_ids):
            raise ValueError("evidence-program evidence is outside its support set")
        if (self.current_action_run_id is None) != (self.current_action_run_ref_id is None):
            raise ValueError("evidence-program action run identity must be complete")
        if (
            self.gate_action_route.stage_id != self.current_stage_id
            or self.gate_action_route.effective_program_sha256 != self.effective_program_sha256
            or len(self.gate_action_route.blocker_codes) != self.current_blocker_count
            or self.gate_action_route.external_actions != self.current_external_actions
            or self.gate_action_route.owner_approval_required
            != self.current_owner_approval_required
        ):
            raise ValueError("program gate action route differs from the current gate")
        if any(set(item.support_ref_ids) - set(self.support_ref_ids) for item in self.phases):
            raise ValueError("evidence-program phase evidence is outside its support set")
        if any(set(item.support_ref_ids) - set(self.support_ref_ids) for item in self.tracks):
            raise ValueError("evidence-program track evidence is outside its support set")
        if self.planning_directive is not None and (
            set(self.planning_directive.support_ref_ids) - set(self.support_ref_ids)
        ):
            raise ValueError("planning-directive evidence is outside the program support set")
        if self.planning_directive is not None:
            if (
                self.planning_authority != "user_published_control"
                or self.planning_directive.publication_id != self.source_publication_id
                or self.planning_directive.publication_sha256 != self.source_publication_sha256
                or not self.planning_directive.controller_consumed
                or self.planning_directive.effective_program_sha256 != self.effective_program_sha256
                or self.planning_directive.control_effect != self.control_effect
            ):
                raise ValueError("planning directive differs from the effective core program")
        return self


class ProjectResourcePortfolioItem(BaseModel):
    """One secret-free project binding to a shared compute resource."""

    model_config = _DATA_MODEL_CONFIG

    binding_id: SafeIdentifier
    resource_id: SafeIdentifier
    kind: Literal["api_model", "gpu_host", "model_checkpoint"]
    role: SafeIdentifier
    priority: int = Field(ge=1, le=100)
    binding_status: Literal["verified", "reported", "pending", "blocked"]
    observed_status: Literal["verified", "reported", "pending", "blocked", "unobserved"]
    access_state: Literal["configured", "missing", "not_required"]
    connection_metadata_complete: bool | None = None
    local_path_present: bool | None = None
    required_for: tuple[SafeIdentifier, ...] = Field(default=(), max_length=20)


class ProjectAvailableResourceItem(BaseModel):
    """One shared-catalog resource that is not yet attached to this project."""

    model_config = _DATA_MODEL_CONFIG

    resource_id: SafeIdentifier
    kind: Literal["api_model", "gpu_host", "model_checkpoint"]
    selection_status: Literal["current", "historical", "disabled"]
    attachable: bool
    observed_status: Literal["verified", "reported", "pending", "blocked", "unobserved"]
    access_state: Literal["configured", "missing", "not_required"]
    compatible_roles: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=20)
    connection_metadata_complete: bool | None = None
    local_path_present: bool | None = None

    @model_validator(mode="after")
    def attachability_matches_lifecycle(self) -> ProjectAvailableResourceItem:
        if self.attachable != (self.selection_status == "current"):
            raise ValueError("project resource attachability differs from catalog lifecycle")
        return self


class ProjectResourcePortfolioData(BaseModel):
    """Project-owned view of a shared registry; secrets and execution remain outside it."""

    model_config = _DATA_MODEL_CONFIG

    project_id: ProjectIdentifier
    binding_set_id: SafeIdentifier
    binding_record_sha256: Sha256
    registry_revision: int = Field(ge=1)
    registry_sha256: Sha256
    catalog_id: SafeIdentifier
    catalog_semantic_sha256: Sha256
    resource_count: int = Field(ge=1)
    verified_binding_count: int = Field(ge=0)
    pending_binding_count: int = Field(ge=0)
    blocked_binding_count: int = Field(ge=0)
    resources: tuple[ProjectResourcePortfolioItem, ...] = Field(min_length=1, max_length=100)
    available_resource_count: int = Field(default=0, ge=0)
    available_resources: tuple[ProjectAvailableResourceItem, ...] = Field(
        default=(),
        max_length=100,
    )
    planner_binding_state: Literal["ready", "unavailable", "unmanaged"] = "unmanaged"
    planner_resource_id: SafeIdentifier | None = None
    planner_provider_id: SafeIdentifier | None = None
    planner_model_id: SafeText | None = None
    configuration_authority: Literal["proposal_only", "user_applied"] = "proposal_only"
    configuration_run_id: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    source_planning_publication_id: SafeIdentifier | None = None
    source_planning_publication_sha256: Sha256 | None = None
    predecessor_binding_record_sha256: Sha256 | None = None
    configuration_verification_route: Literal["direct_path"] | None = None
    credential_values_exposed: Literal[False] = False
    remote_probe_performed: Literal[False] = False
    workload_executed: Literal[False] = False

    @model_validator(mode="after")
    def resource_counts_are_exact(self) -> ProjectResourcePortfolioData:
        if self.resource_count != len(self.resources):
            raise ValueError("project resource count must match its binding rows")
        statuses = [item.binding_status for item in self.resources]
        if self.verified_binding_count != statuses.count("verified"):
            raise ValueError("verified resource count differs from binding rows")
        if self.pending_binding_count != statuses.count("pending"):
            raise ValueError("pending resource count differs from binding rows")
        if self.blocked_binding_count != statuses.count("blocked"):
            raise ValueError("blocked resource count differs from binding rows")
        if len({item.binding_id for item in self.resources}) != len(self.resources):
            raise ValueError("project resource binding IDs must be unique")
        if self.available_resource_count != len(self.available_resources):
            raise ValueError("available resource count differs from catalog rows")
        bound_ids = {item.resource_id for item in self.resources}
        available_ids = [item.resource_id for item in self.available_resources]
        if len(available_ids) != len(set(available_ids)):
            raise ValueError("available project resource IDs must be unique")
        if bound_ids.intersection(available_ids):
            raise ValueError("a project resource cannot be both bound and available")
        planner_fields = (
            self.planner_resource_id,
            self.planner_provider_id,
            self.planner_model_id,
        )
        if self.planner_binding_state == "unmanaged" and any(planner_fields):
            raise ValueError("an unmanaged project planner cannot name a resource")
        if self.planner_binding_state in {"ready", "unavailable"} and not all(planner_fields):
            raise ValueError("a managed project planner requires a complete resource identity")
        configuration_fields = (
            self.configuration_run_id,
            self.source_planning_publication_id,
            self.source_planning_publication_sha256,
            self.predecessor_binding_record_sha256,
            self.configuration_verification_route,
        )
        if self.configuration_authority == "user_applied" and not all(configuration_fields):
            raise ValueError("an applied project resource configuration requires full lineage")
        if self.configuration_authority == "proposal_only" and any(configuration_fields):
            raise ValueError("a proposal-only resource view cannot claim applied lineage")
        return self


class ProjectProgressBoardData(BaseModel):
    """Evidence-native project status without guessed schedules or percentages."""

    model_config = _DATA_MODEL_CONFIG

    project_ref_id: SafeIdentifier
    summary_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    project_status: SafeText
    project_state: ObservedProgressState
    publication_ready: bool
    focus: SafeText
    focus_status: SafeText | None = None
    focus_source: Literal["project_manifest", "effective_evidence_program"]
    next_gate: SafeText | None = None
    focus_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    stage_semantics: SafeText
    stage_state: Literal["available", "empty", "unavailable"]
    stage_reason_code: SafeIdentifier
    milestone_state: Literal["available", "empty", "unavailable"]
    milestone_reason_code: SafeIdentifier
    counts: ProjectProgressCounts
    lifecycle: ProjectLifecycleSummaryData
    evidence_program: ProjectEvidenceProgramData | None = None
    resource_portfolio: ProjectResourcePortfolioData | None = None
    current_run_id: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    current_run_ref_id: SafeIdentifier | None = None
    current_run_status: SafeText | None = None
    current_run_state: ObservedProgressState | None = None
    current_run_ref_ids: tuple[SafeIdentifier, ...] = ()
    current_paper_id: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    recent_activity: tuple[ProjectProgressActivityItem, ...] = ()
    activity_total: int = Field(ge=0)
    activity_truncated: bool
    stages: tuple[ProjectProgressStageItem, ...] = ()
    papers: tuple[ProjectProgressPaperItem, ...] = ()
    evaluations: tuple[ProjectProgressEvaluationItem, ...] = ()
    evaluation_results: tuple[ProjectProgressEvaluationResultItem, ...] = ()
    acquisitions: tuple[ProjectProgressAcquisitionItem, ...] = ()
    acquisition_receipts: tuple[ProjectProgressAcquisitionReceiptItem, ...] = ()
    acquisition_qualifications: tuple[ProjectProgressAcquisitionQualificationItem, ...] = ()
    metadata_audit_plans: tuple[ProjectProgressMetadataAuditPlanItem, ...] = ()
    benchmark_metadata_populations: tuple[ProjectProgressBenchmarkMetadataPopulationItem, ...] = ()
    benchmark_metadata_screenings: tuple[ProjectProgressBenchmarkMetadataScreeningItem, ...] = ()
    benchmark_metadata_allocation_plans: tuple[
        ProjectProgressBenchmarkMetadataAllocationPlanItem, ...
    ] = ()
    benchmark_metadata_allocations: tuple[ProjectProgressBenchmarkMetadataAllocationItem, ...] = ()
    reference_selection_comparisons: tuple[
        ProjectProgressReferenceSelectionComparisonItem, ...
    ] = ()
    taste_candidate_populations: tuple[
        ProjectProgressTasteCandidatePopulationItem, ...
    ] = ()
    taste_domain_expansions: tuple[ProjectProgressTasteDomainExpansionItem, ...] = ()
    taste_source_review_campaigns: tuple[
        ProjectProgressTasteSourceReviewCampaignItem, ...
    ] = ()
    dataset_packages: tuple[ProjectProgressDatasetPackageItem, ...] = ()
    benchmark_qualifications: tuple[ProjectProgressBenchmarkQualificationItem, ...] = ()
    review_iterations: tuple[ProjectProgressReviewIterationItem, ...] = ()
    milestones: tuple[ProjectProgressMilestoneItem, ...] = ()
    attention: tuple[ProjectProgressAttentionItem, ...] = ()
    next_step_candidates: tuple[ProjectProgressCandidateItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def progress_rows_are_closed(self) -> ProjectProgressBoardData:
        if self.project_ref_id not in self.summary_ref_ids:
            raise ValueError("project progress summary must cite the project manifest")
        if self.project_ref_id not in self.focus_ref_ids:
            raise ValueError("project progress focus must cite the project manifest")
        if self.project_ref_id not in self.lifecycle.support_ref_ids:
            raise ValueError("project lifecycle must cite the project manifest")
        for refs in (self.summary_ref_ids, self.focus_ref_ids, self.current_run_ref_ids):
            if len(refs) != len(set(refs)):
                raise ValueError("project progress evidence references must be unique")

        if self.current_run_id is None:
            if (
                any(
                    value is not None
                    for value in (
                        self.current_run_ref_id,
                        self.current_run_status,
                        self.current_run_state,
                    )
                )
                or self.current_run_ref_ids
            ):
                raise ValueError("project progress cannot describe an absent current run")
        elif (
            self.current_run_ref_id is None
            or self.current_run_status is None
            or self.current_run_state is None
            or self.current_run_ref_id not in self.current_run_ref_ids
            or self.project_ref_id not in self.current_run_ref_ids
        ):
            raise ValueError("project progress current run must cite project and run evidence")

        activity_ids = [item.run_id for item in self.recent_activity]
        if len(activity_ids) != len(set(activity_ids)):
            raise ValueError("project progress activity run IDs must be unique")
        if self.activity_total < len(self.recent_activity):
            raise ValueError("project progress activity total cannot be smaller than shown rows")
        if self.activity_total != self.counts.runs_registered:
            raise ValueError("project progress activity total must match registered run count")
        if self.activity_truncated != (self.activity_total > len(self.recent_activity)):
            raise ValueError("project progress activity truncation flag is inconsistent")
        grounded_rows = (
            *self.recent_activity,
            *self.stages,
            *self.papers,
            *self.evaluations,
            *self.evaluation_results,
            *self.acquisitions,
            *self.acquisition_receipts,
            *self.acquisition_qualifications,
            *self.metadata_audit_plans,
            *self.benchmark_metadata_populations,
            *self.benchmark_metadata_screenings,
            *self.benchmark_metadata_allocation_plans,
            *self.benchmark_metadata_allocations,
            *self.reference_selection_comparisons,
            *self.taste_candidate_populations,
            *self.taste_domain_expansions,
            *self.taste_source_review_campaigns,
            *self.dataset_packages,
            *self.benchmark_qualifications,
            *self.review_iterations,
            *self.milestones,
            *self.attention,
            *self.next_step_candidates,
        )
        if any(self.project_ref_id not in item.support_ref_ids for item in grounded_rows):
            raise ValueError("every project progress claim must cite the project manifest")
        if self.evidence_program is not None:
            if self.project_ref_id not in self.evidence_program.support_ref_ids:
                raise ValueError("project evidence program must cite the project manifest")
            if set(self.evidence_program.support_ref_ids) - set(self.summary_ref_ids):
                raise ValueError("project evidence program must remain inside summary evidence")

        paper_ids = [item.paper_id for item in self.papers]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("project progress paper IDs must be unique")
        if self.counts.papers_registered != len(self.papers):
            raise ValueError("project progress paper count must match its paper rows")
        selected_papers = [item.paper_id for item in self.papers if item.selected]
        if selected_papers != ([self.current_paper_id] if self.current_paper_id else []):
            raise ValueError("project progress current paper must match exactly one paper row")

        evaluation_ids = [item.evaluation_id for item in self.evaluations]
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise ValueError("project progress evaluation IDs must be unique")
        if self.counts.evaluations_registered != len(self.evaluations):
            raise ValueError("project progress evaluation count must match its rows")

        acquisition_ids = [item.request_id for item in self.acquisitions]
        if len(acquisition_ids) != len(set(acquisition_ids)):
            raise ValueError("project progress acquisition request IDs must be unique")
        receipt_ids = [item.request_id for item in self.acquisition_receipts]
        if len(receipt_ids) != len(set(receipt_ids)):
            raise ValueError("project progress acquisition receipt IDs must be unique")
        if self.counts.acquisition_receipts != len(self.acquisition_receipts):
            raise ValueError("project progress acquisition receipt count must match its rows")
        if self.counts.acquisition_requests != len(self.acquisitions):
            raise ValueError("project progress acquisition count must match its rows")

        metadata_plan_ids = [item.request_id for item in self.metadata_audit_plans]
        if len(metadata_plan_ids) != len(set(metadata_plan_ids)):
            raise ValueError("project progress metadata audit request IDs must be unique")
        if self.counts.metadata_audit_plans != len(self.metadata_audit_plans):
            raise ValueError("project progress metadata audit count must match its rows")

        population_ids = [item.scope_id for item in self.benchmark_metadata_populations]
        if len(population_ids) != len(set(population_ids)):
            raise ValueError("project progress benchmark metadata scope IDs must be unique")
        if self.counts.benchmark_metadata_populations != len(self.benchmark_metadata_populations):
            raise ValueError("project progress benchmark metadata count must match its rows")

        screening_ids = [item.scope_id for item in self.benchmark_metadata_screenings]
        if len(screening_ids) != len(set(screening_ids)):
            raise ValueError("project progress benchmark screening scope IDs must be unique")
        if self.counts.benchmark_metadata_screenings != len(self.benchmark_metadata_screenings):
            raise ValueError("project progress benchmark screening count must match its rows")

        allocation_plan_ids = [item.scope_id for item in self.benchmark_metadata_allocation_plans]
        if len(allocation_plan_ids) != len(set(allocation_plan_ids)):
            raise ValueError("project progress allocation-plan scope IDs must be unique")
        if self.counts.benchmark_metadata_allocation_plans != len(
            self.benchmark_metadata_allocation_plans
        ):
            raise ValueError("project progress allocation-plan count must match its rows")

        allocation_ids = [item.scope_id for item in self.benchmark_metadata_allocations]
        if len(allocation_ids) != len(set(allocation_ids)):
            raise ValueError("project progress allocation scope IDs must be unique")
        if self.counts.benchmark_metadata_allocations != len(self.benchmark_metadata_allocations):
            raise ValueError("project progress allocation count must match its rows")

        reference_selection_ids = [
            item.comparison_id for item in self.reference_selection_comparisons
        ]
        if len(reference_selection_ids) != len(set(reference_selection_ids)):
            raise ValueError("project progress reference-selection IDs must be unique")
        if self.counts.reference_selection_comparisons != len(self.reference_selection_comparisons):
            raise ValueError("project progress reference-selection count must match its rows")
        if self.counts.taste_candidate_populations != len(self.taste_candidate_populations):
            raise ValueError("project progress Taste-population count must match its rows")
        if self.counts.taste_domain_expansions != len(self.taste_domain_expansions):
            raise ValueError("project progress Taste-domain count must match its rows")
        if self.counts.taste_source_review_campaigns != len(
            self.taste_source_review_campaigns
        ):
            raise ValueError("project progress Taste-review count must match its rows")

        qualification_ids = [item.selection_id for item in self.acquisition_qualifications]
        if len(qualification_ids) != len(set(qualification_ids)):
            raise ValueError("project progress acquisition qualification IDs must be unique")

        package_ids = [item.request_id for item in self.dataset_packages]
        if len(package_ids) != len(set(package_ids)):
            raise ValueError("project progress dataset package request IDs must be unique")

        benchmark_ids = [item.candidate_id for item in self.benchmark_qualifications]
        if len(benchmark_ids) != len(set(benchmark_ids)):
            raise ValueError("project progress benchmark qualification IDs must be unique")

        stages = [item.stage for item in self.stages]
        if stages != sorted(set(stages)):
            raise ValueError("project progress stages must be sorted and unique")
        if self.counts.completed_stages != len(self.stages):
            raise ValueError("project progress stage count must match its stage rows")
        if self.stage_state == "available" and not self.stages:
            raise ValueError("available project progress stages require observed rows")
        if self.stage_state != "available" and self.stages:
            raise ValueError("empty or unavailable project progress stages cannot have rows")

        milestone_ids = [item.milestone_id for item in self.milestones]
        if len(milestone_ids) != len(set(milestone_ids)):
            raise ValueError("project progress milestone IDs must be unique")
        if self.milestone_state == "available" and not self.milestones:
            raise ValueError("available project progress milestones require observed rows")
        if self.milestone_state != "available" and self.milestones:
            raise ValueError("empty or unavailable project progress milestones cannot have rows")

        attention_ids = [item.run_id for item in self.attention]
        if len(attention_ids) != len(set(attention_ids)):
            raise ValueError("project progress attention run IDs must be unique")
        candidate_ids = [item.candidate_id for item in self.next_step_candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("project progress candidate IDs must be unique")
        return self


_COMPONENT_DATA_ADAPTERS: dict[TrustedComponent, TypeAdapter[object]] = {
    TrustedComponent.PROJECT_SUMMARY_CARD: TypeAdapter(ProjectSummaryData),
    TrustedComponent.STAGE_TIMELINE: TypeAdapter(StageTimelineData),
    TrustedComponent.BLOCKER_LIST: TypeAdapter(BlockerListData),
    TrustedComponent.RUN_HEALTH: TypeAdapter(RunHealthData),
    TrustedComponent.BUDGET_METER: TypeAdapter(BudgetMeterData),
    TrustedComponent.DECISION_COMPARISON: TypeAdapter(DecisionComparisonData),
    TrustedComponent.EVIDENCE_GRAPH: TypeAdapter(EvidenceGraphData),
    TrustedComponent.CLAIM_MATRIX: TypeAdapter(ClaimMatrixData),
    TrustedComponent.REVIEWER_QUEUE: TypeAdapter(ReviewerQueueData),
    TrustedComponent.ARTIFACT_VIEWER: TypeAdapter(ArtifactViewerData),
    TrustedComponent.PAPER_PREVIEW: TypeAdapter(PaperPreviewData),
    TrustedComponent.AVAILABILITY_NOTICE: TypeAdapter(AvailabilityNoticeData),
    TrustedComponent.RUN_STAGE_EXPLORER: TypeAdapter(RunStageExplorerData),
    TrustedComponent.EVIDENCE_INVENTORY: TypeAdapter(EvidenceInventoryData),
    TrustedComponent.RUN_COMPARISON_PANEL: TypeAdapter(RunComparisonPanelData),
    TrustedComponent.RUN_BLOCKER_PANEL: TypeAdapter(RunBlockerPanelData),
    TrustedComponent.PENDING_PROPOSAL_LIST: TypeAdapter(PendingProposalListData),
    TrustedComponent.PROJECT_PROGRESS_BOARD: TypeAdapter(ProjectProgressBoardData),
    TrustedComponent.RESEARCH_LANDSCAPE_MAP: TypeAdapter(ResearchLandscapeData),
}


def validate_component_data(
    component: TrustedComponent,
    value: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Validate and normalize one component's closed field contract."""

    parsed = _COMPONENT_DATA_ADAPTERS[component].validate_python(value)
    if not isinstance(parsed, BaseModel):  # both union members are models
        raise TypeError("component data schema must produce a model")
    return declarative_dict(parsed.model_dump(mode="json"))


def component_data_json_schema(component: TrustedComponent) -> dict[str, Any]:
    """Expose the exact receiver/adapter contract for one registered component."""

    return _COMPONENT_DATA_ADAPTERS[component].json_schema()


class ComponentSpec(BaseModel):
    """One trusted native component with data-only, evidence-linked content."""

    model_config = _MODEL_CONFIG

    component_id: SafeIdentifier
    component: TrustedComponent
    title: SafeText
    evidence_ref_ids: list[SafeIdentifier] = Field(min_length=1)
    data: dict[str, JsonValue]

    @field_validator("data")
    @classmethod
    def content_is_declarative(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return declarative_dict(value)

    @model_validator(mode="after")
    def data_and_evidence_ids_are_valid(self) -> ComponentSpec:
        if len(self.evidence_ref_ids) != len(set(self.evidence_ref_ids)):
            raise ValueError("component evidence references must be unique")
        object.__setattr__(self, "data", validate_component_data(self.component, self.data))
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
    data_refs = list(_iter_data_ref_fields(component.data))
    outside_component = {ref_id for _, ref_id in data_refs} - set(component.evidence_ref_ids)
    if outside_component:
        raise ValueError(
            f"component {component.component_id!r} data references undeclared evidence: "
            f"{sorted(outside_component)}"
        )
    for field_name, ref_id in data_refs:
        allowed_kinds = _DATA_REF_EVIDENCE_KINDS.get(field_name)
        if allowed_kinds is not None and evidence[ref_id].kind not in allowed_kinds:
            values = sorted(item.value for item in allowed_kinds)
            raise ValueError(
                f"component {component.component_id!r} field {field_name!r} requires "
                f"evidence kinds {values}"
            )
    if component.component == TrustedComponent.ARTIFACT_VIEWER:
        artifact_ref = str(component.data["artifact_ref_id"])
        if component.data["artifact_path"] != evidence[artifact_ref].locator:
            raise ValueError(
                "artifact viewer path must match its content-addressed evidence locator"
            )
    if component.component == TrustedComponent.EVIDENCE_GRAPH:
        for node in component.data["nodes"]:
            if not isinstance(node, dict):  # schema validation guarantees this
                raise TypeError("evidence graph node must be an object")
            ref_id = str(node["evidence_ref_id"])
            if node["kind"] != evidence[ref_id].kind.value:
                raise ValueError("evidence graph node kind must match its evidence reference")
    if component.component == TrustedComponent.EVIDENCE_INVENTORY:
        for item in component.data["items"]:
            if not isinstance(item, dict):  # schema validation guarantees this
                raise TypeError("evidence inventory item must be an object")
            ref_id = str(item["evidence_ref_id"])
            referenced = evidence[ref_id]
            if item["kind"] != referenced.kind.value:
                raise ValueError("evidence inventory kind must match its evidence reference")
            if item["locator"] != referenced.locator or item["sha256"] != referenced.sha256:
                raise ValueError("evidence inventory identity must match its evidence reference")


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
    elif isinstance(payload, RequestApprovalPayload):
        allowed_kinds = APPROVAL_EVIDENCE_KINDS[payload.subject]
        invalid = [
            item for item in payload.subject_ref_ids if evidence[item].kind not in allowed_kinds
        ]
        if invalid:
            values = sorted(item.value for item in allowed_kinds)
            raise ValueError(
                f"{payload.subject.value} approval requires evidence kinds {values}: "
                f"{sorted(invalid)}"
            )


_DATA_REF_EVIDENCE_KINDS: dict[str, frozenset[EvidenceKind]] = {
    "project_ref_id": frozenset({EvidenceKind.PROJECT_MANIFEST}),
    "stage_ref_id": frozenset({EvidenceKind.STAGE_RECORD}),
    "blocker_ref_id": frozenset({EvidenceKind.BLOCKER}),
    "run_ref_id": frozenset({EvidenceKind.RUN_RECORD}),
    "current_run_ref_id": frozenset({EvidenceKind.RUN_RECORD}),
    "baseline_run_ref_id": frozenset({EvidenceKind.RUN_RECORD}),
    "candidate_run_ref_id": frozenset({EvidenceKind.RUN_RECORD}),
    "usage_ref_id": frozenset({EvidenceKind.RESOURCE_USAGE}),
    "decision_ref_id": frozenset({EvidenceKind.DECISION}),
    "claim_ref_id": frozenset({EvidenceKind.CLAIM}),
    "review_ref_id": frozenset({EvidenceKind.REVIEW}),
    "artifact_ref_id": frozenset({EvidenceKind.ARTIFACT}),
    "paper_ref_id": frozenset({EvidenceKind.PAPER}),
    "evaluation_ref_id": frozenset({EvidenceKind.EVALUATION}),
    "result_ref_id": frozenset({EvidenceKind.EVALUATION_RESULT}),
    "audit_ref_id": frozenset({EvidenceKind.AUDIT_RECORD}),
    "evidence_ref_ids": frozenset({EvidenceKind.EVIDENCE_RECORD}),
}


def _iter_data_ref_fields(
    value: JsonValue,
) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.endswith("_ref_id") and isinstance(child, str):
                yield key, child
            elif key.endswith("_ref_ids") and isinstance(child, list):
                yield from ((key, item) for item in child if isinstance(item, str))
            yield from _iter_data_ref_fields(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_data_ref_fields(child)

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

    nodes: tuple[EvidenceGraphNode, ...] = Field(min_length=1)
    edges: tuple[EvidenceGraphEdge, ...] = ()

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
    idea_to_paper_complete: bool
    internal_review_cycle_complete: bool
    independent_pre_submission_review_complete: bool
    official_decision_authority: Literal[False] = False
    scientific_effectiveness_established: Literal[False] = False
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
    next_gate: SafeText | None = None
    focus_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=1)
    stage_semantics: SafeText
    stage_state: Literal["available", "empty", "unavailable"]
    stage_reason_code: SafeIdentifier
    milestone_state: Literal["available", "empty", "unavailable"]
    milestone_reason_code: SafeIdentifier
    counts: ProjectProgressCounts
    lifecycle: ProjectLifecycleSummaryData
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
            *self.milestones,
            *self.attention,
            *self.next_step_candidates,
        )
        if any(self.project_ref_id not in item.support_ref_ids for item in grounded_rows):
            raise ValueError("every project progress claim must cite the project manifest")

        paper_ids = [item.paper_id for item in self.papers]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("project progress paper IDs must be unique")
        if self.counts.papers_registered != len(self.papers):
            raise ValueError("project progress paper count must match its paper rows")
        selected_papers = [item.paper_id for item in self.papers if item.selected]
        if selected_papers != ([self.current_paper_id] if self.current_paper_id else []):
            raise ValueError("project progress current paper must match exactly one paper row")

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

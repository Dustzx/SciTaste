"""Reconstruct exact decision foundations without inventing scientific outcomes."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project import ProjectRuntime
from scitaste.project.idea_revision import ProjectIdeaRevisionBinding, idea_binding_matches_current
from scitaste.project.models import content_sha256, validate_project_id, validate_relative_locator
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import DecisionLogger, StateStore, snapshot_id
from scitaste.state.research_state import ResearchState
from scitaste.taste.episodes import (
    TasteCreditAssignment,
    TasteEpisodeCandidate,
    TasteEpisodeConfounder,
    TasteEpisodeDecisionContext,
    TasteEpisodeEvidence,
    TasteEpisodeEvidenceRole,
    TasteEpisodeOutcome,
    TasteEpisodePartition,
    TasteEpisodeSourceRelationship,
    compile_process_taste_episode_candidate,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_STATE_ID = r"^state-[0-9a-f]{64}$"
_MAX_DECISION_LOG_BYTES = 16 * 1024 * 1024
_MAX_DECISION_LINE_BYTES = 2 * 1024 * 1024
_MAX_STATE_BYTES = 4 * 1024 * 1024
_MAX_CONTRACT_BYTES = 4 * 1024 * 1024
_MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
_MAX_STATE_TREE_ENTRIES = 50_000


class TasteTrajectoryAssignmentTiming(StrEnum):
    PROSPECTIVE = "prospective"
    RETROSPECTIVE_DEVELOPMENT = "retrospective-development"


class TasteTrajectoryFollowup(StrEnum):
    AWAITING_DELAYED_SCIENTIFIC_OUTCOME = "awaiting-delayed-scientific-outcome"
    NOT_COMPARATIVE = "not-comparative-decision"
    NOT_EXECUTED = "not-executed"
    STATE_UNAVAILABLE = "state-unavailable"
    RETROSPECTIVE_AUDIT_ONLY = "retrospective-audit-only"


class TasteTrajectorySamplingPlan(BaseModel):
    """A split and natural sampling unit fixed before attribution review."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    project_id: str
    observed_project_revision: int = Field(ge=0)
    observed_project_snapshot_sha256: str = Field(pattern=_SHA256)
    idea_revision: ProjectIdeaRevisionBinding
    source_project_id: str
    source_run_id: str = Field(pattern=_ID)
    source_relationship: TasteEpisodeSourceRelationship
    source_group_id: str = Field(pattern=_ID)
    dataset_partition: TasteEpisodePartition
    assignment_timing: TasteTrajectoryAssignmentTiming
    decision_log_locator: str
    state_snapshot_root_locator: str
    frozen_at: datetime
    source_absent_when_frozen: bool
    plan_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def sampling_plan_is_closed(self) -> TasteTrajectorySamplingPlan:
        validate_project_id(self.project_id)
        validate_project_id(self.source_project_id)
        validate_relative_locator(self.decision_log_locator, field_name="decision log locator")
        validate_relative_locator(
            self.state_snapshot_root_locator,
            field_name="state snapshot root locator",
        )
        if self.frozen_at.utcoffset() is None:
            raise ValueError("trajectory sampling freeze time must include a timezone")
        if self.idea_revision.project_id != self.project_id:
            raise ValueError("trajectory sampling plan Idea belongs to another project")
        if self.idea_revision.observed_project_revision > self.observed_project_revision:
            raise ValueError("trajectory sampling plan predates its Idea binding")
        if self.source_relationship is TasteEpisodeSourceRelationship.EXTERNAL_RECORD:
            raise ValueError("decision-log reconstruction accepts project trajectories only")
        if (self.source_relationship is TasteEpisodeSourceRelationship.SELF_PROJECT) != (
            self.source_project_id == self.project_id
        ):
            raise ValueError("trajectory source relationship disagrees with project identity")
        if (
            self.source_relationship is TasteEpisodeSourceRelationship.SELF_PROJECT
            and self.dataset_partition is not TasteEpisodePartition.DEVELOPMENT
        ):
            raise ValueError("self-project trajectories are development-only")
        if self.assignment_timing is TasteTrajectoryAssignmentTiming.RETROSPECTIVE_DEVELOPMENT:
            if self.dataset_partition is not TasteEpisodePartition.DEVELOPMENT:
                raise ValueError("retrospective trajectories are development-only")
            if self.source_absent_when_frozen:
                raise ValueError("retrospective sampling cannot claim a pre-source freeze")
        elif not self.source_absent_when_frozen:
            raise ValueError("prospective sampling requires a pre-source freeze")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("trajectory sampling plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteTrajectorySamplingPlan:
        payload = {"schema_version": "1.0", **values}
        payload.pop("plan_sha256", None)
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls(
            **payload,
            plan_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"plan_sha256"})),
        )


class TasteTrajectoryDecisionSeed(BaseModel):
    """Exact pre-attribution decision material from one immutable log line."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    line_number: int = Field(ge=1)
    line_sha256: str = Field(pattern=_SHA256)
    decision_id: str
    decision_sha256: str = Field(pattern=_SHA256)
    decision_timestamp: datetime
    stage: str
    state_snapshot_id: str = Field(pattern=_STATE_ID)
    state_snapshot_locators: tuple[str, ...]
    state_file_sha256: str | None = Field(default=None, pattern=_SHA256)
    state_verified: bool
    alternative_count: int = Field(ge=1)
    selected_action_id: str
    executor_result_id: str | None
    executor_outcome_sha256: str | None = Field(default=None, pattern=_SHA256)
    executor_status: str | None = None
    execution_binding_complete: bool
    delayed_scientific_outcome_bound: Literal[False] = False
    foundation_eligible: bool
    followup: TasteTrajectoryFollowup
    finding_codes: tuple[str, ...]

    @model_validator(mode="after")
    def seed_does_not_invent_an_outcome(self) -> TasteTrajectoryDecisionSeed:
        for locator in self.state_snapshot_locators:
            validate_relative_locator(locator, field_name="state snapshot locator")
        if self.decision_timestamp.utcoffset() is None:
            raise ValueError("trajectory decision timestamp must include a timezone")
        if self.state_verified != (
            self.state_file_sha256 is not None and bool(self.state_snapshot_locators)
        ):
            raise ValueError("trajectory state verification and digest disagree")
        if self.execution_binding_complete != (
            self.executor_result_id is not None and self.executor_outcome_sha256 is not None
        ):
            raise ValueError("trajectory executor binding is incomplete")
        expected_eligible = (
            self.state_verified
            and self.alternative_count >= 2
            and self.execution_binding_complete
            and self.followup is TasteTrajectoryFollowup.AWAITING_DELAYED_SCIENTIFIC_OUTCOME
        )
        if self.foundation_eligible != expected_eligible:
            raise ValueError("trajectory foundation eligibility disagrees with its evidence")
        if len(self.finding_codes) != len(set(self.finding_codes)):
            raise ValueError("trajectory finding codes must be unique")
        return self


class TasteTrajectoryInventory(BaseModel):
    """Read-only reconstruction receipt; it has no attribution or training authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str
    plan_sha256: str = Field(pattern=_SHA256)
    idea_revision_id: str
    idea_revision_record_sha256: str = Field(pattern=_SHA256)
    decision_log_locator: str
    decision_log_sha256: str = Field(pattern=_SHA256)
    decision_count: int = Field(ge=0)
    multi_alternative_count: int = Field(ge=0)
    state_verified_count: int = Field(ge=0)
    execution_bound_count: int = Field(ge=0)
    foundation_eligible_count: int = Field(ge=0)
    decisions: tuple[TasteTrajectoryDecisionSeed, ...]
    scientific_outcome_labels_created: Literal[False] = False
    policy_training_authorized: Literal[False] = False
    inventory_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def inventory_is_closed(self) -> TasteTrajectoryInventory:
        validate_relative_locator(self.decision_log_locator, field_name="decision log locator")
        if self.decision_count != len(self.decisions):
            raise ValueError("trajectory decision count differs")
        if len({item.decision_id for item in self.decisions}) != len(self.decisions):
            raise ValueError("trajectory decision IDs must be unique")
        expected_counts = (
            sum(item.alternative_count >= 2 for item in self.decisions),
            sum(item.state_verified for item in self.decisions),
            sum(item.execution_binding_complete for item in self.decisions),
            sum(item.foundation_eligible for item in self.decisions),
        )
        observed_counts = (
            self.multi_alternative_count,
            self.state_verified_count,
            self.execution_bound_count,
            self.foundation_eligible_count,
        )
        if observed_counts != expected_counts:
            raise ValueError("trajectory inventory aggregate counts differ")
        expected = content_sha256(self.model_dump(mode="json", exclude={"inventory_sha256"}))
        if self.inventory_sha256 != expected:
            raise ValueError("trajectory inventory hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteTrajectoryInventory:
        payload = {"schema_version": "1.0", **values}
        payload.pop("inventory_sha256", None)
        unsigned = cls.model_construct(inventory_sha256="0" * 64, **payload)
        return cls(
            **payload,
            inventory_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"inventory_sha256"})
            ),
        )


class TasteProspectiveDecisionCaptureReceipt(BaseModel):
    """Exact natural decision foundation captured under a pre-source sampling plan."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    source_project_id: str
    source_run_id: str = Field(pattern=_ID)
    observed_project_revision: int = Field(ge=0)
    observed_project_snapshot_sha256: str = Field(pattern=_SHA256)
    decision_id: str
    decision_sha256: str = Field(pattern=_SHA256)
    decision_log_locator: str
    decision_line_number: int = Field(ge=1)
    decision_line_sha256: str = Field(pattern=_SHA256)
    state_snapshot_id: str = Field(pattern=_STATE_ID)
    state_snapshot_locator: str
    state_file_sha256: str = Field(pattern=_SHA256)
    executor_result_id: str
    executor_outcome_sha256: str = Field(pattern=_SHA256)
    alternative_count: int = Field(ge=2)
    captured_at: datetime
    awaiting_delayed_scientific_outcome: Literal[True] = True
    scientific_outcome_labels_created: Literal[False] = False
    policy_training_authorized: Literal[False] = False
    capture_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def capture_is_closed(self) -> TasteProspectiveDecisionCaptureReceipt:
        validate_project_id(self.source_project_id)
        validate_relative_locator(self.decision_log_locator, field_name="decision log locator")
        validate_relative_locator(
            self.state_snapshot_locator,
            field_name="state snapshot locator",
        )
        if self.captured_at.utcoffset() is None:
            raise ValueError("Taste decision capture time must include a timezone")
        expected = content_sha256(self.model_dump(mode="json", exclude={"capture_sha256"}))
        if self.capture_sha256 != expected:
            raise ValueError("Taste decision capture hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteProspectiveDecisionCaptureReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("capture_sha256", None)
        unsigned = cls.model_construct(capture_sha256="0" * 64, **payload)
        return cls(
            **payload,
            capture_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"capture_sha256"})
            ),
        )


class TasteProspectiveDecisionLockReceipt(BaseModel):
    """Write-once proof that a complete action menu was fixed before execution."""

    model_config = _CONFIG

    schema_version: Literal["2.0"] = "2.0"
    plan_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    source_project_id: str
    source_run_id: str = Field(pattern=_ID)
    observed_project_revision: int = Field(ge=0)
    observed_project_snapshot_sha256: str = Field(pattern=_SHA256)
    decision_id: str
    decision_sha256: str = Field(pattern=_SHA256)
    decision_timestamp: datetime
    decision_log_locator: str
    decision_line_number: int = Field(ge=1)
    decision_line_sha256: str = Field(pattern=_SHA256)
    immutable_decision_locator: str
    immutable_decision_file_sha256: str = Field(pattern=_SHA256)
    state_snapshot_id: str = Field(pattern=_STATE_ID)
    state_snapshot_locator: str
    state_file_sha256: str = Field(pattern=_SHA256)
    candidate_set_sha256: str = Field(pattern=_SHA256)
    selected_action_id: str
    selected_action_sha256: str = Field(pattern=_SHA256)
    rationale_sha256: str = Field(pattern=_SHA256)
    alternative_count: int = Field(ge=2)
    captured_at: datetime
    executor_result_id: Literal[None] = None
    actual_outcome: Literal[None] = None
    outcome_attachment_required: Literal[True] = True
    policy_training_authorized: Literal[False] = False
    lock_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def lock_is_closed(self) -> TasteProspectiveDecisionLockReceipt:
        validate_project_id(self.source_project_id)
        for locator in (
            self.decision_log_locator,
            self.immutable_decision_locator,
            self.state_snapshot_locator,
        ):
            validate_relative_locator(locator, field_name="prospective lock locator")
        if self.decision_timestamp.utcoffset() is None or self.captured_at.utcoffset() is None:
            raise ValueError("prospective lock times must include a timezone")
        if self.captured_at < self.decision_timestamp:
            raise ValueError("prospective lock capture predates the decision timestamp")
        expected = content_sha256(self.model_dump(mode="json", exclude={"lock_sha256"}))
        if self.lock_sha256 != expected:
            raise ValueError("prospective decision lock hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteProspectiveDecisionLockReceipt:
        payload = {"schema_version": "2.0", **values}
        payload.pop("lock_sha256", None)
        unsigned = cls.model_construct(lock_sha256="0" * 64, **payload)
        return cls(
            **payload,
            lock_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"lock_sha256"})),
        )


class TasteProspectiveOutcomeAttachmentReceipt(BaseModel):
    """Append-only outcome evidence bound to one predecision lock."""

    model_config = _CONFIG

    schema_version: Literal["2.0"] = "2.0"
    plan_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    lock_sha256: str = Field(pattern=_SHA256)
    decision_id: str
    predecision_sha256: str = Field(pattern=_SHA256)
    executor_result_id: str = Field(min_length=1, max_length=1_000)
    observed_at: datetime
    actual_outcome: dict[str, object]
    actual_outcome_sha256: str = Field(pattern=_SHA256)
    evidence: tuple[TasteEpisodeEvidence, ...] = Field(min_length=1, max_length=200)
    attached_at: datetime
    predecision_mutation_allowed: Literal[False] = False
    policy_training_authorized: Literal[False] = False
    attachment_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def attachment_is_closed(self) -> TasteProspectiveOutcomeAttachmentReceipt:
        if self.observed_at.utcoffset() is None or self.attached_at.utcoffset() is None:
            raise ValueError("outcome attachment times must include a timezone")
        if self.attached_at < self.observed_at:
            raise ValueError("outcome attachment predates outcome observation")
        if not self.actual_outcome:
            raise ValueError("outcome attachment cannot be empty")
        if self.actual_outcome_sha256 != content_sha256(self.actual_outcome):
            raise ValueError("attached outcome hash differs")
        if any(item.role is not TasteEpisodeEvidenceRole.OUTCOME for item in self.evidence):
            raise ValueError("outcome attachment evidence must use the outcome role")
        if len({item.evidence_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("outcome attachment evidence IDs must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"attachment_sha256"}))
        if self.attachment_sha256 != expected:
            raise ValueError("prospective outcome attachment hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteProspectiveOutcomeAttachmentReceipt:
        payload = {"schema_version": "2.0", **values}
        payload.pop("attachment_sha256", None)
        unsigned = cls.model_construct(attachment_sha256="0" * 64, **payload)
        return cls(
            **payload,
            attachment_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"attachment_sha256"})
            ),
        )


class TasteProspectiveDecisionCompletionProjection(BaseModel):
    """Replayable completed decision assembled without changing predecision bytes."""

    model_config = _CONFIG

    schema_version: Literal["2.0"] = "2.0"
    plan_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    lock_sha256: str = Field(pattern=_SHA256)
    attachment_sha256: str = Field(pattern=_SHA256)
    predecision_sha256: str = Field(pattern=_SHA256)
    completed_decision: ResearchDecision
    completed_decision_sha256: str = Field(pattern=_SHA256)
    projected_at: datetime
    source_predecision_bytes_rewritten: Literal[False] = False
    policy_training_authorized: Literal[False] = False
    projection_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def projection_is_closed(self) -> TasteProspectiveDecisionCompletionProjection:
        if self.projected_at.utcoffset() is None:
            raise ValueError("completion projection time must include a timezone")
        if (
            self.completed_decision.executor_result_id is None
            or self.completed_decision.actual_outcome is None
        ):
            raise ValueError("completion projection lacks its outcome binding")
        expected_decision = content_sha256(self.completed_decision.model_dump(mode="json"))
        if self.completed_decision_sha256 != expected_decision:
            raise ValueError("completed decision hash differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"projection_sha256"}))
        if self.projection_sha256 != expected:
            raise ValueError("prospective completion projection hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteProspectiveDecisionCompletionProjection:
        payload = {"schema_version": "2.0", **values}
        payload.pop("projection_sha256", None)
        unsigned = cls.model_construct(projection_sha256="0" * 64, **payload)
        return cls(
            **payload,
            projection_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"projection_sha256"})
            ),
        )


class TasteProcessEvidenceBinding(BaseModel):
    """A declared run-owned input whose digest is computed during compilation."""

    model_config = _CONFIG

    evidence_id: str = Field(pattern=_ID)
    role: TasteEpisodeEvidenceRole
    locator: str

    @model_validator(mode="after")
    def locator_is_owned(self) -> TasteProcessEvidenceBinding:
        validate_relative_locator(self.locator, field_name="process episode evidence")
        return self


class TasteProcessEpisodeProposal(BaseModel):
    """A delayed-outcome attribution proposal with no admission authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: str = Field(pattern=_ID)
    plan_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    capture_sha256: str = Field(pattern=_SHA256)
    inventory_sha256: str = Field(pattern=_SHA256)
    decision_id: str
    candidate_id: str = Field(pattern=_ID)
    producer_id: str = Field(pattern=_ID)
    observed_at: datetime
    state_summary: str = Field(min_length=1, max_length=20_000)
    decision_context: TasteEpisodeDecisionContext | None = None
    decision_principle: str = Field(min_length=1, max_length=10_000)
    why_preferred: str = Field(min_length=1, max_length=10_000)
    outcomes: tuple[TasteEpisodeOutcome, ...] = Field(min_length=1, max_length=100)
    credit_assignments: tuple[TasteCreditAssignment, ...] = Field(min_length=1, max_length=100)
    applicability_conditions: tuple[str, ...] = Field(min_length=1, max_length=30)
    failure_conditions: tuple[str, ...] = Field(min_length=1, max_length=30)
    counterfactual_probe: str = Field(min_length=1, max_length=10_000)
    evidence: tuple[TasteProcessEvidenceBinding, ...] = Field(min_length=3, max_length=200)
    domain_tags: tuple[str, ...] = Field(default=(), max_length=30)
    venue_tags: tuple[str, ...] = Field(default=(), max_length=30)
    confounders: tuple[TasteEpisodeConfounder, ...] = Field(default=(), max_length=100)
    missing_evidence_questions: tuple[str, ...] = Field(default=(), max_length=30)
    canonical_evidence: Literal[False] = False
    admission_authority: Literal[False] = False
    policy_update_authorized: Literal[False] = False
    proposal_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def proposal_is_closed(self) -> TasteProcessEpisodeProposal:
        if self.observed_at.utcoffset() is None:
            raise ValueError("delayed outcome observation time must include a timezone")
        evidence_ids = [item.evidence_id for item in self.evidence]
        evidence_locators = [item.locator for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("process episode evidence IDs must be unique")
        if len(evidence_locators) != len(set(evidence_locators)):
            raise ValueError("process episode evidence locators must be unique")
        required_roles = {
            TasteEpisodeEvidenceRole.DECISION,
            TasteEpisodeEvidenceRole.DECISION_STATE,
            TasteEpisodeEvidenceRole.OUTCOME,
        }
        if not required_roles.issubset({item.role for item in self.evidence}):
            raise ValueError("process episode proposal lacks decision, state, or outcome evidence")
        expected = content_sha256(self.model_dump(mode="json", exclude={"proposal_sha256"}))
        if self.proposal_sha256 != expected:
            raise ValueError("process episode proposal hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteProcessEpisodeProposal:
        payload = {"schema_version": "1.0", **values}
        payload.pop("proposal_sha256", None)
        unsigned = cls.model_construct(proposal_sha256="0" * 64, **payload)
        return cls(
            **payload,
            proposal_sha256=content_sha256(
                unsigned.model_dump(
                    mode="json",
                    exclude={"proposal_sha256"},
                    warnings=False,
                )
            ),
        )


def capture_prospective_taste_decision(
    plan: TasteTrajectorySamplingPlan,
    *,
    runtime: ProjectRuntime,
    state: ResearchState,
    decision: ResearchDecision,
    current_idea_revision: ProjectIdeaRevisionBinding,
    expected_project_revision: int,
    output: str | Path,
) -> TasteProspectiveDecisionCaptureReceipt:
    """Persist one already-made natural decision; do not generate or relabel it."""

    if plan.assignment_timing is not TasteTrajectoryAssignmentTiming.PROSPECTIVE:
        raise ValueError("natural decision capture requires a prospective sampling plan")
    if not idea_binding_matches_current(plan.idea_revision, current_idea_revision):
        raise ValueError("natural decision capture plan belongs to a stale Idea revision")
    snapshot = runtime.open(plan.source_project_id)
    if snapshot.revision != expected_project_revision:
        raise ValueError(
            f"stale project revision {expected_project_revision}; current is {snapshot.revision}"
        )
    if plan.source_run_id not in {item.run_id for item in snapshot.manifest.runs}:
        raise ValueError("prospective source run is not registered")
    if state.project_id != plan.source_project_id:
        raise ValueError("captured research state belongs to another project")
    identifier = snapshot_id(state)
    if decision.state_snapshot_id != identifier:
        raise ValueError("captured decision does not bind the supplied state")
    if decision.stage != state.current_stage.value:
        raise ValueError("captured decision stage differs from the supplied state")
    if len(decision.candidate_actions) < 2:
        raise ValueError("captured Taste decision requires at least two alternatives")
    if decision.executor_result_id is None or decision.actual_outcome is None:
        raise ValueError("captured Taste decision requires an immediate executor outcome")

    run_root = runtime.projects_root / plan.source_project_id / "runs" / plan.source_run_id
    decision_log = run_root / PurePosixPath(plan.decision_log_locator)
    logger = DecisionLogger(decision_log)
    existing = logger.read_all()
    matches = [item for item in existing if item.decision_id == decision.decision_id]
    if matches and matches != [decision]:
        raise ValueError("captured decision ID already binds different bytes")

    state_store = StateStore(run_root / PurePosixPath(plan.state_snapshot_root_locator))
    saved_identifier = state_store.save(state)
    if saved_identifier != identifier:
        raise ValueError("captured state identity changed during persistence")
    if not matches:
        logger.append(decision)
        line_number = len(existing) + 1
    else:
        line_number = next(index for index, item in enumerate(existing, 1) if item == decision)
    raw_lines = decision_log.read_bytes().splitlines(keepends=True)
    raw_line = raw_lines[line_number - 1]
    state_path = state_store.snapshot_dir / f"{identifier}.json"
    state_locator = state_path.relative_to(run_root).as_posix()
    receipt = TasteProspectiveDecisionCaptureReceipt.create(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        source_project_id=plan.source_project_id,
        source_run_id=plan.source_run_id,
        observed_project_revision=snapshot.revision,
        observed_project_snapshot_sha256=snapshot.snapshot_sha256,
        decision_id=decision.decision_id,
        decision_sha256=content_sha256(decision.model_dump(mode="json")),
        decision_log_locator=plan.decision_log_locator,
        decision_line_number=line_number,
        decision_line_sha256=hashlib.sha256(raw_line).hexdigest(),
        state_snapshot_id=identifier,
        state_snapshot_locator=state_locator,
        state_file_sha256=hashlib.sha256(state_path.read_bytes()).hexdigest(),
        executor_result_id=decision.executor_result_id,
        executor_outcome_sha256=content_sha256(decision.actual_outcome),
        alternative_count=len(decision.candidate_actions),
        captured_at=datetime.now(UTC),
    )
    _write_new_json(output, receipt.model_dump_json(indent=2) + "\n")
    return receipt


def lock_prospective_taste_decision(
    plan: TasteTrajectorySamplingPlan,
    *,
    runtime: ProjectRuntime,
    state: ResearchState,
    decision: ResearchDecision,
    current_idea_revision: ProjectIdeaRevisionBinding,
    expected_project_revision: int,
    output: str | Path,
    captured_at: datetime | None = None,
) -> TasteProspectiveDecisionLockReceipt:
    """Persist a state and outcome-free decision before any execution can occur."""

    if plan.assignment_timing is not TasteTrajectoryAssignmentTiming.PROSPECTIVE:
        raise ValueError("predecision lock requires a prospective sampling plan")
    if not idea_binding_matches_current(plan.idea_revision, current_idea_revision):
        raise ValueError("predecision lock plan belongs to a stale Idea revision")
    snapshot = runtime.open(plan.source_project_id)
    if snapshot.revision != expected_project_revision:
        raise ValueError(
            f"stale project revision {expected_project_revision}; current is {snapshot.revision}"
        )
    if plan.source_run_id not in {item.run_id for item in snapshot.manifest.runs}:
        raise ValueError("prospective source run is not registered")
    if state.project_id != plan.source_project_id:
        raise ValueError("predecision research state belongs to another project")
    identifier = snapshot_id(state)
    if decision.state_snapshot_id != identifier:
        raise ValueError("predecision does not bind the supplied research state")
    if decision.stage != state.current_stage.value:
        raise ValueError("predecision stage differs from the supplied research state")
    if decision.executor_result_id is not None or decision.actual_outcome is not None:
        raise ValueError("predecision lock rejects executor results and actual outcomes")
    if decision.timestamp.utcoffset() is None:
        raise ValueError("predecision timestamp must include a timezone")
    actions = tuple(decision.candidate_actions)
    action_ids = tuple(item.action_id for item in actions)
    action_hashes = tuple(content_sha256(item.model_dump(mode="json")) for item in actions)
    if len(actions) < 2:
        raise ValueError("predecision lock requires at least two alternatives")
    if len(set(action_ids)) != len(action_ids) or len(set(action_hashes)) != len(action_hashes):
        raise ValueError("predecision alternatives must be non-duplicate")
    selected_matches = [item for item in actions if item == decision.selected_action]
    if len(selected_matches) != 1:
        raise ValueError("selected action must exactly match one predecision alternative")
    capture_time = captured_at or datetime.now(UTC)
    if capture_time.utcoffset() is None or capture_time < decision.timestamp:
        raise ValueError("predecision lock capture cannot predate the decision")

    run_root = runtime.projects_root / plan.source_project_id / "runs" / plan.source_run_id
    decision_log = run_root / PurePosixPath(plan.decision_log_locator)
    logger = DecisionLogger(decision_log)
    existing = logger.read_all()
    matches = [item for item in existing if item.decision_id == decision.decision_id]
    if matches and matches != [decision]:
        raise ValueError("predecision ID already binds different bytes")

    state_store = StateStore(run_root / PurePosixPath(plan.state_snapshot_root_locator))
    saved_identifier = state_store.save(state)
    if saved_identifier != identifier:
        raise ValueError("predecision state identity changed during persistence")
    state_path = state_store.snapshot_dir / f"{identifier}.json"
    state_locator = state_path.relative_to(run_root).as_posix()

    decision_sha256 = content_sha256(decision.model_dump(mode="json"))
    immutable_path = decision_log.parent / "predecision_locks" / f"{decision_sha256}.json"
    immutable_locator = immutable_path.relative_to(run_root).as_posix()
    serialized_decision = decision.model_dump_json() + "\n"
    _write_or_verify_immutable(immutable_path, serialized_decision.encode("utf-8"))

    if not matches:
        logger.append(decision)
        line_number = len(existing) + 1
    else:
        line_number = next(index for index, item in enumerate(existing, 1) if item == decision)
    raw_lines = decision_log.read_bytes().splitlines(keepends=True)
    raw_line = raw_lines[line_number - 1]
    if raw_line != serialized_decision.encode("utf-8"):
        raise ValueError("predecision log serialization differs from the immutable record")

    receipt = TasteProspectiveDecisionLockReceipt.create(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        source_project_id=plan.source_project_id,
        source_run_id=plan.source_run_id,
        observed_project_revision=snapshot.revision,
        observed_project_snapshot_sha256=snapshot.snapshot_sha256,
        decision_id=decision.decision_id,
        decision_sha256=decision_sha256,
        decision_timestamp=decision.timestamp,
        decision_log_locator=plan.decision_log_locator,
        decision_line_number=line_number,
        decision_line_sha256=hashlib.sha256(raw_line).hexdigest(),
        immutable_decision_locator=immutable_locator,
        immutable_decision_file_sha256=hashlib.sha256(immutable_path.read_bytes()).hexdigest(),
        state_snapshot_id=identifier,
        state_snapshot_locator=state_locator,
        state_file_sha256=hashlib.sha256(state_path.read_bytes()).hexdigest(),
        candidate_set_sha256=content_sha256(
            tuple(item.model_dump(mode="json") for item in actions)
        ),
        selected_action_id=decision.selected_action.action_id,
        selected_action_sha256=content_sha256(decision.selected_action.model_dump(mode="json")),
        rationale_sha256=content_sha256(decision.rationale),
        alternative_count=len(actions),
        captured_at=capture_time,
    )
    _write_new_json(output, receipt.model_dump_json(indent=2) + "\n")
    return receipt


def attach_prospective_taste_outcome(
    plan: TasteTrajectorySamplingPlan,
    lock: TasteProspectiveDecisionLockReceipt,
    *,
    source_root: str | Path,
    executor_result_id: str,
    observed_at: datetime,
    actual_outcome: dict[str, object],
    evidence: tuple[TasteProcessEvidenceBinding, ...],
    output: str | Path,
    projection_output: str | Path,
    attached_at: datetime | None = None,
) -> tuple[
    TasteProspectiveOutcomeAttachmentReceipt,
    TasteProspectiveDecisionCompletionProjection,
]:
    """Attach a later outcome while proving that the locked decision stayed unchanged."""

    if lock.plan_id != plan.plan_id or lock.plan_sha256 != plan.plan_sha256:
        raise ValueError("outcome attachment binds a lock from another sampling plan")
    if lock.source_project_id != plan.source_project_id or lock.source_run_id != plan.source_run_id:
        raise ValueError("outcome attachment source differs from the sampling plan")
    if observed_at.utcoffset() is None or observed_at <= lock.captured_at:
        raise ValueError("outcome observation must be strictly later than the predecision lock")
    attachment_time = attached_at or datetime.now(UTC)
    if attachment_time.utcoffset() is None or attachment_time <= lock.captured_at:
        raise ValueError("outcome attachment must be strictly later than the predecision lock")
    if attachment_time < observed_at:
        raise ValueError("outcome attachment cannot predate outcome observation")
    if not executor_result_id.strip():
        raise ValueError("outcome attachment requires an executor result ID")
    if not actual_outcome:
        raise ValueError("outcome attachment requires a non-empty actual outcome")
    if not evidence:
        raise ValueError("outcome attachment requires outcome evidence")

    root = _canonical_root(source_root)
    decision = _load_and_verify_locked_predecision(root, lock)
    outcome_evidence = tuple(
        TasteEpisodeEvidence(
            evidence_id=item.evidence_id,
            role=item.role,
            locator=item.locator,
            sha256=hashlib.sha256(
                _owned_file(root, item.locator, max_bytes=_MAX_EVIDENCE_BYTES).read_bytes()
            ).hexdigest(),
        )
        for item in evidence
    )
    if any(item.role is not TasteEpisodeEvidenceRole.OUTCOME for item in outcome_evidence):
        raise ValueError("outcome attachment accepts outcome evidence only")
    attachment = TasteProspectiveOutcomeAttachmentReceipt.create(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        lock_sha256=lock.lock_sha256,
        decision_id=lock.decision_id,
        predecision_sha256=lock.decision_sha256,
        executor_result_id=executor_result_id,
        observed_at=observed_at,
        actual_outcome=actual_outcome,
        actual_outcome_sha256=content_sha256(actual_outcome),
        evidence=outcome_evidence,
        attached_at=attachment_time,
    )
    completed = decision.model_copy(
        deep=True,
        update={
            "executor_result_id": executor_result_id,
            "actual_outcome": actual_outcome,
        },
    )
    projection = TasteProspectiveDecisionCompletionProjection.create(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        lock_sha256=lock.lock_sha256,
        attachment_sha256=attachment.attachment_sha256,
        predecision_sha256=lock.decision_sha256,
        completed_decision=completed,
        completed_decision_sha256=content_sha256(completed.model_dump(mode="json")),
        projected_at=attachment_time,
    )
    _write_new_json(output, attachment.model_dump_json(indent=2) + "\n")
    try:
        _write_new_json(projection_output, projection.model_dump_json(indent=2) + "\n")
    except BaseException:
        Path(output).unlink(missing_ok=True)
        raise
    _load_and_verify_locked_predecision(root, lock)
    return attachment, projection


def compile_prospective_taste_episode(
    plan: TasteTrajectorySamplingPlan,
    capture: TasteProspectiveDecisionCaptureReceipt,
    inventory: TasteTrajectoryInventory,
    proposal: TasteProcessEpisodeProposal,
    *,
    runtime: ProjectRuntime,
    current_idea_revision: ProjectIdeaRevisionBinding,
    expected_project_revision: int,
    output: str | Path,
) -> TasteEpisodeCandidate:
    """Bind a delayed-outcome proposal to one exact prospective foundation."""

    if plan.assignment_timing is not TasteTrajectoryAssignmentTiming.PROSPECTIVE:
        raise ValueError("process episode compilation requires a prospective plan")
    if not idea_binding_matches_current(plan.idea_revision, current_idea_revision):
        raise ValueError("process episode plan belongs to a stale Idea revision")
    if (
        proposal.plan_id != plan.plan_id
        or proposal.plan_sha256 != plan.plan_sha256
        or capture.plan_id != plan.plan_id
        or capture.plan_sha256 != plan.plan_sha256
        or inventory.plan_id != plan.plan_id
        or inventory.plan_sha256 != plan.plan_sha256
    ):
        raise ValueError("process episode artifacts bind different sampling plans")
    if proposal.capture_sha256 != capture.capture_sha256:
        raise ValueError("process episode proposal binds another capture")
    if proposal.inventory_sha256 != inventory.inventory_sha256:
        raise ValueError("process episode proposal binds another reconstruction inventory")
    if proposal.decision_id != capture.decision_id:
        raise ValueError("process episode proposal binds another decision")
    seeds = [item for item in inventory.decisions if item.decision_id == capture.decision_id]
    if len(seeds) != 1 or not seeds[0].foundation_eligible:
        raise ValueError("process episode decision lacks one eligible prospective foundation")
    seed = seeds[0]
    if (
        seed.line_number != capture.decision_line_number
        or seed.line_sha256 != capture.decision_line_sha256
        or seed.decision_sha256 != capture.decision_sha256
        or seed.state_snapshot_id != capture.state_snapshot_id
        or seed.executor_result_id != capture.executor_result_id
        or seed.executor_outcome_sha256 != capture.executor_outcome_sha256
    ):
        raise ValueError("process episode capture differs from reconstructed decision")

    snapshot = runtime.open(plan.source_project_id)
    if snapshot.revision != expected_project_revision:
        raise ValueError(
            f"stale project revision {expected_project_revision}; current is {snapshot.revision}"
        )
    run_root = runtime.projects_root / plan.source_project_id / "runs" / plan.source_run_id
    decision_path = _owned_file(
        run_root,
        plan.decision_log_locator,
        max_bytes=_MAX_DECISION_LOG_BYTES,
    )
    raw_lines = decision_path.read_bytes().splitlines(keepends=True)
    if capture.decision_line_number > len(raw_lines):
        raise ValueError("captured decision line is absent")
    raw_line = raw_lines[capture.decision_line_number - 1]
    if hashlib.sha256(raw_line).hexdigest() != capture.decision_line_sha256:
        raise ValueError("process episode decision line drifted after capture")
    decision = ResearchDecision.model_validate_json(raw_line)

    required_bindings = {
        (TasteEpisodeEvidenceRole.DECISION, plan.decision_log_locator),
        (TasteEpisodeEvidenceRole.DECISION_STATE, capture.state_snapshot_locator),
    }
    observed_bindings = {(item.role, item.locator) for item in proposal.evidence}
    if not required_bindings.issubset(observed_bindings):
        raise ValueError("process episode proposal does not bind the captured decision and state")
    evidence = tuple(
        TasteEpisodeEvidence(
            evidence_id=item.evidence_id,
            role=item.role,
            locator=item.locator,
            sha256=hashlib.sha256(
                _owned_file(run_root, item.locator, max_bytes=_MAX_EVIDENCE_BYTES).read_bytes()
            ).hexdigest(),
        )
        for item in proposal.evidence
    )
    candidate = compile_process_taste_episode_candidate(
        decision,
        candidate_id=proposal.candidate_id,
        project_id=plan.project_id,
        source_project_id=plan.source_project_id,
        source_group_id=plan.source_group_id,
        dataset_partition=plan.dataset_partition,
        source_project_revision=capture.observed_project_revision,
        source_project_snapshot_sha256=capture.observed_project_snapshot_sha256,
        idea_revision=plan.idea_revision,
        producer_id=proposal.producer_id,
        state_summary=proposal.state_summary,
        decision_context=proposal.decision_context,
        decision_principle=proposal.decision_principle,
        why_preferred=proposal.why_preferred,
        outcomes=proposal.outcomes,
        credit_assignments=proposal.credit_assignments,
        applicability_conditions=proposal.applicability_conditions,
        failure_conditions=proposal.failure_conditions,
        counterfactual_probe=proposal.counterfactual_probe,
        evidence=evidence,
        domain_tags=proposal.domain_tags,
        venue_tags=proposal.venue_tags,
        confounders=proposal.confounders,
        missing_evidence_questions=proposal.missing_evidence_questions,
    )
    _write_new_json(output, candidate.model_dump_json(indent=2) + "\n")
    return candidate


def compile_prospective_taste_episode_v2(
    plan: TasteTrajectorySamplingPlan,
    lock: TasteProspectiveDecisionLockReceipt,
    attachment: TasteProspectiveOutcomeAttachmentReceipt,
    projection: TasteProspectiveDecisionCompletionProjection,
    proposal: TasteProcessEpisodeProposal,
    *,
    runtime: ProjectRuntime,
    current_idea_revision: ProjectIdeaRevisionBinding,
    expected_project_revision: int,
    output: str | Path,
) -> TasteEpisodeCandidate:
    """Compile attribution against a two-phase decision/outcome foundation."""

    if plan.assignment_timing is not TasteTrajectoryAssignmentTiming.PROSPECTIVE:
        raise ValueError("process episode compilation requires a prospective plan")
    if not idea_binding_matches_current(plan.idea_revision, current_idea_revision):
        raise ValueError("process episode plan belongs to a stale Idea revision")
    if any(
        (
            lock.plan_id != plan.plan_id,
            lock.plan_sha256 != plan.plan_sha256,
            attachment.plan_id != plan.plan_id,
            attachment.plan_sha256 != plan.plan_sha256,
            projection.plan_id != plan.plan_id,
            projection.plan_sha256 != plan.plan_sha256,
        )
    ):
        raise ValueError("process episode v2 artifacts bind different sampling plans")
    if (
        attachment.lock_sha256 != lock.lock_sha256
        or attachment.decision_id != lock.decision_id
        or attachment.predecision_sha256 != lock.decision_sha256
        or projection.lock_sha256 != lock.lock_sha256
        or projection.attachment_sha256 != attachment.attachment_sha256
        or projection.predecision_sha256 != lock.decision_sha256
    ):
        raise ValueError("process episode v2 lock/outcome/projection chain differs")
    if (
        lock.decision_timestamp < plan.frozen_at
        or lock.captured_at < plan.frozen_at
        or attachment.observed_at <= lock.captured_at
        or attachment.attached_at <= lock.captured_at
        or projection.projected_at < attachment.attached_at
    ):
        raise ValueError("process episode v2 temporal ordering differs")
    if (
        proposal.capture_sha256 != attachment.attachment_sha256
        or proposal.inventory_sha256 != projection.projection_sha256
        or proposal.decision_id != lock.decision_id
    ):
        raise ValueError("process episode proposal binds another v2 completion")
    if proposal.observed_at < attachment.observed_at:
        raise ValueError("process episode proposal predates its attached outcome")

    snapshot = runtime.open(plan.source_project_id)
    if snapshot.revision != expected_project_revision:
        raise ValueError(
            f"stale project revision {expected_project_revision}; current is {snapshot.revision}"
        )
    run_root = runtime.projects_root / plan.source_project_id / "runs" / plan.source_run_id
    locked_decision = _load_and_verify_locked_predecision(run_root, lock)
    decision = projection.completed_decision
    restored_predecision = decision.model_copy(
        deep=True,
        update={"executor_result_id": None, "actual_outcome": None},
    )
    if restored_predecision != locked_decision:
        raise ValueError("completion projection changed predecision content")
    if (
        decision.executor_result_id != attachment.executor_result_id
        or decision.actual_outcome != attachment.actual_outcome
    ):
        raise ValueError("completion projection differs from the outcome attachment")

    required_bindings = {
        (TasteEpisodeEvidenceRole.DECISION, lock.immutable_decision_locator),
        (TasteEpisodeEvidenceRole.DECISION_STATE, lock.state_snapshot_locator),
    }
    observed_bindings = {(item.role, item.locator) for item in proposal.evidence}
    if not required_bindings.issubset(observed_bindings):
        raise ValueError("v2 proposal does not bind the immutable decision and state")
    attached_evidence = {
        (item.evidence_id, item.locator, item.sha256) for item in attachment.evidence
    }
    proposed_outcomes = {
        (
            item.evidence_id,
            item.locator,
            hashlib.sha256(
                _owned_file(run_root, item.locator, max_bytes=_MAX_EVIDENCE_BYTES).read_bytes()
            ).hexdigest(),
        )
        for item in proposal.evidence
        if item.role is TasteEpisodeEvidenceRole.OUTCOME
    }
    if not attached_evidence.issubset(proposed_outcomes):
        raise ValueError("v2 proposal omits outcome evidence from the attachment")
    compiled_evidence = tuple(
        TasteEpisodeEvidence(
            evidence_id=item.evidence_id,
            role=item.role,
            locator=item.locator,
            sha256=hashlib.sha256(
                _owned_file(run_root, item.locator, max_bytes=_MAX_EVIDENCE_BYTES).read_bytes()
            ).hexdigest(),
        )
        for item in proposal.evidence
    )
    candidate = compile_process_taste_episode_candidate(
        decision,
        candidate_id=proposal.candidate_id,
        project_id=plan.project_id,
        source_project_id=plan.source_project_id,
        source_group_id=plan.source_group_id,
        dataset_partition=plan.dataset_partition,
        source_project_revision=lock.observed_project_revision,
        source_project_snapshot_sha256=lock.observed_project_snapshot_sha256,
        idea_revision=plan.idea_revision,
        producer_id=proposal.producer_id,
        state_summary=proposal.state_summary,
        decision_context=proposal.decision_context,
        decision_principle=proposal.decision_principle,
        why_preferred=proposal.why_preferred,
        outcomes=proposal.outcomes,
        credit_assignments=proposal.credit_assignments,
        applicability_conditions=proposal.applicability_conditions,
        failure_conditions=proposal.failure_conditions,
        counterfactual_probe=proposal.counterfactual_probe,
        evidence=compiled_evidence,
        domain_tags=proposal.domain_tags,
        venue_tags=proposal.venue_tags,
        confounders=proposal.confounders,
        missing_evidence_questions=proposal.missing_evidence_questions,
    )
    _write_new_json(output, candidate.model_dump_json(indent=2) + "\n")
    return candidate


def reconstruct_taste_trajectory(
    plan: TasteTrajectorySamplingPlan,
    *,
    source_root: str | Path,
    current_idea_revision: ProjectIdeaRevisionBinding,
) -> TasteTrajectoryInventory:
    """Verify exact decisions and states while leaving scientific outcomes unlabelled."""

    if not idea_binding_matches_current(plan.idea_revision, current_idea_revision):
        raise ValueError("trajectory sampling plan belongs to a stale Idea revision")
    root = _canonical_root(source_root)
    decision_path = _owned_file(
        root,
        plan.decision_log_locator,
        max_bytes=_MAX_DECISION_LOG_BYTES,
    )
    decision_bytes = decision_path.read_bytes()
    decision_log_sha256 = hashlib.sha256(decision_bytes).hexdigest()
    state_index = _index_state_snapshots(root, plan.state_snapshot_root_locator)
    decisions: list[TasteTrajectoryDecisionSeed] = []
    for line_number, raw_line in enumerate(decision_bytes.splitlines(keepends=True), 1):
        if len(raw_line) > _MAX_DECISION_LINE_BYTES:
            raise ValueError(f"decision log line {line_number} exceeds the byte limit")
        if not raw_line.strip():
            raise ValueError(f"decision log line {line_number} is empty")
        try:
            decision = ResearchDecision.model_validate_json(raw_line)
        except ValueError as exc:
            raise ValueError(f"invalid decision log line {line_number}") from exc
        decisions.append(
            _reconstruct_decision(plan, root, state_index, line_number, raw_line, decision)
        )
    return TasteTrajectoryInventory.create(
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        idea_revision_id=plan.idea_revision.revision_id,
        idea_revision_record_sha256=plan.idea_revision.record_sha256,
        decision_log_locator=plan.decision_log_locator,
        decision_log_sha256=decision_log_sha256,
        decision_count=len(decisions),
        multi_alternative_count=sum(item.alternative_count >= 2 for item in decisions),
        state_verified_count=sum(item.state_verified for item in decisions),
        execution_bound_count=sum(item.execution_binding_complete for item in decisions),
        foundation_eligible_count=sum(item.foundation_eligible for item in decisions),
        decisions=tuple(decisions),
    )


def load_taste_trajectory_sampling_plan(path: str | Path) -> TasteTrajectorySamplingPlan:
    source = _bounded_input_file(path, max_bytes=_MAX_CONTRACT_BYTES)
    return TasteTrajectorySamplingPlan.model_validate_json(source.read_bytes())


def load_taste_prospective_capture(
    path: str | Path,
) -> TasteProspectiveDecisionCaptureReceipt:
    source = _bounded_input_file(path, max_bytes=_MAX_CONTRACT_BYTES)
    return TasteProspectiveDecisionCaptureReceipt.model_validate_json(source.read_bytes())


def load_taste_prospective_decision_lock(
    path: str | Path,
) -> TasteProspectiveDecisionLockReceipt:
    source = _bounded_input_file(path, max_bytes=_MAX_CONTRACT_BYTES)
    return TasteProspectiveDecisionLockReceipt.model_validate_json(source.read_bytes())


def load_taste_prospective_outcome_attachment(
    path: str | Path,
) -> TasteProspectiveOutcomeAttachmentReceipt:
    source = _bounded_input_file(path, max_bytes=_MAX_CONTRACT_BYTES)
    return TasteProspectiveOutcomeAttachmentReceipt.model_validate_json(source.read_bytes())


def load_taste_prospective_completion_projection(
    path: str | Path,
) -> TasteProspectiveDecisionCompletionProjection:
    source = _bounded_input_file(path, max_bytes=_MAX_CONTRACT_BYTES)
    return TasteProspectiveDecisionCompletionProjection.model_validate_json(source.read_bytes())


def load_taste_trajectory_inventory(path: str | Path) -> TasteTrajectoryInventory:
    source = _bounded_input_file(path, max_bytes=_MAX_CONTRACT_BYTES)
    return TasteTrajectoryInventory.model_validate_json(source.read_bytes())


def load_taste_process_episode_proposal(path: str | Path) -> TasteProcessEpisodeProposal:
    source = _bounded_input_file(path, max_bytes=_MAX_CONTRACT_BYTES)
    return TasteProcessEpisodeProposal.model_validate_json(source.read_bytes())


def save_taste_trajectory_sampling_plan(
    plan: TasteTrajectorySamplingPlan,
    path: str | Path,
) -> Path:
    return _write_new_json(path, plan.model_dump_json(indent=2) + "\n")


def save_taste_process_episode_proposal(
    proposal: TasteProcessEpisodeProposal,
    path: str | Path,
) -> Path:
    return _write_new_json(path, proposal.model_dump_json(indent=2) + "\n")


def save_taste_trajectory_inventory(
    inventory: TasteTrajectoryInventory,
    path: str | Path,
) -> Path:
    return _write_new_json(path, inventory.model_dump_json(indent=2) + "\n")


def _reconstruct_decision(
    plan: TasteTrajectorySamplingPlan,
    root: Path,
    state_index: dict[str, tuple[str, ...]],
    line_number: int,
    raw_line: bytes,
    decision: ResearchDecision,
) -> TasteTrajectoryDecisionSeed:
    state_locators = state_index.get(decision.state_snapshot_id, ())
    state_verified = False
    state_file_sha256: str | None = None
    findings: list[str] = []
    try:
        state_paths = tuple(
            _owned_file(root, locator, max_bytes=_MAX_STATE_BYTES) for locator in state_locators
        )
        if not state_paths:
            raise FileNotFoundError(decision.state_snapshot_id)
    except FileNotFoundError:
        findings.append("state-snapshot-missing")
    else:
        state_bytes = state_paths[0].read_bytes()
        if any(path.read_bytes() != state_bytes for path in state_paths[1:]):
            raise ValueError("duplicate state snapshot locators contain different bytes")
        try:
            state = ResearchState.model_validate_json(state_bytes)
        except ValueError:
            findings.append("state-snapshot-invalid")
        else:
            if snapshot_id(state) != decision.state_snapshot_id:
                findings.append("state-snapshot-identity-drift")
            else:
                state_verified = True
                state_file_sha256 = hashlib.sha256(state_bytes).hexdigest()

    alternative_count = len(decision.candidate_actions)
    if alternative_count < 2:
        findings.append("decision-has-no-recorded-alternative")
    outcome = decision.actual_outcome
    outcome_sha256 = content_sha256(outcome) if outcome is not None else None
    execution_complete = decision.executor_result_id is not None and outcome_sha256 is not None
    if not execution_complete:
        findings.append("executor-outcome-unbound")
    if plan.assignment_timing is TasteTrajectoryAssignmentTiming.RETROSPECTIVE_DEVELOPMENT:
        findings.append("retrospective-development-audit")

    if not state_verified:
        followup = TasteTrajectoryFollowup.STATE_UNAVAILABLE
    elif alternative_count < 2:
        followup = TasteTrajectoryFollowup.NOT_COMPARATIVE
    elif not execution_complete:
        followup = TasteTrajectoryFollowup.NOT_EXECUTED
    elif plan.assignment_timing is TasteTrajectoryAssignmentTiming.RETROSPECTIVE_DEVELOPMENT:
        followup = TasteTrajectoryFollowup.RETROSPECTIVE_AUDIT_ONLY
    else:
        followup = TasteTrajectoryFollowup.AWAITING_DELAYED_SCIENTIFIC_OUTCOME

    executor_status = outcome.get("status") if isinstance(outcome, dict) else None
    if not isinstance(executor_status, str):
        executor_status = None
    return TasteTrajectoryDecisionSeed(
        line_number=line_number,
        line_sha256=hashlib.sha256(raw_line).hexdigest(),
        decision_id=decision.decision_id,
        decision_sha256=content_sha256(decision.model_dump(mode="json")),
        decision_timestamp=decision.timestamp,
        stage=decision.stage,
        state_snapshot_id=decision.state_snapshot_id,
        state_snapshot_locators=state_locators if state_verified else (),
        state_file_sha256=state_file_sha256,
        state_verified=state_verified,
        alternative_count=alternative_count,
        selected_action_id=decision.selected_action.action_id,
        executor_result_id=decision.executor_result_id,
        executor_outcome_sha256=outcome_sha256,
        executor_status=executor_status,
        execution_binding_complete=execution_complete,
        foundation_eligible=followup is TasteTrajectoryFollowup.AWAITING_DELAYED_SCIENTIFIC_OUTCOME,
        followup=followup,
        finding_codes=tuple(findings),
    )


def _load_and_verify_locked_predecision(
    root: Path,
    lock: TasteProspectiveDecisionLockReceipt,
) -> ResearchDecision:
    immutable_path = _owned_file(
        root,
        lock.immutable_decision_locator,
        max_bytes=_MAX_DECISION_LINE_BYTES,
    )
    immutable_bytes = immutable_path.read_bytes()
    if hashlib.sha256(immutable_bytes).hexdigest() != lock.immutable_decision_file_sha256:
        raise ValueError("immutable predecision record drifted")
    decision = ResearchDecision.model_validate_json(immutable_bytes)
    if decision.executor_result_id is not None or decision.actual_outcome is not None:
        raise ValueError("immutable predecision record contains post-execution fields")
    if decision.decision_id != lock.decision_id:
        raise ValueError("immutable predecision identity drifted")
    if content_sha256(decision.model_dump(mode="json")) != lock.decision_sha256:
        raise ValueError("immutable predecision semantic hash drifted")
    if decision.timestamp != lock.decision_timestamp:
        raise ValueError("immutable predecision timestamp drifted")
    actions = tuple(decision.candidate_actions)
    if len(actions) != lock.alternative_count:
        raise ValueError("immutable predecision alternative count drifted")
    if content_sha256(tuple(item.model_dump(mode="json") for item in actions)) != (
        lock.candidate_set_sha256
    ):
        raise ValueError("immutable predecision action menu drifted")
    if (
        decision.selected_action.action_id != lock.selected_action_id
        or content_sha256(decision.selected_action.model_dump(mode="json"))
        != lock.selected_action_sha256
        or content_sha256(decision.rationale) != lock.rationale_sha256
    ):
        raise ValueError("immutable predecision selection or rationale drifted")

    decision_log = _owned_file(root, lock.decision_log_locator, max_bytes=_MAX_DECISION_LOG_BYTES)
    lines = decision_log.read_bytes().splitlines(keepends=True)
    if lock.decision_line_number > len(lines):
        raise ValueError("locked predecision line is missing")
    line = lines[lock.decision_line_number - 1]
    if hashlib.sha256(line).hexdigest() != lock.decision_line_sha256 or line != immutable_bytes:
        raise ValueError("locked predecision log line drifted")

    state_path = _owned_file(root, lock.state_snapshot_locator, max_bytes=_MAX_STATE_BYTES)
    state_bytes = state_path.read_bytes()
    if hashlib.sha256(state_bytes).hexdigest() != lock.state_file_sha256:
        raise ValueError("locked state snapshot bytes drifted")
    state = ResearchState.model_validate_json(state_bytes)
    if snapshot_id(state) != lock.state_snapshot_id:
        raise ValueError("locked state snapshot identity drifted")
    if decision.state_snapshot_id != lock.state_snapshot_id:
        raise ValueError("locked decision no longer binds its state")
    return decision


def _canonical_root(value: str | Path) -> Path:
    root = Path(value).expanduser()
    if root.is_symlink():
        raise ValueError("trajectory source root cannot be a symbolic link")
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("trajectory source root must be a directory")
    return resolved


def _owned_file(root: Path, locator: str, *, max_bytes: int) -> Path:
    validate_relative_locator(locator, field_name="trajectory source locator")
    current = root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("trajectory sources cannot use symbolic links")
    resolved = current.resolve(strict=True)
    resolved.relative_to(root)
    stat = resolved.stat()
    if not resolved.is_file() or stat.st_size > max_bytes:
        raise ValueError("trajectory source is not a bounded regular file")
    return resolved


def _index_state_snapshots(root: Path, locator: str) -> dict[str, tuple[str, ...]]:
    search_root = _owned_directory(root, locator)
    discovered: dict[str, list[str]] = {}
    entry_count = 0
    for directory, names, files in os.walk(search_root, followlinks=False):
        directory_path = Path(directory)
        entry_count += len(names) + len(files)
        if entry_count > _MAX_STATE_TREE_ENTRIES:
            raise ValueError("trajectory state tree exceeds the entry limit")
        for name in (*names, *files):
            if (directory_path / name).is_symlink():
                raise ValueError("trajectory state tree cannot contain symbolic links")
        if directory_path.name != "state_snapshots":
            continue
        for name in files:
            if not name.startswith("state-") or not name.endswith(".json"):
                continue
            identifier = name.removesuffix(".json")
            if len(identifier) != 70 or any(
                character not in "0123456789abcdef" for character in identifier[6:]
            ):
                raise ValueError("trajectory state snapshot filename is not content-addressed")
            path = directory_path / name
            relative = path.relative_to(root).as_posix()
            discovered.setdefault(identifier, []).append(relative)
    return {identifier: tuple(sorted(locators)) for identifier, locators in discovered.items()}


def _owned_directory(root: Path, locator: str) -> Path:
    validate_relative_locator(locator, field_name="trajectory source locator")
    current = root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("trajectory sources cannot use symbolic links")
    resolved = current.resolve(strict=True)
    resolved.relative_to(root)
    if not resolved.is_dir():
        raise ValueError("trajectory source is not a directory")
    return resolved


def _bounded_input_file(value: str | Path, *, max_bytes: int) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError("trajectory contract input cannot be a symbolic link")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > max_bytes:
        raise ValueError("trajectory contract input is not a bounded regular file")
    return resolved


def _write_new_json(value: str | Path, contents: str) -> Path:
    path = Path(value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    parent = path.parent.resolve(strict=True)
    if parent.is_symlink():
        raise ValueError("trajectory output parent cannot be a symbolic link")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def _write_or_verify_immutable(path: Path, contents: bytes) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != contents:
            raise ValueError("immutable predecision record already binds different bytes")
        return
    _write_new_json(path, contents.decode("utf-8"))


__all__ = [
    "TasteProcessEpisodeProposal",
    "TasteProcessEvidenceBinding",
    "TasteProspectiveDecisionCaptureReceipt",
    "TasteProspectiveDecisionCompletionProjection",
    "TasteProspectiveDecisionLockReceipt",
    "TasteProspectiveOutcomeAttachmentReceipt",
    "TasteTrajectoryAssignmentTiming",
    "TasteTrajectoryDecisionSeed",
    "TasteTrajectoryFollowup",
    "TasteTrajectoryInventory",
    "TasteTrajectorySamplingPlan",
    "attach_prospective_taste_outcome",
    "capture_prospective_taste_decision",
    "compile_prospective_taste_episode",
    "compile_prospective_taste_episode_v2",
    "load_taste_process_episode_proposal",
    "load_taste_prospective_capture",
    "load_taste_prospective_completion_projection",
    "load_taste_prospective_decision_lock",
    "load_taste_prospective_outcome_attachment",
    "load_taste_trajectory_inventory",
    "load_taste_trajectory_sampling_plan",
    "lock_prospective_taste_decision",
    "reconstruct_taste_trajectory",
    "save_taste_process_episode_proposal",
    "save_taste_trajectory_inventory",
    "save_taste_trajectory_sampling_plan",
]

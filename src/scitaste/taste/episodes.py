"""Unified, proposal-only supervision episodes for lifecycle Scientific Taste."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_binding_matches_current,
)
from scitaste.project.models import content_sha256, validate_project_id, validate_relative_locator
from scitaste.schema.decisions import ResearchDecision

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_EVIDENCE_BYTES = 64 * 1024 * 1024


class TasteSupervisionChannel(StrEnum):
    """Orthogonal sources of evidence for one lifecycle policy."""

    EXTERNAL_PRECEDENT = "external-precedent"
    INTERNAL_OUTCOME = "internal-outcome"
    HUMAN_INTERVENTION = "human-intervention"


class TasteEpisodeProducerRole(StrEnum):
    REFERENCE_MINER = "reference-miner"
    PROCESS_TASTE_MINER = "process-taste-miner"
    GENERATION_AS_CONTENT = "generation-as-content"


class TasteEpisodeMaturity(StrEnum):
    AWAITING_OUTCOME = "awaiting-outcome"
    ATTRIBUTION_PROPOSED = "attribution-proposed"


class TasteSupervisionScope(StrEnum):
    USER = "user"
    PROJECT = "project"
    COMMUNITY_CANDIDATE = "community-candidate"


class TasteEpisodePartition(StrEnum):
    DEVELOPMENT = "development"
    CALIBRATION = "calibration"
    PILOT = "pilot"
    FORMAL_HELDOUT = "formal-heldout"


class TasteEpisodeSourceRelationship(StrEnum):
    SELF_PROJECT = "self-project"
    INDEPENDENT_PROJECT = "independent-project"
    EXTERNAL_RECORD = "external-record"


class TasteInterventionOperation(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    EDIT = "edit"
    REPRIORITIZE = "reprioritize"
    ADD_MISSING_ALTERNATIVE = "add-missing-alternative"
    CHALLENGE_EVIDENCE = "challenge-evidence"
    CHALLENGE_ATTRIBUTION = "challenge-attribution"
    SET_APPLICABILITY_SCOPE = "set-applicability-scope"
    SET_REVERSAL_OBSERVATION = "set-reversal-observation"


class TasteEpisodeEvidenceRole(StrEnum):
    DECISION = "decision"
    DECISION_STATE = "decision-state"
    EXTERNAL_SOURCE = "external-source"
    TOOL_OBSERVATION = "tool-observation"
    OUTCOME = "outcome"
    HUMAN_INTERVENTION = "human-intervention"
    REVIEW = "review"


class TasteOutcomeFamily(StrEnum):
    HYPOTHESIS = "hypothesis"
    DESIGN = "design"
    EXECUTION = "execution"
    ADAPTATION = "adaptation"
    CLAIM = "claim"
    REVIEW = "review"
    COMMUNICATION = "communication"


class TasteOutcomePolarity(StrEnum):
    SUPPORTS = "supports"
    CHALLENGES = "challenges"
    MIXED = "mixed"
    UNRESOLVED = "unresolved"


class TasteCreditDirection(StrEnum):
    BENEFICIAL = "beneficial"
    HARMFUL = "harmful"
    MIXED = "mixed"
    NOT_ATTRIBUTABLE = "not-attributable"


class TasteEpisodeEvidence(BaseModel):
    """Exact project-owned bytes visible to an episode producer or reviewer."""

    model_config = _CONFIG

    evidence_id: str = Field(pattern=_ID)
    role: TasteEpisodeEvidenceRole
    locator: str = Field(min_length=1, max_length=2_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_relative(self) -> TasteEpisodeEvidence:
        validate_relative_locator(self.locator, field_name="Taste episode evidence")
        return self


class TasteEpisodeAlternative(BaseModel):
    model_config = _CONFIG

    action_id: str = Field(min_length=1, max_length=300)
    action_type: str = Field(default="unspecified", min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4_000)
    tags: tuple[str, ...] = Field(default=(), max_length=30)
    expected_value: dict[str, float] = Field(default_factory=dict)
    expected_cost: dict[str, float] = Field(default_factory=dict)
    selected: bool

    @model_validator(mode="after")
    def features_are_closed(self) -> TasteEpisodeAlternative:
        if len(self.tags) != len(set(tag.casefold() for tag in self.tags)):
            raise ValueError("Taste episode action tags must be unique")
        for mapping in (self.expected_value, self.expected_cost):
            if any(
                value != value or value in {float("inf"), float("-inf")}
                for value in mapping.values()
            ):
                raise ValueError("Taste episode action features must be finite")
        if any(value < 0 for value in self.expected_cost.values()):
            raise ValueError("Taste episode action costs must be nonnegative")
        return self


class TasteEpisodeOutcome(BaseModel):
    """Delayed observation without assuming that success implies good Taste."""

    model_config = _CONFIG

    outcome_id: str = Field(pattern=_ID)
    family: TasteOutcomeFamily
    summary: str = Field(min_length=1, max_length=10_000)
    horizon: str = Field(min_length=1, max_length=500)
    polarity: TasteOutcomePolarity
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def evidence_is_unique(self) -> TasteEpisodeOutcome:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Taste outcome evidence IDs must be unique")
        return self


class TasteEpisodeConfounder(BaseModel):
    model_config = _CONFIG

    confounder_id: str = Field(pattern=_ID)
    description: str = Field(min_length=1, max_length=4_000)
    resolution: Literal["unresolved", "partially-controlled", "controlled"]


class TasteCreditAssignment(BaseModel):
    """A reviewable attribution hypothesis, never a self-certifying label."""

    model_config = _CONFIG

    credit_id: str = Field(pattern=_ID)
    family: TasteOutcomeFamily
    direction: TasteCreditDirection
    outcome_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    confounder_ids: tuple[str, ...] = Field(default=(), max_length=100)
    rationale: str = Field(min_length=1, max_length=10_000)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def references_are_unique(self) -> TasteCreditAssignment:
        if len(self.outcome_ids) != len(set(self.outcome_ids)):
            raise ValueError("Taste credit outcome IDs must be unique")
        if len(self.confounder_ids) != len(set(self.confounder_ids)):
            raise ValueError("Taste credit confounder IDs must be unique")
        return self


class TasteEpisodeDecisionContext(BaseModel):
    """Outcome-blind state available when the archived decision was made."""

    model_config = _CONFIG

    remaining_experiments: Literal["zero", "one", "two-to-three", "four-plus"]
    failure_count: Literal["zero", "one", "two-plus"]
    no_improvement_streak: Literal["zero", "one", "two-plus"]
    score_trend: Literal["unknown", "declining", "flat", "improving"]
    best_vs_baseline: Literal["unknown", "below", "equal", "above"]


class TasteEpisodeCandidate(BaseModel):
    """One quarantined decision precedent proposed by any supervision channel."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2", "1.3"] = "1.2"
    candidate_id: str = Field(pattern=_ID)
    project_id: str
    source_project_id: str | None = None
    source_group_id: str | None = Field(default=None, pattern=_ID)
    dataset_partition: TasteEpisodePartition | None = None
    source_relationship: TasteEpisodeSourceRelationship | None = None
    source_project_revision: int = Field(ge=0)
    source_project_snapshot_sha256: str = Field(pattern=_SHA256)
    idea_revision: ProjectIdeaRevisionBinding
    channel: TasteSupervisionChannel
    producer_role: TasteEpisodeProducerRole
    producer_id: str = Field(pattern=_ID)
    attribution_producer_role: TasteEpisodeProducerRole | None = None
    attribution_producer_id: str | None = Field(default=None, pattern=_ID)
    maturity: TasteEpisodeMaturity
    supervision_scope: TasteSupervisionScope
    human_operation: TasteInterventionOperation | None = None
    stage: str = Field(min_length=1, max_length=300)
    decision_id: str = Field(min_length=1, max_length=300)
    state_summary: str = Field(min_length=1, max_length=20_000)
    decision_context: TasteEpisodeDecisionContext | None = None
    alternatives: tuple[TasteEpisodeAlternative, ...] = Field(min_length=2, max_length=30)
    selected_action_id: str = Field(min_length=1, max_length=300)
    decision_principle: str = Field(min_length=1, max_length=10_000)
    why_preferred: str = Field(min_length=1, max_length=10_000)
    outcomes: tuple[TasteEpisodeOutcome, ...] = Field(default=(), max_length=100)
    credit_assignments: tuple[TasteCreditAssignment, ...] = Field(default=(), max_length=100)
    applicability_conditions: tuple[str, ...] = Field(min_length=1, max_length=30)
    failure_conditions: tuple[str, ...] = Field(min_length=1, max_length=30)
    counterfactual_probe: str = Field(min_length=1, max_length=10_000)
    domain_tags: tuple[str, ...] = Field(default=(), max_length=30)
    venue_tags: tuple[str, ...] = Field(default=(), max_length=30)
    confounders: tuple[TasteEpisodeConfounder, ...] = Field(default=(), max_length=100)
    evidence: tuple[TasteEpisodeEvidence, ...] = Field(min_length=2, max_length=200)
    missing_evidence_questions: tuple[str, ...] = Field(default=(), max_length=30)
    canonical_evidence: Literal[False] = False
    retrieval_eligible: Literal[False] = False
    admission_authority: Literal[False] = False
    policy_update_authorized: Literal[False] = False
    execution_authority: Literal["none"] = "none"
    candidate_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def candidate_is_closed_and_quarantined(self) -> TasteEpisodeCandidate:
        validate_project_id(self.project_id)
        if self.source_project_id is not None:
            validate_project_id(self.source_project_id)
        if self.idea_revision.project_id != self.project_id:
            raise ValueError("Taste episode Idea revision belongs to another project")
        if (
            self.source_project_id == self.project_id
            and self.idea_revision.observed_project_revision > self.source_project_revision
        ):
            raise ValueError("Taste episode predates its bound Idea revision")
        action_ids = [item.action_id for item in self.alternatives]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("Taste episode alternatives must be unique")
        selected = [item.action_id for item in self.alternatives if item.selected]
        if selected != [self.selected_action_id]:
            raise ValueError("Taste episode must mark exactly its selected action")
        if self.schema_version in {"1.1", "1.2", "1.3"} and any(
            item.action_type == "unspecified" for item in self.alternatives
        ):
            raise ValueError("schema-1.1+ Taste alternatives require action types")
        if self.schema_version in {"1.2", "1.3"}:
            if (
                self.source_group_id is None
                or self.dataset_partition is None
                or self.source_relationship is None
            ):
                raise ValueError("schema-1.2 Taste episodes require a frozen sampling unit")
            if self.source_relationship is TasteEpisodeSourceRelationship.EXTERNAL_RECORD:
                if self.source_project_id is not None:
                    raise ValueError("external-record Taste source cannot claim a project identity")
            elif self.source_project_id is None:
                raise ValueError("project trajectory Taste source requires a source project")
            elif (self.source_relationship is TasteEpisodeSourceRelationship.SELF_PROJECT) != (
                self.source_project_id == self.project_id
            ):
                raise ValueError("Taste source relationship disagrees with project identity")
            if (
                self.source_relationship is TasteEpisodeSourceRelationship.SELF_PROJECT
                and self.dataset_partition is not TasteEpisodePartition.DEVELOPMENT
            ):
                raise ValueError("self-project Taste evidence is development-only")
        outcome_ids = [item.outcome_id for item in self.outcomes]
        credit_ids = [item.credit_id for item in self.credit_assignments]
        confounder_ids = [item.confounder_id for item in self.confounders]
        evidence_ids = [item.evidence_id for item in self.evidence]
        for label, values in (
            ("outcomes", outcome_ids),
            ("credit assignments", credit_ids),
            ("confounders", confounder_ids),
            ("evidence", evidence_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"Taste episode {label} must be unique")
        if len({item.locator for item in self.evidence}) != len(self.evidence):
            raise ValueError("Taste episode evidence locators must be unique")
        known_outcomes = set(outcome_ids)
        known_confounders = set(confounder_ids)
        known_evidence = set(evidence_ids)
        if any(set(item.evidence_ids) - known_evidence for item in self.outcomes):
            raise ValueError("Taste outcome references unknown evidence")
        if any(set(item.outcome_ids) - known_outcomes for item in self.credit_assignments):
            raise ValueError("Taste credit assignment references an unknown outcome")
        if any(set(item.confounder_ids) - known_confounders for item in self.credit_assignments):
            raise ValueError("Taste credit assignment references an unknown confounder")
        expected_role = {
            TasteSupervisionChannel.EXTERNAL_PRECEDENT: TasteEpisodeProducerRole.REFERENCE_MINER,
            TasteSupervisionChannel.INTERNAL_OUTCOME: TasteEpisodeProducerRole.PROCESS_TASTE_MINER,
            TasteSupervisionChannel.HUMAN_INTERVENTION: (
                TasteEpisodeProducerRole.GENERATION_AS_CONTENT
            ),
        }[self.channel]
        if self.producer_role is not expected_role:
            raise ValueError("Taste episode producer role does not match its supervision channel")
        required_roles = {
            TasteSupervisionChannel.EXTERNAL_PRECEDENT: {
                TasteEpisodeEvidenceRole.DECISION,
                TasteEpisodeEvidenceRole.EXTERNAL_SOURCE,
            },
            TasteSupervisionChannel.INTERNAL_OUTCOME: {
                TasteEpisodeEvidenceRole.DECISION,
                TasteEpisodeEvidenceRole.OUTCOME,
            },
            TasteSupervisionChannel.HUMAN_INTERVENTION: {
                TasteEpisodeEvidenceRole.DECISION,
                TasteEpisodeEvidenceRole.HUMAN_INTERVENTION,
            },
        }[self.channel]
        if not required_roles.issubset({item.role for item in self.evidence}):
            raise ValueError("Taste episode lacks evidence required by its supervision channel")
        if self.channel is TasteSupervisionChannel.HUMAN_INTERVENTION:
            if self.human_operation is None:
                raise ValueError("human Taste intervention requires a typed operation")
            if self.supervision_scope is TasteSupervisionScope.COMMUNITY_CANDIDATE:
                raise ValueError("human intervention cannot begin with community-wide scope")
        elif self.human_operation is not None:
            raise ValueError("only human-intervention episodes carry a human operation")
        if self.maturity is TasteEpisodeMaturity.AWAITING_OUTCOME:
            if (
                self.outcomes
                or self.credit_assignments
                or self.attribution_producer_role is not None
                or self.attribution_producer_id is not None
            ):
                raise ValueError("outcome-pending Taste episodes cannot carry attribution")
        elif not self.outcomes or not self.credit_assignments:
            raise ValueError("attribution-proposed episodes require outcomes and credit")
        elif self.schema_version in {"1.1", "1.2", "1.3"}:
            if self.attribution_producer_role is None or self.attribution_producer_id is None:
                raise ValueError("outcome attribution requires its producer identity")
            expected_attribution_role = (
                TasteEpisodeProducerRole.REFERENCE_MINER
                if self.channel is TasteSupervisionChannel.EXTERNAL_PRECEDENT
                else TasteEpisodeProducerRole.PROCESS_TASTE_MINER
            )
            if self.attribution_producer_role is not expected_attribution_role:
                raise ValueError("Taste attribution producer role violates channel ownership")
        for label, values in (
            ("applicability", self.applicability_conditions),
            ("failure", self.failure_conditions),
            ("domain", self.domain_tags),
            ("venue", self.venue_tags),
            ("missing evidence", self.missing_evidence_questions),
        ):
            folded = [value.casefold() for value in values]
            if len(folded) != len(set(folded)):
                raise ValueError(f"Taste episode {label} items must be unique")
        if self.schema_version == "1.3":
            if self.decision_context is None:
                raise ValueError("schema-1.3 Taste episode requires decision-time context")
        elif self.decision_context is not None:
            raise ValueError("legacy Taste episode cannot carry decision-time context")
        payload = self.model_dump(mode="json", exclude={"candidate_sha256"})
        expected = content_sha256(payload)
        accepted_hashes = {expected}
        if self.schema_version in {"1.0", "1.1", "1.2"}:
            legacy = _legacy_candidate_payload(payload, self.schema_version)
            accepted_hashes.add(content_sha256(legacy))
            accepted_hashes.add(content_sha256({**legacy, "decision_context": None}))
        if self.candidate_sha256 not in accepted_hashes:
            raise ValueError("Taste episode candidate hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteEpisodeCandidate:
        payload = {
            "schema_version": "1.3" if values.get("decision_context") is not None else "1.2",
            **values,
        }
        payload.pop("candidate_sha256", None)
        unsigned = cls.model_construct(candidate_sha256="0" * 64, **payload)
        return cls(
            **payload,
            candidate_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"candidate_sha256"})
            ),
        )


class TasteEpisodeFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class TasteEpisodeInspection(BaseModel):
    """Core-side intake verdict; review readiness is weaker than admission."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str
    candidate_sha256: str = Field(pattern=_SHA256)
    channel: TasteSupervisionChannel
    evidence_verified: bool
    current_idea_revision_matches: bool
    attribution_proposed: bool
    ready_for_independent_review: bool
    retrieval_eligible: Literal[False] = False
    policy_update_authorized: Literal[False] = False
    findings: tuple[TasteEpisodeFinding, ...]
    no_external_action_performed: Literal[True] = True


def compile_process_taste_episode_candidate(
    decision: ResearchDecision,
    *,
    candidate_id: str,
    project_id: str,
    source_project_id: str,
    source_group_id: str,
    dataset_partition: TasteEpisodePartition,
    source_project_revision: int,
    source_project_snapshot_sha256: str,
    idea_revision: ProjectIdeaRevisionBinding,
    producer_id: str,
    state_summary: str,
    decision_context: TasteEpisodeDecisionContext | None = None,
    decision_principle: str,
    why_preferred: str,
    outcomes: tuple[TasteEpisodeOutcome, ...],
    credit_assignments: tuple[TasteCreditAssignment, ...],
    applicability_conditions: tuple[str, ...],
    failure_conditions: tuple[str, ...],
    counterfactual_probe: str,
    evidence: tuple[TasteEpisodeEvidence, ...],
    domain_tags: tuple[str, ...] = (),
    venue_tags: tuple[str, ...] = (),
    confounders: tuple[TasteEpisodeConfounder, ...] = (),
    missing_evidence_questions: tuple[str, ...] = (),
) -> TasteEpisodeCandidate:
    """Compile Tool Intelligence output without allowing it to admit its lesson."""

    if decision.executor_result_id is None or decision.actual_outcome is None:
        raise ValueError("process Taste mining requires an executed decision and outcome")
    alternatives = tuple(
        TasteEpisodeAlternative(
            action_id=action.action_id,
            action_type=action.type.value,
            summary=action.description,
            tags=tuple(action.tags),
            expected_value=dict(action.expected_value),
            expected_cost=dict(action.expected_cost),
            selected=action.action_id == decision.selected_action.action_id,
        )
        for action in decision.candidate_actions
    )
    return TasteEpisodeCandidate.create(
        candidate_id=candidate_id,
        project_id=project_id,
        source_project_id=source_project_id,
        source_group_id=source_group_id,
        dataset_partition=dataset_partition,
        source_relationship=(
            TasteEpisodeSourceRelationship.SELF_PROJECT
            if source_project_id == project_id
            else TasteEpisodeSourceRelationship.INDEPENDENT_PROJECT
        ),
        source_project_revision=source_project_revision,
        source_project_snapshot_sha256=source_project_snapshot_sha256,
        idea_revision=idea_revision,
        channel=TasteSupervisionChannel.INTERNAL_OUTCOME,
        producer_role=TasteEpisodeProducerRole.PROCESS_TASTE_MINER,
        producer_id=producer_id,
        attribution_producer_role=TasteEpisodeProducerRole.PROCESS_TASTE_MINER,
        attribution_producer_id=producer_id,
        maturity=TasteEpisodeMaturity.ATTRIBUTION_PROPOSED,
        supervision_scope=TasteSupervisionScope.PROJECT,
        stage=decision.stage,
        decision_id=decision.decision_id,
        state_summary=state_summary,
        decision_context=decision_context,
        alternatives=alternatives,
        selected_action_id=decision.selected_action.action_id,
        decision_principle=decision_principle,
        why_preferred=why_preferred,
        outcomes=outcomes,
        credit_assignments=credit_assignments,
        applicability_conditions=applicability_conditions,
        failure_conditions=failure_conditions,
        counterfactual_probe=counterfactual_probe,
        domain_tags=domain_tags,
        venue_tags=venue_tags,
        confounders=confounders,
        evidence=evidence,
        missing_evidence_questions=missing_evidence_questions,
    )


def attach_outcome_attribution_to_human_intervention(
    candidate: TasteEpisodeCandidate,
    *,
    source_project_revision: int,
    source_project_snapshot_sha256: str,
    attribution_producer_id: str,
    outcomes: tuple[TasteEpisodeOutcome, ...],
    credit_assignments: tuple[TasteCreditAssignment, ...],
    outcome_evidence: tuple[TasteEpisodeEvidence, ...],
    confounders: tuple[TasteEpisodeConfounder, ...] = (),
    missing_evidence_questions: tuple[str, ...] = (),
) -> TasteEpisodeCandidate:
    """Join a later process observation to a preserved human correction."""

    if candidate.channel is not TasteSupervisionChannel.HUMAN_INTERVENTION:
        raise ValueError("outcome join accepts only a human-intervention candidate")
    if candidate.maturity is not TasteEpisodeMaturity.AWAITING_OUTCOME:
        raise ValueError("human intervention already carries outcome attribution")
    if source_project_revision < candidate.source_project_revision:
        raise ValueError("outcome attribution cannot move a project revision backward")
    if not any(item.role is TasteEpisodeEvidenceRole.OUTCOME for item in outcome_evidence):
        raise ValueError("human intervention outcome join requires outcome evidence")
    payload = {
        name: getattr(candidate, name)
        for name in type(candidate).model_fields
        if name != "candidate_sha256"
    }
    payload.update(
        {
            "source_project_revision": source_project_revision,
            "source_project_snapshot_sha256": source_project_snapshot_sha256,
            "attribution_producer_role": TasteEpisodeProducerRole.PROCESS_TASTE_MINER,
            "attribution_producer_id": attribution_producer_id,
            "maturity": TasteEpisodeMaturity.ATTRIBUTION_PROPOSED,
            "outcomes": outcomes,
            "credit_assignments": credit_assignments,
            "confounders": confounders,
            "evidence": (*candidate.evidence, *outcome_evidence),
            "missing_evidence_questions": missing_evidence_questions,
        }
    )
    return TasteEpisodeCandidate.create(**payload)


def compile_human_taste_intervention_candidate(
    decision: ResearchDecision,
    *,
    candidate_id: str,
    project_id: str,
    source_project_id: str,
    source_group_id: str,
    dataset_partition: TasteEpisodePartition,
    source_project_revision: int,
    source_project_snapshot_sha256: str,
    idea_revision: ProjectIdeaRevisionBinding,
    producer_id: str,
    operation: TasteInterventionOperation,
    supervision_scope: Literal[TasteSupervisionScope.USER, TasteSupervisionScope.PROJECT],
    state_summary: str,
    decision_context: TasteEpisodeDecisionContext | None = None,
    decision_principle: str,
    why_preferred: str,
    applicability_conditions: tuple[str, ...],
    failure_conditions: tuple[str, ...],
    counterfactual_probe: str,
    evidence: tuple[TasteEpisodeEvidence, ...],
    domain_tags: tuple[str, ...] = (),
    venue_tags: tuple[str, ...] = (),
    missing_evidence_questions: tuple[str, ...] = (),
) -> TasteEpisodeCandidate:
    """Compile a GAC correction that waits for outcomes before attribution."""

    alternatives = tuple(
        TasteEpisodeAlternative(
            action_id=action.action_id,
            action_type=action.type.value,
            summary=action.description,
            tags=tuple(action.tags),
            expected_value=dict(action.expected_value),
            expected_cost=dict(action.expected_cost),
            selected=action.action_id == decision.selected_action.action_id,
        )
        for action in decision.candidate_actions
    )
    return TasteEpisodeCandidate.create(
        candidate_id=candidate_id,
        project_id=project_id,
        source_project_id=source_project_id,
        source_group_id=source_group_id,
        dataset_partition=dataset_partition,
        source_relationship=(
            TasteEpisodeSourceRelationship.SELF_PROJECT
            if source_project_id == project_id
            else TasteEpisodeSourceRelationship.INDEPENDENT_PROJECT
        ),
        source_project_revision=source_project_revision,
        source_project_snapshot_sha256=source_project_snapshot_sha256,
        idea_revision=idea_revision,
        channel=TasteSupervisionChannel.HUMAN_INTERVENTION,
        producer_role=TasteEpisodeProducerRole.GENERATION_AS_CONTENT,
        producer_id=producer_id,
        maturity=TasteEpisodeMaturity.AWAITING_OUTCOME,
        supervision_scope=supervision_scope,
        human_operation=operation,
        stage=decision.stage,
        decision_id=decision.decision_id,
        state_summary=state_summary,
        decision_context=decision_context,
        alternatives=alternatives,
        selected_action_id=decision.selected_action.action_id,
        decision_principle=decision_principle,
        why_preferred=why_preferred,
        applicability_conditions=applicability_conditions,
        failure_conditions=failure_conditions,
        counterfactual_probe=counterfactual_probe,
        domain_tags=domain_tags,
        venue_tags=venue_tags,
        evidence=evidence,
        missing_evidence_questions=missing_evidence_questions,
    )


def inspect_taste_episode_candidate(
    candidate: TasteEpisodeCandidate,
    *,
    evidence_root: str | Path,
    current_idea_revision: ProjectIdeaRevisionBinding,
) -> TasteEpisodeInspection:
    """Verify exact bytes and reject candidates bound to an outdated scientific idea."""

    findings: list[TasteEpisodeFinding] = []
    evidence_verified = True
    root = Path(evidence_root).expanduser()
    try:
        canonical_root = root.resolve(strict=True)
    except OSError as exc:
        canonical_root = root
        evidence_verified = False
        _episode_add(findings, "evidence-root-unavailable", str(exc))
    for item in candidate.evidence:
        try:
            current = canonical_root
            for part in PurePosixPath(item.locator).parts:
                current /= part
                if current.is_symlink():
                    raise ValueError("symbolic links are not allowed")
            resolved = current.resolve(strict=True)
            resolved.relative_to(canonical_root)
            if not resolved.is_file() or resolved.stat().st_size > _MAX_EVIDENCE_BYTES:
                raise ValueError("evidence is not a bounded regular file")
            observed = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if observed != item.sha256:
                raise ValueError("SHA-256 differs from the candidate")
        except (OSError, ValueError) as exc:
            evidence_verified = False
            _episode_add(
                findings,
                "evidence-unavailable-or-drifted",
                f"{item.evidence_id}: {exc}",
            )
    idea_matches = idea_binding_matches_current(
        candidate.idea_revision,
        current_idea_revision,
    )
    if not idea_matches:
        _episode_add(
            findings,
            "idea-revision-stale",
            "Taste episode was produced under a different current Idea revision",
        )
    attribution_proposed = candidate.maturity is TasteEpisodeMaturity.ATTRIBUTION_PROPOSED
    if not attribution_proposed:
        _episode_add(
            findings,
            "outcome-attribution-pending",
            "human intervention is retained but cannot be reviewed as reusable Taste yet",
        )
    attribution_producer_bound = (
        candidate.attribution_producer_role is not None
        and candidate.attribution_producer_id is not None
    )
    if attribution_proposed and not attribution_producer_bound:
        _episode_add(
            findings,
            "attribution-producer-unbound",
            "legacy attribution lacks an independently identifiable producer",
        )
    attributable = any(
        item.direction is not TasteCreditDirection.NOT_ATTRIBUTABLE
        for item in candidate.credit_assignments
    )
    if attribution_proposed and not attributable:
        _episode_add(
            findings,
            "no-attributable-credit",
            "episode contains no reviewable contribution to a research outcome",
        )
    ready = (
        evidence_verified
        and idea_matches
        and attribution_proposed
        and attribution_producer_bound
        and attributable
    )
    return TasteEpisodeInspection(
        candidate_id=candidate.candidate_id,
        candidate_sha256=candidate.candidate_sha256,
        channel=candidate.channel,
        evidence_verified=evidence_verified,
        current_idea_revision_matches=idea_matches,
        attribution_proposed=attribution_proposed,
        ready_for_independent_review=ready,
        retrieval_eligible=False,
        policy_update_authorized=False,
        findings=tuple(findings),
    )


def _episode_add(
    findings: list[TasteEpisodeFinding],
    code: str,
    message: str,
) -> None:
    if code not in {item.code for item in findings}:
        findings.append(TasteEpisodeFinding(code=code, message=message))


def _legacy_candidate_payload(
    payload: dict[str, object],
    schema_version: str,
) -> dict[str, object]:
    """Reproduce older hashes after additive parsing."""

    legacy = dict(payload)
    legacy.pop("decision_context", None)
    if schema_version == "1.2":
        return legacy
    for field in (
        "source_project_id",
        "source_group_id",
        "dataset_partition",
        "source_relationship",
    ):
        legacy.pop(field, None)
    if schema_version == "1.1":
        return legacy
    for field in (
        "attribution_producer_role",
        "attribution_producer_id",
        "domain_tags",
        "venue_tags",
    ):
        legacy.pop(field, None)
    alternatives = []
    for value in legacy.get("alternatives", []):
        alternative = dict(value)
        for field in ("action_type", "tags", "expected_value", "expected_cost"):
            alternative.pop(field, None)
        alternatives.append(alternative)
    legacy["alternatives"] = alternatives
    return legacy


__all__ = [
    "TasteCreditAssignment",
    "TasteCreditDirection",
    "TasteEpisodeAlternative",
    "TasteEpisodeCandidate",
    "TasteEpisodeConfounder",
    "TasteEpisodeDecisionContext",
    "TasteEpisodeEvidence",
    "TasteEpisodeEvidenceRole",
    "TasteEpisodeFinding",
    "TasteEpisodeInspection",
    "TasteEpisodeMaturity",
    "TasteEpisodeOutcome",
    "TasteEpisodePartition",
    "TasteEpisodeProducerRole",
    "TasteEpisodeSourceRelationship",
    "TasteInterventionOperation",
    "TasteOutcomeFamily",
    "TasteOutcomePolarity",
    "TasteSupervisionChannel",
    "TasteSupervisionScope",
    "attach_outcome_attribution_to_human_intervention",
    "compile_human_taste_intervention_candidate",
    "compile_process_taste_episode_candidate",
    "inspect_taste_episode_candidate",
]

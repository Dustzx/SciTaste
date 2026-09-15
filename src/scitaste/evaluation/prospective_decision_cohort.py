"""Fail-closed trajectory ingress for prospective SciTasteBench decisions.

This layer does not infer decisions from review prose or manufacture outcomes.
It binds the existing prospective Taste trajectory artifacts into a cohort,
keeps self-development evidence separate from formal external evidence, and
publishes an outcome-hidden source pool plus a scoring-only label vault.

The H4 research-loop source kind is deliberately an adapter hook.  It can bind
the state and fixed-candidate action decision written before patch generation,
plus later iteration/result receipts, but it remains pending until a delayed
scientific outcome and attribution are joined through a dedicated contract.
Post-run scores are never treated as pre-decision alternatives.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.h4_execution import H4ResearchActionDecision
from scitaste.evaluation.task_research_loop import (
    BenchmarkResearchIteration,
    BenchmarkResearchLoopResult,
)
from scitaste.project.models import content_sha256, validate_project_id, validate_relative_locator
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import snapshot_id
from scitaste.state.research_state import ResearchState
from scitaste.taste.episode_learning import (
    AdmittedTasteEpisode,
    AITasteEpisodeAttributionReview,
)
from scitaste.taste.episodes import (
    TasteEpisodeCandidate,
    TasteEpisodeEvidenceRole,
    TasteEpisodeMaturity,
    TasteEpisodePartition,
    TasteEpisodeSourceRelationship,
    TasteSupervisionChannel,
)
from scitaste.taste.trajectory_reconstruction import (
    TasteProcessEpisodeProposal,
    TasteProspectiveDecisionCaptureReceipt,
    TasteProspectiveDecisionCompletionProjection,
    TasteProspectiveDecisionLockReceipt,
    TasteProspectiveOutcomeAttachmentReceipt,
    TasteTrajectoryAssignmentTiming,
    TasteTrajectoryInventory,
    TasteTrajectorySamplingPlan,
)

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 16 * 1_048_576
_MAX_EVIDENCE_BYTES = 64 * 1_048_576


class DecisionEpisodeSourceKind(StrEnum):
    PROSPECTIVE_TASTE_EPISODE = "prospective-taste-episode"
    H4_RESEARCH_LOOP = "h4-research-loop"


class DecisionEpisodeEvidenceTier(StrEnum):
    SELF_DOGFOOD = "self-dogfood"
    FORMAL_EXTERNAL = "formal-external"


class DecisionEpisodeTrackARole(StrEnum):
    DIAGNOSTIC = "diagnostic"
    PRECEDENT = "precedent"
    HELDOUT_TARGET = "heldout-target"


class DecisionEpisodeIngressStatus(StrEnum):
    ELIGIBLE = "eligible"
    PENDING = "pending"
    QUARANTINED = "quarantined"


class DecisionEpisodeFindingSeverity(StrEnum):
    PENDING = "pending"
    QUARANTINE = "quarantine"


class ProspectiveDecisionSourceSpec(BaseModel):
    """One declared run-owned source; locators are relative to evidence root."""

    model_config = _CONFIG

    source_id: str = Field(pattern=_ID)
    source_kind: DecisionEpisodeSourceKind = DecisionEpisodeSourceKind.PROSPECTIVE_TASTE_EPISODE
    evidence_tier: DecisionEpisodeEvidenceTier
    track_a_role: DecisionEpisodeTrackARole
    source_group_id: str = Field(pattern=_ID)
    dataset_partition: TasteEpisodePartition
    trajectory_root_locator: str
    sampling_plan_locator: str | None = None
    capture_receipt_locator: str | None = None
    trajectory_inventory_locator: str | None = None
    predecision_lock_locator: str | None = None
    outcome_attachment_locator: str | None = None
    completion_projection_locator: str | None = None
    process_episode_proposal_locator: str | None = None
    episode_candidate_locator: str | None = None
    admitted_episode_locator: str | None = None
    h4_state_locator: str | None = None
    h4_decision_locator: str | None = None
    h4_iteration_locator: str | None = None
    h4_loop_result_locator: str | None = None

    @model_validator(mode="after")
    def locators_are_safe_and_source_kind_is_explicit(self) -> ProspectiveDecisionSourceSpec:
        for locator in (
            self.trajectory_root_locator,
            self.sampling_plan_locator,
            self.capture_receipt_locator,
            self.trajectory_inventory_locator,
            self.predecision_lock_locator,
            self.outcome_attachment_locator,
            self.completion_projection_locator,
            self.process_episode_proposal_locator,
            self.episode_candidate_locator,
            self.admitted_episode_locator,
            self.h4_state_locator,
            self.h4_decision_locator,
            self.h4_iteration_locator,
            self.h4_loop_result_locator,
        ):
            if locator is not None:
                validate_relative_locator(locator, field_name="decision episode source locator")
        legacy_prospective = (
            self.sampling_plan_locator,
            self.capture_receipt_locator,
            self.trajectory_inventory_locator,
        )
        prospective_v2 = (
            self.sampling_plan_locator,
            self.predecision_lock_locator,
            self.outcome_attachment_locator,
            self.completion_projection_locator,
        )
        h4 = (self.h4_state_locator, self.h4_decision_locator)
        if self.source_kind is DecisionEpisodeSourceKind.PROSPECTIVE_TASTE_EPISODE:
            legacy_complete = all(item is not None for item in legacy_prospective)
            v2_complete = all(item is not None for item in prospective_v2)
            if legacy_complete == v2_complete:
                raise ValueError(
                    "prospective Taste ingress requires exactly one complete v1 or v2 chain"
                )
            if legacy_complete and any(item is not None for item in prospective_v2[1:]):
                raise ValueError("legacy prospective ingress cannot mix v2 artifacts")
            if v2_complete and any(
                item is not None
                for item in (self.capture_receipt_locator, self.trajectory_inventory_locator)
            ):
                raise ValueError("prospective v2 ingress cannot mix legacy artifacts")
            if any(item is not None for item in h4):
                raise ValueError("prospective Taste ingress cannot claim H4 foundation locators")
        else:
            if any(item is None for item in h4):
                raise ValueError("H4 ingress requires pre-patch state and action decision locators")
            if any(item is not None for item in (*legacy_prospective, *prospective_v2[1:])):
                raise ValueError("H4 ingress cannot claim a prospective Taste sampling chain")
            if any(
                item is not None
                for item in (
                    self.process_episode_proposal_locator,
                    self.episode_candidate_locator,
                    self.admitted_episode_locator,
                )
            ):
                raise ValueError("H4 attribution must use a future dedicated adapter contract")
        return self


class ProspectiveDecisionCohortPlan(BaseModel):
    """Frozen cohort membership and leakage policy; no source bytes are inferred."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.1"
    cohort_id: str = Field(pattern=_ID)
    project_id: str
    prepared_at: datetime
    sources: tuple[ProspectiveDecisionSourceSpec, ...] = Field(min_length=1, max_length=10_000)
    minimum_independent_ai_reviews: Literal[2] = 2
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_review_required: Literal[False] = False
    human_validity_claim_allowed: Literal[False] = False
    self_dogfood_external_validity_claim_allowed: Literal[False] = False
    source_group_split_disjoint_required: Literal[True] = True
    postdecision_alternative_backfill_allowed: Literal[False] = False
    model_calls_authorized: Literal[False] = False
    api_calls_authorized: Literal[False] = False
    gpu_work_authorized: Literal[False] = False
    experiment_authorized: Literal[False] = False
    plan_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def plan_is_closed(self) -> ProspectiveDecisionCohortPlan:
        validate_project_id(self.project_id)
        if self.prepared_at.utcoffset() is None:
            raise ValueError("cohort preparation time must include a timezone")
        source_ids = [item.source_id for item in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("cohort source IDs must be unique")
        if self.schema_version == "1.0" and any(
            source.predecision_lock_locator is not None for source in self.sources
        ):
            raise ValueError("prospective v2 sources require cohort schema 1.1")
        hash_payload = self.model_dump(mode="json", exclude={"plan_sha256"})
        if self.schema_version == "1.0":
            for source in hash_payload["sources"]:
                for field in (
                    "predecision_lock_locator",
                    "outcome_attachment_locator",
                    "completion_projection_locator",
                ):
                    source.pop(field, None)
        expected = content_sha256(hash_payload)
        if self.plan_sha256 != expected:
            raise ValueError("prospective decision cohort plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProspectiveDecisionCohortPlan:
        payload = {"schema_version": "1.1", **values}
        payload.pop("plan_sha256", None)
        source_values = payload.get("sources", ())
        if not isinstance(source_values, (list, tuple)):
            raise ValueError("prospective cohort sources must be a sequence")
        payload["sources"] = tuple(
            item
            if isinstance(item, ProspectiveDecisionSourceSpec)
            else ProspectiveDecisionSourceSpec.model_validate(item)
            for item in source_values
        )
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls(
            **payload,
            plan_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"plan_sha256"})),
        )


class DecisionEpisodeFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?$")
    severity: DecisionEpisodeFindingSeverity
    message: str = Field(min_length=1, max_length=2_000)


class DecisionEpisodeArtifactBinding(BaseModel):
    model_config = _CONFIG

    role: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?$")
    locator: str
    file_sha256: str = Field(pattern=_SHA256)
    semantic_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_safe(self) -> DecisionEpisodeArtifactBinding:
        validate_relative_locator(self.locator, field_name="decision episode artifact")
        return self


class DecisionEpisodeSourceAudit(BaseModel):
    model_config = _CONFIG

    source_id: str = Field(pattern=_ID)
    source_kind: DecisionEpisodeSourceKind
    evidence_tier: DecisionEpisodeEvidenceTier
    track_a_role: DecisionEpisodeTrackARole
    source_group_id: str = Field(pattern=_ID)
    dataset_partition: TasteEpisodePartition
    status: DecisionEpisodeIngressStatus
    findings: tuple[DecisionEpisodeFinding, ...]
    artifacts: tuple[DecisionEpisodeArtifactBinding, ...]
    predecision_candidate_set_verified: bool
    selected_action_binding_verified: bool
    delayed_scientific_outcome_bound: bool
    attribution_uncertainty_preserved: bool
    postdecision_alternative_backfill_used: Literal[False] = False
    ai_review_count: int = Field(ge=0, le=3)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    self_dogfood_only: bool
    formal_external_validity_eligible: bool
    source_audit_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def audit_is_closed(self) -> DecisionEpisodeSourceAudit:
        has_quarantine = any(
            item.severity is DecisionEpisodeFindingSeverity.QUARANTINE for item in self.findings
        )
        has_pending = any(
            item.severity is DecisionEpisodeFindingSeverity.PENDING for item in self.findings
        )
        expected_status = (
            DecisionEpisodeIngressStatus.QUARANTINED
            if has_quarantine
            else DecisionEpisodeIngressStatus.PENDING
            if has_pending
            else DecisionEpisodeIngressStatus.ELIGIBLE
        )
        if self.status is not expected_status:
            raise ValueError("decision episode status differs from its findings")
        if self.self_dogfood_only != (
            self.evidence_tier is DecisionEpisodeEvidenceTier.SELF_DOGFOOD
        ):
            raise ValueError("decision episode self-dogfood marker differs from its tier")
        expected_formal = (
            self.status is DecisionEpisodeIngressStatus.ELIGIBLE
            and self.evidence_tier is DecisionEpisodeEvidenceTier.FORMAL_EXTERNAL
            and self.track_a_role is not DecisionEpisodeTrackARole.DIAGNOSTIC
        )
        if self.formal_external_validity_eligible != expected_formal:
            raise ValueError("formal external eligibility differs from the source evidence")
        if self.status is DecisionEpisodeIngressStatus.ELIGIBLE and not all(
            (
                self.predecision_candidate_set_verified,
                self.selected_action_binding_verified,
                self.delayed_scientific_outcome_bound,
                self.attribution_uncertainty_preserved,
                self.ai_review_count >= 2,
            )
        ):
            raise ValueError("eligible decision episode lacks a required integrity gate")
        expected = content_sha256(self.model_dump(mode="json", exclude={"source_audit_sha256"}))
        if self.source_audit_sha256 != expected:
            raise ValueError("decision episode source audit hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DecisionEpisodeSourceAudit:
        payload = dict(values)
        payload.pop("source_audit_sha256", None)
        unsigned = cls.model_construct(source_audit_sha256="0" * 64, **payload)
        return cls(
            **payload,
            source_audit_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"source_audit_sha256"})
            ),
        )


class DecisionEpisodeActionProjection(BaseModel):
    """Outcome-blind action projection; it intentionally has no selected field."""

    model_config = _CONFIG

    action_id: str
    action_type: str
    summary: str
    tags: tuple[str, ...]
    expected_value: dict[str, float]
    expected_cost: dict[str, float]
    action_sha256: str = Field(pattern=_SHA256)


class DecisionEpisodeTargetProjection(BaseModel):
    """Model-visible target material with choice and outcome labels removed."""

    model_config = _CONFIG

    decision_id: str
    decision_sha256: str = Field(pattern=_SHA256)
    stage: str
    state_summary: str
    actions: tuple[DecisionEpisodeActionProjection, ...] = Field(min_length=2, max_length=30)
    action_menu_sha256: str = Field(pattern=_SHA256)
    domain_tags: tuple[str, ...]
    venue_tags: tuple[str, ...]
    selected_action_exposed: Literal[False] = False
    outcome_exposed: Literal[False] = False
    attribution_exposed: Literal[False] = False
    projection_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def projection_is_closed(self) -> DecisionEpisodeTargetProjection:
        if self.action_menu_sha256 != content_sha256(
            tuple(item.model_dump(mode="json") for item in self.actions)
        ):
            raise ValueError("target action-menu hash differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"projection_sha256"}))
        if self.projection_sha256 != expected:
            raise ValueError("target projection hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DecisionEpisodeTargetProjection:
        payload = dict(values)
        payload.pop("projection_sha256", None)
        unsigned = cls.model_construct(projection_sha256="0" * 64, **payload)
        return cls(
            **payload,
            projection_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"projection_sha256"})
            ),
        )


class DecisionEpisodePrecedentProjection(BaseModel):
    """Taste precedent content; never emitted for a held-out target."""

    model_config = _CONFIG

    selected_action_id: str
    decision_principle: str
    why_preferred: str
    outcomes: tuple[dict[str, object], ...]
    credit_assignments: tuple[dict[str, object], ...]
    confounders: tuple[dict[str, object], ...]
    applicability_conditions: tuple[str, ...]
    failure_conditions: tuple[str, ...]
    counterfactual_probe: str
    missing_evidence_questions: tuple[str, ...]
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    projection_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def projection_is_closed(self) -> DecisionEpisodePrecedentProjection:
        expected = content_sha256(self.model_dump(mode="json", exclude={"projection_sha256"}))
        if self.projection_sha256 != expected:
            raise ValueError("precedent projection hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DecisionEpisodePrecedentProjection:
        payload = dict(values)
        payload.pop("projection_sha256", None)
        unsigned = cls.model_construct(projection_sha256="0" * 64, **payload)
        return cls(
            **payload,
            projection_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"projection_sha256"})
            ),
        )


class DecisionEpisodeSourcePoolEntry(BaseModel):
    model_config = _CONFIG

    source_id: str = Field(pattern=_ID)
    evidence_tier: DecisionEpisodeEvidenceTier
    track_a_role: DecisionEpisodeTrackARole
    source_group_id: str = Field(pattern=_ID)
    dataset_partition: TasteEpisodePartition
    candidate_sha256: str = Field(pattern=_SHA256)
    source_audit_sha256: str = Field(pattern=_SHA256)
    target_projection: DecisionEpisodeTargetProjection
    precedent_projection: DecisionEpisodePrecedentProjection | None = None
    label_record_sha256: str = Field(pattern=_SHA256)
    formal_external_validity_eligible: bool

    @model_validator(mode="after")
    def role_controls_label_visibility(self) -> DecisionEpisodeSourcePoolEntry:
        if (self.precedent_projection is None) != (
            self.track_a_role is DecisionEpisodeTrackARole.HELDOUT_TARGET
        ):
            raise ValueError("source-pool role differs from precedent label visibility")
        expected_formal = (
            self.evidence_tier is DecisionEpisodeEvidenceTier.FORMAL_EXTERNAL
            and self.track_a_role is not DecisionEpisodeTrackARole.DIAGNOSTIC
        )
        if self.formal_external_validity_eligible != expected_formal:
            raise ValueError("source-pool formal eligibility differs")
        return self


class DecisionEpisodeLabelRecord(BaseModel):
    """Scoring-only label; this record must never enter target model context."""

    model_config = _CONFIG

    source_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    candidate_sha256: str = Field(pattern=_SHA256)
    observed_selected_action_id: str
    ai_reviewed_preferred_action_id: str
    outcome_sha256: str = Field(pattern=_SHA256)
    attribution_sha256: str = Field(pattern=_SHA256)
    minimum_ai_attribution_confidence: float = Field(gt=0.0, le=1.0)
    never_model_visible: Literal[True] = True
    scoring_only: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    label_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def label_is_closed(self) -> DecisionEpisodeLabelRecord:
        expected = content_sha256(self.model_dump(mode="json", exclude={"label_sha256"}))
        if self.label_sha256 != expected:
            raise ValueError("decision episode label hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> DecisionEpisodeLabelRecord:
        payload = dict(values)
        payload.pop("label_sha256", None)
        unsigned = cls.model_construct(label_sha256="0" * 64, **payload)
        return cls(
            **payload,
            label_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"label_sha256"})),
        )


class ProspectiveDecisionSourcePool(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    cohort_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    entries: tuple[DecisionEpisodeSourcePoolEntry, ...]
    diagnostic_count: int = Field(ge=0)
    precedent_count: int = Field(ge=0)
    heldout_target_count: int = Field(ge=0)
    self_dogfood_count: int = Field(ge=0)
    formal_external_count: int = Field(ge=0)
    selected_action_exposed_to_heldout_target: Literal[False] = False
    outcome_exposed_to_heldout_target: Literal[False] = False
    source_group_role_disjoint: Literal[True] = True
    pool_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def pool_is_closed(self) -> ProspectiveDecisionSourcePool:
        counts = Counter(item.track_a_role for item in self.entries)
        if (
            self.diagnostic_count,
            self.precedent_count,
            self.heldout_target_count,
        ) != (
            counts[DecisionEpisodeTrackARole.DIAGNOSTIC],
            counts[DecisionEpisodeTrackARole.PRECEDENT],
            counts[DecisionEpisodeTrackARole.HELDOUT_TARGET],
        ):
            raise ValueError("source-pool role counts differ")
        if self.self_dogfood_count != sum(
            item.evidence_tier is DecisionEpisodeEvidenceTier.SELF_DOGFOOD for item in self.entries
        ):
            raise ValueError("source-pool dogfood count differs")
        if self.formal_external_count != sum(
            item.formal_external_validity_eligible for item in self.entries
        ):
            raise ValueError("source-pool formal count differs")
        _assert_group_disjoint(self.entries)
        expected = content_sha256(self.model_dump(mode="json", exclude={"pool_sha256"}))
        if self.pool_sha256 != expected:
            raise ValueError("prospective source-pool hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProspectiveDecisionSourcePool:
        payload = {"schema_version": "1.0", **values}
        payload.pop("pool_sha256", None)
        unsigned = cls.model_construct(pool_sha256="0" * 64, **payload)
        return cls(
            **payload,
            pool_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"pool_sha256"})),
        )


class ProspectiveDecisionLabelVault(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    cohort_id: str = Field(pattern=_ID)
    plan_sha256: str = Field(pattern=_SHA256)
    labels: tuple[DecisionEpisodeLabelRecord, ...]
    target_model_access_authorized: Literal[False] = False
    scoring_access_only: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    vault_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def vault_is_closed(self) -> ProspectiveDecisionLabelVault:
        if len({item.source_id for item in self.labels}) != len(self.labels):
            raise ValueError("decision label source IDs must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"vault_sha256"}))
        if self.vault_sha256 != expected:
            raise ValueError("decision label-vault hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProspectiveDecisionLabelVault:
        payload = {"schema_version": "1.0", **values}
        payload.pop("vault_sha256", None)
        unsigned = cls.model_construct(vault_sha256="0" * 64, **payload)
        return cls(
            **payload,
            vault_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"vault_sha256"})),
        )


class ProspectiveDecisionCohortManifest(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    cohort_id: str = Field(pattern=_ID)
    project_id: str
    materialized_at: datetime
    plan: DecisionEpisodeArtifactBinding
    plan_sha256: str = Field(pattern=_SHA256)
    source_pool: DecisionEpisodeArtifactBinding
    source_pool_sha256: str = Field(pattern=_SHA256)
    label_vault: DecisionEpisodeArtifactBinding
    label_vault_sha256: str = Field(pattern=_SHA256)
    source_count: int = Field(ge=1)
    eligible_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    quarantined_count: int = Field(ge=0)
    self_dogfood_eligible_count: int = Field(ge=0)
    formal_external_eligible_count: int = Field(ge=0)
    formal_precedent_count: int = Field(ge=0)
    formal_heldout_target_count: int = Field(ge=0)
    audits: tuple[DecisionEpisodeSourceAudit, ...]
    status: Literal["formal-track-a-ready", "blocked-formal-external-cohort-incomplete"]
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_review_required: Literal[False] = False
    human_validity_claim_allowed: Literal[False] = False
    self_dogfood_external_validity_claim_allowed: Literal[False] = False
    post_run_score_used_as_predecision_alternative: Literal[False] = False
    track_a_suite_authorized: Literal[False] = False
    model_calls_performed: Literal[False] = False
    api_calls_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def manifest_is_closed(self) -> ProspectiveDecisionCohortManifest:
        if self.materialized_at.utcoffset() is None:
            raise ValueError("cohort materialization time must include a timezone")
        counts = Counter(item.status for item in self.audits)
        if (
            self.source_count,
            self.eligible_count,
            self.pending_count,
            self.quarantined_count,
        ) != (
            len(self.audits),
            counts[DecisionEpisodeIngressStatus.ELIGIBLE],
            counts[DecisionEpisodeIngressStatus.PENDING],
            counts[DecisionEpisodeIngressStatus.QUARANTINED],
        ):
            raise ValueError("cohort manifest status counts differ")
        ready = self.formal_precedent_count > 0 and self.formal_heldout_target_count > 0
        expected_status = (
            "formal-track-a-ready" if ready else "blocked-formal-external-cohort-incomplete"
        )
        if self.status != expected_status:
            raise ValueError("cohort formal readiness status differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("prospective cohort manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProspectiveDecisionCohortManifest:
        payload = {"schema_version": "1.0", **values}
        payload.pop("manifest_sha256", None)
        unsigned = cls.model_construct(manifest_sha256="0" * 64, **payload)
        return cls(
            **payload,
            manifest_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"manifest_sha256"})
            ),
        )


class ProspectiveDecisionCohortInspection(BaseModel):
    model_config = _CONFIG

    directory: Path
    manifest_file_sha256: str = Field(pattern=_SHA256)
    manifest: ProspectiveDecisionCohortManifest
    plan: ProspectiveDecisionCohortPlan
    source_pool: ProspectiveDecisionSourcePool
    label_vault: ProspectiveDecisionLabelVault
    file_bindings_verified: Literal[True] = True
    cross_artifact_bindings_verified: Literal[True] = True
    source_group_leakage_absent: Literal[True] = True


def prepare_prospective_decision_cohort_plan(
    *,
    draft_path: str | Path,
    output_path: str | Path,
    prepared_at: datetime | None = None,
) -> ProspectiveDecisionCohortPlan:
    """Seal a YAML/JSON cohort draft without reading trajectory evidence."""

    draft = _bounded_file(Path(draft_path).resolve(strict=True), _MAX_CONTROL_BYTES)
    payload = yaml.safe_load(draft.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("prospective cohort draft must be an object")
    payload.pop("plan_sha256", None)
    payload["prepared_at"] = prepared_at or datetime.now(UTC)
    plan = ProspectiveDecisionCohortPlan.create(**payload)
    _write_new_json(output_path, plan.model_dump_json(indent=2) + "\n")
    return plan


def materialize_prospective_decision_cohort(
    *,
    plan_path: str | Path,
    evidence_root: str | Path,
    output_dir: str | Path,
    materialized_at: datetime | None = None,
) -> ProspectiveDecisionCohortManifest:
    """Verify real trajectory bytes and atomically publish a no-call cohort."""

    root = _canonical_directory(evidence_root)
    plan_file = _within_root(root, plan_path, must_exist=True)
    plan = ProspectiveDecisionCohortPlan.model_validate_json(
        _bounded_file(plan_file, _MAX_CONTROL_BYTES).read_bytes()
    )
    audited = [_audit_source(root, plan, source) for source in plan.sources]
    audits, projections, labels = _apply_group_leakage_gate(audited)
    pool = ProspectiveDecisionSourcePool.create(
        cohort_id=plan.cohort_id,
        plan_sha256=plan.plan_sha256,
        entries=tuple(projections),
        diagnostic_count=sum(
            item.track_a_role is DecisionEpisodeTrackARole.DIAGNOSTIC for item in projections
        ),
        precedent_count=sum(
            item.track_a_role is DecisionEpisodeTrackARole.PRECEDENT for item in projections
        ),
        heldout_target_count=sum(
            item.track_a_role is DecisionEpisodeTrackARole.HELDOUT_TARGET for item in projections
        ),
        self_dogfood_count=sum(
            item.evidence_tier is DecisionEpisodeEvidenceTier.SELF_DOGFOOD for item in projections
        ),
        formal_external_count=sum(item.formal_external_validity_eligible for item in projections),
    )
    vault = ProspectiveDecisionLabelVault.create(
        cohort_id=plan.cohort_id,
        plan_sha256=plan.plan_sha256,
        labels=tuple(labels),
    )
    target = _new_output_directory(output_dir)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        pool_path = temporary / "SOURCE_POOL.json"
        vault_path = temporary / "LABEL_VAULT.json"
        pool_path.write_text(pool.model_dump_json(indent=2) + "\n", encoding="utf-8")
        vault_path.write_text(vault.model_dump_json(indent=2) + "\n", encoding="utf-8")
        counts = Counter(item.status for item in audits)
        formal_precedents = sum(
            item.formal_external_validity_eligible
            and item.track_a_role is DecisionEpisodeTrackARole.PRECEDENT
            for item in projections
        )
        formal_targets = sum(
            item.formal_external_validity_eligible
            and item.track_a_role is DecisionEpisodeTrackARole.HELDOUT_TARGET
            for item in projections
        )
        manifest = ProspectiveDecisionCohortManifest.create(
            cohort_id=plan.cohort_id,
            project_id=plan.project_id,
            materialized_at=materialized_at or datetime.now(UTC),
            plan=DecisionEpisodeArtifactBinding(
                role="cohort-plan",
                locator=_relative(plan_file, root),
                file_sha256=_sha256_file(plan_file),
                semantic_sha256=plan.plan_sha256,
            ),
            plan_sha256=plan.plan_sha256,
            source_pool=DecisionEpisodeArtifactBinding(
                role="source-pool",
                locator="SOURCE_POOL.json",
                file_sha256=_sha256_file(pool_path),
                semantic_sha256=pool.pool_sha256,
            ),
            source_pool_sha256=pool.pool_sha256,
            label_vault=DecisionEpisodeArtifactBinding(
                role="label-vault",
                locator="LABEL_VAULT.json",
                file_sha256=_sha256_file(vault_path),
                semantic_sha256=vault.vault_sha256,
            ),
            label_vault_sha256=vault.vault_sha256,
            source_count=len(audits),
            eligible_count=counts[DecisionEpisodeIngressStatus.ELIGIBLE],
            pending_count=counts[DecisionEpisodeIngressStatus.PENDING],
            quarantined_count=counts[DecisionEpisodeIngressStatus.QUARANTINED],
            self_dogfood_eligible_count=sum(
                item.status is DecisionEpisodeIngressStatus.ELIGIBLE and item.self_dogfood_only
                for item in audits
            ),
            formal_external_eligible_count=sum(
                item.formal_external_validity_eligible for item in audits
            ),
            formal_precedent_count=formal_precedents,
            formal_heldout_target_count=formal_targets,
            audits=tuple(audits),
            status=(
                "formal-track-a-ready"
                if formal_precedents and formal_targets
                else "blocked-formal-external-cohort-incomplete"
            ),
        )
        (temporary / "MANIFEST.json").write_text(
            manifest.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    except Exception:
        for child in temporary.iterdir():
            child.unlink(missing_ok=True)
        temporary.rmdir()
        raise
    return manifest


def inspect_prospective_decision_cohort(
    directory: str | Path,
    *,
    evidence_root: str | Path,
) -> ProspectiveDecisionCohortInspection:
    """Replay hashes, cross-file identities, and source-group isolation."""

    root = _canonical_directory(evidence_root)
    bundle = _canonical_directory(directory)
    manifest_path = _bounded_file(bundle / "MANIFEST.json", _MAX_CONTROL_BYTES)
    manifest = ProspectiveDecisionCohortManifest.model_validate_json(manifest_path.read_bytes())
    pool_path = _verify_binding(bundle, manifest.source_pool)
    vault_path = _verify_binding(bundle, manifest.label_vault)
    plan_path = _verify_binding(root, manifest.plan)
    plan = ProspectiveDecisionCohortPlan.model_validate_json(plan_path.read_bytes())
    pool = ProspectiveDecisionSourcePool.model_validate_json(pool_path.read_bytes())
    vault = ProspectiveDecisionLabelVault.model_validate_json(vault_path.read_bytes())
    if (
        plan.plan_sha256 != manifest.plan_sha256
        or pool.plan_sha256 != plan.plan_sha256
        or vault.plan_sha256 != plan.plan_sha256
        or pool.pool_sha256 != manifest.source_pool_sha256
        or vault.vault_sha256 != manifest.label_vault_sha256
        or pool.cohort_id != plan.cohort_id
        or vault.cohort_id != plan.cohort_id
        or manifest.cohort_id != plan.cohort_id
    ):
        raise ValueError("prospective cohort cross-artifact identity mismatch")
    labels = {item.source_id: item.label_sha256 for item in vault.labels}
    if any(labels.get(item.source_id) != item.label_record_sha256 for item in pool.entries):
        raise ValueError("prospective cohort source pool differs from label vault")
    return ProspectiveDecisionCohortInspection(
        directory=bundle,
        manifest_file_sha256=_sha256_file(manifest_path),
        manifest=manifest,
        plan=plan,
        source_pool=pool,
        label_vault=vault,
    )


def _audit_source(
    root: Path,
    cohort: ProspectiveDecisionCohortPlan,
    spec: ProspectiveDecisionSourceSpec,
) -> tuple[
    DecisionEpisodeSourceAudit,
    DecisionEpisodeSourcePoolEntry | None,
    DecisionEpisodeLabelRecord | None,
]:
    if spec.source_kind is DecisionEpisodeSourceKind.H4_RESEARCH_LOOP:
        return _audit_h4_source(root, spec)
    return _audit_prospective_source(root, cohort, spec)


def _audit_h4_source(
    root: Path,
    spec: ProspectiveDecisionSourceSpec,
) -> tuple[
    DecisionEpisodeSourceAudit,
    DecisionEpisodeSourcePoolEntry | None,
    DecisionEpisodeLabelRecord | None,
]:
    artifacts: list[DecisionEpisodeArtifactBinding] = []
    findings: list[DecisionEpisodeFinding] = []
    candidate_set_verified = False
    selected_verified = False
    try:
        trajectory_root = _within_root(root, spec.trajectory_root_locator, must_exist=True)
        state_path = _source_owned_file(
            trajectory_root,
            spec.h4_state_locator or "",
            _MAX_EVIDENCE_BYTES,
        )
        decision_path = _source_owned_file(
            trajectory_root,
            spec.h4_decision_locator or "",
            _MAX_EVIDENCE_BYTES,
        )
        state = ResearchState.model_validate_json(state_path.read_bytes())
        action_decision = H4ResearchActionDecision.model_validate_json(decision_path.read_bytes())
        if action_decision.decision.state_snapshot_id != snapshot_id(state):
            raise ValueError("H4 decision does not bind the pre-patch research state")
        if len(action_decision.decision.candidate_actions) < 2:
            raise ValueError("H4 decision has fewer than two pre-patch alternatives")
        candidate_set_verified = True
        selected_verified = action_decision.decision.selected_action.action_id in {
            item.action_id for item in action_decision.decision.candidate_actions
        }
        artifacts.extend(
            (
                _artifact("h4-predecision-state", state_path, root, snapshot_id(state)[6:]),
                _artifact(
                    "h4-prepatch-action-decision",
                    decision_path,
                    root,
                    action_decision.decision_sha256,
                ),
            )
        )
        if spec.h4_iteration_locator is not None:
            iteration_path = _source_owned_file(
                trajectory_root,
                spec.h4_iteration_locator,
                _MAX_EVIDENCE_BYTES,
            )
            iteration = BenchmarkResearchIteration.model_validate_json(iteration_path.read_bytes())
            if iteration.research_action_decision_sha256 != action_decision.decision_sha256:
                raise ValueError("H4 iteration binds another research action decision")
            artifacts.append(
                _artifact(
                    "h4-postdecision-iteration",
                    iteration_path,
                    root,
                    iteration.iteration_receipt_sha256,
                )
            )
        if spec.h4_loop_result_locator is not None:
            result_path = _source_owned_file(
                trajectory_root,
                spec.h4_loop_result_locator,
                _MAX_EVIDENCE_BYTES,
            )
            result = BenchmarkResearchLoopResult.model_validate_json(result_path.read_bytes())
            if action_decision.decision_sha256 not in {
                item.research_action_decision_sha256 for item in result.iterations
            }:
                raise ValueError("H4 loop result does not contain the action decision")
            artifacts.append(_artifact("h4-loop-result", result_path, root, result.result_sha256))
        findings.extend(
            (
                DecisionEpisodeFinding(
                    code="h4-delayed-scientific-outcome-pending",
                    severity=DecisionEpisodeFindingSeverity.PENDING,
                    message=(
                        "H4 development scores are bound only as post-run receipts; a delayed "
                        "scientific outcome has not been joined."
                    ),
                ),
                DecisionEpisodeFinding(
                    code="h4-outcome-attribution-adapter-pending",
                    severity=DecisionEpisodeFindingSeverity.PENDING,
                    message=(
                        "A dedicated H4 outcome-attribution adapter must preserve confounders "
                        "before this source can enter SciTasteBench."
                    ),
                ),
                DecisionEpisodeFinding(
                    code="h4-ai-attribution-review-pending",
                    severity=DecisionEpisodeFindingSeverity.PENDING,
                    message="Two independent AI attribution reviews remain required.",
                ),
            )
        )
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        findings.append(
            DecisionEpisodeFinding(
                code="h4-foundation-quarantined",
                severity=DecisionEpisodeFindingSeverity.QUARANTINE,
                message=str(exc),
            )
        )
    audit = DecisionEpisodeSourceAudit.create(
        source_id=spec.source_id,
        source_kind=spec.source_kind,
        evidence_tier=spec.evidence_tier,
        track_a_role=spec.track_a_role,
        source_group_id=spec.source_group_id,
        dataset_partition=spec.dataset_partition,
        status=_status(findings),
        findings=tuple(findings),
        artifacts=tuple(artifacts),
        predecision_candidate_set_verified=candidate_set_verified,
        selected_action_binding_verified=selected_verified,
        delayed_scientific_outcome_bound=False,
        attribution_uncertainty_preserved=False,
        ai_review_count=0,
        self_dogfood_only=(spec.evidence_tier is DecisionEpisodeEvidenceTier.SELF_DOGFOOD),
        formal_external_validity_eligible=False,
    )
    return audit, None, None


def _audit_prospective_source(
    root: Path,
    cohort: ProspectiveDecisionCohortPlan,
    spec: ProspectiveDecisionSourceSpec,
) -> tuple[
    DecisionEpisodeSourceAudit,
    DecisionEpisodeSourcePoolEntry | None,
    DecisionEpisodeLabelRecord | None,
]:
    if spec.predecision_lock_locator is not None:
        return _audit_prospective_source_v2(root, cohort, spec)
    artifacts: list[DecisionEpisodeArtifactBinding] = []
    findings: list[DecisionEpisodeFinding] = [
        DecisionEpisodeFinding(
            code="legacy-temporal-unverified",
            severity=DecisionEpisodeFindingSeverity.PENDING,
            message=(
                "The legacy one-phase capture includes an outcome in the decision line, so "
                "its pre-execution action menu cannot receive prospective eligibility."
            ),
        )
    ]
    candidate_set_verified = False
    selected_verified = False
    outcome_bound = False
    uncertainty_preserved = False
    ai_review_count = 0
    projection: DecisionEpisodeSourcePoolEntry | None = None
    label: DecisionEpisodeLabelRecord | None = None
    try:
        trajectory_root = _within_root(root, spec.trajectory_root_locator, must_exist=True)
        plan_path = _source_artifact(root, spec.sampling_plan_locator)
        capture_path = _source_artifact(root, spec.capture_receipt_locator)
        inventory_path = _source_artifact(root, spec.trajectory_inventory_locator)
        plan = TasteTrajectorySamplingPlan.model_validate_json(plan_path.read_bytes())
        capture = TasteProspectiveDecisionCaptureReceipt.model_validate_json(
            capture_path.read_bytes()
        )
        inventory = TasteTrajectoryInventory.model_validate_json(inventory_path.read_bytes())
        artifacts.extend(
            (
                _artifact("sampling-plan", plan_path, root, plan.plan_sha256),
                _artifact("capture-receipt", capture_path, root, capture.capture_sha256),
                _artifact("trajectory-inventory", inventory_path, root, inventory.inventory_sha256),
            )
        )
        _verify_foundation(cohort, spec, plan, capture, inventory)
        decision = _load_captured_decision(trajectory_root, plan, capture)
        candidate_set_verified = len(decision.candidate_actions) >= 2
        selected_verified = decision.selected_action.action_id in {
            item.action_id for item in decision.candidate_actions
        }

        if spec.process_episode_proposal_locator is None:
            findings.append(
                DecisionEpisodeFinding(
                    code="delayed-scientific-outcome-pending",
                    severity=DecisionEpisodeFindingSeverity.PENDING,
                    message=(
                        "The prospective foundation is valid, but no delayed outcome "
                        "proposal exists."
                    ),
                )
            )
            raise _ExpectedIncomplete
        proposal_path = _source_artifact(root, spec.process_episode_proposal_locator)
        proposal = TasteProcessEpisodeProposal.model_validate_json(proposal_path.read_bytes())
        artifacts.append(
            _artifact("outcome-proposal", proposal_path, root, proposal.proposal_sha256)
        )
        if spec.episode_candidate_locator is None:
            findings.append(
                DecisionEpisodeFinding(
                    code="compiled-episode-missing",
                    severity=DecisionEpisodeFindingSeverity.QUARANTINE,
                    message="An outcome proposal exists without its compiled prospective episode.",
                )
            )
            raise _ExpectedIncomplete
        candidate_path = _source_artifact(root, spec.episode_candidate_locator)
        candidate = TasteEpisodeCandidate.model_validate_json(candidate_path.read_bytes())
        artifacts.append(
            _artifact("episode-candidate", candidate_path, root, candidate.candidate_sha256)
        )
        _verify_candidate(
            trajectory_root,
            plan,
            capture,
            inventory,
            proposal,
            candidate,
            decision,
        )
        outcome_bound = True
        uncertainty_preserved = _uncertainty_is_explicit(candidate)
        if not uncertainty_preserved:
            findings.append(
                DecisionEpisodeFinding(
                    code="outcome-attribution-uncertainty-unbound",
                    severity=DecisionEpisodeFindingSeverity.QUARANTINE,
                    message=(
                        "Attribution must preserve at least one confidence, confounder, "
                        "unresolved/mixed outcome, or missing-evidence signal."
                    ),
                )
            )
            raise _ExpectedIncomplete
        if spec.admitted_episode_locator is None:
            findings.append(
                DecisionEpisodeFinding(
                    code="independent-ai-review-pending",
                    severity=DecisionEpisodeFindingSeverity.PENDING,
                    message="The attributed episode still needs two independent AI reviews.",
                )
            )
            raise _ExpectedIncomplete
        admission_path = _source_artifact(root, spec.admitted_episode_locator)
        admission = AdmittedTasteEpisode.model_validate_json(admission_path.read_bytes())
        artifacts.append(
            _artifact("ai-reviewed-admission", admission_path, root, admission.admission_sha256)
        )
        ai_review_count = _verify_ai_admission(trajectory_root, candidate, admission)
        projection, label = _build_projection(spec, decision, candidate, admission)
    except _ExpectedIncomplete:
        pass
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        findings.append(
            DecisionEpisodeFinding(
                code="trajectory-artifact-binding-quarantined",
                severity=DecisionEpisodeFindingSeverity.QUARANTINE,
                message=str(exc),
            )
        )
        projection = None
        label = None

    status = _status(findings)
    formal = (
        status is DecisionEpisodeIngressStatus.ELIGIBLE
        and spec.evidence_tier is DecisionEpisodeEvidenceTier.FORMAL_EXTERNAL
        and spec.track_a_role is not DecisionEpisodeTrackARole.DIAGNOSTIC
    )
    audit = DecisionEpisodeSourceAudit.create(
        source_id=spec.source_id,
        source_kind=spec.source_kind,
        evidence_tier=spec.evidence_tier,
        track_a_role=spec.track_a_role,
        source_group_id=spec.source_group_id,
        dataset_partition=spec.dataset_partition,
        status=status,
        findings=tuple(findings),
        artifacts=tuple(artifacts),
        predecision_candidate_set_verified=candidate_set_verified,
        selected_action_binding_verified=selected_verified,
        delayed_scientific_outcome_bound=outcome_bound,
        attribution_uncertainty_preserved=uncertainty_preserved,
        ai_review_count=ai_review_count,
        self_dogfood_only=(spec.evidence_tier is DecisionEpisodeEvidenceTier.SELF_DOGFOOD),
        formal_external_validity_eligible=formal,
    )
    if projection is not None:
        projection = projection.model_copy(
            update={"source_audit_sha256": audit.source_audit_sha256}
        )
    return (
        audit,
        projection if status is DecisionEpisodeIngressStatus.ELIGIBLE else None,
        label if status is DecisionEpisodeIngressStatus.ELIGIBLE else None,
    )


def _audit_prospective_source_v2(
    root: Path,
    cohort: ProspectiveDecisionCohortPlan,
    spec: ProspectiveDecisionSourceSpec,
) -> tuple[
    DecisionEpisodeSourceAudit,
    DecisionEpisodeSourcePoolEntry | None,
    DecisionEpisodeLabelRecord | None,
]:
    artifacts: list[DecisionEpisodeArtifactBinding] = []
    findings: list[DecisionEpisodeFinding] = []
    candidate_set_verified = False
    selected_verified = False
    outcome_bound = False
    uncertainty_preserved = False
    ai_review_count = 0
    target_projection: DecisionEpisodeSourcePoolEntry | None = None
    label: DecisionEpisodeLabelRecord | None = None
    try:
        trajectory_root = _within_root(root, spec.trajectory_root_locator, must_exist=True)
        plan_path = _source_artifact(root, spec.sampling_plan_locator)
        lock_path = _source_artifact(root, spec.predecision_lock_locator)
        attachment_path = _source_artifact(root, spec.outcome_attachment_locator)
        completion_path = _source_artifact(root, spec.completion_projection_locator)
        plan = TasteTrajectorySamplingPlan.model_validate_json(plan_path.read_bytes())
        lock = TasteProspectiveDecisionLockReceipt.model_validate_json(lock_path.read_bytes())
        attachment = TasteProspectiveOutcomeAttachmentReceipt.model_validate_json(
            attachment_path.read_bytes()
        )
        completion = TasteProspectiveDecisionCompletionProjection.model_validate_json(
            completion_path.read_bytes()
        )
        artifacts.extend(
            (
                _artifact("sampling-plan", plan_path, root, plan.plan_sha256),
                _artifact("predecision-lock", lock_path, root, lock.lock_sha256),
                _artifact(
                    "outcome-attachment",
                    attachment_path,
                    root,
                    attachment.attachment_sha256,
                ),
                _artifact(
                    "completion-projection",
                    completion_path,
                    root,
                    completion.projection_sha256,
                ),
            )
        )
        decision = _verify_foundation_v2(
            root=trajectory_root,
            cohort=cohort,
            spec=spec,
            plan=plan,
            lock=lock,
            attachment=attachment,
            completion=completion,
        )
        candidate_set_verified = True
        selected_verified = True
        outcome_bound = True

        if spec.process_episode_proposal_locator is None:
            findings.append(
                DecisionEpisodeFinding(
                    code="delayed-scientific-attribution-pending",
                    severity=DecisionEpisodeFindingSeverity.PENDING,
                    message="The v2 outcome is attached, but attribution has not been proposed.",
                )
            )
            raise _ExpectedIncomplete
        proposal_path = _source_artifact(root, spec.process_episode_proposal_locator)
        proposal = TasteProcessEpisodeProposal.model_validate_json(proposal_path.read_bytes())
        artifacts.append(
            _artifact("outcome-proposal", proposal_path, root, proposal.proposal_sha256)
        )
        if spec.episode_candidate_locator is None:
            findings.append(
                DecisionEpisodeFinding(
                    code="compiled-episode-missing",
                    severity=DecisionEpisodeFindingSeverity.QUARANTINE,
                    message="A v2 outcome proposal exists without its compiled episode.",
                )
            )
            raise _ExpectedIncomplete
        candidate_path = _source_artifact(root, spec.episode_candidate_locator)
        candidate = TasteEpisodeCandidate.model_validate_json(candidate_path.read_bytes())
        artifacts.append(
            _artifact("episode-candidate", candidate_path, root, candidate.candidate_sha256)
        )
        _verify_candidate_v2(
            trajectory_root,
            plan,
            lock,
            attachment,
            completion,
            proposal,
            candidate,
            decision,
        )
        uncertainty_preserved = _uncertainty_is_explicit(candidate)
        if not uncertainty_preserved:
            findings.append(
                DecisionEpisodeFinding(
                    code="outcome-attribution-uncertainty-unbound",
                    severity=DecisionEpisodeFindingSeverity.QUARANTINE,
                    message="The v2 attribution lacks an explicit uncertainty signal.",
                )
            )
            raise _ExpectedIncomplete
        if spec.admitted_episode_locator is None:
            findings.append(
                DecisionEpisodeFinding(
                    code="independent-ai-review-pending",
                    severity=DecisionEpisodeFindingSeverity.PENDING,
                    message="The attributed episode still needs two independent AI reviews.",
                )
            )
            raise _ExpectedIncomplete
        admission_path = _source_artifact(root, spec.admitted_episode_locator)
        admission = AdmittedTasteEpisode.model_validate_json(admission_path.read_bytes())
        artifacts.append(
            _artifact("ai-reviewed-admission", admission_path, root, admission.admission_sha256)
        )
        ai_review_count = _verify_ai_admission(trajectory_root, candidate, admission)
        target_projection, label = _build_projection(spec, decision, candidate, admission)
    except _ExpectedIncomplete:
        pass
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        findings.append(
            DecisionEpisodeFinding(
                code="trajectory-v2-binding-quarantined",
                severity=DecisionEpisodeFindingSeverity.QUARANTINE,
                message=str(exc),
            )
        )
        target_projection = None
        label = None

    status = _status(findings)
    formal = (
        status is DecisionEpisodeIngressStatus.ELIGIBLE
        and spec.evidence_tier is DecisionEpisodeEvidenceTier.FORMAL_EXTERNAL
        and spec.track_a_role is not DecisionEpisodeTrackARole.DIAGNOSTIC
    )
    audit = DecisionEpisodeSourceAudit.create(
        source_id=spec.source_id,
        source_kind=spec.source_kind,
        evidence_tier=spec.evidence_tier,
        track_a_role=spec.track_a_role,
        source_group_id=spec.source_group_id,
        dataset_partition=spec.dataset_partition,
        status=status,
        findings=tuple(findings),
        artifacts=tuple(artifacts),
        predecision_candidate_set_verified=candidate_set_verified,
        selected_action_binding_verified=selected_verified,
        delayed_scientific_outcome_bound=outcome_bound,
        attribution_uncertainty_preserved=uncertainty_preserved,
        ai_review_count=ai_review_count,
        self_dogfood_only=(spec.evidence_tier is DecisionEpisodeEvidenceTier.SELF_DOGFOOD),
        formal_external_validity_eligible=formal,
    )
    if target_projection is not None:
        target_projection = target_projection.model_copy(
            update={"source_audit_sha256": audit.source_audit_sha256}
        )
    return (
        audit,
        target_projection if status is DecisionEpisodeIngressStatus.ELIGIBLE else None,
        label if status is DecisionEpisodeIngressStatus.ELIGIBLE else None,
    )


def _verify_foundation(
    cohort: ProspectiveDecisionCohortPlan,
    spec: ProspectiveDecisionSourceSpec,
    plan: TasteTrajectorySamplingPlan,
    capture: TasteProspectiveDecisionCaptureReceipt,
    inventory: TasteTrajectoryInventory,
) -> None:
    if plan.assignment_timing is not TasteTrajectoryAssignmentTiming.PROSPECTIVE:
        raise ValueError("cohort accepts only genuinely prospective sampling plans")
    if not plan.source_absent_when_frozen:
        raise ValueError("prospective source existed before its sampling freeze")
    if plan.project_id != cohort.project_id:
        raise ValueError("trajectory sampling plan belongs to another evaluation project")
    if (
        plan.source_group_id != spec.source_group_id
        or plan.dataset_partition is not spec.dataset_partition
    ):
        raise ValueError("declared source group or split differs from the frozen plan")
    if (
        capture.plan_id != plan.plan_id
        or capture.plan_sha256 != plan.plan_sha256
        or inventory.plan_id != plan.plan_id
        or inventory.plan_sha256 != plan.plan_sha256
    ):
        raise ValueError("prospective foundation artifacts bind different plans")
    if capture.source_project_id != plan.source_project_id:
        raise ValueError("capture source project differs from the sampling plan")
    expected_relationship = {
        DecisionEpisodeEvidenceTier.SELF_DOGFOOD: TasteEpisodeSourceRelationship.SELF_PROJECT,
        DecisionEpisodeEvidenceTier.FORMAL_EXTERNAL: (
            TasteEpisodeSourceRelationship.INDEPENDENT_PROJECT
        ),
    }[spec.evidence_tier]
    if plan.source_relationship is not expected_relationship:
        raise ValueError("evidence tier differs from the frozen source relationship")
    if spec.evidence_tier is DecisionEpisodeEvidenceTier.SELF_DOGFOOD:
        if (
            plan.source_project_id != cohort.project_id
            or spec.dataset_partition is not TasteEpisodePartition.DEVELOPMENT
            or spec.track_a_role is not DecisionEpisodeTrackARole.DIAGNOSTIC
        ):
            raise ValueError("self-dogfood sources are development diagnostics only")
    else:
        if plan.source_project_id == cohort.project_id:
            raise ValueError("formal external evidence cannot use the evaluation project")
        allowed = {
            DecisionEpisodeTrackARole.PRECEDENT: {
                TasteEpisodePartition.DEVELOPMENT,
                TasteEpisodePartition.CALIBRATION,
            },
            DecisionEpisodeTrackARole.HELDOUT_TARGET: {
                TasteEpisodePartition.FORMAL_HELDOUT,
            },
            DecisionEpisodeTrackARole.DIAGNOSTIC: {TasteEpisodePartition.PILOT},
        }[spec.track_a_role]
        if spec.dataset_partition not in allowed:
            raise ValueError("formal external split is incompatible with its Track-A role")
    seeds = [item for item in inventory.decisions if item.decision_id == capture.decision_id]
    if len(seeds) != 1 or not seeds[0].foundation_eligible:
        raise ValueError("capture lacks one eligible reconstructed decision foundation")
    seed = seeds[0]
    if (
        seed.line_number != capture.decision_line_number
        or seed.line_sha256 != capture.decision_line_sha256
        or seed.decision_sha256 != capture.decision_sha256
        or seed.state_snapshot_id != capture.state_snapshot_id
        or seed.executor_result_id != capture.executor_result_id
        or seed.executor_outcome_sha256 != capture.executor_outcome_sha256
    ):
        raise ValueError("capture differs from the reconstruction inventory")


def _verify_foundation_v2(
    *,
    root: Path,
    cohort: ProspectiveDecisionCohortPlan,
    spec: ProspectiveDecisionSourceSpec,
    plan: TasteTrajectorySamplingPlan,
    lock: TasteProspectiveDecisionLockReceipt,
    attachment: TasteProspectiveOutcomeAttachmentReceipt,
    completion: TasteProspectiveDecisionCompletionProjection,
) -> ResearchDecision:
    if plan.assignment_timing is not TasteTrajectoryAssignmentTiming.PROSPECTIVE:
        raise ValueError("cohort accepts only genuinely prospective sampling plans")
    if not plan.source_absent_when_frozen:
        raise ValueError("prospective source existed before its sampling freeze")
    if plan.project_id != cohort.project_id:
        raise ValueError("trajectory sampling plan belongs to another evaluation project")
    if (
        plan.source_group_id != spec.source_group_id
        or plan.dataset_partition is not spec.dataset_partition
    ):
        raise ValueError("declared source group or split differs from the frozen plan")
    expected_relationship = {
        DecisionEpisodeEvidenceTier.SELF_DOGFOOD: TasteEpisodeSourceRelationship.SELF_PROJECT,
        DecisionEpisodeEvidenceTier.FORMAL_EXTERNAL: (
            TasteEpisodeSourceRelationship.INDEPENDENT_PROJECT
        ),
    }[spec.evidence_tier]
    if plan.source_relationship is not expected_relationship:
        raise ValueError("evidence tier differs from the frozen source relationship")
    if spec.evidence_tier is DecisionEpisodeEvidenceTier.SELF_DOGFOOD:
        if (
            plan.source_project_id != cohort.project_id
            or spec.dataset_partition is not TasteEpisodePartition.DEVELOPMENT
            or spec.track_a_role is not DecisionEpisodeTrackARole.DIAGNOSTIC
        ):
            raise ValueError("self-dogfood sources are development diagnostics only")
    else:
        if plan.source_project_id == cohort.project_id:
            raise ValueError("formal external evidence cannot use the evaluation project")
        allowed = {
            DecisionEpisodeTrackARole.PRECEDENT: {
                TasteEpisodePartition.DEVELOPMENT,
                TasteEpisodePartition.CALIBRATION,
            },
            DecisionEpisodeTrackARole.HELDOUT_TARGET: {TasteEpisodePartition.FORMAL_HELDOUT},
            DecisionEpisodeTrackARole.DIAGNOSTIC: {TasteEpisodePartition.PILOT},
        }[spec.track_a_role]
        if spec.dataset_partition not in allowed:
            raise ValueError("formal external split is incompatible with its Track-A role")
    if any(
        (
            lock.plan_id != plan.plan_id,
            lock.plan_sha256 != plan.plan_sha256,
            attachment.plan_id != plan.plan_id,
            attachment.plan_sha256 != plan.plan_sha256,
            completion.plan_id != plan.plan_id,
            completion.plan_sha256 != plan.plan_sha256,
        )
    ):
        raise ValueError("prospective v2 artifacts bind different plans")
    if lock.source_project_id != plan.source_project_id or lock.source_run_id != plan.source_run_id:
        raise ValueError("prospective v2 lock source differs from its plan")
    if lock.captured_at < plan.frozen_at or lock.decision_timestamp < plan.frozen_at:
        raise ValueError("prospective v2 decision predates the sampling freeze")
    if attachment.observed_at <= lock.captured_at or attachment.attached_at <= lock.captured_at:
        raise ValueError("prospective v2 outcome is not strictly later than its lock")
    if attachment.attached_at < attachment.observed_at:
        raise ValueError("prospective v2 attachment predates outcome observation")
    if (
        attachment.lock_sha256 != lock.lock_sha256
        or attachment.decision_id != lock.decision_id
        or attachment.predecision_sha256 != lock.decision_sha256
        or completion.lock_sha256 != lock.lock_sha256
        or completion.attachment_sha256 != attachment.attachment_sha256
        or completion.predecision_sha256 != lock.decision_sha256
    ):
        raise ValueError("prospective v2 temporal chain identity differs")
    if completion.projected_at < attachment.attached_at:
        raise ValueError("prospective completion projection predates outcome attachment")

    immutable_path = _source_owned_file(
        root,
        lock.immutable_decision_locator,
        _MAX_EVIDENCE_BYTES,
    )
    immutable_bytes = immutable_path.read_bytes()
    if _sha256_file(immutable_path) != lock.immutable_decision_file_sha256:
        raise ValueError("v2 immutable predecision bytes drifted")
    locked = ResearchDecision.model_validate_json(immutable_bytes)
    if locked.executor_result_id is not None or locked.actual_outcome is not None:
        raise ValueError("v2 immutable predecision contains an outcome")
    if (
        locked.decision_id != lock.decision_id
        or content_sha256(locked.model_dump(mode="json")) != lock.decision_sha256
        or locked.timestamp != lock.decision_timestamp
    ):
        raise ValueError("v2 immutable predecision identity drifted")
    if len(locked.candidate_actions) != lock.alternative_count:
        raise ValueError("v2 immutable action menu count drifted")
    action_ids = tuple(item.action_id for item in locked.candidate_actions)
    action_hashes = tuple(
        content_sha256(item.model_dump(mode="json")) for item in locked.candidate_actions
    )
    if (
        len(action_ids) < 2
        or len(set(action_ids)) != len(action_ids)
        or len(set(action_hashes)) != len(action_hashes)
        or content_sha256(tuple(item.model_dump(mode="json") for item in locked.candidate_actions))
        != lock.candidate_set_sha256
    ):
        raise ValueError("v2 immutable action menu is incomplete or drifted")
    if (
        locked.selected_action.action_id != lock.selected_action_id
        or content_sha256(locked.selected_action.model_dump(mode="json"))
        != lock.selected_action_sha256
        or content_sha256(locked.rationale) != lock.rationale_sha256
        or sum(item == locked.selected_action for item in locked.candidate_actions) != 1
    ):
        raise ValueError("v2 immutable selected action or rationale drifted")

    log_path = _source_owned_file(root, lock.decision_log_locator, _MAX_EVIDENCE_BYTES)
    lines = log_path.read_bytes().splitlines(keepends=True)
    if lock.decision_line_number > len(lines):
        raise ValueError("v2 locked decision line is missing")
    line = lines[lock.decision_line_number - 1]
    if hashlib.sha256(line).hexdigest() != lock.decision_line_sha256 or line != immutable_bytes:
        raise ValueError("v2 locked decision log line drifted")
    state_path = _source_owned_file(root, lock.state_snapshot_locator, _MAX_EVIDENCE_BYTES)
    if _sha256_file(state_path) != lock.state_file_sha256:
        raise ValueError("v2 locked state bytes drifted")
    state = ResearchState.model_validate_json(state_path.read_bytes())
    if (
        snapshot_id(state) != lock.state_snapshot_id
        or state.project_id != plan.source_project_id
        or locked.state_snapshot_id != lock.state_snapshot_id
        or locked.stage != state.current_stage.value
    ):
        raise ValueError("v2 locked state identity drifted")

    for item in attachment.evidence:
        path = _source_owned_file(root, item.locator, _MAX_EVIDENCE_BYTES)
        if _sha256_file(path) != item.sha256:
            raise ValueError(f"v2 outcome evidence bytes drifted: {item.evidence_id}")
    completed = completion.completed_decision
    restored = completed.model_copy(
        deep=True,
        update={"executor_result_id": None, "actual_outcome": None},
    )
    if restored != locked:
        raise ValueError("v2 completion projection changed predecision content")
    if (
        completed.executor_result_id != attachment.executor_result_id
        or completed.actual_outcome != attachment.actual_outcome
    ):
        raise ValueError("v2 completion projection differs from its attachment")
    return completed


def _load_captured_decision(
    trajectory_root: Path,
    plan: TasteTrajectorySamplingPlan,
    capture: TasteProspectiveDecisionCaptureReceipt,
) -> ResearchDecision:
    decision_path = _source_owned_file(
        trajectory_root,
        plan.decision_log_locator,
        _MAX_EVIDENCE_BYTES,
    )
    lines = decision_path.read_bytes().splitlines(keepends=True)
    if capture.decision_line_number > len(lines):
        raise ValueError("captured decision line is missing")
    raw = lines[capture.decision_line_number - 1]
    if hashlib.sha256(raw).hexdigest() != capture.decision_line_sha256:
        raise ValueError("captured decision line bytes drifted")
    decision = ResearchDecision.model_validate_json(raw)
    if content_sha256(decision.model_dump(mode="json")) != capture.decision_sha256:
        raise ValueError("captured decision semantic hash drifted")
    if decision.decision_id != capture.decision_id:
        raise ValueError("captured decision identity drifted")
    if capture.captured_at < decision.timestamp:
        raise ValueError("capture timestamp predates the recorded decision")
    return decision


def _verify_candidate(
    trajectory_root: Path,
    plan: TasteTrajectorySamplingPlan,
    capture: TasteProspectiveDecisionCaptureReceipt,
    inventory: TasteTrajectoryInventory,
    proposal: TasteProcessEpisodeProposal,
    candidate: TasteEpisodeCandidate,
    decision: ResearchDecision,
) -> None:
    if (
        proposal.plan_id != plan.plan_id
        or proposal.plan_sha256 != plan.plan_sha256
        or proposal.capture_sha256 != capture.capture_sha256
        or proposal.inventory_sha256 != inventory.inventory_sha256
        or proposal.decision_id != capture.decision_id
    ):
        raise ValueError("outcome proposal differs from the prospective foundation")
    if proposal.observed_at < capture.captured_at:
        raise ValueError("delayed outcome proposal predates the prospective capture")
    if (
        candidate.project_id != plan.project_id
        or candidate.source_project_id != plan.source_project_id
        or candidate.source_group_id != plan.source_group_id
        or candidate.dataset_partition is not plan.dataset_partition
        or candidate.source_relationship is not plan.source_relationship
        or candidate.idea_revision != plan.idea_revision
        or candidate.source_project_revision != capture.observed_project_revision
        or candidate.source_project_snapshot_sha256 != capture.observed_project_snapshot_sha256
        or candidate.decision_id != decision.decision_id
        or candidate.channel is not TasteSupervisionChannel.INTERNAL_OUTCOME
        or candidate.maturity is not TasteEpisodeMaturity.ATTRIBUTION_PROPOSED
    ):
        raise ValueError("compiled episode differs from its prospective source identity")
    expected_actions = tuple(
        {
            "action_id": item.action_id,
            "action_type": item.type.value,
            "summary": item.description,
            "tags": tuple(item.tags),
            "expected_value": dict(item.expected_value),
            "expected_cost": dict(item.expected_cost),
            "selected": item.action_id == decision.selected_action.action_id,
        }
        for item in decision.candidate_actions
    )
    observed_actions = tuple(item.model_dump(mode="python") for item in candidate.alternatives)
    if observed_actions != expected_actions:
        raise ValueError("episode alternatives were not copied from the predecision action set")
    if candidate.selected_action_id != decision.selected_action.action_id:
        raise ValueError("episode selected action differs from the recorded decision")
    proposal_fields = (
        "candidate_id",
        "producer_id",
        "state_summary",
        "decision_context",
        "decision_principle",
        "why_preferred",
        "outcomes",
        "credit_assignments",
        "applicability_conditions",
        "failure_conditions",
        "counterfactual_probe",
        "domain_tags",
        "venue_tags",
        "confounders",
        "missing_evidence_questions",
    )
    if any(getattr(proposal, field) != getattr(candidate, field) for field in proposal_fields):
        raise ValueError("compiled episode content differs from the sealed outcome proposal")
    expected_bindings = {(item.evidence_id, item.role, item.locator) for item in proposal.evidence}
    observed_bindings = {(item.evidence_id, item.role, item.locator) for item in candidate.evidence}
    if expected_bindings != observed_bindings:
        raise ValueError("compiled episode evidence differs from the outcome proposal")
    for evidence in candidate.evidence:
        path = _source_owned_file(trajectory_root, evidence.locator, _MAX_EVIDENCE_BYTES)
        if _sha256_file(path) != evidence.sha256:
            raise ValueError(f"episode evidence bytes drifted: {evidence.evidence_id}")
    outcome_locators = {item.locator for item in candidate.evidence if item.role.value == "outcome"}
    decision_locators = {
        item.locator
        for item in candidate.evidence
        if item.role.value in {"decision", "decision-state"}
    }
    if not outcome_locators or outcome_locators.intersection(decision_locators):
        raise ValueError("postdecision outcome evidence is missing or backfills decision material")


def _verify_candidate_v2(
    trajectory_root: Path,
    plan: TasteTrajectorySamplingPlan,
    lock: TasteProspectiveDecisionLockReceipt,
    attachment: TasteProspectiveOutcomeAttachmentReceipt,
    completion: TasteProspectiveDecisionCompletionProjection,
    proposal: TasteProcessEpisodeProposal,
    candidate: TasteEpisodeCandidate,
    decision: ResearchDecision,
) -> None:
    if (
        proposal.plan_id != plan.plan_id
        or proposal.plan_sha256 != plan.plan_sha256
        or proposal.capture_sha256 != attachment.attachment_sha256
        or proposal.inventory_sha256 != completion.projection_sha256
        or proposal.decision_id != lock.decision_id
    ):
        raise ValueError("v2 outcome proposal differs from the temporal foundation")
    if proposal.observed_at < attachment.observed_at:
        raise ValueError("v2 delayed attribution predates its outcome attachment")
    if (
        candidate.project_id != plan.project_id
        or candidate.source_project_id != plan.source_project_id
        or candidate.source_group_id != plan.source_group_id
        or candidate.dataset_partition is not plan.dataset_partition
        or candidate.source_relationship is not plan.source_relationship
        or candidate.idea_revision != plan.idea_revision
        or candidate.source_project_revision != lock.observed_project_revision
        or candidate.source_project_snapshot_sha256 != lock.observed_project_snapshot_sha256
        or candidate.decision_id != decision.decision_id
        or candidate.channel is not TasteSupervisionChannel.INTERNAL_OUTCOME
        or candidate.maturity is not TasteEpisodeMaturity.ATTRIBUTION_PROPOSED
    ):
        raise ValueError("compiled v2 episode differs from its prospective source identity")
    expected_actions = tuple(
        {
            "action_id": item.action_id,
            "action_type": item.type.value,
            "summary": item.description,
            "tags": tuple(item.tags),
            "expected_value": dict(item.expected_value),
            "expected_cost": dict(item.expected_cost),
            "selected": item.action_id == decision.selected_action.action_id,
        }
        for item in decision.candidate_actions
    )
    observed_actions = tuple(item.model_dump(mode="python") for item in candidate.alternatives)
    if observed_actions != expected_actions:
        raise ValueError("v2 episode alternatives differ from the locked action menu")
    if candidate.selected_action_id != lock.selected_action_id:
        raise ValueError("v2 episode selection differs from the predecision lock")
    proposal_fields = (
        "candidate_id",
        "producer_id",
        "state_summary",
        "decision_context",
        "decision_principle",
        "why_preferred",
        "outcomes",
        "credit_assignments",
        "applicability_conditions",
        "failure_conditions",
        "counterfactual_probe",
        "domain_tags",
        "venue_tags",
        "confounders",
        "missing_evidence_questions",
    )
    if any(getattr(proposal, field) != getattr(candidate, field) for field in proposal_fields):
        raise ValueError("compiled v2 episode content differs from its sealed proposal")
    expected_bindings = {(item.evidence_id, item.role, item.locator) for item in proposal.evidence}
    observed_bindings = {(item.evidence_id, item.role, item.locator) for item in candidate.evidence}
    if expected_bindings != observed_bindings:
        raise ValueError("compiled v2 episode evidence differs from its proposal")
    for evidence in candidate.evidence:
        path = _source_owned_file(trajectory_root, evidence.locator, _MAX_EVIDENCE_BYTES)
        if _sha256_file(path) != evidence.sha256:
            raise ValueError(f"v2 episode evidence bytes drifted: {evidence.evidence_id}")
    attachment_bindings = {
        (item.evidence_id, item.locator, item.sha256) for item in attachment.evidence
    }
    candidate_outcomes = {
        (item.evidence_id, item.locator, item.sha256)
        for item in candidate.evidence
        if item.role is TasteEpisodeEvidenceRole.OUTCOME
    }
    if not attachment_bindings.issubset(candidate_outcomes):
        raise ValueError("compiled v2 episode omits attached outcome evidence")
    outcome_locators = {item.locator for item in candidate.evidence if item.role.value == "outcome"}
    decision_locators = {
        item.locator
        for item in candidate.evidence
        if item.role.value in {"decision", "decision-state"}
    }
    if not outcome_locators or outcome_locators.intersection(decision_locators):
        raise ValueError("v2 outcome evidence is missing or backfills predecision material")


def _verify_ai_admission(
    trajectory_root: Path,
    candidate: TasteEpisodeCandidate,
    admission: AdmittedTasteEpisode,
) -> int:
    if admission.candidate != candidate:
        raise ValueError("AI-reviewed admission embeds another episode candidate")
    if (
        admission.review_evidence_kind != "ai"
        or admission.human_validity_claim_allowed
        or not admission.cross_model_ai_panel
        or admission.ai_review_count < 2
        or admission.ai_review_count != len(admission.reviews)
    ):
        raise ValueError("episode lacks a completed cross-model AI-only review panel")
    reviews = admission.reviews
    if not all(isinstance(item, AITasteEpisodeAttributionReview) for item in reviews):
        raise ValueError("episode admission includes a non-AI review record")
    ai_reviews = tuple(
        item for item in reviews if isinstance(item, AITasteEpisodeAttributionReview)
    )
    if any(
        item.reviewer_kind != "ai" or not item.not_human_review or item.human_performed
        for item in ai_reviews
    ):
        raise ValueError("AI review identity is mislabeled as human")
    if (
        len({item.reviewer_id for item in ai_reviews}) != len(ai_reviews)
        or len({item.run_id for item in ai_reviews}) != len(ai_reviews)
        or len({(item.provider_id, item.model_id, item.model_revision) for item in ai_reviews})
        != len(ai_reviews)
    ):
        raise ValueError("AI attribution reviewers are not identity-distinct")
    for review in ai_reviews:
        for artifact in review.artifacts:
            path = _source_owned_file(
                trajectory_root,
                artifact.locator,
                _MAX_EVIDENCE_BYTES,
            )
            if _sha256_file(path) != artifact.sha256:
                raise ValueError(f"AI review artifact bytes drifted: {artifact.role.value}")
    if admission.preferred_action_id != candidate.selected_action_id:
        raise ValueError("AI-reviewed preferred action differs from the observed selection")
    return admission.ai_review_count


def _uncertainty_is_explicit(candidate: TasteEpisodeCandidate) -> bool:
    return bool(
        candidate.confounders
        or candidate.missing_evidence_questions
        or any(item.confidence < 1.0 for item in candidate.credit_assignments)
        or any(
            item.direction.value in {"mixed", "not-attributable"}
            for item in candidate.credit_assignments
        )
        or any(item.polarity.value in {"mixed", "unresolved"} for item in candidate.outcomes)
    )


def _build_projection(
    spec: ProspectiveDecisionSourceSpec,
    decision: ResearchDecision,
    candidate: TasteEpisodeCandidate,
    admission: AdmittedTasteEpisode,
) -> tuple[DecisionEpisodeSourcePoolEntry, DecisionEpisodeLabelRecord]:
    actions = tuple(
        DecisionEpisodeActionProjection(
            action_id=item.action_id,
            action_type=item.action_type,
            summary=item.summary,
            tags=item.tags,
            expected_value=item.expected_value,
            expected_cost=item.expected_cost,
            action_sha256=content_sha256(item.model_dump(mode="json", exclude={"selected"})),
        )
        for item in candidate.alternatives
    )
    target = DecisionEpisodeTargetProjection.create(
        decision_id=decision.decision_id,
        decision_sha256=content_sha256(decision.model_dump(mode="json")),
        stage=candidate.stage,
        state_summary=candidate.state_summary,
        actions=actions,
        action_menu_sha256=content_sha256(tuple(item.model_dump(mode="json") for item in actions)),
        domain_tags=candidate.domain_tags,
        venue_tags=candidate.venue_tags,
    )
    precedent = None
    if spec.track_a_role is not DecisionEpisodeTrackARole.HELDOUT_TARGET:
        precedent = DecisionEpisodePrecedentProjection.create(
            selected_action_id=candidate.selected_action_id,
            decision_principle=candidate.decision_principle,
            why_preferred=candidate.why_preferred,
            outcomes=tuple(item.model_dump(mode="json") for item in candidate.outcomes),
            credit_assignments=tuple(
                item.model_dump(mode="json") for item in candidate.credit_assignments
            ),
            confounders=tuple(item.model_dump(mode="json") for item in candidate.confounders),
            applicability_conditions=candidate.applicability_conditions,
            failure_conditions=candidate.failure_conditions,
            counterfactual_probe=candidate.counterfactual_probe,
            missing_evidence_questions=candidate.missing_evidence_questions,
        )
    label = DecisionEpisodeLabelRecord.create(
        source_id=spec.source_id,
        source_group_id=spec.source_group_id,
        candidate_sha256=candidate.candidate_sha256,
        observed_selected_action_id=candidate.selected_action_id,
        ai_reviewed_preferred_action_id=admission.preferred_action_id,
        outcome_sha256=content_sha256(
            tuple(item.model_dump(mode="json") for item in candidate.outcomes)
        ),
        attribution_sha256=content_sha256(
            {
                "credit_assignments": tuple(
                    item.model_dump(mode="json") for item in candidate.credit_assignments
                ),
                "confounders": tuple(
                    item.model_dump(mode="json") for item in candidate.confounders
                ),
                "missing_evidence_questions": candidate.missing_evidence_questions,
            }
        ),
        minimum_ai_attribution_confidence=admission.attribution_confidence,
    )
    entry = DecisionEpisodeSourcePoolEntry(
        source_id=spec.source_id,
        evidence_tier=spec.evidence_tier,
        track_a_role=spec.track_a_role,
        source_group_id=spec.source_group_id,
        dataset_partition=spec.dataset_partition,
        candidate_sha256=candidate.candidate_sha256,
        source_audit_sha256="0" * 64,
        target_projection=target,
        precedent_projection=precedent,
        label_record_sha256=label.label_sha256,
        formal_external_validity_eligible=(
            spec.evidence_tier is DecisionEpisodeEvidenceTier.FORMAL_EXTERNAL
            and spec.track_a_role is not DecisionEpisodeTrackARole.DIAGNOSTIC
        ),
    )
    return entry, label


def _apply_group_leakage_gate(
    audited: list[
        tuple[
            DecisionEpisodeSourceAudit,
            DecisionEpisodeSourcePoolEntry | None,
            DecisionEpisodeLabelRecord | None,
        ]
    ],
) -> tuple[
    list[DecisionEpisodeSourceAudit],
    list[DecisionEpisodeSourcePoolEntry],
    list[DecisionEpisodeLabelRecord],
]:
    group_cells: dict[str, set[tuple[object, ...]]] = defaultdict(set)
    for audit, _, _ in audited:
        group_cells[audit.source_group_id].add(
            (audit.evidence_tier, audit.dataset_partition, audit.track_a_role)
        )
    leaking = {group for group, cells in group_cells.items() if len(cells) > 1}
    audits: list[DecisionEpisodeSourceAudit] = []
    projections: list[DecisionEpisodeSourcePoolEntry] = []
    labels: list[DecisionEpisodeLabelRecord] = []
    for audit, projection, label in audited:
        if audit.source_group_id in leaking:
            finding = DecisionEpisodeFinding(
                code="source-group-split-or-role-leakage",
                severity=DecisionEpisodeFindingSeverity.QUARANTINE,
                message=(
                    "One source group was assigned to multiple evidence tiers, splits, or roles."
                ),
            )
            audit = DecisionEpisodeSourceAudit.create(
                **audit.model_dump(
                    mode="python",
                    exclude={"source_audit_sha256", "formal_external_validity_eligible"},
                ),
                findings=(*audit.findings, finding),
                status=DecisionEpisodeIngressStatus.QUARANTINED,
                formal_external_validity_eligible=False,
            )
            projection = None
            label = None
        audits.append(audit)
        if projection is not None and label is not None:
            projections.append(projection)
            labels.append(label)
    return audits, projections, labels


def _assert_group_disjoint(entries: tuple[DecisionEpisodeSourcePoolEntry, ...]) -> None:
    groups: dict[str, set[tuple[object, ...]]] = defaultdict(set)
    for item in entries:
        groups[item.source_group_id].add(
            (item.evidence_tier, item.dataset_partition, item.track_a_role)
        )
    if any(len(values) > 1 for values in groups.values()):
        raise ValueError("source pool contains cross-split or cross-role group leakage")


class _ExpectedIncomplete(Exception):
    pass


def _status(findings: list[DecisionEpisodeFinding]) -> DecisionEpisodeIngressStatus:
    if any(item.severity is DecisionEpisodeFindingSeverity.QUARANTINE for item in findings):
        return DecisionEpisodeIngressStatus.QUARANTINED
    if findings:
        return DecisionEpisodeIngressStatus.PENDING
    return DecisionEpisodeIngressStatus.ELIGIBLE


def _source_artifact(root: Path, locator: str | None) -> Path:
    if locator is None:
        raise ValueError("required prospective source locator is absent")
    return _bounded_file(_within_root(root, locator, must_exist=True), _MAX_EVIDENCE_BYTES)


def _artifact(
    role: str,
    path: Path,
    root: Path,
    semantic_sha256: str | None,
) -> DecisionEpisodeArtifactBinding:
    return DecisionEpisodeArtifactBinding(
        role=role,
        locator=_relative(path, root),
        file_sha256=_sha256_file(path),
        semantic_sha256=semantic_sha256,
    )


def _source_owned_file(root: Path, locator: str, max_bytes: int) -> Path:
    validate_relative_locator(locator, field_name="run-owned decision episode artifact")
    return _bounded_file(_within_root(root, locator, must_exist=True), max_bytes)


def _canonical_directory(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError("decision episode root cannot be a symbolic link")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("decision episode root must be a directory")
    return resolved


def _within_root(root: Path, value: str | Path, *, must_exist: bool) -> Path:
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    if candidate.is_symlink():
        raise ValueError("decision episode paths cannot be symbolic links")
    resolved = candidate.resolve(strict=must_exist)
    resolved.relative_to(root)
    return resolved


def _bounded_file(path: Path, max_bytes: int) -> Path:
    if path.is_symlink():
        raise ValueError("decision episode artifact cannot be a symbolic link")
    stat = path.stat()
    if not path.is_file() or stat.st_size > max_bytes:
        raise ValueError("decision episode artifact is not a bounded regular file")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve(strict=True).relative_to(root).as_posix()


def _new_output_directory(value: str | Path) -> Path:
    target = Path(value).expanduser()
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    parent = target.parent.resolve(strict=True)
    if parent.is_symlink():
        raise ValueError("cohort output parent cannot be a symbolic link")
    resolved = (parent / target.name).resolve(strict=False)
    resolved.relative_to(parent)
    return resolved


def _write_new_json(value: str | Path, contents: str) -> Path:
    path = Path(value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    parent = path.parent.resolve(strict=True)
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


def _verify_binding(root: Path, binding: DecisionEpisodeArtifactBinding) -> Path:
    path = _bounded_file(_within_root(root, binding.locator, must_exist=True), _MAX_CONTROL_BYTES)
    if _sha256_file(path) != binding.file_sha256:
        raise ValueError(f"cohort artifact bytes drifted: {binding.role}")
    return path


__all__ = [
    "DecisionEpisodeEvidenceTier",
    "DecisionEpisodeIngressStatus",
    "DecisionEpisodeSourceKind",
    "DecisionEpisodeTrackARole",
    "ProspectiveDecisionCohortInspection",
    "ProspectiveDecisionCohortManifest",
    "ProspectiveDecisionCohortPlan",
    "ProspectiveDecisionLabelVault",
    "ProspectiveDecisionSourcePool",
    "ProspectiveDecisionSourceSpec",
    "inspect_prospective_decision_cohort",
    "materialize_prospective_decision_cohort",
    "prepare_prospective_decision_cohort_plan",
]

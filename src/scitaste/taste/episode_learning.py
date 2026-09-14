"""Reviewed outcome attribution and an uncertainty-aware lifecycle Taste policy."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_binding_matches_current,
)
from scitaste.project.models import content_sha256
from scitaste.schema.actions import ResearchAction
from scitaste.state.research_state import ResearchState
from scitaste.taste.episodes import (
    TasteCreditDirection,
    TasteEpisodeCandidate,
    TasteEpisodeInspection,
    TasteEpisodeMaturity,
    TasteEpisodePartition,
    TasteOutcomeFamily,
    TasteOutcomePolarity,
    inspect_taste_episode_candidate,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"


class TasteAttributionReviewRole(StrEnum):
    PRIMARY = "primary"
    ADJUDICATOR = "adjudicator"


class TasteAttributionReviewVerdict(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


class TasteEpisodeAttributionReview(BaseModel):
    """Independent review of outcome credit, preference, and transfer scope."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    review_id: str = Field(pattern=_ID)
    candidate_id: str = Field(pattern=_ID)
    candidate_sha256: str = Field(pattern=_SHA256)
    idea_revision_binding_sha256: str = Field(pattern=_SHA256)
    reviewer_id: str = Field(pattern=_ID)
    role: TasteAttributionReviewRole
    verdict: TasteAttributionReviewVerdict
    preferred_action_id: str | None = Field(default=None, max_length=300)
    supported_credit_ids: tuple[str, ...] = Field(default=(), max_length=100)
    decision_trace_supported: bool
    outcome_trace_supported: bool
    alternatives_supported: bool
    credit_assignment_supported: bool
    transfer_scope_supported: bool
    reversal_probe_supported: bool
    attribution_confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=10_000)
    reviewed_at: datetime
    human_performed: Literal[True] = True
    independent_review: Literal[True] = True
    conflict_cleared: Literal[True] = True
    blinded_to_other_reviews: Literal[True] = True

    @model_validator(mode="after")
    def verdict_matches_dimensions(self) -> TasteEpisodeAttributionReview:
        if self.reviewed_at.utcoffset() is None:
            raise ValueError("Taste attribution review time must include a timezone")
        if len(self.supported_credit_ids) != len(set(self.supported_credit_ids)):
            raise ValueError("Taste attribution supported credit IDs must be unique")
        dimensions = (
            self.decision_trace_supported,
            self.outcome_trace_supported,
            self.alternatives_supported,
            self.credit_assignment_supported,
            self.transfer_scope_supported,
            self.reversal_probe_supported,
        )
        if self.verdict is TasteAttributionReviewVerdict.ACCEPT:
            if not all(dimensions):
                raise ValueError("accepted Taste attribution requires every review dimension")
            if self.preferred_action_id is None or not self.supported_credit_ids:
                raise ValueError("accepted Taste attribution requires preference and credit")
        elif all(dimensions):
            raise ValueError("rejected Taste attribution must identify a failed dimension")
        return self

    @property
    def review_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


class TasteEpisodeAdmissionFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class TasteEpisodeAdmissionReport(BaseModel):
    """Deterministic verdict over an episode and its independent reviews."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str
    candidate_sha256: str = Field(pattern=_SHA256)
    episode_inspection: TasteEpisodeInspection
    primary_review_count: int = Field(ge=0)
    adjudicator_review_count: int = Field(ge=0)
    accepted_review_ids: tuple[str, ...]
    decisive_review_ids: tuple[str, ...]
    preferred_action_id: str | None
    supported_credit_ids: tuple[str, ...]
    attribution_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ready_for_policy_training: bool
    findings: tuple[TasteEpisodeAdmissionFinding, ...]
    policy_update_authorized: Literal[False] = False
    no_external_action_performed: Literal[True] = True


class AdmittedTasteEpisode(BaseModel):
    """Review-admitted training unit; updating a policy remains a separate operation."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    admission_id: str = Field(pattern=_ID)
    candidate: TasteEpisodeCandidate
    reviews: tuple[TasteEpisodeAttributionReview, ...] = Field(min_length=2, max_length=3)
    decisive_review_ids: tuple[str, ...] = Field(min_length=2, max_length=3)
    preferred_action_id: str = Field(min_length=1, max_length=300)
    supported_credit_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    attribution_confidence: float = Field(gt=0.0, le=1.0)
    training_weight: float = Field(gt=0.0, le=1.0)
    policy_training_eligible: Literal[True] = True
    policy_update_authorized: Literal[False] = False
    admission_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def admission_is_self_hashed(self) -> AdmittedTasteEpisode:
        if self.candidate.maturity is not TasteEpisodeMaturity.ATTRIBUTION_PROPOSED:
            raise ValueError("only outcome-attributed episodes can be admitted")
        alternatives = {item.action_id for item in self.candidate.alternatives}
        if self.preferred_action_id not in alternatives:
            raise ValueError("admitted Taste preference is outside the alternatives")
        review_ids = {item.review_id for item in self.reviews}
        if not set(self.decisive_review_ids).issubset(review_ids):
            raise ValueError("admitted Taste decisive review is absent")
        credit_ids = {item.credit_id for item in self.candidate.credit_assignments}
        if not set(self.supported_credit_ids).issubset(credit_ids):
            raise ValueError("admitted Taste credit is absent from the candidate")
        expected = content_sha256(self.model_dump(mode="json", exclude={"admission_sha256"}))
        if self.admission_sha256 != expected:
            raise ValueError("admitted Taste episode hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AdmittedTasteEpisode:
        payload = {"schema_version": "1.0", **values}
        payload.pop("admission_sha256", None)
        unsigned = cls.model_construct(admission_sha256="0" * 64, **payload)
        return cls(
            **payload,
            admission_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"admission_sha256"})
            ),
        )


def inspect_taste_episode_admission(
    candidate: TasteEpisodeCandidate,
    reviews: tuple[TasteEpisodeAttributionReview, ...],
    *,
    evidence_root: str | Path,
    current_idea_revision: ProjectIdeaRevisionBinding,
) -> TasteEpisodeAdmissionReport:
    """Require two independent reviews and adjudicate any substantive split."""

    episode_inspection = inspect_taste_episode_candidate(
        candidate,
        evidence_root=evidence_root,
        current_idea_revision=current_idea_revision,
    )
    findings: list[TasteEpisodeAdmissionFinding] = []
    alternative_ids = {item.action_id for item in candidate.alternatives}
    credit_ids = {item.credit_id for item in candidate.credit_assignments}
    review_ids = [item.review_id for item in reviews]
    reviewer_ids = [item.reviewer_id for item in reviews]
    if len(review_ids) != len(set(review_ids)):
        _admission_add(findings, "duplicate-review", "Taste attribution review IDs repeat")
    if len(reviewer_ids) != len(set(reviewer_ids)):
        _admission_add(findings, "duplicate-reviewer", "Taste reviewers must be distinct")
    producer_ids = {candidate.producer_id}
    if candidate.attribution_producer_id is not None:
        producer_ids.add(candidate.attribution_producer_id)
    if producer_ids.intersection(reviewer_ids):
        _admission_add(
            findings,
            "producer-review-conflict",
            "episode or attribution producer cannot review its own attribution",
        )
    for review in reviews:
        if (
            review.candidate_id != candidate.candidate_id
            or review.candidate_sha256 != candidate.candidate_sha256
            or review.idea_revision_binding_sha256 != candidate.idea_revision.binding_sha256
        ):
            _admission_add(
                findings,
                "review-binding-mismatch",
                "Taste attribution review binds another candidate or Idea revision",
            )
        if (
            review.preferred_action_id is not None
            and review.preferred_action_id not in alternative_ids
        ):
            _admission_add(
                findings,
                "review-preference-outside-alternatives",
                "Taste attribution review preferred an unavailable action",
            )
        if set(review.supported_credit_ids) - credit_ids:
            _admission_add(
                findings,
                "review-credit-outside-candidate",
                "Taste attribution review references unknown credit",
            )
    primary = tuple(item for item in reviews if item.role is TasteAttributionReviewRole.PRIMARY)
    adjudicators = tuple(
        item for item in reviews if item.role is TasteAttributionReviewRole.ADJUDICATOR
    )
    if len(primary) != 2:
        _admission_add(
            findings,
            "primary-review-count",
            "Taste episode admission requires exactly two primary reviews",
        )
    if len(adjudicators) > 1:
        _admission_add(
            findings,
            "adjudicator-review-count",
            "Taste episode admission allows at most one adjudicator",
        )

    accepted = tuple(
        item for item in reviews if item.verdict is TasteAttributionReviewVerdict.ACCEPT
    )
    decisive: tuple[TasteEpisodeAttributionReview, ...] = ()
    preferred: str | None = None
    supported: tuple[str, ...] = ()
    confidence: float | None = None
    if len(primary) == 2:
        primary_accept = tuple(
            item for item in primary if item.verdict is TasteAttributionReviewVerdict.ACCEPT
        )
        same_preference = (
            len(primary_accept) == 2
            and primary_accept[0].preferred_action_id == primary_accept[1].preferred_action_id
        )
        if same_preference:
            if adjudicators:
                _admission_add(
                    findings,
                    "unneeded-adjudication",
                    "unanimous primary attribution cannot be overridden",
                )
            decisive = primary
            preferred = primary[0].preferred_action_id
            shared_credit = set(primary[0].supported_credit_ids) & set(
                primary[1].supported_credit_ids
            )
            supported = tuple(sorted(shared_credit))
            confidence = min(item.attribution_confidence for item in primary)
            if not supported:
                _admission_add(
                    findings,
                    "credit-review-disagreement",
                    "primary reviewers share no supported outcome credit",
                )
        elif not primary_accept:
            if adjudicators:
                _admission_add(
                    findings,
                    "unneeded-adjudication",
                    "two rejecting primary reviews cannot be overridden",
                )
            _admission_add(
                findings,
                "attribution-not-accepted",
                "both primary reviewers rejected the episode attribution",
            )
        elif len(adjudicators) != 1:
            _admission_add(
                findings,
                "adjudication-required",
                "split verdicts or preferences require one independent adjudicator",
            )
        else:
            adjudicator = adjudicators[0]
            if adjudicator.verdict is TasteAttributionReviewVerdict.REJECT:
                _admission_add(
                    findings,
                    "attribution-not-accepted",
                    "independent adjudication rejected the episode attribution",
                )
            else:
                decisive = (*primary, adjudicator)
                preferred = adjudicator.preferred_action_id
                supported = tuple(sorted(adjudicator.supported_credit_ids))
                confidence = min(item.attribution_confidence for item in decisive)

    credit_by_id = {item.credit_id: item for item in candidate.credit_assignments}
    if supported and any(
        credit_by_id[credit_id].direction is TasteCreditDirection.NOT_ATTRIBUTABLE
        for credit_id in supported
    ):
        _admission_add(
            findings,
            "review-supported-non-attributable-credit",
            "reviewers cannot train on credit declared not attributable",
        )

    if not episode_inspection.ready_for_independent_review:
        _admission_add(
            findings,
            "episode-not-review-ready",
            "episode evidence, Idea binding, or outcome attribution is incomplete",
        )
    ready = not findings and preferred is not None and confidence is not None and bool(supported)
    return TasteEpisodeAdmissionReport(
        candidate_id=candidate.candidate_id,
        candidate_sha256=candidate.candidate_sha256,
        episode_inspection=episode_inspection,
        primary_review_count=len(primary),
        adjudicator_review_count=len(adjudicators),
        accepted_review_ids=tuple(item.review_id for item in accepted),
        decisive_review_ids=tuple(item.review_id for item in decisive),
        preferred_action_id=preferred,
        supported_credit_ids=supported,
        attribution_confidence=confidence,
        ready_for_policy_training=ready,
        findings=tuple(findings),
    )


def admit_taste_episode(
    candidate: TasteEpisodeCandidate,
    reviews: tuple[TasteEpisodeAttributionReview, ...],
    *,
    admission_id: str,
    evidence_root: str | Path,
    current_idea_revision: ProjectIdeaRevisionBinding,
) -> AdmittedTasteEpisode:
    """Construct an immutable training unit; do not fit or mutate a policy."""

    report = inspect_taste_episode_admission(
        candidate,
        reviews,
        evidence_root=evidence_root,
        current_idea_revision=current_idea_revision,
    )
    if not report.ready_for_policy_training:
        codes = ", ".join(item.code for item in report.findings)
        raise ValueError(f"Taste episode attribution is not admissible: {codes}")
    assert report.preferred_action_id is not None
    assert report.attribution_confidence is not None
    return AdmittedTasteEpisode.create(
        admission_id=admission_id,
        candidate=candidate,
        reviews=reviews,
        decisive_review_ids=report.decisive_review_ids,
        preferred_action_id=report.preferred_action_id,
        supported_credit_ids=report.supported_credit_ids,
        attribution_confidence=report.attribution_confidence,
        training_weight=report.attribution_confidence,
        policy_training_eligible=True,
        policy_update_authorized=False,
    )


class LifecycleTastePolicyUpdateMode(StrEnum):
    OUTCOME_UPDATED = "outcome-updated"
    NO_UPDATE = "no-update"
    SUCCESS_ONLY = "success-only"
    FAILURE_ONLY = "failure-only"
    SHUFFLED_CREDIT = "shuffled-credit"


class LifecycleTastePolicyConfig(BaseModel):
    """Precommitted estimator and abstention policy used by H3 controls."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str = Field(pattern=_ID)
    update_mode: LifecycleTastePolicyUpdateMode
    idea_revision: ProjectIdeaRevisionBinding
    prior_alpha: float = Field(default=1.0, gt=0.0, le=100.0)
    prior_beta: float = Field(default=1.0, gt=0.0, le=100.0)
    minimum_feature_support: float = Field(default=3.0, ge=0.0, le=10_000.0)
    credible_z: float = Field(default=1.6448536269514722, ge=0.0, le=5.0)
    minimum_pairwise_probability: float = Field(default=0.6, ge=0.5, le=0.99)
    maximum_absolute_adjustment: float = Field(default=1.0, gt=0.0, le=10.0)
    require_stage_support: bool = True
    allow_cross_domain: bool = False
    shuffle_seed: int = Field(default=0, ge=0)
    eligible_outcome_families: tuple[TasteOutcomeFamily, ...] = (
        TasteOutcomeFamily.HYPOTHESIS,
        TasteOutcomeFamily.DESIGN,
        TasteOutcomeFamily.ADAPTATION,
        TasteOutcomeFamily.CLAIM,
        TasteOutcomeFamily.REVIEW,
        TasteOutcomeFamily.COMMUNICATION,
    )
    training_partitions: tuple[TasteEpisodePartition, ...] = (
        TasteEpisodePartition.DEVELOPMENT,
        TasteEpisodePartition.CALIBRATION,
    )

    @model_validator(mode="after")
    def control_parameters_match_mode(self) -> LifecycleTastePolicyConfig:
        if self.update_mode is not LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT:
            if self.shuffle_seed != 0:
                raise ValueError("shuffle_seed is reserved for shuffled-credit control")
        if not self.eligible_outcome_families:
            raise ValueError("lifecycle Taste policy requires an eligible outcome family")
        if len(self.eligible_outcome_families) != len(set(self.eligible_outcome_families)):
            raise ValueError("lifecycle Taste outcome families must be unique")
        if not self.training_partitions:
            raise ValueError("lifecycle Taste policy requires a training partition")
        if len(self.training_partitions) != len(set(self.training_partitions)):
            raise ValueError("lifecycle Taste training partitions must be unique")
        if TasteEpisodePartition.FORMAL_HELDOUT in self.training_partitions:
            raise ValueError("formal-heldout Taste episodes can never train a policy")
        return self

    @property
    def config_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


class LifecycleTasteFeaturePosterior(BaseModel):
    model_config = _CONFIG

    feature: str = Field(min_length=1, max_length=500)
    feature_kind: Literal[
        "action-type",
        "stage-action",
        "domain-action",
        "venue-action",
        "tag",
        "stage-tag",
    ]
    wins: float = Field(ge=0.0)
    losses: float = Field(ge=0.0)
    alpha: float = Field(gt=0.0)
    beta: float = Field(gt=0.0)
    support: float = Field(ge=0.0)
    posterior_mean: float = Field(gt=0.0, lt=1.0)
    log_odds: float
    log_odds_variance: float = Field(gt=0.0)

    @model_validator(mode="after")
    def posterior_is_reproducible(self) -> LifecycleTasteFeaturePosterior:
        expected_support = self.wins + self.losses
        expected_mean = self.alpha / (self.alpha + self.beta)
        probability_variance = (
            self.alpha
            * self.beta
            / ((self.alpha + self.beta) ** 2 * (self.alpha + self.beta + 1.0))
        )
        expected_log_odds = math.log(expected_mean / (1.0 - expected_mean))
        expected_log_variance = probability_variance / (
            expected_mean**2 * (1.0 - expected_mean) ** 2
        )
        checks = (
            abs(self.support - expected_support),
            abs(self.posterior_mean - expected_mean),
            abs(self.log_odds - expected_log_odds),
            abs(self.log_odds_variance - expected_log_variance),
        )
        if any(value > 1e-9 for value in checks):
            raise ValueError("lifecycle Taste feature posterior is inconsistent")
        return self


class LifecycleTastePolicyModel(BaseModel):
    """Hash-bound posterior table learned from independently admitted episodes."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.1"
    policy_id: str
    config: LifecycleTastePolicyConfig
    source_episode_ids: tuple[str, ...]
    source_episode_sha256: tuple[str, ...]
    training_episode_ids: tuple[str, ...]
    training_episode_sha256: tuple[str, ...]
    training_episode_count: int = Field(ge=0)
    training_source_group_keys: tuple[str, ...] = ()
    training_source_group_count: int = Field(default=0, ge=0)
    effective_training_weight: float = Field(default=0.0, ge=0.0)
    pairwise_comparison_count: int = Field(ge=0)
    trained_stages: tuple[str, ...]
    trained_domain_tags: tuple[str, ...]
    trained_venue_tags: tuple[str, ...]
    feature_posteriors: tuple[LifecycleTasteFeaturePosterior, ...]
    estimator: Literal["factorized-beta-pairwise-v1"] = "factorized-beta-pairwise-v1"
    policy_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def policy_is_closed(self) -> LifecycleTastePolicyModel:
        if self.policy_id != self.config.policy_id:
            raise ValueError("lifecycle Taste policy and config IDs differ")
        if len(self.source_episode_ids) != len(set(self.source_episode_ids)):
            raise ValueError("lifecycle Taste source episode IDs must be unique")
        if len(self.training_episode_ids) != self.training_episode_count:
            raise ValueError("lifecycle Taste training episode count differs")
        if self.training_source_group_count != len(self.training_source_group_keys):
            raise ValueError("lifecycle Taste training source-group count differs")
        if list(self.training_source_group_keys) != sorted(self.training_source_group_keys):
            raise ValueError("lifecycle Taste training source groups must be sorted")
        if len(self.training_source_group_keys) != len(set(self.training_source_group_keys)):
            raise ValueError("lifecycle Taste training source groups must be unique")
        if self.effective_training_weight > self.training_source_group_count + 1e-9:
            raise ValueError("lifecycle Taste effective weight exceeds independent source groups")
        if len(self.training_episode_ids) != len(self.training_episode_sha256):
            raise ValueError("lifecycle Taste training episode hashes do not close")
        if len(self.source_episode_ids) != len(self.source_episode_sha256):
            raise ValueError("lifecycle Taste source episode hashes do not close")
        source = dict(zip(self.source_episode_ids, self.source_episode_sha256, strict=True))
        if len(self.training_episode_ids) != len(set(self.training_episode_ids)):
            raise ValueError("lifecycle Taste training episode IDs must be unique")
        if any(
            source.get(episode_id) != episode_sha256
            for episode_id, episode_sha256 in zip(
                self.training_episode_ids,
                self.training_episode_sha256,
                strict=True,
            )
        ):
            raise ValueError("lifecycle Taste training episodes are not a source subset")
        features = [item.feature for item in self.feature_posteriors]
        if features != sorted(features) or len(features) != len(set(features)):
            raise ValueError("lifecycle Taste posterior features must be sorted and unique")
        if self.config.update_mode is LifecycleTastePolicyUpdateMode.NO_UPDATE and (
            self.training_episode_count
            or self.training_source_group_count
            or self.effective_training_weight
            or self.feature_posteriors
        ):
            raise ValueError("no-update control cannot estimate episode posteriors")
        if any(
            abs(item.alpha - (self.config.prior_alpha + item.wins)) > 1e-9
            or abs(item.beta - (self.config.prior_beta + item.losses)) > 1e-9
            for item in self.feature_posteriors
        ):
            raise ValueError("lifecycle Taste posteriors differ from the configured prior")
        if self.schema_version == "1.1" and any(
            item.support > self.effective_training_weight + 1e-9 for item in self.feature_posteriors
        ):
            raise ValueError("lifecycle Taste feature support exceeds source-group weight")
        expected = content_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        legacy_payload = self.model_dump(mode="json", exclude={"policy_sha256"})
        for field in (
            "training_source_group_keys",
            "training_source_group_count",
            "effective_training_weight",
        ):
            legacy_payload.pop(field)
        legacy_expected = content_sha256(legacy_payload) if self.schema_version == "1.0" else None
        if self.policy_sha256 not in {expected, legacy_expected}:
            raise ValueError("lifecycle Taste policy hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> LifecycleTastePolicyModel:
        payload = {"schema_version": "1.1", **values}
        payload.pop("policy_sha256", None)
        unsigned = cls.model_construct(policy_sha256="0" * 64, **payload)
        return cls(
            **payload,
            policy_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"policy_sha256"})
            ),
        )


class LifecycleTasteActionScore(BaseModel):
    model_config = _CONFIG

    action_id: str
    score: float
    standard_error: float | None = Field(default=None, ge=0.0)
    effective_support: float = Field(ge=0.0)
    matched_features: tuple[str, ...]
    stage_supported: bool
    adjustment: float

    @model_validator(mode="after")
    def score_is_finite(self) -> LifecycleTasteActionScore:
        values = (self.score, self.effective_support, self.adjustment)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("lifecycle Taste action score must be finite")
        if self.standard_error is not None and not math.isfinite(self.standard_error):
            raise ValueError("lifecycle Taste action uncertainty must be finite")
        return self


class LifecycleTastePolicyAssessment(BaseModel):
    """One candidate-set prediction with an explicit abstention decision."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str
    policy_sha256: str = Field(pattern=_SHA256)
    idea_revision_id: str
    idea_revision_record_sha256: str = Field(pattern=_SHA256)
    observed_idea_revision_id: str | None = None
    observed_idea_revision_record_sha256: str | None = Field(default=None, pattern=_SHA256)
    candidate_set_sha256: str = Field(pattern=_SHA256)
    action_scores: tuple[LifecycleTasteActionScore, ...] = Field(min_length=1)
    recommended_action_id: str | None
    abstained: bool
    reason_codes: tuple[str, ...] = Field(min_length=1)
    pairwise_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    margin: float | None = None
    margin_standard_error: float | None = Field(default=None, ge=0.0)
    lower_credible_margin: float | None = None
    assessment_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def assessment_is_closed(self) -> LifecycleTastePolicyAssessment:
        action_ids = [item.action_id for item in self.action_scores]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("lifecycle Taste assessment action IDs must be unique")
        if self.abstained != (self.recommended_action_id is None):
            raise ValueError("lifecycle Taste abstention and recommendation disagree")
        if self.recommended_action_id is not None and self.recommended_action_id not in action_ids:
            raise ValueError("lifecycle Taste recommendation is outside the candidate set")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("lifecycle Taste assessment reason codes must be unique")
        if (self.observed_idea_revision_id is None) != (
            self.observed_idea_revision_record_sha256 is None
        ):
            raise ValueError("observed lifecycle Taste Idea identity is incomplete")
        if self.abstained and any(item.adjustment != 0 for item in self.action_scores):
            raise ValueError("abstained lifecycle Taste assessment cannot change scores")
        if not self.abstained and self.reason_codes != ("policy-applied",):
            raise ValueError("applied lifecycle Taste assessment has inconsistent reasons")
        expected = content_sha256(self.model_dump(mode="json", exclude={"assessment_sha256"}))
        if self.assessment_sha256 != expected:
            raise ValueError("lifecycle Taste assessment hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> LifecycleTastePolicyAssessment:
        payload = {"schema_version": "1.0", **values}
        payload.pop("assessment_sha256", None)
        unsigned = cls.model_construct(assessment_sha256="0" * 64, **payload)
        return cls(
            **payload,
            assessment_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"assessment_sha256"})
            ),
        )


def fit_lifecycle_taste_policy(
    episodes: tuple[AdmittedTasteEpisode, ...],
    config: LifecycleTastePolicyConfig,
) -> LifecycleTastePolicyModel:
    """Fit a deterministic partial-pooling preference table from episode units."""

    ids = [item.admission_id for item in episodes]
    if len(ids) != len(set(ids)):
        raise ValueError("lifecycle Taste update received duplicate episodes")
    for episode in episodes:
        if not idea_binding_matches_current(
            episode.candidate.idea_revision,
            config.idea_revision,
        ):
            raise ValueError("lifecycle Taste episode belongs to another Idea revision")
        if (
            episode.candidate.schema_version != "1.2"
            or episode.candidate.source_group_id is None
            or episode.candidate.dataset_partition is None
        ):
            raise ValueError("lifecycle Taste update requires a frozen sampling unit")
        if episode.candidate.dataset_partition not in config.training_partitions:
            raise ValueError("lifecycle Taste episode belongs to a non-training partition")
    group_partitions: dict[str, TasteEpisodePartition] = {}
    for episode in episodes:
        assert episode.candidate.dataset_partition is not None
        group_key = _source_group_key(episode)
        existing = group_partitions.setdefault(
            group_key,
            episode.candidate.dataset_partition,
        )
        if existing is not episode.candidate.dataset_partition:
            raise ValueError("lifecycle Taste source group crosses dataset partitions")
    selected = _select_training_episodes(episodes, config)
    group_counts: dict[str, int] = defaultdict(int)
    for episode in selected:
        group_counts[_source_group_key(episode)] += 1
    observations: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    comparisons = 0
    effective_weight = 0.0
    for episode in selected:
        group_key = _source_group_key(episode)
        alternatives = episode.candidate.alternatives
        preferred_id = _training_preference(episode, config)
        preferred = next(item for item in alternatives if item.action_id == preferred_id)
        competitors = tuple(item for item in alternatives if item.action_id != preferred_id)
        episode_weight = episode.training_weight / group_counts[group_key]
        effective_weight += episode_weight
        weight = episode_weight / len(competitors)
        preferred_features = set(_episode_action_features(episode, preferred))
        for competitor in competitors:
            competitor_features = set(_episode_action_features(episode, competitor))
            for feature, _ in preferred_features - competitor_features:
                observations[feature][0] += weight
            for feature, _ in competitor_features - preferred_features:
                observations[feature][1] += weight
            comparisons += 1
    kinds = {
        feature: kind
        for episode in selected
        for alternative in episode.candidate.alternatives
        for feature, kind in _episode_action_features(episode, alternative)
    }
    posteriors = tuple(
        _posterior(
            feature,
            kinds[feature],
            wins=values[0],
            losses=values[1],
            alpha0=config.prior_alpha,
            beta0=config.prior_beta,
        )
        for feature, values in sorted(observations.items())
    )
    return LifecycleTastePolicyModel.create(
        policy_id=config.policy_id,
        config=config,
        source_episode_ids=tuple(ids),
        source_episode_sha256=tuple(item.admission_sha256 for item in episodes),
        training_episode_ids=tuple(item.admission_id for item in selected),
        training_episode_sha256=tuple(item.admission_sha256 for item in selected),
        training_episode_count=len(selected),
        training_source_group_keys=tuple(sorted(group_counts)),
        training_source_group_count=len(group_counts),
        effective_training_weight=_rounded(effective_weight),
        pairwise_comparison_count=comparisons,
        trained_stages=tuple(sorted({item.candidate.stage for item in selected})),
        trained_domain_tags=tuple(
            sorted({tag.casefold() for item in selected for tag in item.candidate.domain_tags})
        ),
        trained_venue_tags=tuple(
            sorted({tag.casefold() for item in selected for tag in item.candidate.venue_tags})
        ),
        feature_posteriors=posteriors,
        estimator="factorized-beta-pairwise-v1",
    )


def assess_lifecycle_taste_policy(
    model: LifecycleTastePolicyModel,
    *,
    state: ResearchState,
    actions: tuple[ResearchAction, ...],
    current_idea_revision: ProjectIdeaRevisionBinding | None = None,
) -> LifecycleTastePolicyAssessment:
    """Apply only supported structured scopes and abstain on uncertain preference."""

    if not actions:
        raise ValueError("lifecycle Taste policy requires at least one action")
    if len({item.action_id for item in actions}) != len(actions):
        raise ValueError("lifecycle Taste policy action IDs must be unique")
    posterior = {item.feature: item for item in model.feature_posteriors}
    raw: list[tuple[ResearchAction, float, float, float, tuple[str, ...], bool]] = []
    for action in actions:
        candidates = _state_action_features(state, action)
        matched = tuple(
            feature
            for feature, _ in candidates
            if feature in posterior and posterior[feature].support > 0
        )
        weighted = [
            (posterior[feature], _feature_weight(kind), kind)
            for feature, kind in candidates
            if feature in posterior and posterior[feature].support > 0
        ]
        total_weight = sum(weight for _, weight, _ in weighted)
        if total_weight:
            score = sum(item.log_odds * weight for item, weight, _ in weighted) / total_weight
            # Features from one episode are correlated. Treat them as fully
            # correlated for uncertainty instead of manufacturing sample size.
            variance = max(item.log_odds_variance for item, _, _ in weighted)
            stage_action = tuple(item for item, _, kind in weighted if kind == "stage-action")
            support = max(
                item.support for item in stage_action or tuple(item for item, _, _ in weighted)
            )
        else:
            score = 0.0
            variance = float("inf")
            support = 0.0
        stage_supported = any(
            kind == "stage-action" and feature in posterior for feature, kind in candidates
        )
        raw.append((action, score, variance, support, matched, stage_supported))

    reason_codes: list[str] = []
    recommended: str | None = None
    probability: float | None = None
    margin: float | None = None
    margin_se: float | None = None
    lower: float | None = None
    if current_idea_revision is None:
        reason_codes.append("idea-revision-unverified")
    elif not idea_binding_matches_current(model.config.idea_revision, current_idea_revision):
        reason_codes.append("idea-revision-stale")
    elif model.config.update_mode is LifecycleTastePolicyUpdateMode.NO_UPDATE:
        reason_codes.append("no-update-control")
    elif len(actions) < 2:
        reason_codes.append("single-feasible-action")
    elif not any(item[4] for item in raw):
        reason_codes.append("unseen-features")
    elif (
        model.trained_domain_tags
        and not model.config.allow_cross_domain
        and state.target_domain.casefold() not in set(model.trained_domain_tags)
    ):
        reason_codes.append("domain-out-of-scope")
    else:
        ranked = sorted(raw, key=lambda item: (-item[1], item[0].action_id))
        first, second = ranked[:2]
        margin = first[1] - second[1]
        margin_se = (
            math.sqrt(first[2]) + math.sqrt(second[2])
            if math.isfinite(first[2]) and math.isfinite(second[2])
            else None
        )
        if margin_se is not None:
            lower = margin - model.config.credible_z * margin_se
            probability = _sigmoid(margin / math.sqrt(1.0 + math.pi * margin_se**2 / 8.0))
        if min(first[3], second[3]) < model.config.minimum_feature_support:
            reason_codes.append("insufficient-support")
        if model.config.require_stage_support and not (first[5] and second[5]):
            reason_codes.append("missing-stage-support")
        if probability is None or probability < model.config.minimum_pairwise_probability:
            reason_codes.append("uncertain-pairwise-probability")
        if lower is None or lower <= 0:
            reason_codes.append("credible-margin-crosses-zero")
        if not reason_codes:
            recommended = first[0].action_id
            reason_codes.append("policy-applied")

    center = sum(item[1] for item in raw) / len(raw)
    maximum = max((abs(item[1] - center) for item in raw), default=0.0)
    scale = (
        model.config.maximum_absolute_adjustment / maximum
        if recommended is not None and maximum > model.config.maximum_absolute_adjustment
        else 1.0
    )
    action_scores = tuple(
        LifecycleTasteActionScore(
            action_id=action.action_id,
            score=_rounded(score),
            standard_error=(_rounded(math.sqrt(variance)) if math.isfinite(variance) else None),
            effective_support=_rounded(support),
            matched_features=matched,
            stage_supported=stage_supported,
            adjustment=(_rounded((score - center) * scale) if recommended is not None else 0.0),
        )
        for action, score, variance, support, matched, stage_supported in raw
    )
    candidate_set_sha256 = content_sha256([item.model_dump(mode="json") for item in actions])
    return LifecycleTastePolicyAssessment.create(
        policy_id=model.policy_id,
        policy_sha256=model.policy_sha256,
        idea_revision_id=model.config.idea_revision.revision_id,
        idea_revision_record_sha256=model.config.idea_revision.record_sha256,
        observed_idea_revision_id=(
            None if current_idea_revision is None else current_idea_revision.revision_id
        ),
        observed_idea_revision_record_sha256=(
            None if current_idea_revision is None else current_idea_revision.record_sha256
        ),
        candidate_set_sha256=candidate_set_sha256,
        action_scores=action_scores,
        recommended_action_id=recommended,
        abstained=recommended is None,
        reason_codes=tuple(reason_codes),
        pairwise_probability=None if probability is None else _rounded(probability),
        margin=None if margin is None else _rounded(margin),
        margin_standard_error=None if margin_se is None else _rounded(margin_se),
        lower_credible_margin=None if lower is None else _rounded(lower),
    )


def _select_training_episodes(
    episodes: tuple[AdmittedTasteEpisode, ...],
    config: LifecycleTastePolicyConfig,
) -> tuple[AdmittedTasteEpisode, ...]:
    if config.update_mode is LifecycleTastePolicyUpdateMode.NO_UPDATE:
        return ()
    eligible = tuple(
        episode for episode in episodes if _has_eligible_policy_credit(episode, config)
    )
    if config.update_mode in {
        LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
        LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT,
    }:
        return eligible
    target = (
        TasteOutcomePolarity.SUPPORTS
        if config.update_mode is LifecycleTastePolicyUpdateMode.SUCCESS_ONLY
        else TasteOutcomePolarity.CHALLENGES
    )
    return tuple(episode for episode in eligible if _unambiguous_outcome(episode, config) is target)


def _source_group_key(episode: AdmittedTasteEpisode) -> str:
    candidate = episode.candidate
    assert candidate.source_group_id is not None
    assert candidate.source_relationship is not None
    source_identity = candidate.source_project_id or "external-record"
    return f"{candidate.source_relationship.value}:{source_identity}:{candidate.source_group_id}"


def _has_eligible_policy_credit(
    episode: AdmittedTasteEpisode,
    config: LifecycleTastePolicyConfig,
) -> bool:
    credit_by_id = {item.credit_id: item for item in episode.candidate.credit_assignments}
    return any(
        credit_by_id[credit_id].family in config.eligible_outcome_families
        for credit_id in episode.supported_credit_ids
    )


def _unambiguous_outcome(
    episode: AdmittedTasteEpisode,
    config: LifecycleTastePolicyConfig,
) -> TasteOutcomePolarity | None:
    credit_by_id = {item.credit_id: item for item in episode.candidate.credit_assignments}
    relevant_outcome_ids = {
        outcome_id
        for credit_id in episode.supported_credit_ids
        if credit_by_id[credit_id].family in config.eligible_outcome_families
        for outcome_id in credit_by_id[credit_id].outcome_ids
    }
    polarities = {
        item.polarity
        for item in episode.candidate.outcomes
        if item.outcome_id in relevant_outcome_ids
    }
    if polarities == {TasteOutcomePolarity.SUPPORTS}:
        return TasteOutcomePolarity.SUPPORTS
    if polarities == {TasteOutcomePolarity.CHALLENGES}:
        return TasteOutcomePolarity.CHALLENGES
    return None


def _training_preference(
    episode: AdmittedTasteEpisode,
    config: LifecycleTastePolicyConfig,
) -> str:
    if config.update_mode is not LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT:
        return episode.preferred_action_id
    alternatives = episode.candidate.alternatives
    true_index = next(
        index
        for index, item in enumerate(alternatives)
        if item.action_id == episode.preferred_action_id
    )
    digest = hashlib.sha256(f"{config.shuffle_seed}:{episode.admission_id}".encode()).digest()
    offset = 1 + int.from_bytes(digest[:8], "big") % (len(alternatives) - 1)
    return alternatives[(true_index + offset) % len(alternatives)].action_id


def _episode_action_features(episode, action) -> tuple[tuple[str, str], ...]:  # type: ignore[no-untyped-def]
    return _features(
        stage=episode.candidate.stage,
        domain_tags=episode.candidate.domain_tags,
        venue_tags=episode.candidate.venue_tags,
        action_type=action.action_type,
        tags=action.tags,
    )


def _state_action_features(
    state: ResearchState,
    action: ResearchAction,
) -> tuple[tuple[str, str], ...]:
    return _features(
        stage=state.current_stage.value,
        domain_tags=(state.target_domain,),
        venue_tags=(() if state.target_venue is None else (state.target_venue,)),
        action_type=action.type.value,
        tags=tuple(action.tags),
    )


def _features(
    *,
    stage: str,
    domain_tags: tuple[str, ...],
    venue_tags: tuple[str, ...],
    action_type: str,
    tags: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    normalized_stage = _normal(stage)
    normalized_action = _normal(action_type)
    features: list[tuple[str, str]] = [
        (f"action::{normalized_action}", "action-type"),
        (f"stage::{normalized_stage}::action::{normalized_action}", "stage-action"),
    ]
    for domain in sorted({_normal(item) for item in domain_tags if item.strip()}):
        features.append((f"domain::{domain}::action::{normalized_action}", "domain-action"))
    for venue in sorted({_normal(item) for item in venue_tags if item.strip()}):
        features.append((f"venue::{venue}::action::{normalized_action}", "venue-action"))
    for tag in sorted({_normal(item) for item in tags if item.strip()}):
        features.extend(
            (
                (f"tag::{tag}", "tag"),
                (f"stage::{normalized_stage}::tag::{tag}", "stage-tag"),
            )
        )
    return tuple(features)


def _posterior(
    feature: str,
    feature_kind: str,
    *,
    wins: float,
    losses: float,
    alpha0: float,
    beta0: float,
) -> LifecycleTasteFeaturePosterior:
    alpha = alpha0 + wins
    beta = beta0 + losses
    mean = alpha / (alpha + beta)
    probability_variance = alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1.0))
    return LifecycleTasteFeaturePosterior(
        feature=feature,
        feature_kind=feature_kind,
        wins=_rounded(wins),
        losses=_rounded(losses),
        alpha=_rounded(alpha),
        beta=_rounded(beta),
        support=_rounded(wins + losses),
        posterior_mean=_rounded(mean),
        log_odds=_rounded(math.log(mean / (1.0 - mean))),
        log_odds_variance=_rounded(probability_variance / (mean**2 * (1.0 - mean) ** 2)),
    )


def _feature_weight(kind: str) -> float:
    return {
        "action-type": 1.0,
        "stage-action": 2.0,
        "domain-action": 2.0,
        "venue-action": 1.5,
        "tag": 0.5,
        "stage-tag": 1.0,
    }[kind]


def _normal(value: str) -> str:
    return "-".join(value.casefold().strip().replace("_", "-").split())


def _rounded(value: float) -> float:
    return round(value, 12)


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def _admission_add(
    findings: list[TasteEpisodeAdmissionFinding],
    code: str,
    message: str,
) -> None:
    if code not in {item.code for item in findings}:
        findings.append(TasteEpisodeAdmissionFinding(code=code, message=message))


__all__ = [
    "AdmittedTasteEpisode",
    "LifecycleTasteActionScore",
    "LifecycleTasteFeaturePosterior",
    "LifecycleTastePolicyAssessment",
    "LifecycleTastePolicyConfig",
    "LifecycleTastePolicyModel",
    "LifecycleTastePolicyUpdateMode",
    "TasteAttributionReviewRole",
    "TasteAttributionReviewVerdict",
    "TasteEpisodeAdmissionFinding",
    "TasteEpisodeAdmissionReport",
    "TasteEpisodeAttributionReview",
    "admit_taste_episode",
    "assess_lifecycle_taste_policy",
    "fit_lifecycle_taste_policy",
    "inspect_taste_episode_admission",
]

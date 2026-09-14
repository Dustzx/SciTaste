"""Independent human review for natural Scientific Taste source episodes.

The workflow separates two instruments. Scientific reviewers see a prestige-,
publisher-subject-, and outcome-blind projection and assess domain, decision
family, and content-grounded reference quality. A separate privacy reviewer sees
all locally de-identified free text and decides whether an episode is safe to
retain. Preparing files never recruits a person or admits a source.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.evaluation.aries_population import (
    AriesTasteCandidate,
    AriesTastePopulationReport,
)
from scitaste.evaluation.f1000_domain_population import (
    F1000TasteCandidate,
    F1000TastePopulationReport,
)
from scitaste.model_nodes.verification_policy import (
    ActionEffect,
    ActionReversibility,
    VerificationDecision,
    VerificationDecisionInput,
    VerificationRoute,
    decide_verification_route,
)
from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import validate_entry_id, validate_project_id
from scitaste.taste.intrinsic import TasteTask
from scitaste.taste.reference_quality import (
    ReferenceQualityDimension,
    ReferenceQualityRating,
)

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_EXACT_CONFIG = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_POLICY_BYTES = 256 * 1024
_MAX_CONTROL_BYTES = 16 * 1_048_576
_MAX_ITEMS_BYTES = 128 * 1_048_576
_STAGE = "taste_source_review_campaign"
_PROJECTION = "natural-taste-source-review-campaign-v1"


class TasteSourceReviewRole(StrEnum):
    SCIENTIFIC = "scientific"
    PRIVACY = "privacy"


class TasteSourceDomainLabel(StrEnum):
    COMPUTING = "computing"
    ECOLOGY = "ecology"
    PUBLIC_HEALTH = "public-health"
    OTHER = "other"
    CANNOT_ASSESS = "cannot-assess"


class TasteSourceReviewRisk(StrEnum):
    NONE = "none"
    DIRECT_PERSON_NAME = "direct-person-name"
    DIRECT_CONTACT = "direct-contact"
    INSTITUTION_UNIQUENESS = "institution-uniqueness"
    SENSITIVE_PERSONAL_INFORMATION = "sensitive-personal-information"
    FREE_TEXT_REIDENTIFICATION = "free-text-reidentification"
    OTHER_BOUNDED_RISK = "other-bounded-risk"


class TasteSourceReviewPolicy(BaseModel):
    """Frozen reviewer design; it grants neither recruitment nor admission."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    population_id: str = Field(pattern=_ID)
    scientific_reviewers_per_item: Literal[2] = 2
    privacy_reviewers_per_item: Literal[1] = 1
    required_decision_families: tuple[TasteTask, ...]
    allowed_domain_labels: tuple[TasteSourceDomainLabel, ...]
    minimum_eligible_groups_per_domain: int = Field(ge=1, le=1_000)
    domain_instruction: str = Field(min_length=1, max_length=4_000)
    decision_family_instructions: dict[TasteTask, str] = Field(min_length=6, max_length=6)
    quality_dimension_instructions: dict[ReferenceQualityDimension, str] = Field(
        min_length=5,
        max_length=5,
    )
    privacy_instruction: str = Field(min_length=1, max_length=4_000)
    cannot_assess_instruction: str = Field(min_length=1, max_length=4_000)
    adjudication_rule: str = Field(min_length=1, max_length=4_000)
    scientific_review_hides_publisher_subject: Literal[True] = True
    scientific_review_hides_recommendation: Literal[True] = True
    scientific_review_hides_author_response: Literal[True] = True
    scientific_review_hides_later_revision: Literal[True] = True
    scientific_review_hides_other_reviews: Literal[True] = True
    privacy_review_separate_from_scientific_review: Literal[True] = True
    ethics_determination_required_before_recruitment: Literal[True] = True
    compensation_and_consent_required_before_recruitment: Literal[True] = True
    authorizes_reviewer_recruitment: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def policy_is_complete(self) -> TasteSourceReviewPolicy:
        if set(self.required_decision_families) != set(TasteTask):
            raise ValueError("Taste source review must retain all six decision families")
        if len(self.required_decision_families) != len(set(self.required_decision_families)):
            raise ValueError("Taste source review decision families must be unique")
        labels = set(self.allowed_domain_labels)
        missingness = {
            TasteSourceDomainLabel.OTHER,
            TasteSourceDomainLabel.CANNOT_ASSESS,
        }
        if not missingness.issubset(labels) or not labels.difference(missingness):
            raise ValueError("Taste source review must retain target and missingness labels")
        if len(self.allowed_domain_labels) != len(set(self.allowed_domain_labels)):
            raise ValueError("Taste source review domain labels must be unique")
        if set(self.decision_family_instructions) != set(TasteTask):
            raise ValueError("Taste source review lacks decision-family anchors")
        if set(self.quality_dimension_instructions) != set(ReferenceQualityDimension):
            raise ValueError("Taste source review lacks quality-dimension anchors")
        return self

    @computed_field
    @property
    def policy_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))


class TasteSourceReviewFileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)
    bytes: int = Field(gt=0, le=_MAX_ITEMS_BYTES)

    @model_validator(mode="after")
    def locator_is_relative(self) -> TasteSourceReviewFileBinding:
        _relative_locator(self.locator)
        return self


class ScientificTasteSourceReviewItem(BaseModel):
    """Outcome- and publisher-blind episode shown to scientific reviewers."""

    model_config = _EXACT_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    review_item_id: str = Field(pattern=_ID)
    article_title: str = Field(min_length=1, max_length=8_000)
    reviewed_abstract: str = Field(min_length=1, max_length=8_000)
    review_comment: str = Field(min_length=1, max_length=8_000)
    publisher_subject_hidden: Literal[True] = True
    recommendation_hidden: Literal[True] = True
    author_response_hidden: Literal[True] = True
    later_revision_hidden: Literal[True] = True
    source_identity_hidden: Literal[True] = True
    prestige_signals_hidden: Literal[True] = True


class PrivacyTasteSourceReviewItem(BaseModel):
    """Complete de-identified text shown only to the release privacy reviewer."""

    model_config = _EXACT_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    review_item_id: str = Field(pattern=_ID)
    article_title: str = Field(min_length=1, max_length=8_000)
    reviewed_abstract: str = Field(min_length=1, max_length=8_000)
    revised_abstract: str = Field(min_length=1, max_length=8_000)
    review_comment: str = Field(min_length=1, max_length=8_000)
    author_response: str | None = Field(default=None, max_length=8_000)
    structured_author_identity_removed: Literal[True] = True
    structured_reviewer_identity_removed: Literal[True] = True
    source_identity_hidden: Literal[True] = True


class TasteSourcePrivateMapItem(BaseModel):
    model_config = _CONFIG

    review_item_id: str = Field(pattern=_ID)
    candidate_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    publisher_subject: str = Field(pattern=_ID)
    observed_recommendation: str = Field(pattern=_ID)


class TasteSourceReviewCampaign(BaseModel):
    """Self-hashed bindings for one review campaign before human contact."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    population_id: str = Field(pattern=_ID)
    population_report_file_sha256: str = Field(pattern=_SHA256)
    population_report_sha256: str = Field(pattern=_SHA256)
    candidate_file_sha256: str = Field(pattern=_SHA256)
    policy_file_sha256: str = Field(pattern=_SHA256)
    policy_sha256: str = Field(pattern=_SHA256)
    compiler_implementation_sha256: str = Field(pattern=_SHA256)
    reviewer_interface_sha256: str = Field(pattern=_SHA256)
    prepared_at: datetime
    candidate_count: int = Field(gt=0, le=100_000)
    source_group_count: int = Field(gt=0, le=100_000)
    publisher_subject_group_counts: dict[str, int] = Field(min_length=1, max_length=100)
    scientific_items: TasteSourceReviewFileBinding
    privacy_items: TasteSourceReviewFileBinding
    private_item_map: TasteSourceReviewFileBinding
    policy_document: TasteSourceReviewFileBinding
    reviewer_interface: TasteSourceReviewFileBinding
    preparation_verification_input: VerificationDecisionInput
    preparation_verification: VerificationDecision
    recruitment_verification_input: VerificationDecisionInput
    recruitment_verification: VerificationDecision
    required_scientific_reviewer_count: Literal[2] = 2
    required_privacy_reviewer_count: Literal[1] = 1
    required_scientific_assessment_count: int = Field(gt=0)
    required_privacy_assessment_count: int = Field(gt=0)
    reviewer_sessions_prepared: Literal[0] = 0
    reviewer_submissions_collected: Literal[0] = 0
    recruitment_status: Literal["owner-and-ethics-approval-required"] = (
        "owner-and-ethics-approval-required"
    )
    source_outcomes_hidden_from_scientific_review: Literal[True] = True
    project_owned: Literal[True] = True
    ready_for_taste_abstraction_review: Literal[False] = False
    ready_for_benchmark_admission: Literal[False] = False
    model_calls_performed: Literal[False] = False
    api_spend_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    human_recruitment_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    standalone_preflight_performed: Literal[False] = False
    campaign_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def campaign_is_closed(self) -> TasteSourceReviewCampaign:
        if self.prepared_at.utcoffset() is None:
            raise ValueError("Taste source review campaign time must include a timezone")
        if self.source_group_count != sum(self.publisher_subject_group_counts.values()):
            raise ValueError("Taste source review source-group counts are inconsistent")
        if self.required_scientific_assessment_count != 2 * self.candidate_count:
            raise ValueError("Taste source review scientific workload is inconsistent")
        if self.required_privacy_assessment_count != self.candidate_count:
            raise ValueError("Taste source review privacy workload is inconsistent")
        if self.reviewer_interface_sha256 != self.reviewer_interface.sha256:
            raise ValueError("Taste source review interface identity is inconsistent")
        if self.policy_file_sha256 != self.policy_document.sha256:
            raise ValueError("Taste source review policy identity is inconsistent")
        for action, decision in (
            (self.preparation_verification_input, self.preparation_verification),
            (self.recruitment_verification_input, self.recruitment_verification),
        ):
            if decision != decide_verification_route(action):
                raise ValueError("Taste source review verification route differs from policy")
        if self.preparation_verification.route is not VerificationRoute.DIRECT_PATH:
            raise ValueError("local review-package preparation must remain direct")
        if self.recruitment_verification.route is not VerificationRoute.OWNER_APPROVAL:
            raise ValueError("human recruitment must remain owner-gated")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"campaign_sha256"}))
        if self.campaign_sha256 != expected:
            raise ValueError("Taste source review campaign hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteSourceReviewCampaign:
        payload = {"schema_version": "1.0", **values}
        payload.pop("campaign_sha256", None)
        unsigned = cls.model_construct(campaign_sha256="0" * 64, **payload)
        digest = _canonical_sha256(unsigned.model_dump(mode="json", exclude={"campaign_sha256"}))
        return cls(**payload, campaign_sha256=digest)


class TasteSourceReviewActivation(BaseModel):
    """Owner/ethics authorization for contacting exactly three reviewers."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    activation_id: str = Field(pattern=_ID)
    campaign_id: str = Field(pattern=_ID)
    campaign_sha256: str = Field(pattern=_SHA256)
    project_id: str = Field(pattern=_ID)
    scientific_reviewer_identity_sha256s: tuple[str, str]
    privacy_reviewer_identity_sha256: str = Field(pattern=_SHA256)
    ethics_status: Literal["approved", "not-required"]
    ethics_determination_ref: str = Field(min_length=1, max_length=1_000)
    compensation_terms_confirmed: Literal[True] = True
    consent_terms_confirmed: Literal[True] = True
    retention_and_withdrawal_terms_confirmed: Literal[True] = True
    conflicts_screened: Literal[True] = True
    maximum_reviewer_hours: float = Field(gt=0, le=1_000)
    approved_at: datetime
    owner_confirmed: Literal[True] = True
    authorizes_reviewer_recruitment: Literal[True] = True
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False
    activation_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def activation_is_closed(self) -> TasteSourceReviewActivation:
        if self.approved_at.utcoffset() is None:
            raise ValueError("Taste source review approval time must include a timezone")
        reviewers = (
            *self.scientific_reviewer_identity_sha256s,
            self.privacy_reviewer_identity_sha256,
        )
        if len(set(reviewers)) != 3 or any(
            re.fullmatch(_SHA256, item) is None for item in reviewers
        ):
            raise ValueError("Taste source review activation requires three distinct hashes")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"activation_sha256"}))
        if self.activation_sha256 != expected:
            raise ValueError("Taste source review activation hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteSourceReviewActivation:
        payload = {"schema_version": "1.0", **values}
        payload.pop("activation_sha256", None)
        unsigned = cls.model_construct(activation_sha256="0" * 64, **payload)
        digest = _canonical_sha256(unsigned.model_dump(mode="json", exclude={"activation_sha256"}))
        return cls(**payload, activation_sha256=digest)


class TasteSourceReviewSession(BaseModel):
    """One reviewer-specific local session; creating it does not contact anyone."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(pattern=_ID)
    campaign_id: str = Field(pattern=_ID)
    campaign_sha256: str = Field(pattern=_SHA256)
    role: TasteSourceReviewRole
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    reviewer_interface_sha256: str = Field(pattern=_SHA256)
    prepared_at: datetime
    items: tuple[ScientificTasteSourceReviewItem | PrivacyTasteSourceReviewItem, ...] = Field(
        min_length=1,
        max_length=100_000,
    )
    publisher_subject_hidden: bool
    recommendation_hidden: bool
    author_response_hidden: bool
    later_revision_hidden: bool
    domain_instruction: str = Field(min_length=1, max_length=4_000)
    decision_family_instructions: dict[TasteTask, str] = Field(min_length=6, max_length=6)
    quality_dimension_instructions: dict[ReferenceQualityDimension, str] = Field(
        min_length=5,
        max_length=5,
    )
    privacy_instruction: str = Field(min_length=1, max_length=4_000)
    cannot_assess_instruction: str = Field(min_length=1, max_length=4_000)
    other_reviewer_data_absent: Literal[True] = True
    authorizes_reviewer_contact: Literal[False] = False
    authorizes_source_admission: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def session_matches_role(self) -> TasteSourceReviewSession:
        if self.prepared_at.utcoffset() is None:
            raise ValueError("Taste source review session time must include a timezone")
        ids = [item.review_item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Taste source review session item IDs must be unique")
        scientific = self.role is TasteSourceReviewRole.SCIENTIFIC
        scientific_items = all(
            isinstance(item, ScientificTasteSourceReviewItem) for item in self.items
        )
        if scientific != scientific_items:
            raise ValueError("Taste source review session items differ from its role")
        if not scientific and not all(
            isinstance(item, PrivacyTasteSourceReviewItem) for item in self.items
        ):
            raise ValueError("Taste privacy session contains scientific items")
        blind_flags = (
            self.publisher_subject_hidden,
            self.recommendation_hidden,
            self.author_response_hidden,
            self.later_revision_hidden,
        )
        if scientific and not all(blind_flags):
            raise ValueError("scientific source review must hide publisher and outcome fields")
        if not scientific and any(blind_flags):
            raise ValueError("privacy source review must see all de-identified free text")
        if set(self.decision_family_instructions) != set(TasteTask) or set(
            self.quality_dimension_instructions
        ) != set(ReferenceQualityDimension):
            raise ValueError("Taste source review session rubric is incomplete")
        return self

    @computed_field
    @property
    def session_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"session_sha256"}))


class TasteSourceDimensionResponse(BaseModel):
    model_config = _CONFIG

    dimension: ReferenceQualityDimension
    rating: ReferenceQualityRating


class ScientificTasteSourceResponse(BaseModel):
    model_config = _CONFIG

    review_item_id: str = Field(pattern=_ID)
    domain_label: TasteSourceDomainLabel
    primary_decision_family: TasteTask | Literal["cannot-assess"]
    dimension_ratings: tuple[TasteSourceDimensionResponse, ...] = Field(
        min_length=5,
        max_length=5,
    )
    transferable_taste_candidate: bool
    rationale: str = Field(min_length=1, max_length=4_000)
    duration_seconds: int = Field(gt=0, le=7 * 24 * 60 * 60)

    @model_validator(mode="after")
    def scientific_response_is_closed(self) -> ScientificTasteSourceResponse:
        dimensions = [item.dimension for item in self.dimension_ratings]
        if set(dimensions) != set(ReferenceQualityDimension) or len(dimensions) != len(
            set(dimensions)
        ):
            raise ValueError("scientific source review must rate every quality dimension once")
        all_strong = all(
            item.rating is ReferenceQualityRating.STRONG for item in self.dimension_ratings
        )
        complete_labels = (
            self.domain_label is not TasteSourceDomainLabel.CANNOT_ASSESS
            and self.primary_decision_family != "cannot-assess"
        )
        if self.transferable_taste_candidate and not (all_strong and complete_labels):
            raise ValueError("transferable Taste requires strong dimensions and complete labels")
        return self


class PrivacyTasteSourceResponse(BaseModel):
    model_config = _CONFIG

    review_item_id: str = Field(pattern=_ID)
    release_safe: bool
    risk_codes: tuple[TasteSourceReviewRisk, ...] = Field(min_length=1, max_length=7)
    rationale: str = Field(min_length=1, max_length=4_000)
    duration_seconds: int = Field(gt=0, le=7 * 24 * 60 * 60)

    @model_validator(mode="after")
    def privacy_response_is_closed(self) -> PrivacyTasteSourceResponse:
        if len(self.risk_codes) != len(set(self.risk_codes)):
            raise ValueError("privacy review risk codes must be unique")
        none_only = self.risk_codes == (TasteSourceReviewRisk.NONE,)
        if self.release_safe != none_only:
            raise ValueError("privacy release decision differs from its risk codes")
        return self


class TasteSourceReviewSubmission(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(pattern=_ID)
    session_sha256: str = Field(pattern=_SHA256)
    campaign_sha256: str = Field(pattern=_SHA256)
    role: TasteSourceReviewRole
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    review_started_at: datetime
    submitted_at: datetime
    scientific_responses: tuple[ScientificTasteSourceResponse, ...] = ()
    privacy_responses: tuple[PrivacyTasteSourceResponse, ...] = ()
    conflict_cleared: Literal[True] = True
    independent_review: Literal[True] = True
    blinded_to_other_reviews: Literal[True] = True
    blinded_to_publisher_subject: bool
    blinded_to_observed_outcomes: bool
    consent_terms_accepted: Literal[True] = True
    explicit_lock_confirmed: Literal[True] = True

    @model_validator(mode="after")
    def submission_matches_role(self) -> TasteSourceReviewSubmission:
        if (
            self.review_started_at.utcoffset() is None
            or self.submitted_at.utcoffset() is None
            or self.submitted_at < self.review_started_at
        ):
            raise ValueError("Taste source review submission timestamps are invalid")
        scientific = self.role is TasteSourceReviewRole.SCIENTIFIC
        if scientific:
            if not self.scientific_responses or self.privacy_responses:
                raise ValueError("scientific submission must contain only scientific responses")
            if not self.blinded_to_publisher_subject or not self.blinded_to_observed_outcomes:
                raise ValueError("scientific submission must attest both blind conditions")
            responses: tuple[ScientificTasteSourceResponse | PrivacyTasteSourceResponse, ...] = (
                self.scientific_responses
            )
        else:
            if not self.privacy_responses or self.scientific_responses:
                raise ValueError("privacy submission must contain only privacy responses")
            if self.blinded_to_publisher_subject or self.blinded_to_observed_outcomes:
                raise ValueError("privacy submission cannot claim scientific outcome blinding")
            responses = self.privacy_responses
        ids = [item.review_item_id for item in responses]
        if len(ids) != len(set(ids)):
            raise ValueError("Taste source review submission item IDs must be unique")
        return self


class TasteSourceReviewItemResult(BaseModel):
    model_config = _CONFIG

    review_item_id: str = Field(pattern=_ID)
    candidate_id: str = Field(pattern=_ID)
    source_group_id: str = Field(pattern=_ID)
    publisher_subject: str = Field(pattern=_ID)
    independent_domain_confirmed: bool
    agreed_domain_label: TasteSourceDomainLabel | None
    dual_quality_review_passed: bool
    decision_family_agreed: bool
    agreed_decision_family: TasteTask | None
    privacy_review_passed: bool
    eligible_for_taste_abstraction_review: bool
    adjudication_required: bool
    blocker_codes: tuple[str, ...]


class TasteSourceReviewResult(BaseModel):
    """Locked human result; it still cannot admit a benchmark or abstraction."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    campaign_id: str = Field(pattern=_ID)
    campaign_sha256: str = Field(pattern=_SHA256)
    project_id: str = Field(pattern=_ID)
    population_id: str = Field(pattern=_ID)
    locked_at: datetime
    scientific_reviewer_count: Literal[2] = 2
    privacy_reviewer_count: Literal[1] = 1
    reviewer_identity_sha256s: tuple[str, str, str]
    candidate_count: int = Field(gt=0)
    domain_confirmed_count: int = Field(ge=0)
    dual_quality_passed_count: int = Field(ge=0)
    decision_family_agreed_count: int = Field(ge=0)
    privacy_passed_count: int = Field(ge=0)
    eligible_candidate_count: int = Field(ge=0)
    adjudication_required_count: int = Field(ge=0)
    eligible_source_group_counts: dict[str, int]
    decision_family_counts: dict[str, int]
    required_decision_family_coverage_met: bool
    eligible_group_floor_met: bool
    ready_for_taste_abstraction_review: bool
    ready_for_benchmark_admission: Literal[False] = False
    items: tuple[TasteSourceReviewItemResult, ...]
    activation_file: TasteSourceReviewFileBinding
    session_files: tuple[TasteSourceReviewFileBinding, ...] = Field(min_length=3, max_length=3)
    submission_files: tuple[TasteSourceReviewFileBinding, ...] = Field(
        min_length=3,
        max_length=3,
    )
    model_calls_performed: Literal[False] = False
    api_spend_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    result_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def result_is_closed(self) -> TasteSourceReviewResult:
        if self.locked_at.utcoffset() is None:
            raise ValueError("Taste source review lock time must include a timezone")
        if len(set(self.reviewer_identity_sha256s)) != 3:
            raise ValueError("scientific and privacy reviewers must be distinct")
        if self.candidate_count != len(self.items):
            raise ValueError("Taste source review result item count is inconsistent")
        counters = {
            "domain_confirmed_count": sum(item.independent_domain_confirmed for item in self.items),
            "dual_quality_passed_count": sum(
                item.dual_quality_review_passed for item in self.items
            ),
            "decision_family_agreed_count": sum(item.decision_family_agreed for item in self.items),
            "privacy_passed_count": sum(item.privacy_review_passed for item in self.items),
            "eligible_candidate_count": sum(
                item.eligible_for_taste_abstraction_review for item in self.items
            ),
            "adjudication_required_count": sum(item.adjudication_required for item in self.items),
        }
        if any(getattr(self, key) != value for key, value in counters.items()):
            raise ValueError("Taste source review aggregate counts are inconsistent")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("Taste source review result hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TasteSourceReviewResult:
        payload = {"schema_version": "1.0", **values}
        payload.pop("result_sha256", None)
        unsigned = cls.model_construct(result_sha256="0" * 64, **payload)
        digest = _canonical_sha256(unsigned.model_dump(mode="json", exclude={"result_sha256"}))
        return cls(**payload, result_sha256=digest)


def load_taste_source_review_policy(path: str | Path) -> TasteSourceReviewPolicy:
    resolved = _bounded_file(Path(path), maximum_bytes=_MAX_POLICY_BYTES)
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Taste source review policy must contain a mapping")
    recorded = payload.pop("policy_sha256", None)
    policy = TasteSourceReviewPolicy.model_validate(payload)
    if recorded is not None and recorded != policy.policy_sha256:
        raise ValueError("Taste source review policy hash mismatch")
    return policy


def prepare_taste_source_review_campaign(
    *,
    population_report_path: str | Path,
    policy_path: str | Path,
    output_dir: str | Path,
    prepared_at: datetime | None = None,
) -> TasteSourceReviewCampaign:
    """Prepare exact blind review projections without model or human action."""

    report_path = _bounded_file(Path(population_report_path), maximum_bytes=_MAX_CONTROL_BYTES)
    report = _load_supported_population_report(report_path)
    candidate_path = _bounded_file(
        report_path.parent / report.candidate_file,
        maximum_bytes=_MAX_ITEMS_BYTES,
    )
    if _sha256_file(candidate_path) != report.candidate_file_sha256:
        raise ValueError("Taste source review candidate bytes differ from population")
    policy_file = _bounded_file(Path(policy_path), maximum_bytes=_MAX_POLICY_BYTES)
    policy = load_taste_source_review_policy(policy_file)
    if policy.project_id != report.project_id or policy.population_id != report.population_id:
        raise ValueError("Taste source review policy targets another population")
    candidates = _load_candidates(candidate_path, report)
    source_group_count, source_group_counts = _population_group_counts(report)

    scientific_items: list[ScientificTasteSourceReviewItem] = []
    privacy_items: list[PrivacyTasteSourceReviewItem] = []
    item_map: list[TasteSourcePrivateMapItem] = []
    for candidate in candidates:
        (
            article_title,
            reviewed_abstract,
            revised_abstract,
            review_comment,
            author_response,
            source_stratum,
            observed_outcome,
        ) = _candidate_review_projection(candidate)
        review_item_id = (
            "item-" + _canonical_sha256([report.report_sha256, candidate.candidate_id])[:24]
        )
        scientific_items.append(
            ScientificTasteSourceReviewItem(
                review_item_id=review_item_id,
                article_title=article_title,
                reviewed_abstract=reviewed_abstract,
                review_comment=review_comment,
            )
        )
        privacy_items.append(
            PrivacyTasteSourceReviewItem(
                review_item_id=review_item_id,
                article_title=article_title,
                reviewed_abstract=reviewed_abstract,
                revised_abstract=revised_abstract,
                review_comment=review_comment,
                author_response=author_response,
            )
        )
        item_map.append(
            TasteSourcePrivateMapItem(
                review_item_id=review_item_id,
                candidate_id=candidate.candidate_id,
                source_group_id=candidate.source_group_id,
                publisher_subject=source_stratum,
                observed_recommendation=observed_outcome,
            )
        )

    target = Path(output_dir)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".staging", dir=target.parent)
    )
    try:
        scientific_path = staging / "SCIENTIFIC_ITEMS.jsonl"
        privacy_path = staging / "PRIVACY_ITEMS.jsonl"
        map_path = staging / "PRIVATE_ITEM_MAP.json"
        policy_copy_path = staging / "POLICY.yaml"
        interface_path = staging / "REVIEWER_INTERFACE.html"
        _write_new(scientific_path, _jsonl_bytes(scientific_items))
        _write_new(privacy_path, _jsonl_bytes(privacy_items))
        _write_new(
            map_path,
            _canonical_json(
                {
                    "schema_version": "1.0",
                    "items": [item.model_dump(mode="json") for item in item_map],
                }
            )
            + b"\n",
        )
        _write_new(policy_copy_path, policy_file.read_bytes())
        _write_new(interface_path, _interface_bytes())
        preparation_input = VerificationDecisionInput(
            action_id="prepare-taste-source-review-package",
            reversibility=ActionReversibility.REVERSIBLE,
            effects=(ActionEffect.FILESYSTEM_WRITE,),
            evidence_state="current",
            semantic_uncertainty="low",
            failure_probability=0.02,
            failure_impact_units=10,
            targeted_check_cost_units=0.5,
            targeted_detection_probability=0.8,
            full_preflight_cost_units=2,
            full_preflight_detection_probability=0.95,
        )
        recruitment_input = VerificationDecisionInput(
            action_id="recruit-taste-source-reviewers",
            reversibility=ActionReversibility.IRREVERSIBLE,
            effects=(
                ActionEffect.EXTERNAL_MUTATION,
                ActionEffect.DECLARED_OWNER_BOUNDARY,
            ),
            evidence_state="current",
            semantic_uncertainty="medium",
            failure_probability=0.08,
            failure_impact_units=80,
            targeted_check_cost_units=1,
            targeted_detection_probability=0.8,
            full_preflight_cost_units=4,
            full_preflight_detection_probability=0.95,
        )
        campaign = TasteSourceReviewCampaign.create(
            campaign_id=policy.policy_id,
            project_id=report.project_id,
            population_id=report.population_id,
            population_report_file_sha256=_sha256_file(report_path),
            population_report_sha256=report.report_sha256,
            candidate_file_sha256=report.candidate_file_sha256,
            policy_file_sha256=_sha256_file(policy_file),
            policy_sha256=policy.policy_sha256,
            compiler_implementation_sha256=_sha256_file(Path(__file__)),
            reviewer_interface_sha256=hashlib.sha256(_interface_bytes()).hexdigest(),
            prepared_at=prepared_at or datetime.now(UTC),
            candidate_count=len(candidates),
            source_group_count=source_group_count,
            publisher_subject_group_counts=source_group_counts,
            scientific_items=_binding(staging, scientific_path),
            privacy_items=_binding(staging, privacy_path),
            private_item_map=_binding(staging, map_path),
            policy_document=_binding(staging, policy_copy_path),
            reviewer_interface=_binding(staging, interface_path),
            preparation_verification_input=preparation_input,
            preparation_verification=decide_verification_route(preparation_input),
            recruitment_verification_input=recruitment_input,
            recruitment_verification=decide_verification_route(recruitment_input),
            required_scientific_assessment_count=2 * len(candidates),
            required_privacy_assessment_count=len(candidates),
        )
        _write_new(
            staging / "CAMPAIGN.json",
            _canonical_json(campaign.model_dump(mode="json", exclude_computed_fields=True)) + b"\n",
        )
        os.rename(staging, target)
        return campaign
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_taste_source_review_campaign(path: str | Path) -> TasteSourceReviewCampaign:
    source = _bounded_file(Path(path), maximum_bytes=_MAX_CONTROL_BYTES)
    campaign = TasteSourceReviewCampaign.model_validate_json(source.read_bytes())
    root = source.parent.resolve(strict=True)
    for binding in (
        campaign.scientific_items,
        campaign.privacy_items,
        campaign.private_item_map,
        campaign.policy_document,
        campaign.reviewer_interface,
    ):
        _bound_file(root, binding)
    return campaign


def load_taste_source_review_private_map(
    path: str | Path,
) -> tuple[TasteSourcePrivateMapItem, ...]:
    """Load the owner-private item map bound to one immutable campaign."""

    source = _bounded_file(Path(path), maximum_bytes=_MAX_CONTROL_BYTES)
    campaign = load_taste_source_review_campaign(source)
    root = source.parent.resolve(strict=True)
    return _load_private_map(_bound_file(root, campaign.private_item_map))


def load_taste_source_review_items(
    path: str | Path,
    role: TasteSourceReviewRole,
) -> tuple[ScientificTasteSourceReviewItem | PrivacyTasteSourceReviewItem, ...]:
    """Load the exact reviewer-visible projection bound to one campaign."""

    source = _bounded_file(Path(path), maximum_bytes=_MAX_CONTROL_BYTES)
    campaign = load_taste_source_review_campaign(source)
    root = source.parent.resolve(strict=True)
    binding = (
        campaign.scientific_items
        if role is TasteSourceReviewRole.SCIENTIFIC
        else campaign.privacy_items
    )
    item_type = (
        ScientificTasteSourceReviewItem
        if role is TasteSourceReviewRole.SCIENTIFIC
        else PrivacyTasteSourceReviewItem
    )
    return _load_jsonl(_bound_file(root, binding), item_type)


def load_taste_source_review_activation(path: str | Path) -> TasteSourceReviewActivation:
    source = _bounded_file(Path(path), maximum_bytes=_MAX_CONTROL_BYTES)
    return TasteSourceReviewActivation.model_validate_json(source.read_bytes())


def prepare_taste_source_review_session(
    *,
    campaign_path: str | Path,
    role: TasteSourceReviewRole,
    reviewer_identity_sha256: str,
    output_dir: str | Path,
    assigned_item_ids: tuple[str, ...] | None = None,
    prepared_at: datetime | None = None,
) -> TasteSourceReviewSession:
    """Create a local reviewer workspace; this does not authorize contacting them."""

    if not re.fullmatch(_SHA256, reviewer_identity_sha256):
        raise ValueError("reviewer identity must be a SHA-256 pseudonym")
    campaign_file = _bounded_file(Path(campaign_path), maximum_bytes=_MAX_CONTROL_BYTES)
    campaign = load_taste_source_review_campaign(campaign_file)
    root = campaign_file.parent.resolve(strict=True)
    policy = _load_bound_policy(root, campaign)
    binding = (
        campaign.scientific_items
        if role is TasteSourceReviewRole.SCIENTIFIC
        else campaign.privacy_items
    )
    item_type = (
        ScientificTasteSourceReviewItem
        if role is TasteSourceReviewRole.SCIENTIFIC
        else PrivacyTasteSourceReviewItem
    )
    items = _load_jsonl(_bound_file(root, binding), item_type)
    scope_identity = "full-campaign"
    if assigned_item_ids is not None:
        if not assigned_item_ids or len(assigned_item_ids) != len(set(assigned_item_ids)):
            raise ValueError("assigned taste source-review item IDs must be nonempty and unique")
        requested = set(assigned_item_ids)
        available = {item.review_item_id for item in items}
        missing = requested - available
        if missing:
            raise ValueError(
                "assigned taste source-review item IDs are outside the campaign: "
                + ", ".join(sorted(missing))
            )
        items = [item for item in items if item.review_item_id in requested]
        scope_identity = _canonical_sha256(sorted(requested))
    ordered = tuple(
        sorted(
            items,
            key=lambda item: _canonical_sha256(
                [
                    campaign.campaign_sha256,
                    role.value,
                    reviewer_identity_sha256,
                    item.review_item_id,
                ]
            ),
        )
    )
    blind = role is TasteSourceReviewRole.SCIENTIFIC
    identity_components = [
        campaign.campaign_sha256,
        role.value,
        reviewer_identity_sha256,
    ]
    if assigned_item_ids is not None:
        identity_components.append(scope_identity)
    identity = _canonical_sha256(identity_components)
    session = TasteSourceReviewSession(
        session_id=f"session-{identity[:24]}",
        campaign_id=campaign.campaign_id,
        campaign_sha256=campaign.campaign_sha256,
        role=role,
        reviewer_identity_sha256=reviewer_identity_sha256,
        reviewer_interface_sha256=campaign.reviewer_interface_sha256,
        prepared_at=prepared_at or datetime.now(UTC),
        items=ordered,
        publisher_subject_hidden=blind,
        recommendation_hidden=blind,
        author_response_hidden=blind,
        later_revision_hidden=blind,
        domain_instruction=policy.domain_instruction,
        decision_family_instructions=policy.decision_family_instructions,
        quality_dimension_instructions=policy.quality_dimension_instructions,
        privacy_instruction=policy.privacy_instruction,
        cannot_assess_instruction=policy.cannot_assess_instruction,
    )
    target = Path(output_dir)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".staging", dir=target.parent)
    )
    try:
        payload = session.model_dump(mode="json", exclude={"session_sha256"})
        _write_new(
            staging / "session.json",
            json.dumps(payload, indent=2, ensure_ascii=False).encode() + b"\n",
        )
        template = _bound_file(root, campaign.reviewer_interface).read_text(encoding="utf-8")
        embedded = json.dumps(
            {**payload, "session_sha256": session.session_sha256},
            ensure_ascii=False,
        ).replace("<", "\\u003c")
        rendered = template.replace("__SCITASTE_TASTE_SOURCE_SESSION__", embedded)
        if "__SCITASTE_TASTE_SOURCE_SESSION__" in rendered:
            raise ValueError("Taste source review UI template was not fully rendered")
        _write_new(staging / "review.html", rendered.encode())
        os.rename(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return session


def lock_taste_source_review_submissions(
    *,
    campaign_path: str | Path,
    activation_path: str | Path,
    scientific_session_paths: tuple[str | Path, str | Path],
    scientific_submission_paths: tuple[str | Path, str | Path],
    privacy_session_path: str | Path,
    privacy_submission_path: str | Path,
    output_path: str | Path,
    locked_at: datetime | None = None,
) -> TasteSourceReviewResult:
    """Lock exact independent judgments and derive candidate eligibility."""

    campaign_file = _bounded_file(Path(campaign_path), maximum_bytes=_MAX_CONTROL_BYTES)
    campaign = load_taste_source_review_campaign(campaign_file)
    root = campaign_file.parent.resolve(strict=True)
    activation_file = _contained_file(
        root,
        Path(activation_path),
        maximum_bytes=_MAX_CONTROL_BYTES,
    )
    activation = load_taste_source_review_activation(activation_file)
    if (
        activation.campaign_id != campaign.campaign_id
        or activation.campaign_sha256 != campaign.campaign_sha256
        or activation.project_id != campaign.project_id
    ):
        raise ValueError("Taste source review activation targets another campaign")
    session_paths = (
        *(Path(item) for item in scientific_session_paths),
        Path(privacy_session_path),
    )
    submission_paths = (
        *(Path(item) for item in scientific_submission_paths),
        Path(privacy_submission_path),
    )
    sessions = tuple(
        TasteSourceReviewSession.model_validate_json(
            _contained_file(root, path, maximum_bytes=_MAX_ITEMS_BYTES).read_bytes()
        )
        for path in session_paths
    )
    submissions = tuple(
        TasteSourceReviewSubmission.model_validate_json(
            _contained_file(root, path, maximum_bytes=_MAX_ITEMS_BYTES).read_bytes()
        )
        for path in submission_paths
    )
    if tuple(session.role for session in sessions) != (
        TasteSourceReviewRole.SCIENTIFIC,
        TasteSourceReviewRole.SCIENTIFIC,
        TasteSourceReviewRole.PRIVACY,
    ):
        raise ValueError("Taste source review requires two scientific and one privacy session")
    reviewer_ids = tuple(session.reviewer_identity_sha256 for session in sessions)
    if len(set(reviewer_ids)) != 3:
        raise ValueError("Taste source review requires three distinct reviewers")
    if reviewer_ids != (
        *activation.scientific_reviewer_identity_sha256s,
        activation.privacy_reviewer_identity_sha256,
    ):
        raise ValueError("Taste source review sessions differ from approved reviewers")
    expected_ids = _campaign_item_ids(root, campaign)
    scientific_by_item: dict[str, list[ScientificTasteSourceResponse]] = defaultdict(list)
    privacy_by_item: dict[str, PrivacyTasteSourceResponse] = {}
    for session, submission in zip(sessions, submissions, strict=True):
        _verify_session(campaign, root, session)
        if (
            submission.session_id != session.session_id
            or submission.session_sha256 != session.session_sha256
            or submission.campaign_sha256 != campaign.campaign_sha256
            or submission.role is not session.role
            or submission.reviewer_identity_sha256 != session.reviewer_identity_sha256
        ):
            raise ValueError("Taste source review submission differs from its exact session")
        session_ids = {item.review_item_id for item in session.items}
        if session_ids != expected_ids:
            raise ValueError("Taste source review session does not cover the campaign")
        responses: tuple[ScientificTasteSourceResponse | PrivacyTasteSourceResponse, ...] = (
            submission.scientific_responses
            if session.role is TasteSourceReviewRole.SCIENTIFIC
            else submission.privacy_responses
        )
        if {item.review_item_id for item in responses} != expected_ids:
            raise ValueError("Taste source review submission does not cover the campaign")
        if session.role is TasteSourceReviewRole.SCIENTIFIC:
            for response in submission.scientific_responses:
                scientific_by_item[response.review_item_id].append(response)
        else:
            privacy_by_item = {item.review_item_id: item for item in submission.privacy_responses}

    private_items = _load_private_map(_bound_file(root, campaign.private_item_map))
    results: list[TasteSourceReviewItemResult] = []
    eligible_groups: dict[str, set[str]] = defaultdict(set)
    family_counts: Counter[str] = Counter()
    for private in private_items:
        scientific = scientific_by_item[private.review_item_id]
        if len(scientific) != 2:
            raise ValueError("Taste source review item lacks dual scientific review")
        privacy = privacy_by_item[private.review_item_id]
        domains = {item.domain_label for item in scientific}
        domain_agreement = len(domains) == 1
        agreed_domain = next(iter(domains)) if domain_agreement else None
        domain_confirmed = bool(
            agreed_domain is not None and agreed_domain.value == private.publisher_subject
        )
        families = {item.primary_decision_family for item in scientific}
        family_agreement = len(families) == 1 and "cannot-assess" not in families
        agreed_family = next(iter(families)) if family_agreement else None
        if agreed_family is not None and not isinstance(agreed_family, TasteTask):
            agreed_family = TasteTask(agreed_family)
        quality_opinions = [
            item.transferable_taste_candidate
            and all(
                rating.rating is ReferenceQualityRating.STRONG for rating in item.dimension_ratings
            )
            for item in scientific
        ]
        quality_passed = all(quality_opinions)
        privacy_passed = privacy.release_safe
        blockers: list[str] = []
        if not domain_confirmed:
            blockers.append("independent-domain-review-failed")
        if not quality_passed:
            blockers.append("dual-quality-review-failed")
        if not family_agreement:
            blockers.append("decision-family-agreement-failed")
        if not privacy_passed:
            blockers.append("privacy-review-failed")
        adjudication = not domain_agreement or len(families) != 1 or len(set(quality_opinions)) != 1
        if adjudication:
            blockers.append("scientific-adjudication-required")
        eligible = not blockers
        if eligible:
            eligible_groups[private.publisher_subject].add(private.source_group_id)
            assert agreed_family is not None
            family_counts[agreed_family.value] += 1
        results.append(
            TasteSourceReviewItemResult(
                review_item_id=private.review_item_id,
                candidate_id=private.candidate_id,
                source_group_id=private.source_group_id,
                publisher_subject=private.publisher_subject,
                independent_domain_confirmed=domain_confirmed,
                agreed_domain_label=agreed_domain,
                dual_quality_review_passed=quality_passed,
                decision_family_agreed=family_agreement,
                agreed_decision_family=agreed_family,
                privacy_review_passed=privacy_passed,
                eligible_for_taste_abstraction_review=eligible,
                adjudication_required=adjudication,
                blocker_codes=tuple(blockers),
            )
        )
    eligible_group_counts = {
        domain: len(eligible_groups.get(domain, set()))
        for domain in sorted(campaign.publisher_subject_group_counts)
    }
    policy = _load_bound_policy(root, campaign)
    family_coverage = set(family_counts) == {item.value for item in TasteTask}
    group_floor = all(
        count >= policy.minimum_eligible_groups_per_domain
        for count in eligible_group_counts.values()
    )
    ready = (
        any(item.eligible_for_taste_abstraction_review for item in results)
        and family_coverage
        and group_floor
        and not any(item.adjudication_required for item in results)
    )
    session_bindings = tuple(_external_binding(root, path) for path in session_paths)
    submission_bindings = tuple(_external_binding(root, path) for path in submission_paths)
    result = TasteSourceReviewResult.create(
        campaign_id=campaign.campaign_id,
        campaign_sha256=campaign.campaign_sha256,
        project_id=campaign.project_id,
        population_id=campaign.population_id,
        locked_at=locked_at or datetime.now(UTC),
        reviewer_identity_sha256s=reviewer_ids,
        candidate_count=len(results),
        domain_confirmed_count=sum(item.independent_domain_confirmed for item in results),
        dual_quality_passed_count=sum(item.dual_quality_review_passed for item in results),
        decision_family_agreed_count=sum(item.decision_family_agreed for item in results),
        privacy_passed_count=sum(item.privacy_review_passed for item in results),
        eligible_candidate_count=sum(
            item.eligible_for_taste_abstraction_review for item in results
        ),
        adjudication_required_count=sum(item.adjudication_required for item in results),
        eligible_source_group_counts=eligible_group_counts,
        decision_family_counts=dict(family_counts),
        required_decision_family_coverage_met=family_coverage,
        eligible_group_floor_met=group_floor,
        ready_for_taste_abstraction_review=ready,
        items=tuple(sorted(results, key=lambda item: item.review_item_id)),
        activation_file=_external_binding(root, activation_file),
        session_files=session_bindings,
        submission_files=submission_bindings,
    )
    target = _new_contained_target(root, Path(output_path))
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    _atomic_json(target, result.model_dump(mode="json"))
    return result


def publish_taste_source_review_campaign_run(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    run_id: str,
    source_campaign_path: str | Path,
    expected_revision: int,
) -> tuple[ProjectSnapshot, TasteSourceReviewCampaign]:
    """Register the prepared no-contact campaign as project planning evidence."""

    validate_project_id(project_id)
    validate_entry_id(run_id, field_name="run_id")
    source_path = _bounded_file(Path(source_campaign_path), maximum_bytes=_MAX_CONTROL_BYTES)
    campaign = load_taste_source_review_campaign(source_path)
    if campaign.project_id != project_id:
        raise ValueError("Taste source review campaign belongs to another project")
    project_root = runtime.projects_root.joinpath(project_id).resolve(strict=True)
    if not source_path.is_relative_to(project_root):
        raise ValueError("Taste source review campaign must remain inside its project")
    snapshot = runtime.open(project_id)
    existing = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    artifact = f"runs/{run_id}/{_STAGE}/CAMPAIGN.json"
    if existing is not None and existing.status == "awaiting-independent-reviewers":
        observed = load_taste_source_review_campaign(project_root / artifact)
        if observed.campaign_sha256 != campaign.campaign_sha256:
            raise ValueError("registered Taste source review campaign differs")
        return snapshot, observed
    if existing is None:
        if snapshot.revision != expected_revision:
            raise ValueError("Taste source review publication uses a stale project revision")
        snapshot = runtime.begin_run(
            project_id,
            ProjectRun(
                run_id=run_id,
                provider="scitaste-native",
                model="natural-taste-source-review-campaign-v1",
                condition="independent-domain-quality-family-privacy-review",
                seed=0,
                status="preparing-independent-review-campaign",
                evidence_scope="outcome-blind-scientific-review-and-separate-privacy-review",
                stage_path=_STAGE,
                artifact=artifact,
                generative_ui_projection=_PROJECTION,
                campaign_id=campaign.campaign_id,
                campaign_sha256=campaign.campaign_sha256,
                population_id=campaign.population_id,
                authorizes_reviewer_recruitment=False,
                authorizes_model_calls=False,
                authorizes_experiment=False,
                no_reviewer_recruitment_performed=True,
                no_model_call_performed=True,
                no_gpu_work_performed=True,
                no_experiment_performed=True,
            ),
            expected_revision=expected_revision,
        )
    elif existing.status != "preparing-independent-review-campaign":
        raise ValueError("Taste source review campaign cannot resume from its state")
    target = project_root / "runs" / run_id / _STAGE
    if target.is_symlink():
        raise ValueError("Taste source review campaign target cannot be a symlink")
    target.mkdir(parents=True, exist_ok=True)
    source_root = source_path.parent
    for name in (
        "SCIENTIFIC_ITEMS.jsonl",
        "PRIVACY_ITEMS.jsonl",
        "PRIVATE_ITEM_MAP.json",
        "POLICY.yaml",
        "REVIEWER_INTERFACE.html",
        "CAMPAIGN.json",
    ):
        destination = target / name
        source = _bounded_file(source_root / name, maximum_bytes=_MAX_ITEMS_BYTES)
        if not destination.exists():
            _write_new(destination, source.read_bytes())
    observed = load_taste_source_review_campaign(target / "CAMPAIGN.json")
    if observed.campaign_sha256 != campaign.campaign_sha256:
        raise ValueError("published Taste source review campaign differs")
    snapshot = runtime.update_run(
        project_id,
        run_id,
        expected_revision=snapshot.revision,
        status="awaiting-independent-reviewers",
        campaign_sha256=campaign.campaign_sha256,
        candidate_count=campaign.candidate_count,
        source_group_count=campaign.source_group_count,
        required_scientific_reviewer_count=campaign.required_scientific_reviewer_count,
        required_privacy_reviewer_count=campaign.required_privacy_reviewer_count,
        required_scientific_assessment_count=(campaign.required_scientific_assessment_count),
        required_privacy_assessment_count=campaign.required_privacy_assessment_count,
        reviewer_sessions_prepared=0,
        reviewer_submissions_collected=0,
        recruitment_status=campaign.recruitment_status,
        ready_for_taste_abstraction_review=False,
        ready_for_benchmark_admission=False,
    )
    return snapshot, observed


def _load_candidates(
    path: Path,
    report: F1000TastePopulationReport | AriesTastePopulationReport,
) -> tuple[F1000TasteCandidate | AriesTasteCandidate, ...]:
    item_type = (
        AriesTasteCandidate
        if isinstance(report, AriesTastePopulationReport)
        else F1000TasteCandidate
    )
    values = _load_jsonl(path, item_type)
    ids = [item.candidate_id for item in values]
    if len(values) != report.candidate_count or len(ids) != len(set(ids)):
        raise ValueError("Taste source review candidates are incomplete or duplicated")
    return tuple(sorted(values, key=lambda item: item.candidate_id))


def _load_supported_population_report(
    path: Path,
) -> F1000TastePopulationReport | AriesTastePopulationReport:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("Taste source population report must contain a mapping")
    if "split_source_group_counts" in payload:
        return AriesTastePopulationReport.model_validate(payload)
    if "domain_source_group_counts" in payload:
        return F1000TastePopulationReport.model_validate(payload)
    raise ValueError("Taste source population is not a supported natural source")


def _population_group_counts(
    report: F1000TastePopulationReport | AriesTastePopulationReport,
) -> tuple[int, dict[str, int]]:
    if isinstance(report, AriesTastePopulationReport):
        return report.source_group_count, {
            TasteSourceDomainLabel.COMPUTING.value: report.source_group_count
        }
    return report.candidate_source_group_count, dict(report.domain_source_group_counts)


def _candidate_review_projection(
    candidate: F1000TasteCandidate | AriesTasteCandidate,
) -> tuple[str, str, str, str, str | None, str, str]:
    if isinstance(candidate, F1000TasteCandidate):
        return (
            candidate.article_title,
            candidate.reviewed_abstract,
            candidate.revised_abstract,
            candidate.review_comment,
            candidate.author_response,
            candidate.source_domain,
            candidate.recommendation,
        )
    revised_context = "\n\n".join(
        edit.target_text for edit in candidate.observed_edits if edit.target_text
    )
    return (
        "De-identified computing manuscript",
        candidate.paper_context,
        revised_context or candidate.paper_context,
        candidate.review_comment,
        None,
        TasteSourceDomainLabel.COMPUTING.value,
        candidate.observed_response,
    )


def _campaign_item_ids(root: Path, campaign: TasteSourceReviewCampaign) -> set[str]:
    scientific = _load_jsonl(
        _bound_file(root, campaign.scientific_items), ScientificTasteSourceReviewItem
    )
    privacy = _load_jsonl(_bound_file(root, campaign.privacy_items), PrivacyTasteSourceReviewItem)
    scientific_ids = {item.review_item_id for item in scientific}
    privacy_ids = {item.review_item_id for item in privacy}
    if scientific_ids != privacy_ids or len(scientific_ids) != campaign.candidate_count:
        raise ValueError("Taste source review projections differ")
    return scientific_ids


def _verify_session(
    campaign: TasteSourceReviewCampaign,
    root: Path,
    session: TasteSourceReviewSession,
) -> None:
    if session.campaign_id != campaign.campaign_id or session.campaign_sha256 != (
        campaign.campaign_sha256
    ):
        raise ValueError("Taste source review session targets another campaign")
    if session.reviewer_interface_sha256 != campaign.reviewer_interface_sha256:
        raise ValueError("Taste source review session interface differs from campaign")
    binding = (
        campaign.scientific_items
        if session.role is TasteSourceReviewRole.SCIENTIFIC
        else campaign.privacy_items
    )
    item_type = (
        ScientificTasteSourceReviewItem
        if session.role is TasteSourceReviewRole.SCIENTIFIC
        else PrivacyTasteSourceReviewItem
    )
    expected = _load_jsonl(_bound_file(root, binding), item_type)
    ordered = tuple(
        sorted(
            expected,
            key=lambda item: _canonical_sha256(
                [
                    campaign.campaign_sha256,
                    session.role.value,
                    session.reviewer_identity_sha256,
                    item.review_item_id,
                ]
            ),
        )
    )
    if session.items != ordered:
        raise ValueError("Taste source review session differs from its frozen projection")


def _load_private_map(path: Path) -> tuple[TasteSourcePrivateMapItem, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("Taste source review private map is invalid")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("Taste source review private map lacks items")
    parsed = tuple(TasteSourcePrivateMapItem.model_validate(item) for item in items)
    ids = [item.review_item_id for item in parsed]
    if len(ids) != len(set(ids)):
        raise ValueError("Taste source review private map contains duplicate items")
    return parsed


def _load_bound_policy(
    root: Path,
    campaign: TasteSourceReviewCampaign,
) -> TasteSourceReviewPolicy:
    policy_path = _bound_file(root, campaign.policy_document)
    if _sha256_file(policy_path) != campaign.policy_file_sha256:
        raise ValueError("Taste source review policy bytes differ from campaign")
    policy = load_taste_source_review_policy(policy_path)
    if policy.policy_sha256 != campaign.policy_sha256:
        raise ValueError("Taste source review policy semantics differ")
    return policy


def _load_jsonl(path: Path, model: type[BaseModel]) -> tuple[BaseModel, ...]:
    values: list[BaseModel] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Taste source review JSONL line {line_number} is invalid") from exc
        values.append(model.model_validate(payload))
    if not values:
        raise ValueError("Taste source review JSONL is empty")
    return tuple(values)


def _jsonl_bytes(values: list[BaseModel]) -> bytes:
    return b"".join(_canonical_json(value.model_dump(mode="json")) + b"\n" for value in values)


def _binding(root: Path, path: Path) -> TasteSourceReviewFileBinding:
    return TasteSourceReviewFileBinding(
        locator=path.relative_to(root).as_posix(),
        sha256=_sha256_file(path),
        bytes=path.stat().st_size,
    )


def _external_binding(root: Path, path: Path) -> TasteSourceReviewFileBinding:
    resolved = _contained_file(root, path, maximum_bytes=_MAX_ITEMS_BYTES)
    return TasteSourceReviewFileBinding(
        locator=resolved.relative_to(root).as_posix(),
        sha256=_sha256_file(resolved),
        bytes=resolved.stat().st_size,
    )


def _bound_file(root: Path, binding: TasteSourceReviewFileBinding) -> Path:
    path = _bounded_file(
        root.joinpath(*PurePosixPath(binding.locator).parts),
        maximum_bytes=binding.bytes,
    )
    if path.stat().st_size != binding.bytes or _sha256_file(path) != binding.sha256:
        raise ValueError("Taste source review bound file differs")
    return path


def _bounded_file(path: Path, *, maximum_bytes: int) -> Path:
    if path.is_symlink():
        raise ValueError("Taste source review files cannot be symlinks")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not 1 <= resolved.stat().st_size <= maximum_bytes:
        raise ValueError("Taste source review file is not a bounded regular file")
    return resolved


def _contained_file(root: Path, path: Path, *, maximum_bytes: int) -> Path:
    candidate = path if path.is_absolute() else root / path
    resolved = _bounded_file(candidate, maximum_bytes=maximum_bytes)
    if not resolved.is_relative_to(root):
        raise ValueError("Taste source review evidence must remain inside its campaign")
    return resolved


def _new_contained_target(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    parent = candidate.parent.resolve(strict=True)
    if not parent.is_relative_to(root):
        raise ValueError("Taste source review output must remain inside its campaign")
    return candidate


def _relative_locator(locator: str) -> PurePosixPath:
    parsed = PurePosixPath(locator)
    if (
        "\\" in locator
        or parsed.is_absolute()
        or not parsed.parts
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ValueError("Taste source review locator must be normalized and relative")
    return parsed


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _interface_bytes() -> bytes:
    return files("scitaste.evaluation").joinpath("taste_source_reviewer_ui.html").read_bytes()


__all__ = [
    "PrivacyTasteSourceResponse",
    "ScientificTasteSourceResponse",
    "TasteSourceDimensionResponse",
    "TasteSourceDomainLabel",
    "TasteSourceReviewActivation",
    "TasteSourceReviewCampaign",
    "TasteSourceReviewPolicy",
    "TasteSourceReviewResult",
    "TasteSourceReviewRisk",
    "TasteSourceReviewRole",
    "TasteSourceReviewSession",
    "TasteSourceReviewSubmission",
    "load_taste_source_review_activation",
    "load_taste_source_review_campaign",
    "load_taste_source_review_items",
    "load_taste_source_review_policy",
    "load_taste_source_review_private_map",
    "lock_taste_source_review_submissions",
    "prepare_taste_source_review_campaign",
    "prepare_taste_source_review_session",
    "publish_taste_source_review_campaign_run",
]

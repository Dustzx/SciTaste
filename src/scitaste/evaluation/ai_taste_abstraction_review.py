"""Independent AI-only review and admission for grounded Taste abstractions.

The generation model identity stays outside reviewer-visible requests.  Two
provider-distinct AI reviewers assess every abstraction against the exact
source projection.  Their raw response and execution-receipt bytes are locked
before a third identity receives only disputed items.  The resulting accepted
set is operational evidence, never human or expert validation.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.model_nodes.models import NodeResult, NodeResultStatus
from scitaste.model_nodes.runtime import RuntimeInvocationReceipt, RuntimeOutcome
from scitaste.taste.semantic_models import (
    GROUNDED_TASTE_ABSTRACTION_NODE,
    GroundedTasteCaseAbstraction,
    TasteAbstractionInput,
    validate_grounded_abstraction_against_projection,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_EXACT_CONFIG = ConfigDict(extra="forbid", frozen=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_ZERO_HASH = "0" * 64
_MAX_INPUT_BYTES = 64 * 1_048_576


class AIAbstractionReviewDisposition(StrEnum):
    """Allowed primary-review outcomes."""

    ACCEPT = "accept"
    REJECT = "reject"
    NEEDS_DISPUTE = "needs-dispute"


class AIAbstractionFinalDisposition(StrEnum):
    """Resolved operational admission outcomes."""

    ACCEPT = "accept"
    REJECT = "reject"


class AIAbstractionReviewCriterion(StrEnum):
    """The four independent abstraction-review dimensions."""

    GROUNDING_SUFFICIENCY = "grounding-sufficiency"
    CLOSED_ALTERNATIVES = "closed-alternatives"
    TRANSFER_BOUNDARY_QUALITY = "transfer-boundary-quality"
    UNSUPPORTED_CLAIMS = "unsupported-claims"


class AIAbstractionFileBinding(BaseModel):
    """Portable binding to exact bytes inside one evidence root."""

    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=2_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_portable(self) -> AIAbstractionFileBinding:
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts or "\\" in self.path:
            raise ValueError("AI abstraction file bindings must be portable relative paths")
        return self


class AIAbstractionReviewerIdentity(BaseModel):
    """Exact provider/model identity for one nonhuman review role."""

    model_config = _CONFIG

    reviewer_id: str = Field(pattern=_ID)
    role: Literal["primary-a", "primary-b", "adjudicator"]
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    model_revision: str = Field(min_length=1, max_length=300)
    identity_sha256: str = Field(pattern=_SHA256)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_identity_verified: Literal[False] = False
    human_qualification_verified: Literal[False] = False

    @model_validator(mode="after")
    def identity_is_content_derived(self) -> AIAbstractionReviewerIdentity:
        expected = _canonical_sha256(
            {
                "provider": self.provider,
                "model": self.model,
                "model_revision": self.model_revision,
            }
        )
        if self.identity_sha256 != expected:
            raise ValueError("AI abstraction reviewer identity hash mismatch")
        return self


class AITasteAbstractionReviewProtocol(BaseModel):
    """No-call policy for independent, condition-blind AI review."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    protocol_id: str = Field(pattern=_ID)
    primary_reviewers: tuple[
        AIAbstractionReviewerIdentity,
        AIAbstractionReviewerIdentity,
    ]
    adjudicator: AIAbstractionReviewerIdentity
    review_question: str = Field(min_length=1, max_length=10_000)
    criterion_instructions: dict[AIAbstractionReviewCriterion, str] = Field(
        min_length=4,
        max_length=4,
    )
    accept_rule: str = Field(min_length=1, max_length=4_000)
    reject_rule: str = Field(min_length=1, max_length=4_000)
    dispute_rule: str = Field(min_length=1, max_length=4_000)
    maximum_rationale_characters: int = Field(gt=0, le=40_000)
    generation_provider_and_model_hidden: Literal[True] = True
    source_condition_hidden: Literal[True] = True
    primary_reviewers_blinded_to_each_other: Literal[True] = True
    adjudicator_sees_disputed_items_only: Literal[True] = True
    adjudicator_sees_no_primary_outputs: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_human_or_expert_validity_claim: Literal[True] = True
    human_review_replacement_claim_allowed: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def identities_and_criteria_are_closed(self) -> AITasteAbstractionReviewProtocol:
        if tuple(item.role for item in self.primary_reviewers) != (
            "primary-a",
            "primary-b",
        ):
            raise ValueError("AI abstraction primaries must be ordered primary-a then primary-b")
        if self.adjudicator.role != "adjudicator":
            raise ValueError("AI abstraction adjudicator must use the adjudicator role")
        identities = (*self.primary_reviewers, self.adjudicator)
        if len({item.reviewer_id for item in identities}) != 3:
            raise ValueError("AI abstraction reviewer IDs must be distinct")
        if len({item.identity_sha256 for item in identities}) != 3:
            raise ValueError("AI abstraction provider/model identities must be distinct")
        if len({item.provider for item in self.primary_reviewers}) != 2:
            raise ValueError("AI abstraction primary reviewers must use different providers")
        if set(self.criterion_instructions) != set(AIAbstractionReviewCriterion):
            raise ValueError("AI abstraction protocol must define all four criteria")
        return self

    @computed_field
    @property
    def protocol_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"protocol_sha256"}))


class AIVisibleGroundedTasteAbstraction(BaseModel):
    """Grounded abstraction with controller and generation identities removed."""

    model_config = _EXACT_CONFIG

    context_summary: str
    problem_pattern: str | None
    evidence_state: str | None
    reviewer_context: str | None
    candidate_actions: tuple[str, ...]
    preferred_action: str
    rejected_actions: tuple[str, ...]
    decision_principle: str
    why_preferred: str
    outcome_summary: str | None
    confidence: float
    grounding: tuple[dict[str, object], ...]
    transfer_boundary: dict[str, object]


class AIAbstractionReviewItem(BaseModel):
    """One condition-blind source/proposal pair shown to an AI reviewer."""

    model_config = _EXACT_CONFIG

    ordinal: int = Field(gt=0, le=100_000)
    review_item_id: str = Field(pattern=_ID)
    stage: str = Field(min_length=1, max_length=100)
    decision_role: str = Field(min_length=1, max_length=300)
    domain_tags: tuple[str, ...] = Field(min_length=1, max_length=20)
    source_projection: str = Field(min_length=1, max_length=800_000)
    source_projection_sha256: str = Field(pattern=_SHA256)
    abstraction: AIVisibleGroundedTasteAbstraction
    abstraction_sha256: str = Field(pattern=_SHA256)
    generation_provider_and_model_hidden: Literal[True] = True
    source_id_hidden: Literal[True] = True
    candidate_id_hidden: Literal[True] = True
    source_condition_hidden: Literal[True] = True

    @model_validator(mode="after")
    def projection_and_abstraction_are_hashed(self) -> AIAbstractionReviewItem:
        if hashlib.sha256(self.source_projection.encode()).hexdigest() != (
            self.source_projection_sha256
        ):
            raise ValueError("AI abstraction review source projection hash mismatch")
        if _canonical_sha256(self.abstraction.model_dump(mode="json")) != (self.abstraction_sha256):
            raise ValueError("AI-visible abstraction hash mismatch")
        return self


class AIAbstractionPrimaryRequest(BaseModel):
    """One complete provider-ready primary-review request."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    protocol_sha256: str = Field(pattern=_SHA256)
    reviewer: AIAbstractionReviewerIdentity
    review_question: str
    criterion_instructions: dict[AIAbstractionReviewCriterion, str]
    accept_rule: str
    reject_rule: str
    dispute_rule: str
    maximum_rationale_characters: int
    required_response_schema: Literal["scitaste-ai-taste-abstraction-review-v1"] = (
        "scitaste-ai-taste-abstraction-review-v1"
    )
    items: tuple[AIAbstractionReviewItem, ...] = Field(min_length=1, max_length=100_000)
    generation_provider_and_model_hidden: Literal[True] = True
    source_condition_hidden: Literal[True] = True
    other_primary_review_output_absent: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_human_or_expert_validity_claim: Literal[True] = True
    authorizes_model_calls: Literal[False] = False

    @computed_field
    @property
    def request_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))


class AIAbstractionCandidateEvidence(BaseModel):
    """Controller-only provenance for one reviewed abstraction."""

    model_config = _CONFIG

    review_item_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    candidate_id: str = Field(pattern=_ID)
    case_id: str = Field(pattern=_ID)
    runtime_receipt: AIAbstractionFileBinding
    runtime_entry_sha256: str = Field(pattern=_SHA256)
    runtime_request_fingerprint: str = Field(pattern=_SHA256)
    abstraction_sha256: str = Field(pattern=_SHA256)
    source_projection_sha256: str = Field(pattern=_SHA256)


class AIAbstractionRequestPack(BaseModel):
    """Immutable controller binding for two condition-blind requests."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    pack_id: str = Field(pattern=_ID)
    protocol: AIAbstractionFileBinding
    protocol_sha256: str = Field(pattern=_SHA256)
    candidates: tuple[AIAbstractionCandidateEvidence, ...] = Field(min_length=1)
    primary_requests: tuple[AIAbstractionFileBinding, AIAbstractionFileBinding]
    primary_request_sha256s: tuple[str, str]
    primary_reviewer_identity_sha256s: tuple[str, str]
    adjudicator_identity_sha256: str = Field(pattern=_SHA256)
    candidate_count: int = Field(gt=0)
    planned_source_count: int | None = Field(default=None, ge=0)
    eligible_source_count: int | None = Field(default=None, ge=0)
    runtime_accepted_source_count: int | None = Field(default=None, ge=0)
    runtime_rejected_source_count: int | None = Field(default=None, ge=0)
    reviewer_count: Literal[2] = 2
    generation_identity_absent_from_reviewer_requests: Literal[True] = True
    source_condition_absent_from_reviewer_requests: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_human_or_expert_validity_claim: Literal[True] = True
    formal_human_validity: Literal[False] = False
    replacement_sampling_performed: Literal[False] = False
    no_external_action_performed: Literal[True] = True
    authorizes_model_calls: Literal[False] = False

    @model_validator(mode="after")
    def pack_is_complete(self) -> AIAbstractionRequestPack:
        if self.candidate_count != len(self.candidates):
            raise ValueError("AI abstraction request-pack candidate count mismatch")
        _require_unique(
            (item.review_item_id for item in self.candidates),
            "AI abstraction review items",
        )
        _require_unique((item.case_id for item in self.candidates), "AI abstraction cases")
        if self.schema_version == "1.0":
            return self
        counts = (
            self.planned_source_count,
            self.eligible_source_count,
            self.runtime_accepted_source_count,
            self.runtime_rejected_source_count,
        )
        if any(value is None for value in counts):
            raise ValueError("coverage-aware request packs require all source counts")
        planned, eligible, accepted, rejected = counts
        assert planned is not None and eligible is not None
        assert accepted is not None and rejected is not None
        if (
            not 0 < accepted <= eligible <= planned
            or accepted != self.candidate_count
            or accepted + rejected > eligible
        ):
            raise ValueError("AI abstraction request-pack source counts are inconsistent")
        return self

    @computed_field
    @property
    def pack_sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"pack_sha256"})
        if self.schema_version == "1.0":
            for field in (
                "planned_source_count",
                "eligible_source_count",
                "runtime_accepted_source_count",
                "runtime_rejected_source_count",
                "formal_human_validity",
                "replacement_sampling_performed",
            ):
                payload.pop(field, None)
        return _canonical_sha256(payload)


class AIAbstractionCriterionAssessment(BaseModel):
    """Explicit four-part assessment; no scalar can conceal a failed dimension."""

    model_config = _CONFIG

    grounding_sufficiency: Literal["sufficient", "insufficient"]
    closed_alternatives: Literal["closed", "not-closed"]
    transfer_boundary_quality: Literal["sufficient", "insufficient"]
    unsupported_claims: Literal["absent", "present"]

    @property
    def all_clear(self) -> bool:
        return (
            self.grounding_sufficiency == "sufficient"
            and self.closed_alternatives == "closed"
            and self.transfer_boundary_quality == "sufficient"
            and self.unsupported_claims == "absent"
        )


class AIAbstractionRawReviewItem(BaseModel):
    """One structured response item retained in the exact raw-response file."""

    model_config = _CONFIG

    review_item_id: str = Field(pattern=_ID)
    assessment: AIAbstractionCriterionAssessment
    disposition: AIAbstractionReviewDisposition
    issue_codes: tuple[str, ...] = Field(max_length=32)
    rationale: str = Field(min_length=1, max_length=40_000)

    @model_validator(mode="after")
    def decision_matches_assessment(self) -> AIAbstractionRawReviewItem:
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("AI abstraction issue codes must be sorted and unique")
        if self.disposition is AIAbstractionReviewDisposition.ACCEPT:
            if not self.assessment.all_clear or self.issue_codes:
                raise ValueError("AI abstraction acceptance requires four clear criteria")
        elif not self.issue_codes:
            raise ValueError("rejection or needs-dispute requires at least one issue code")
        if self.disposition is AIAbstractionReviewDisposition.REJECT:
            if self.assessment.all_clear:
                raise ValueError("AI abstraction rejection requires a deficient criterion")
        return self


class AIAbstractionRawReviewResponse(BaseModel):
    """Strict AI response document; it cannot represent a human review."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    response_schema: Literal["scitaste-ai-taste-abstraction-review-v1"]
    reviewer_id: str = Field(pattern=_ID)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    responses: tuple[AIAbstractionRawReviewItem, ...] = Field(min_length=1)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_human_or_expert_validity_claim: Literal[True] = True

    @model_validator(mode="after")
    def response_items_are_unique(self) -> AIAbstractionRawReviewResponse:
        _require_unique(
            (item.review_item_id for item in self.responses),
            "AI abstraction raw responses",
        )
        return self


class AIAbstractionReviewExecutionReceipt(BaseModel):
    """Evidence binding one observed AI call to request and raw-response bytes."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str = Field(pattern=_ID)
    reviewer_id: str = Field(pattern=_ID)
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    model_revision: str = Field(min_length=1, max_length=300)
    provider_kind: Literal["api", "local-model", "agent"] = "api"
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    request: AIAbstractionFileBinding
    request_sha256: str = Field(pattern=_SHA256)
    raw_response: AIAbstractionFileBinding
    started_at: datetime
    completed_at: datetime
    provider_request_id: str | None = Field(default=None, min_length=1, max_length=1_000)
    http_status: int | None = Field(default=None, ge=100, le=599)
    agent_session_id: str | None = Field(default=None, min_length=1, max_length=1_000)
    agent_runtime: str | None = Field(default=None, min_length=1, max_length=1_000)
    model_call_observed: bool
    agent_execution_observed: bool = False
    exact_model_identity_verified: bool = True
    provider_execution_fabricated: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_human_or_expert_validity_claim: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    authorizes_additional_model_calls: Literal[False] = False

    @model_validator(mode="after")
    def time_is_closed(self) -> AIAbstractionReviewExecutionReceipt:
        if self.started_at.utcoffset() is None or self.completed_at.utcoffset() is None:
            raise ValueError("AI abstraction receipt times must include a timezone")
        if self.completed_at < self.started_at:
            raise ValueError("AI abstraction receipt cannot complete before it starts")
        if self.provider_kind == "api":
            if (
                self.provider_request_id is None
                or self.http_status is None
                or not 200 <= self.http_status < 300
                or not self.model_call_observed
                or self.agent_execution_observed
                or self.agent_session_id is not None
                or self.agent_runtime is not None
                or not self.exact_model_identity_verified
            ):
                raise ValueError("API review receipt lacks exact successful provider evidence")
        elif self.provider_kind == "local-model":
            if (
                self.provider_request_id is not None
                or self.http_status is not None
                or not self.model_call_observed
                or self.agent_execution_observed
                or self.agent_session_id is not None
                or self.agent_runtime is not None
                or not self.exact_model_identity_verified
            ):
                raise ValueError("local-model receipt mixes API or agent execution evidence")
        elif (
            self.provider_request_id is not None
            or self.http_status is not None
            or self.model_call_observed
            or not self.agent_execution_observed
            or self.agent_session_id is None
            or self.agent_runtime is None
            or self.exact_model_identity_verified
        ):
            raise ValueError("agent receipt must disclose import-only, non-provider execution")
        return self

    @computed_field
    @property
    def receipt_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))


class AINormalizedAbstractionReview(BaseModel):
    """Self-hashed primary review with exact byte provenance."""

    model_config = _CONFIG

    row_id: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    reviewer_id: str = Field(pattern=_ID)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    raw_response_file_sha256: str = Field(pattern=_SHA256)
    execution_receipt_file_sha256: str = Field(pattern=_SHA256)
    assessment: AIAbstractionCriterionAssessment
    disposition: AIAbstractionReviewDisposition
    issue_codes: tuple[str, ...]
    rationale: str
    condition_blind: Literal[True] = True
    blinded_to_other_primary_review: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_human_or_expert_validity_claim: Literal[True] = True
    row_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def row_hash_matches(self) -> AINormalizedAbstractionReview:
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"row_sha256"}))
        if self.row_sha256 != expected:
            raise ValueError("normalized AI abstraction review hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AINormalizedAbstractionReview:
        payload = dict(values)
        payload.pop("row_sha256", None)
        unsigned = cls.model_construct(row_sha256=_ZERO_HASH, **payload)
        return cls(
            **payload,
            row_sha256=_canonical_sha256(unsigned.model_dump(mode="json", exclude={"row_sha256"})),
        )


class AIAbstractionReviewDispute(BaseModel):
    model_config = _CONFIG

    dispute_id: str = Field(pattern=_ID)
    review_item_id: str = Field(pattern=_ID)
    primary_row_sha256s: tuple[str, str]
    reason: Literal["decision-disagreement", "primary-uncertainty"]


class AIAbstractionAdjudicationRequest(BaseModel):
    """Third-identity request containing disputed items but no primary opinions."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    protocol_sha256: str = Field(pattern=_SHA256)
    locked_primary_review_set_sha256: str = Field(pattern=_SHA256)
    adjudicator: AIAbstractionReviewerIdentity
    review_question: str
    criterion_instructions: dict[AIAbstractionReviewCriterion, str]
    accept_rule: str
    reject_rule: str
    maximum_rationale_characters: int
    required_response_schema: Literal["scitaste-ai-taste-abstraction-review-v1"] = (
        "scitaste-ai-taste-abstraction-review-v1"
    )
    items: tuple[AIAbstractionReviewItem, ...] = Field(min_length=1)
    disputed_items_only: Literal[True] = True
    primary_decisions_absent: Literal[True] = True
    primary_rationales_absent: Literal[True] = True
    generation_provider_and_model_hidden: Literal[True] = True
    source_condition_hidden: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_human_or_expert_validity_claim: Literal[True] = True
    authorizes_model_calls: Literal[False] = False

    @computed_field
    @property
    def request_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))


class LockedAIAbstractionPrimaryReviews(BaseModel):
    """Primary AI decisions frozen before disputed-only adjudication."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    lock_id: str = Field(pattern=_ID)
    request_pack: AIAbstractionFileBinding
    request_pack_sha256: str = Field(pattern=_SHA256)
    normalized_rows: tuple[AINormalizedAbstractionReview, ...] = Field(min_length=2)
    raw_responses: tuple[AIAbstractionFileBinding, AIAbstractionFileBinding]
    execution_receipts: tuple[AIAbstractionFileBinding, AIAbstractionFileBinding]
    disputes: tuple[AIAbstractionReviewDispute, ...]
    adjudication_request: AIAbstractionFileBinding | None = None
    adjudication_request_sha256: str | None = Field(default=None, pattern=_SHA256)
    locked_at: datetime
    all_primary_ai_reviews_locked: Literal[True] = True
    adjudication_performed: Literal[False] = False
    adjudicator_pack_created_only_for_disputes: Literal[True] = True
    condition_blind_through_primary_lock: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_human_or_expert_validity_claim: Literal[True] = True
    no_external_action_performed: Literal[True] = True
    authorizes_model_calls: Literal[False] = False

    @model_validator(mode="after")
    def lock_is_complete(self) -> LockedAIAbstractionPrimaryReviews:
        if self.locked_at.utcoffset() is None:
            raise ValueError("AI abstraction lock timestamp must include a timezone")
        present = self.adjudication_request is not None
        if present != bool(self.disputes):
            raise ValueError("AI abstraction adjudication request must exactly follow disputes")
        if present != (self.adjudication_request_sha256 is not None):
            raise ValueError("AI abstraction adjudication binding and hash must be atomic")
        grouped: dict[str, set[str]] = defaultdict(set)
        for row in self.normalized_rows:
            grouped[row.review_item_id].add(row.reviewer_id)
        if any(len(reviewers) != 2 for reviewers in grouped.values()):
            raise ValueError("each abstraction requires two distinct primary AI reviews")
        return self

    @computed_field
    @property
    def primary_review_sha256(self) -> str:
        """Stable primary-only hash, excluding the non-circular adjudication request."""

        return _canonical_sha256(
            self.model_dump(
                mode="json",
                exclude={
                    "primary_review_sha256",
                    "review_set_sha256",
                    "adjudication_request",
                    "adjudication_request_sha256",
                },
            )
        )

    @computed_field
    @property
    def review_set_sha256(self) -> str:
        return _canonical_sha256(
            self.model_dump(
                mode="json",
                exclude={"primary_review_sha256", "review_set_sha256"},
            )
        )


class AIAbstractionAdjudicationResponse(BaseModel):
    """Decisive response from the third identity for all and only disputes."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    response_schema: Literal["scitaste-ai-taste-abstraction-review-v1"]
    reviewer_id: str = Field(pattern=_ID)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    responses: tuple[AIAbstractionRawReviewItem, ...] = Field(min_length=1)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_human_or_expert_validity_claim: Literal[True] = True

    @model_validator(mode="after")
    def adjudication_is_decisive(self) -> AIAbstractionAdjudicationResponse:
        _require_unique(
            (item.review_item_id for item in self.responses),
            "AI abstraction adjudications",
        )
        if any(
            item.disposition is AIAbstractionReviewDisposition.NEEDS_DISPUTE
            for item in self.responses
        ):
            raise ValueError("the final AI adjudicator must return accept or reject")
        return self


class AIFinalAbstractionDecision(BaseModel):
    model_config = _CONFIG

    review_item_id: str = Field(pattern=_ID)
    disposition: AIAbstractionFinalDisposition
    resolution: Literal["primary-agreement", "ai-adjudicated"]
    deciding_row_sha256s: tuple[str, ...] = Field(min_length=1, max_length=2)


class AIAcceptedTasteAbstraction(BaseModel):
    """Operationally accepted abstraction with model and AI-review provenance."""

    model_config = _CONFIG

    review_item_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    candidate_id: str = Field(pattern=_ID)
    case_id: str = Field(pattern=_ID)
    runtime_receipt: AIAbstractionFileBinding
    runtime_entry_sha256: str = Field(pattern=_SHA256)
    abstraction_sha256: str = Field(pattern=_SHA256)
    resolution: Literal["primary-agreement", "ai-adjudicated"]
    deciding_row_sha256s: tuple[str, ...] = Field(min_length=1, max_length=2)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_human_or_expert_validity_claim: Literal[True] = True
    track_a_pilot_use_authorized: Literal[True] = True
    formal_retrieval_or_training_use_authorized: Literal[False] = False


class AIAcceptedTasteAbstractionSet(BaseModel):
    """Fully resolved AI-only set; acceptance grants no human-validity claim."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    accepted_set_id: str = Field(pattern=_ID)
    request_pack: AIAbstractionFileBinding
    request_pack_sha256: str = Field(pattern=_SHA256)
    locked_primary_reviews: AIAbstractionFileBinding
    locked_primary_review_set_sha256: str = Field(pattern=_SHA256)
    adjudication_response: AIAbstractionFileBinding | None = None
    adjudication_execution_receipt: AIAbstractionFileBinding | None = None
    decisions: tuple[AIFinalAbstractionDecision, ...] = Field(min_length=1)
    accepted: tuple[AIAcceptedTasteAbstraction, ...]
    input_candidate_count: int = Field(gt=0)
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    unresolved_count: Literal[0] = 0
    finalized_at: datetime
    operational_ai_acceptance_only: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    no_human_or_expert_validity_claim: Literal[True] = True
    human_review_replacement_claim_allowed: Literal[False] = False
    formal_construct_validity_established: Literal[False] = False
    track_a_pilot_use_authorized: Literal[True] = True
    formal_benchmark_admission_authorized: Literal[False] = False
    formal_retrieval_or_training_use_authorized: Literal[False] = False
    authorizes_additional_model_calls: Literal[False] = False

    @model_validator(mode="after")
    def counts_and_decisions_are_closed(self) -> AIAcceptedTasteAbstractionSet:
        if self.finalized_at.utcoffset() is None:
            raise ValueError("AI abstraction finalization time must include a timezone")
        if self.input_candidate_count != len(self.decisions):
            raise ValueError("AI abstraction final decision count mismatch")
        if self.accepted_count != len(self.accepted):
            raise ValueError("AI abstraction accepted count mismatch")
        if self.rejected_count != self.input_candidate_count - self.accepted_count:
            raise ValueError("AI abstraction rejected count mismatch")
        accepted_ids = {item.review_item_id for item in self.accepted}
        decision_ids = {
            item.review_item_id
            for item in self.decisions
            if item.disposition is AIAbstractionFinalDisposition.ACCEPT
        }
        if accepted_ids != decision_ids:
            raise ValueError("AI abstraction accepted set differs from final decisions")
        return self

    @computed_field
    @property
    def accepted_set_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"accepted_set_sha256"}))


def load_ai_taste_abstraction_review_protocol(
    path: str | Path,
) -> AITasteAbstractionReviewProtocol:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("AI Taste abstraction review protocol must be a mapping")
    return AITasteAbstractionReviewProtocol.model_validate(payload)


def load_ai_abstraction_request_pack(path: str | Path) -> AIAbstractionRequestPack:
    source = Path(path)
    if source.is_dir():
        source = source / "PACK.json"
    return AIAbstractionRequestPack.model_validate_json(source.read_text(encoding="utf-8"))


def import_codex_agent_abstraction_review(
    *,
    evidence_root: str | Path,
    request_path: str | Path,
    raw_response_path: str | Path,
    agent_session_id: str,
    agent_runtime: str,
    started_at: datetime,
    completed_at: datetime,
    output_path: str | Path,
) -> AIAbstractionReviewExecutionReceipt:
    """Bind a Codex-agent JSON result without inventing an API/provider execution.

    The reviewer identity in the request must explicitly declare an agent provider.
    The imported raw bytes remain untouched, and the receipt records that the exact
    underlying model identity is not independently verified by this process.
    """

    root = Path(evidence_root).resolve(strict=True)
    request_file = _regular_file(root, request_path)
    raw_file = _regular_file(root, raw_response_path)
    if request_file == raw_file:
        raise ValueError("Codex-agent request and response must be distinct files")
    request_payload = json.loads(request_file.read_text(encoding="utf-8"))
    if not isinstance(request_payload, dict):
        raise ValueError("Codex-agent abstraction-review request must be a JSON object")
    if request_payload.get("disputed_items_only") is True:
        request: AIAbstractionPrimaryRequest | AIAbstractionAdjudicationRequest = (
            AIAbstractionAdjudicationRequest.model_validate(request_payload)
        )
        response: AIAbstractionRawReviewResponse | AIAbstractionAdjudicationResponse = (
            AIAbstractionAdjudicationResponse.model_validate_json(
                raw_file.read_text(encoding="utf-8")
            )
        )
        identity = request.adjudicator
    else:
        request = AIAbstractionPrimaryRequest.model_validate(request_payload)
        response = AIAbstractionRawReviewResponse.model_validate_json(
            raw_file.read_text(encoding="utf-8")
        )
        identity = request.reviewer
    if "agent" not in identity.provider.casefold():
        raise ValueError("Codex-agent import requires an explicitly agent-labelled provider")
    if "codex" not in agent_runtime.casefold():
        raise ValueError("Codex-agent import runtime must explicitly identify Codex")
    if (
        response.reviewer_id != identity.reviewer_id
        or response.reviewer_identity_sha256 != identity.identity_sha256
        or response.request_sha256 != request.request_sha256
    ):
        raise ValueError("Codex-agent response does not bind its request and declared identity")
    if {item.review_item_id for item in response.responses} != {
        item.review_item_id for item in request.items
    }:
        raise ValueError("Codex-agent response does not cover its exact review request")
    if any(
        len(item.rationale) > request.maximum_rationale_characters for item in response.responses
    ):
        raise ValueError("Codex-agent response rationale exceeds the protocol bound")
    invocation_identity = _canonical_sha256(
        [request.request_sha256, _sha256(raw_file), agent_session_id]
    )
    receipt = AIAbstractionReviewExecutionReceipt(
        invocation_id=f"codex-agent-review-{invocation_identity[:24]}",
        reviewer_id=identity.reviewer_id,
        provider=identity.provider,
        model=identity.model,
        model_revision=identity.model_revision,
        provider_kind="agent",
        reviewer_identity_sha256=identity.identity_sha256,
        request=_binding(root, request_file),
        request_sha256=request.request_sha256,
        raw_response=_binding(root, raw_file),
        started_at=started_at,
        completed_at=completed_at,
        provider_request_id=None,
        http_status=None,
        agent_session_id=agent_session_id,
        agent_runtime=agent_runtime,
        model_call_observed=False,
        agent_execution_observed=True,
        exact_model_identity_verified=False,
    )
    target = _new_file(root, output_path)
    _write_new_json(
        target,
        receipt.model_dump(mode="json", exclude={"receipt_sha256"}),
    )
    return receipt


def compile_ai_taste_abstraction_review_requests(
    *,
    evidence_root: str | Path,
    runtime_receipt_paths: Sequence[str | Path],
    protocol_path: str | Path,
    output_dir: str | Path,
    planned_source_count: int | None = None,
    eligible_source_count: int | None = None,
    runtime_rejected_source_count: int | None = None,
) -> AIAbstractionRequestPack:
    """Compile two complete blind request packs from accepted model-node receipts."""

    root = Path(evidence_root).resolve(strict=True)
    protocol_file = _regular_file(root, protocol_path)
    protocol = load_ai_taste_abstraction_review_protocol(protocol_file)
    target = _new_target(root, output_dir)
    if not runtime_receipt_paths:
        raise ValueError("at least one accepted grounded abstraction receipt is required")
    coverage_values = (
        planned_source_count,
        eligible_source_count,
        runtime_rejected_source_count,
    )
    if any(value is None for value in coverage_values) and any(
        value is not None for value in coverage_values
    ):
        raise ValueError("coverage-aware review requests require all source counts")

    loaded = [
        _candidate_from_receipt(root, _regular_file(root, path)) for path in runtime_receipt_paths
    ]
    loaded.sort(key=lambda item: (item[1].case_id, item[0].invocation_id))
    _require_unique((item[1].case_id for item in loaded), "grounded abstraction cases")
    review_items: list[AIAbstractionReviewItem] = []
    candidates: list[AIAbstractionCandidateEvidence] = []
    for ordinal, (receipt, node_input, abstraction, receipt_path) in enumerate(loaded, 1):
        visible = _visible_abstraction(abstraction)
        abstraction_sha = _canonical_sha256(visible.model_dump(mode="json"))
        review_identity = _canonical_sha256(
            [node_input.case_id, receipt.entry_sha256, abstraction_sha]
        )
        review_id = f"taste-abstraction-{review_identity[:24]}"
        review_items.append(
            AIAbstractionReviewItem(
                ordinal=ordinal,
                review_item_id=review_id,
                stage=node_input.stage,
                decision_role=node_input.decision_role,
                domain_tags=node_input.domain_tags,
                source_projection=node_input.source_projection,
                source_projection_sha256=node_input.source_projection_sha256,
                abstraction=visible,
                abstraction_sha256=abstraction_sha,
            )
        )
        assert receipt.request_fingerprint is not None
        candidates.append(
            AIAbstractionCandidateEvidence(
                review_item_id=review_id,
                source_id=node_input.source_id,
                candidate_id=node_input.candidate_id,
                case_id=node_input.case_id,
                runtime_receipt=_binding(root, receipt_path),
                runtime_entry_sha256=receipt.entry_sha256,
                runtime_request_fingerprint=receipt.request_fingerprint,
                abstraction_sha256=abstraction_sha,
                source_projection_sha256=node_input.source_projection_sha256,
            )
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as temporary:
        workspace = Path(temporary)
        requests: list[AIAbstractionPrimaryRequest] = []
        bindings: list[AIAbstractionFileBinding] = []
        request_identity = _canonical_sha256(
            [protocol.protocol_sha256, *(item.review_item_id for item in review_items)]
        )
        for reviewer in protocol.primary_reviewers:
            request = AIAbstractionPrimaryRequest(
                request_id=f"{reviewer.role}-{request_identity[:24]}",
                protocol_sha256=protocol.protocol_sha256,
                reviewer=reviewer,
                review_question=protocol.review_question,
                criterion_instructions=protocol.criterion_instructions,
                accept_rule=protocol.accept_rule,
                reject_rule=protocol.reject_rule,
                dispute_rule=protocol.dispute_rule,
                maximum_rationale_characters=protocol.maximum_rationale_characters,
                items=tuple(review_items),
            )
            relative = Path("requests") / f"{reviewer.role}.json"
            _write_json(
                workspace / relative, request.model_dump(mode="json", exclude={"request_sha256"})
            )
            requests.append(request)
            bindings.append(_workspace_binding(root, target, workspace, relative))
        pack_identity = _canonical_sha256(
            [protocol.protocol_sha256, *(item.runtime_entry_sha256 for item in candidates)]
        )
        pack = AIAbstractionRequestPack(
            schema_version=("1.0" if planned_source_count is None else "1.1"),
            pack_id=f"ai-taste-abstraction-{pack_identity[:24]}",
            protocol=_binding(root, protocol_file),
            protocol_sha256=protocol.protocol_sha256,
            candidates=tuple(candidates),
            primary_requests=tuple(bindings),  # type: ignore[arg-type]
            primary_request_sha256s=tuple(  # type: ignore[arg-type]
                item.request_sha256 for item in requests
            ),
            primary_reviewer_identity_sha256s=tuple(  # type: ignore[arg-type]
                item.reviewer.identity_sha256 for item in requests
            ),
            adjudicator_identity_sha256=protocol.adjudicator.identity_sha256,
            candidate_count=len(candidates),
            planned_source_count=planned_source_count,
            eligible_source_count=eligible_source_count,
            runtime_accepted_source_count=(
                None if planned_source_count is None else len(candidates)
            ),
            runtime_rejected_source_count=runtime_rejected_source_count,
        )
        _write_json(workspace / "PACK.json", pack.model_dump(mode="json", exclude={"pack_sha256"}))
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        os.replace(workspace, target)
    return pack


def lock_ai_taste_abstraction_primary_reviews(
    *,
    evidence_root: str | Path,
    request_pack_path_or_dir: str | Path,
    raw_response_paths: tuple[str | Path, str | Path],
    execution_receipt_paths: tuple[str | Path, str | Path],
    output_dir: str | Path,
    locked_at: datetime | None = None,
) -> LockedAIAbstractionPrimaryReviews:
    """Lock both primary reviews and create a third-model request only for disputes."""

    root = Path(evidence_root).resolve(strict=True)
    pack_file = _resolve_pack(root, request_pack_path_or_dir)
    pack = load_ai_abstraction_request_pack(pack_file)
    protocol = _load_bound_protocol(root, pack)
    _verify_pack_candidates(root, pack)
    requests = _load_primary_requests(root, pack)
    raw_files = tuple(_regular_file(root, path) for path in raw_response_paths)
    receipt_files = tuple(_regular_file(root, path) for path in execution_receipt_paths)
    raw_by_reviewer: dict[str, tuple[AIAbstractionRawReviewResponse, Path]] = {}
    receipts_by_reviewer: dict[str, tuple[AIAbstractionReviewExecutionReceipt, Path]] = {}
    for path in raw_files:
        response = AIAbstractionRawReviewResponse.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if response.reviewer_id in raw_by_reviewer:
            raise ValueError("duplicate AI abstraction primary response")
        raw_by_reviewer[response.reviewer_id] = (response, path)
    for path in receipt_files:
        receipt = AIAbstractionReviewExecutionReceipt.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if receipt.reviewer_id in receipts_by_reviewer:
            raise ValueError("duplicate AI abstraction primary receipt")
        receipts_by_reviewer[receipt.reviewer_id] = (receipt, path)
    if set(raw_by_reviewer) != set(requests) or set(receipts_by_reviewer) != set(requests):
        raise ValueError("AI abstraction responses and receipts must cover both primaries")

    rows: list[AINormalizedAbstractionReview] = []
    for reviewer_id, request in requests.items():
        response, raw_file = raw_by_reviewer[reviewer_id]
        receipt, receipt_file = receipts_by_reviewer[reviewer_id]
        _verify_review_evidence(root, request, response, raw_file, receipt, receipt_file)
        responses = {item.review_item_id: item for item in response.responses}
        for request_item in request.items:
            item = responses[request_item.review_item_id]
            row_identity = _canonical_sha256(
                [
                    reviewer_id,
                    request_item.review_item_id,
                    _sha256(raw_file),
                    _sha256(receipt_file),
                ]
            )
            rows.append(
                AINormalizedAbstractionReview.create(
                    row_id=f"row-{row_identity[:24]}",
                    review_item_id=request_item.review_item_id,
                    reviewer_id=reviewer_id,
                    reviewer_identity_sha256=request.reviewer.identity_sha256,
                    request_sha256=request.request_sha256,
                    raw_response_file_sha256=_sha256(raw_file),
                    execution_receipt_file_sha256=_sha256(receipt_file),
                    assessment=item.assessment,
                    disposition=item.disposition,
                    issue_codes=item.issue_codes,
                    rationale=item.rationale,
                )
            )
    rows.sort(key=lambda item: (item.review_item_id, item.reviewer_id))
    disputes = _find_disputes(rows)
    lock_time = locked_at or datetime.now(UTC)
    target = _new_target(root, output_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_identity = _canonical_sha256([pack.pack_sha256, lock_time.isoformat()])
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as temporary:
        workspace = Path(temporary)
        placeholder = (
            LockedAIAbstractionPrimaryReviews(
                lock_id=f"ai-taste-abstraction-lock-{lock_identity[:20]}",
                request_pack=_binding(root, pack_file),
                request_pack_sha256=pack.pack_sha256,
                normalized_rows=tuple(rows),
                raw_responses=tuple(_binding(root, item) for item in raw_files),  # type: ignore[arg-type]
                execution_receipts=tuple(  # type: ignore[arg-type]
                    _binding(root, item) for item in receipt_files
                ),
                disputes=disputes,
                adjudication_request=None,
                adjudication_request_sha256=None,
                locked_at=lock_time,
            )
            if not disputes
            else None
        )
        if disputes:
            provisional = LockedAIAbstractionPrimaryReviews.model_construct(
                lock_id=f"ai-taste-abstraction-lock-{lock_identity[:20]}",
                request_pack=_binding(root, pack_file),
                request_pack_sha256=pack.pack_sha256,
                normalized_rows=tuple(rows),
                raw_responses=tuple(_binding(root, item) for item in raw_files),
                execution_receipts=tuple(_binding(root, item) for item in receipt_files),
                disputes=disputes,
                adjudication_request=None,
                adjudication_request_sha256=None,
                locked_at=lock_time,
            )
            adjudication = _build_adjudication_request(
                protocol=protocol,
                primary_review_set_sha256=provisional.primary_review_sha256,
                disputes=disputes,
                items=requests[protocol.primary_reviewers[0].reviewer_id].items,
            )
            relative = Path("adjudication") / "request.json"
            _write_json(
                workspace / relative,
                adjudication.model_dump(mode="json", exclude={"request_sha256"}),
            )
            binding = _workspace_binding(root, target, workspace, relative)
            lock = LockedAIAbstractionPrimaryReviews(
                lock_id=provisional.lock_id,
                request_pack=provisional.request_pack,
                request_pack_sha256=provisional.request_pack_sha256,
                normalized_rows=provisional.normalized_rows,
                raw_responses=provisional.raw_responses,
                execution_receipts=provisional.execution_receipts,
                disputes=provisional.disputes,
                adjudication_request=binding,
                adjudication_request_sha256=adjudication.request_sha256,
                locked_at=lock_time,
            )
        else:
            assert placeholder is not None
            lock = placeholder
        _write_json(
            workspace / "LOCK.json",
            lock.model_dump(
                mode="json",
                exclude={"primary_review_sha256", "review_set_sha256"},
            ),
        )
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        os.replace(workspace, target)
    return lock


def finalize_ai_taste_abstraction_reviews(
    *,
    evidence_root: str | Path,
    locked_primary_reviews_path_or_dir: str | Path,
    output_path: str | Path,
    adjudication_response_path: str | Path | None = None,
    adjudication_execution_receipt_path: str | Path | None = None,
    finalized_at: datetime | None = None,
) -> AIAcceptedTasteAbstractionSet:
    """Resolve all primary decisions and emit an AI-only operational accepted set."""

    root = Path(evidence_root).resolve(strict=True)
    lock_file = _resolve_lock(root, locked_primary_reviews_path_or_dir)
    lock = LockedAIAbstractionPrimaryReviews.model_validate_json(
        lock_file.read_text(encoding="utf-8")
    )
    pack_file = _bound_file(root, lock.request_pack)
    pack = load_ai_abstraction_request_pack(pack_file)
    if pack.pack_sha256 != lock.request_pack_sha256:
        raise ValueError("AI abstraction lock binds a different request pack")
    protocol = _load_bound_protocol(root, pack)
    _verify_pack_candidates(root, pack)
    grouped: dict[str, list[AINormalizedAbstractionReview]] = defaultdict(list)
    for row in lock.normalized_rows:
        grouped[row.review_item_id].append(row)

    adjudication_by_id: dict[str, AIAbstractionRawReviewItem] = {}
    adjudication_binding: AIAbstractionFileBinding | None = None
    adjudication_receipt_binding: AIAbstractionFileBinding | None = None
    if lock.disputes:
        if adjudication_response_path is None or adjudication_execution_receipt_path is None:
            raise ValueError(
                "AI abstraction disputes require one third-identity response and receipt"
            )
        assert lock.adjudication_request is not None
        request_file = _bound_file(root, lock.adjudication_request)
        request = AIAbstractionAdjudicationRequest.model_validate_json(
            request_file.read_text(encoding="utf-8")
        )
        if request.locked_primary_review_set_sha256 != lock.primary_review_sha256:
            raise ValueError("AI adjudication request binds another primary-review set")
        response_file = _regular_file(root, adjudication_response_path)
        receipt_file = _regular_file(root, adjudication_execution_receipt_path)
        response = AIAbstractionAdjudicationResponse.model_validate_json(
            response_file.read_text(encoding="utf-8")
        )
        receipt = AIAbstractionReviewExecutionReceipt.model_validate_json(
            receipt_file.read_text(encoding="utf-8")
        )
        _verify_review_evidence(
            root,
            request,
            response,
            response_file,
            receipt,
            receipt_file,
        )
        expected = {item.review_item_id for item in lock.disputes}
        if {item.review_item_id for item in response.responses} != expected:
            raise ValueError("AI abstraction adjudication must cover all and only disputes")
        adjudication_by_id = {item.review_item_id: item for item in response.responses}
        adjudication_binding = _binding(root, response_file)
        adjudication_receipt_binding = _binding(root, receipt_file)
    elif adjudication_response_path is not None or adjudication_execution_receipt_path is not None:
        raise ValueError("AI abstraction adjudication evidence is forbidden without disputes")

    dispute_ids = {item.review_item_id for item in lock.disputes}
    decisions: list[AIFinalAbstractionDecision] = []
    for candidate in pack.candidates:
        rows = grouped.get(candidate.review_item_id, [])
        if len(rows) != 2:
            raise ValueError("AI abstraction lock lacks two primary rows for a candidate")
        if candidate.review_item_id in dispute_ids:
            result = adjudication_by_id[candidate.review_item_id]
            disposition = AIAbstractionFinalDisposition(result.disposition.value)
            assert adjudication_binding is not None
            assert adjudication_receipt_binding is not None
            decision_hashes = (
                _canonical_sha256(
                    {
                        "review_item_id": result.review_item_id,
                        "reviewer_identity_sha256": protocol.adjudicator.identity_sha256,
                        "request_sha256": lock.adjudication_request_sha256,
                        "raw_response_file_sha256": adjudication_binding.sha256,
                        "execution_receipt_file_sha256": adjudication_receipt_binding.sha256,
                        "assessment": result.assessment.model_dump(mode="json"),
                        "disposition": result.disposition.value,
                        "issue_codes": result.issue_codes,
                        "rationale": result.rationale,
                    }
                ),
            )
            resolution = "ai-adjudicated"
        else:
            if rows[0].disposition != rows[1].disposition or rows[0].disposition is (
                AIAbstractionReviewDisposition.NEEDS_DISPUTE
            ):
                raise ValueError("non-disputed AI abstraction rows are not decisive agreements")
            disposition = AIAbstractionFinalDisposition(rows[0].disposition.value)
            decision_hashes = tuple(item.row_sha256 for item in rows)
            resolution = "primary-agreement"
        decisions.append(
            AIFinalAbstractionDecision(
                review_item_id=candidate.review_item_id,
                disposition=disposition,
                resolution=resolution,
                deciding_row_sha256s=decision_hashes,
            )
        )
    decisions.sort(key=lambda item: item.review_item_id)
    candidate_by_id = {item.review_item_id: item for item in pack.candidates}
    accepted = tuple(
        AIAcceptedTasteAbstraction(
            review_item_id=decision.review_item_id,
            source_id=candidate_by_id[decision.review_item_id].source_id,
            candidate_id=candidate_by_id[decision.review_item_id].candidate_id,
            case_id=candidate_by_id[decision.review_item_id].case_id,
            runtime_receipt=candidate_by_id[decision.review_item_id].runtime_receipt,
            runtime_entry_sha256=candidate_by_id[decision.review_item_id].runtime_entry_sha256,
            abstraction_sha256=candidate_by_id[decision.review_item_id].abstraction_sha256,
            resolution=decision.resolution,
            deciding_row_sha256s=decision.deciding_row_sha256s,
        )
        for decision in decisions
        if decision.disposition is AIAbstractionFinalDisposition.ACCEPT
    )
    finished = finalized_at or datetime.now(UTC)
    accepted_identity = _canonical_sha256([lock.review_set_sha256, finished.isoformat()])
    result = AIAcceptedTasteAbstractionSet(
        accepted_set_id=f"ai-taste-abstraction-accepted-{accepted_identity[:20]}",
        request_pack=_binding(root, pack_file),
        request_pack_sha256=pack.pack_sha256,
        locked_primary_reviews=_binding(root, lock_file),
        locked_primary_review_set_sha256=lock.review_set_sha256,
        adjudication_response=adjudication_binding,
        adjudication_execution_receipt=adjudication_receipt_binding,
        decisions=tuple(decisions),
        accepted=accepted,
        input_candidate_count=len(decisions),
        accepted_count=len(accepted),
        rejected_count=len(decisions) - len(accepted),
        finalized_at=finished,
    )
    target = _new_file(root, output_path)
    _write_new_json(target, result.model_dump(mode="json", exclude={"accepted_set_sha256"}))
    return result


def _candidate_from_receipt(
    root: Path,
    path: Path,
) -> tuple[
    RuntimeInvocationReceipt,
    TasteAbstractionInput,
    GroundedTasteCaseAbstraction,
    Path,
]:
    del root
    receipt = RuntimeInvocationReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    if (
        receipt.outcome is not RuntimeOutcome.ACCEPTED
        or receipt.entry_sha256 == _ZERO_HASH
        or receipt.request_fingerprint is None
        or receipt.result is None
        or receipt.blockers
    ):
        raise ValueError("grounded Taste abstraction runtime receipt is not cleanly accepted")
    result = NodeResult[GroundedTasteCaseAbstraction].model_validate(receipt.result)
    if (
        result.status is not NodeResultStatus.ACCEPTED
        or result.node_name != GROUNDED_TASTE_ABSTRACTION_NODE
        or result.request.node_name != GROUNDED_TASTE_ABSTRACTION_NODE
        or result.proposal is None
        or result.request.fingerprint != receipt.request_fingerprint
        or result.response.request_fingerprint != receipt.request_fingerprint
        or (result.request.expected_backend, result.request.expected_model)
        != (result.response.backend, result.response.model)
        or result.response.tool_calls
    ):
        raise ValueError("runtime receipt does not contain an accepted grounded abstraction result")
    payload = result.request.input_payload
    if set(payload) != {"context", "input"} or not isinstance(payload["input"], dict):
        raise ValueError("grounded abstraction request does not expose its closed node input")
    node_input = TasteAbstractionInput.model_validate(payload["input"])
    if result.proposal.case_id != node_input.case_id:
        raise ValueError("grounded abstraction changed its controller-issued case identity")
    findings = validate_grounded_abstraction_against_projection(result.proposal, node_input)
    if findings:
        raise ValueError(f"grounded abstraction failed deterministic grounding: {findings}")
    return receipt, node_input, result.proposal, path


def _visible_abstraction(
    abstraction: GroundedTasteCaseAbstraction,
) -> AIVisibleGroundedTasteAbstraction:
    payload = abstraction.model_dump(mode="json", exclude={"case_id"})
    return AIVisibleGroundedTasteAbstraction.model_validate(payload)


def _load_bound_protocol(
    root: Path,
    pack: AIAbstractionRequestPack,
) -> AITasteAbstractionReviewProtocol:
    path = _bound_file(root, pack.protocol)
    protocol = load_ai_taste_abstraction_review_protocol(path)
    if protocol.protocol_sha256 != pack.protocol_sha256:
        raise ValueError("AI abstraction request pack binds another protocol")
    if tuple(item.identity_sha256 for item in protocol.primary_reviewers) != (
        pack.primary_reviewer_identity_sha256s
    ):
        raise ValueError("AI abstraction request pack binds different primary identities")
    if protocol.adjudicator.identity_sha256 != pack.adjudicator_identity_sha256:
        raise ValueError("AI abstraction request pack binds a different adjudicator identity")
    return protocol


def _verify_pack_candidates(root: Path, pack: AIAbstractionRequestPack) -> None:
    """Replay every controller-only receipt binding before review or admission."""

    for candidate in pack.candidates:
        path = _bound_file(root, candidate.runtime_receipt)
        receipt, node_input, abstraction, _ = _candidate_from_receipt(root, path)
        visible_sha = _canonical_sha256(_visible_abstraction(abstraction).model_dump(mode="json"))
        assert receipt.request_fingerprint is not None
        if (
            candidate.source_id != node_input.source_id
            or candidate.candidate_id != node_input.candidate_id
            or candidate.case_id != node_input.case_id
            or candidate.runtime_entry_sha256 != receipt.entry_sha256
            or candidate.runtime_request_fingerprint != receipt.request_fingerprint
            or candidate.abstraction_sha256 != visible_sha
            or candidate.source_projection_sha256 != node_input.source_projection_sha256
        ):
            raise ValueError("AI abstraction request-pack candidate provenance mismatch")


def _load_primary_requests(
    root: Path,
    pack: AIAbstractionRequestPack,
) -> dict[str, AIAbstractionPrimaryRequest]:
    requests: dict[str, AIAbstractionPrimaryRequest] = {}
    for binding, semantic_hash, identity_hash in zip(
        pack.primary_requests,
        pack.primary_request_sha256s,
        pack.primary_reviewer_identity_sha256s,
        strict=True,
    ):
        path = _bound_file(root, binding)
        request = AIAbstractionPrimaryRequest.model_validate_json(path.read_text(encoding="utf-8"))
        if request.request_sha256 != semantic_hash:
            raise ValueError("AI abstraction primary request semantic hash mismatch")
        if request.protocol_sha256 != pack.protocol_sha256:
            raise ValueError("AI abstraction primary request binds another protocol")
        if request.reviewer.identity_sha256 != identity_hash:
            raise ValueError("AI abstraction request reviewer identity mismatch")
        if request.reviewer.reviewer_id in requests:
            raise ValueError("AI abstraction request pack duplicates a reviewer")
        requests[request.reviewer.reviewer_id] = request
    if len(requests) != 2:
        raise ValueError("AI abstraction request pack requires exactly two primary requests")
    expected_ids = {item.review_item_id for item in pack.candidates}
    for request in requests.values():
        if {item.review_item_id for item in request.items} != expected_ids:
            raise ValueError("AI abstraction request does not cover the exact candidate set")
    return requests


def _verify_review_evidence(
    root: Path,
    request: AIAbstractionPrimaryRequest | AIAbstractionAdjudicationRequest,
    response: AIAbstractionRawReviewResponse | AIAbstractionAdjudicationResponse,
    raw_file: Path,
    receipt: AIAbstractionReviewExecutionReceipt,
    receipt_file: Path,
) -> None:
    identity = (
        request.reviewer
        if isinstance(request, AIAbstractionPrimaryRequest)
        else request.adjudicator
    )
    if (
        response.reviewer_id != identity.reviewer_id
        or response.reviewer_identity_sha256 != identity.identity_sha256
        or response.request_sha256 != request.request_sha256
        or receipt.reviewer_id != identity.reviewer_id
        or receipt.reviewer_identity_sha256 != identity.identity_sha256
        or (receipt.provider, receipt.model, receipt.model_revision)
        != (identity.provider, identity.model, identity.model_revision)
        or receipt.request_sha256 != request.request_sha256
    ):
        raise ValueError("AI abstraction response or receipt identity binding mismatch")
    request_path = _bound_file(root, receipt.request)
    response_path = _bound_file(root, receipt.raw_response)
    expected_request_path = next(
        path for path in (_bound_file(root, receipt.request),) if path == request_path
    )
    del expected_request_path
    if response_path != raw_file or _sha256(response_path) != _sha256(raw_file):
        raise ValueError("AI abstraction receipt does not bind supplied raw-response bytes")
    parsed_request = type(request).model_validate_json(request_path.read_text(encoding="utf-8"))
    if parsed_request != request:
        raise ValueError("AI abstraction receipt binds a different request")
    if receipt_file in {request_path, raw_file}:
        raise ValueError("AI abstraction request, response, and receipt must be distinct files")
    expected_ids = {item.review_item_id for item in request.items}
    if {item.review_item_id for item in response.responses} != expected_ids:
        raise ValueError("AI abstraction response does not cover its exact request")
    if any(
        len(item.rationale) > request.maximum_rationale_characters for item in response.responses
    ):
        raise ValueError("AI abstraction response rationale exceeds the protocol bound")


def _find_disputes(
    rows: Sequence[AINormalizedAbstractionReview],
) -> tuple[AIAbstractionReviewDispute, ...]:
    grouped: dict[str, list[AINormalizedAbstractionReview]] = defaultdict(list)
    for row in rows:
        grouped[row.review_item_id].append(row)
    disputes: list[AIAbstractionReviewDispute] = []
    for review_item_id, pair in sorted(grouped.items()):
        if len(pair) != 2 or len({item.reviewer_id for item in pair}) != 2:
            raise ValueError("each abstraction requires two distinct primary AI reviews")
        if (
            pair[0].disposition == pair[1].disposition
            and pair[0].disposition is not AIAbstractionReviewDisposition.NEEDS_DISPUTE
        ):
            continue
        ordered = sorted(pair, key=lambda item: item.row_id)
        dispute_identity = _canonical_sha256(
            [review_item_id, *(item.row_sha256 for item in ordered)]
        )
        disputes.append(
            AIAbstractionReviewDispute(
                dispute_id=f"abstraction-dispute-{dispute_identity[:24]}",
                review_item_id=review_item_id,
                primary_row_sha256s=tuple(  # type: ignore[arg-type]
                    item.row_sha256 for item in ordered
                ),
                reason=(
                    "primary-uncertainty"
                    if any(
                        item.disposition is AIAbstractionReviewDisposition.NEEDS_DISPUTE
                        for item in pair
                    )
                    else "decision-disagreement"
                ),
            )
        )
    return tuple(disputes)


def _build_adjudication_request(
    *,
    protocol: AITasteAbstractionReviewProtocol,
    primary_review_set_sha256: str,
    disputes: Sequence[AIAbstractionReviewDispute],
    items: Sequence[AIAbstractionReviewItem],
) -> AIAbstractionAdjudicationRequest:
    visible = {item.review_item_id: item for item in items}
    selected = tuple(visible[item.review_item_id] for item in disputes)
    request_identity = _canonical_sha256(
        [primary_review_set_sha256, *(item.dispute_id for item in disputes)]
    )
    return AIAbstractionAdjudicationRequest(
        request_id=f"adjudicate-{request_identity[:24]}",
        protocol_sha256=protocol.protocol_sha256,
        locked_primary_review_set_sha256=primary_review_set_sha256,
        adjudicator=protocol.adjudicator,
        review_question=protocol.review_question,
        criterion_instructions=protocol.criterion_instructions,
        accept_rule=protocol.accept_rule,
        reject_rule=protocol.reject_rule,
        maximum_rationale_characters=protocol.maximum_rationale_characters,
        items=selected,
    )


def _resolve_pack(root: Path, source: str | Path) -> Path:
    path = Path(source)
    if not path.is_absolute():
        path = root / path
    if path.is_dir():
        path = path / "PACK.json"
    return _regular_file(root, path)


def _resolve_lock(root: Path, source: str | Path) -> Path:
    path = Path(source)
    if not path.is_absolute():
        path = root / path
    if path.is_dir():
        path = path / "LOCK.json"
    return _regular_file(root, path)


def _regular_file(root: Path, source: str | Path) -> Path:
    path = Path(source)
    if not path.is_absolute():
        path = root / path
    if path.is_symlink():
        raise ValueError("AI abstraction review inputs cannot be symlinks")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("AI abstraction review inputs must stay inside the evidence root") from exc
    if not resolved.is_file() or resolved.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("AI abstraction review input is not a bounded regular file")
    return resolved


def _bound_file(root: Path, binding: AIAbstractionFileBinding) -> Path:
    path = _regular_file(root, binding.path)
    if _sha256(path) != binding.sha256:
        raise ValueError("AI abstraction review file differs from its content binding")
    return path


def _new_target(root: Path, output: str | Path) -> Path:
    target = Path(output)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("AI abstraction review output must stay inside the evidence root") from exc
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    return target


def _new_file(root: Path, output: str | Path) -> Path:
    return _new_target(root, output)


def _binding(root: Path, path: Path) -> AIAbstractionFileBinding:
    resolved = _regular_file(root, path)
    return AIAbstractionFileBinding(
        path=resolved.relative_to(root).as_posix(),
        sha256=_sha256(resolved),
    )


def _workspace_binding(
    root: Path,
    target: Path,
    workspace: Path,
    relative: Path,
) -> AIAbstractionFileBinding:
    path = workspace / relative
    return AIAbstractionFileBinding(
        path=(target / relative).relative_to(root).as_posix(),
        sha256=_sha256(path),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_new_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _require_unique(values: Iterable[str], label: str) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{label} must be unique")


__all__ = [
    "AIAbstractionAdjudicationRequest",
    "AIAbstractionAdjudicationResponse",
    "AIAbstractionCriterionAssessment",
    "AIAbstractionFinalDisposition",
    "AIAbstractionRawReviewResponse",
    "AIAbstractionRequestPack",
    "AIAbstractionReviewDisposition",
    "AIAbstractionReviewExecutionReceipt",
    "AIAcceptedTasteAbstractionSet",
    "AITasteAbstractionReviewProtocol",
    "LockedAIAbstractionPrimaryReviews",
    "compile_ai_taste_abstraction_review_requests",
    "finalize_ai_taste_abstraction_reviews",
    "import_codex_agent_abstraction_review",
    "load_ai_abstraction_request_pack",
    "load_ai_taste_abstraction_review_protocol",
    "lock_ai_taste_abstraction_primary_reviews",
]

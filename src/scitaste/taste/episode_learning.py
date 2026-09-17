"""Reviewed outcome attribution and an uncertainty-aware lifecycle Taste policy."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_binding_matches_current,
)
from scitaste.project.models import content_sha256, validate_relative_locator
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


class AITasteReviewArtifactRole(StrEnum):
    REVIEW_PACKET = "review-packet"
    INPUT_PROJECTION = "input-projection"
    RUBRIC = "rubric"
    SYSTEM_PROMPT = "system-prompt"
    USER_PROMPT = "user-prompt"
    RAW_RESPONSE = "raw-response"
    NORMALIZATION_REPORT = "normalization-report"
    EXECUTION_RECEIPT = "execution-receipt"
    FIREWALL_REPORT = "firewall-report"
    SAMPLING_CONFIG = "sampling-config"


_AI_REVIEW_ARTIFACT_ROLES = tuple(AITasteReviewArtifactRole)
_AI_REVIEW_ENDPOINT_OVERRIDES = {
    "H1_taste_abstraction": "ai-panel-and-natural-outcome-proxy",
    "H2_taste_specificity": "ai-panel-and-transfer-error-proxy",
    "H2b_taste_selection": "ai-panel-and-reversal-proxy",
    "H3_lifecycle_credit": "ai-panel-and-heldout-decision-proxy",
    "H4_objective_progress": "scorer-owned-objective-endpoint-unchanged",
}
_AI_REVIEW_FORBIDDEN_CLAIMS = (
    "human preference",
    "expert agreement",
    "expert-aligned scientific quality",
    "human-validated SciTasteBench",
    "general scientific-taste construct validity from AI-panel evidence alone",
)


class AITasteReviewArtifactBinding(BaseModel):
    model_config = _CONFIG

    role: AITasteReviewArtifactRole
    locator: str = Field(min_length=1, max_length=2_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def locator_is_relative(self) -> AITasteReviewArtifactBinding:
        validate_relative_locator(self.locator, field_name="AI Taste review artifact")
        return self


class AITasteReviewPanelContract(BaseModel):
    """Content-bound effective review policy for disclosed AI-only panels."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_id: str = Field(pattern=_ID)
    base_program_id: str = Field(pattern=_ID)
    base_program_proposal_sha256: str = Field(pattern=_SHA256)
    primary_role_count: Literal[2] = 2
    maximum_adjudicator_count: Literal[1] = 1
    require_distinct_models: Literal[True] = True
    require_distinct_raw_responses: Literal[True] = True
    required_artifact_roles: tuple[AITasteReviewArtifactRole, ...] = _AI_REVIEW_ARTIFACT_ROLES
    endpoint_overrides: dict[str, str] = Field(min_length=4, max_length=10)
    forbidden_claims: tuple[str, ...] = Field(min_length=5, max_length=30)
    reviewer_kind: Literal["ai"] = "ai"
    human_validity_claim_allowed: Literal[False] = False
    strong_title_authorized: Literal[False] = False
    authorizes_download: Literal[False] = False
    authorizes_api_calls: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_execution: Literal[False] = False
    contract_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def contract_is_closed(self) -> AITasteReviewPanelContract:
        if self.required_artifact_roles != _AI_REVIEW_ARTIFACT_ROLES:
            raise ValueError("AI Taste review contract must bind every artifact role")
        if len(self.forbidden_claims) != len(set(self.forbidden_claims)):
            raise ValueError("AI Taste review forbidden claims must be unique")
        if self.endpoint_overrides != _AI_REVIEW_ENDPOINT_OVERRIDES:
            raise ValueError("AI Taste review endpoint overrides differ from the AI-only route")
        if self.forbidden_claims != _AI_REVIEW_FORBIDDEN_CLAIMS:
            raise ValueError("AI Taste review forbidden claims differ from the AI-only route")
        expected = content_sha256(self.model_dump(mode="json", exclude={"contract_sha256"}))
        if self.contract_sha256 != expected:
            raise ValueError("AI Taste review contract hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> AITasteReviewPanelContract:
        payload = {"schema_version": "1.0", **values}
        payload.pop("contract_sha256", None)
        payload["required_artifact_roles"] = tuple(
            AITasteReviewArtifactRole(item)  # type: ignore[arg-type]
            for item in payload.get("required_artifact_roles", _AI_REVIEW_ARTIFACT_ROLES)
        )
        payload["forbidden_claims"] = tuple(payload.get("forbidden_claims", ()))
        unsigned = cls.model_construct(contract_sha256="0" * 64, **payload)
        return cls(
            **payload,
            contract_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"contract_sha256"})
            ),
        )


def load_ai_taste_review_panel_contract(path: str | Path) -> AITasteReviewPanelContract:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("AI Taste review contract must be a YAML object")
    return AITasteReviewPanelContract.model_validate(payload)


class AITasteReviewFirewallReport(BaseModel):
    """Replayable evidence that one reviewer-visible packet excluded claim leakage."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    review_packet_sha256: str = Field(pattern=_SHA256)
    input_projection_sha256: str = Field(pattern=_SHA256)
    condition_identity_exposed: Literal[False] = False
    paper_claims_exposed: Literal[False] = False
    out_of_window_outcomes_exposed: Literal[False] = False
    other_review_exposed: Literal[False] = False
    producer_response_exposed: Literal[False] = False
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_closed(self) -> AITasteReviewFirewallReport:
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("AI Taste review firewall report hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> AITasteReviewFirewallReport:
        payload = {"schema_version": "1.0", **values}
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


class AITasteReviewExecutionReceipt(BaseModel):
    """Provider-reported identity and usage bound to one raw review response."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    provider_id: str = Field(min_length=1, max_length=300)
    model_id: str = Field(min_length=1, max_length=500)
    model_revision: str = Field(min_length=1, max_length=500)
    run_id: str = Field(pattern=_ID)
    prompt_sha256: str = Field(pattern=_SHA256)
    input_projection_sha256: str = Field(pattern=_SHA256)
    raw_response_sha256: str = Field(pattern=_SHA256)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_closed(self) -> AITasteReviewExecutionReceipt:
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("AI Taste review execution receipt hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> AITasteReviewExecutionReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        return cls(
            **payload,
            receipt_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


class AITasteReviewNormalizationReport(BaseModel):
    """Bound transformation from one raw response to one review payload."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(pattern=_ID)
    candidate_sha256: str = Field(pattern=_SHA256)
    raw_response_sha256: str = Field(pattern=_SHA256)
    normalized_response_sha256: str = Field(pattern=_SHA256)
    schema_valid: Literal[True] = True
    fuzzy_repair_applied: Literal[False] = False
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_closed(self) -> AITasteReviewNormalizationReport:
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("AI Taste review normalization report hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> AITasteReviewNormalizationReport:
        payload = {"schema_version": "1.0", **values}
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


class TasteEpisodeAttributionReview(BaseModel):
    """Legacy self-attested review; it does not establish verified human identity."""

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

    @property
    def reviewer_kind(self) -> Literal["legacy-unverified"]:
        return "legacy-unverified"

    @property
    def not_human_review(self) -> Literal[True]:
        return True


class AITasteEpisodeAttributionReview(BaseModel):
    """Disclosed non-human review usable for policy training, not human validity."""

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
    reviewer_kind: Literal["ai"] = "ai"
    human_performed: Literal[False] = False
    not_human_review: Literal[True] = True
    independent_review: Literal[True] = True
    conflict_cleared: Literal[True] = True
    blinded_to_other_reviews: Literal[True] = True
    condition_blinded: Literal[True] = True
    blinded_to_paper_claims: Literal[True] = True
    isolated_execution: Literal[True] = True
    model_id: str = Field(min_length=1, max_length=500)
    model_revision: str = Field(min_length=1, max_length=500)
    provider_id: str = Field(min_length=1, max_length=300)
    prompt_sha256: str = Field(pattern=_SHA256)
    normalized_response_sha256: str = Field(pattern=_SHA256)
    run_id: str = Field(pattern=_ID)
    producer_model_id: str | None = Field(default=None, max_length=500)
    producer_run_id: str | None = Field(default=None, pattern=_ID)
    panel_contract_sha256: str = Field(pattern=_SHA256)
    artifacts: tuple[AITasteReviewArtifactBinding, ...] = Field(
        min_length=len(_AI_REVIEW_ARTIFACT_ROLES),
        max_length=len(_AI_REVIEW_ARTIFACT_ROLES),
    )

    @model_validator(mode="after")
    def verdict_matches_dimensions(self) -> AITasteEpisodeAttributionReview:
        if self.reviewed_at.utcoffset() is None:
            raise ValueError("AI Taste attribution review time must include a timezone")
        if len(self.supported_credit_ids) != len(set(self.supported_credit_ids)):
            raise ValueError("AI Taste attribution supported credit IDs must be unique")
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
                raise ValueError("accepted AI Taste attribution requires every dimension")
            if self.preferred_action_id is None or not self.supported_credit_ids:
                raise ValueError("accepted AI Taste attribution requires preference and credit")
        elif all(dimensions):
            raise ValueError("rejected AI Taste attribution must identify a failed dimension")
        roles = tuple(item.role for item in self.artifacts)
        if roles != _AI_REVIEW_ARTIFACT_ROLES:
            raise ValueError("AI Taste attribution artifacts must use canonical role order")
        if self.producer_model_id == self.model_id or self.producer_run_id == self.run_id:
            raise ValueError("AI Taste reviewer cannot reuse the producer model or run identity")
        return self

    def artifact(self, role: AITasteReviewArtifactRole) -> AITasteReviewArtifactBinding:
        return next(item for item in self.artifacts if item.role is role)

    @property
    def review_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


TasteEpisodeAttributionReviewRecord = (
    TasteEpisodeAttributionReview | AITasteEpisodeAttributionReview
)


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
    human_review_count: int = Field(default=0, ge=0)
    ai_review_count: int = Field(default=0, ge=0)
    legacy_unverified_review_count: int = Field(default=0, ge=0)
    review_evidence_kind: Literal["ai", "legacy-unverified", "mixed", "none"] = "none"
    human_validity_claim_allowed: Literal[False] = False
    ai_review_contract_sha256: str | None = Field(default=None, pattern=_SHA256)
    cross_model_ai_panel: bool = False
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

    schema_version: Literal["1.0", "1.1"] = "1.1"
    admission_id: str = Field(pattern=_ID)
    candidate: TasteEpisodeCandidate
    reviews: tuple[TasteEpisodeAttributionReviewRecord, ...] = Field(
        min_length=2,
        max_length=3,
    )
    decisive_review_ids: tuple[str, ...] = Field(min_length=2, max_length=3)
    preferred_action_id: str = Field(
        min_length=1,
        max_length=300,
        description=(
            "Legacy field name for the action receiving admitted signed credit; harmful "
            "credit makes this action a negative training target."
        ),
    )
    supported_credit_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    attribution_confidence: float = Field(gt=0.0, le=1.0)
    training_weight: float = Field(gt=0.0, le=1.0)
    review_evidence_kind: Literal["ai", "legacy-unverified", "mixed"] = "legacy-unverified"
    human_validity_claim_allowed: Literal[False] = False
    ai_review_contract_sha256: str | None = Field(default=None, pattern=_SHA256)
    ai_review_count: int = Field(default=0, ge=0, le=3)
    legacy_unverified_review_count: int = Field(default=0, ge=0, le=3)
    cross_model_ai_panel: bool = False
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
        if self.ai_review_count != sum(
            isinstance(item, AITasteEpisodeAttributionReview) for item in self.reviews
        ):
            raise ValueError("admitted Taste AI review count differs")
        if self.legacy_unverified_review_count != sum(
            isinstance(item, TasteEpisodeAttributionReview) for item in self.reviews
        ):
            raise ValueError("admitted Taste legacy review count differs")
        if self.ai_review_count and self.ai_review_contract_sha256 is None:
            raise ValueError("AI-reviewed Taste admission lacks its panel contract")
        if not self.ai_review_count and self.ai_review_contract_sha256 is not None:
            raise ValueError("non-AI Taste admission cannot bind an AI panel contract")
        if self.review_evidence_kind == "ai" and self.ai_review_count != len(self.reviews):
            raise ValueError("AI Taste evidence kind differs from review composition")
        legacy_composition_differs = self.legacy_unverified_review_count != len(self.reviews)
        if self.review_evidence_kind == "legacy-unverified" and legacy_composition_differs:
            raise ValueError("legacy Taste evidence kind differs from review composition")
        if self.review_evidence_kind == "mixed" and not (
            self.ai_review_count and self.legacy_unverified_review_count
        ):
            raise ValueError("mixed Taste evidence kind lacks both review types")
        expected = content_sha256(self.model_dump(mode="json", exclude={"admission_sha256"}))
        legacy_payload = self.model_dump(mode="json", exclude={"admission_sha256"})
        for field in (
            "review_evidence_kind",
            "human_validity_claim_allowed",
            "ai_review_contract_sha256",
            "ai_review_count",
            "legacy_unverified_review_count",
            "cross_model_ai_panel",
        ):
            legacy_payload.pop(field)
        legacy_expected = content_sha256(legacy_payload) if self.schema_version == "1.0" else None
        if self.admission_sha256 not in {expected, legacy_expected}:
            raise ValueError("admitted Taste episode hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AdmittedTasteEpisode:
        payload = {"schema_version": "1.1", **values}
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
    reviews: tuple[TasteEpisodeAttributionReviewRecord, ...],
    *,
    evidence_root: str | Path,
    current_idea_revision: ProjectIdeaRevisionBinding,
    ai_review_contract: AITasteReviewPanelContract | None = None,
    expected_ai_review_contract_sha256: str | None = None,
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
    ai_run_ids = [
        item.run_id for item in reviews if isinstance(item, AITasteEpisodeAttributionReview)
    ]
    if len(ai_run_ids) != len(set(ai_run_ids)):
        _admission_add(
            findings,
            "duplicate-ai-review-run",
            "independent AI Taste reviews must use distinct run identities",
        )
    ai_reviews = tuple(
        item for item in reviews if isinstance(item, AITasteEpisodeAttributionReview)
    )
    if ai_reviews and ai_review_contract is None:
        _admission_add(
            findings,
            "ai-review-contract-required",
            "AI Taste reviews require a content-bound panel contract",
        )
    if ai_reviews and expected_ai_review_contract_sha256 is None:
        _admission_add(
            findings,
            "ai-review-authority-required",
            "AI Taste reviews require the expected contract hash from the review package",
        )
    if not ai_reviews and ai_review_contract is not None:
        _admission_add(
            findings,
            "unused-ai-review-contract",
            "AI Taste panel contract cannot attach to a non-AI review set",
        )
    if not ai_reviews and expected_ai_review_contract_sha256 is not None:
        _admission_add(
            findings,
            "unused-ai-review-authority",
            "AI Taste contract authority cannot attach to a non-AI review set",
        )
    if ai_review_contract is not None:
        if ai_review_contract.contract_sha256 != expected_ai_review_contract_sha256:
            _admission_add(
                findings,
                "ai-review-authority-mismatch",
                "AI Taste panel contract differs from the review-package authority",
            )
        ai_primary_count = sum(
            item.role is TasteAttributionReviewRole.PRIMARY for item in ai_reviews
        )
        ai_adjudicator_count = sum(
            item.role is TasteAttributionReviewRole.ADJUDICATOR for item in ai_reviews
        )
        if ai_primary_count != ai_review_contract.primary_role_count:
            _admission_add(
                findings,
                "ai-primary-panel-incomplete",
                "AI Taste contract requires exactly two AI primary reviewers",
            )
        if ai_adjudicator_count > ai_review_contract.maximum_adjudicator_count:
            _admission_add(
                findings,
                "ai-adjudicator-count",
                "AI Taste panel exceeds its adjudicator limit",
            )
        if len(ai_reviews) != len(reviews):
            _admission_add(
                findings,
                "mixed-ai-panel-forbidden",
                "AI-only panel contract cannot admit legacy or mixed reviewers",
            )
        if any(
            item.panel_contract_sha256 != ai_review_contract.contract_sha256 for item in ai_reviews
        ):
            _admission_add(
                findings,
                "ai-review-contract-mismatch",
                "AI Taste review binds another panel contract",
            )
        if ai_review_contract.require_distinct_models and len(
            {item.model_id for item in ai_reviews}
        ) != len(ai_reviews):
            _admission_add(
                findings,
                "ai-review-model-not-independent",
                "AI Taste panel requires distinct reviewer models",
            )
        raw_hashes = [
            item.artifact(AITasteReviewArtifactRole.RAW_RESPONSE).sha256 for item in ai_reviews
        ]
        if ai_review_contract.require_distinct_raw_responses and len(raw_hashes) != len(
            set(raw_hashes)
        ):
            _admission_add(
                findings,
                "duplicate-ai-review-response",
                "AI Taste panel contains a repeated raw response",
            )
    primary_ai = tuple(
        item for item in ai_reviews if item.role is TasteAttributionReviewRole.PRIMARY
    )
    shared_primary_roles = (
        AITasteReviewArtifactRole.REVIEW_PACKET,
        AITasteReviewArtifactRole.INPUT_PROJECTION,
        AITasteReviewArtifactRole.RUBRIC,
        AITasteReviewArtifactRole.SYSTEM_PROMPT,
        AITasteReviewArtifactRole.USER_PROMPT,
        AITasteReviewArtifactRole.SAMPLING_CONFIG,
    )
    if len(primary_ai) == 2 and any(
        primary_ai[0].artifact(role).sha256 != primary_ai[1].artifact(role).sha256
        for role in shared_primary_roles
    ):
        _admission_add(
            findings,
            "ai-primary-packet-mismatch",
            "AI Taste primary reviewers did not receive the same frozen packet",
        )
    for review in ai_reviews:
        _inspect_ai_review_artifacts(review, evidence_root=evidence_root, findings=findings)
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
    decisive: tuple[TasteEpisodeAttributionReviewRecord, ...] = ()
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
    human_review_count = 0
    ai_review_count = len(ai_reviews)
    legacy_unverified_review_count = len(reviews) - ai_review_count
    review_evidence_kind: Literal["ai", "legacy-unverified", "mixed", "none"] = "none"
    if legacy_unverified_review_count and ai_review_count:
        review_evidence_kind = "mixed"
    elif legacy_unverified_review_count:
        review_evidence_kind = "legacy-unverified"
    elif ai_review_count:
        review_evidence_kind = "ai"
    return TasteEpisodeAdmissionReport(
        candidate_id=candidate.candidate_id,
        candidate_sha256=candidate.candidate_sha256,
        episode_inspection=episode_inspection,
        primary_review_count=len(primary),
        adjudicator_review_count=len(adjudicators),
        human_review_count=human_review_count,
        ai_review_count=ai_review_count,
        legacy_unverified_review_count=legacy_unverified_review_count,
        review_evidence_kind=review_evidence_kind,
        human_validity_claim_allowed=False,
        ai_review_contract_sha256=(
            ai_review_contract.contract_sha256 if ai_review_contract is not None else None
        ),
        cross_model_ai_panel=bool(ai_reviews)
        and len(ai_reviews) >= 2
        and len({item.model_id for item in ai_reviews}) == len(ai_reviews),
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
    reviews: tuple[TasteEpisodeAttributionReviewRecord, ...],
    *,
    admission_id: str,
    evidence_root: str | Path,
    current_idea_revision: ProjectIdeaRevisionBinding,
    ai_review_contract: AITasteReviewPanelContract | None = None,
    expected_ai_review_contract_sha256: str | None = None,
) -> AdmittedTasteEpisode:
    """Construct an immutable training unit; do not fit or mutate a policy."""

    report = inspect_taste_episode_admission(
        candidate,
        reviews,
        evidence_root=evidence_root,
        current_idea_revision=current_idea_revision,
        ai_review_contract=ai_review_contract,
        expected_ai_review_contract_sha256=expected_ai_review_contract_sha256,
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
        review_evidence_kind=report.review_evidence_kind,
        human_validity_claim_allowed=False,
        ai_review_contract_sha256=report.ai_review_contract_sha256,
        ai_review_count=report.ai_review_count,
        legacy_unverified_review_count=report.legacy_unverified_review_count,
        cross_model_ai_panel=report.cross_model_ai_panel,
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
        "decision-state-action",
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


class LifecycleTasteShuffleAssignment(BaseModel):
    """One auditable donor-to-recipient label assignment in the placebo control."""

    model_config = _CONFIG

    block_sha256: str = Field(pattern=_SHA256)
    recipient_admission_id: str = Field(pattern=_ID)
    recipient_source_group_key: str = Field(min_length=1, max_length=1_000)
    donor_admission_id: str = Field(pattern=_ID)
    donor_source_group_key: str = Field(min_length=1, max_length=1_000)
    original_action_id: str = Field(min_length=1, max_length=300)
    original_action_type: str = Field(min_length=1, max_length=200)
    assigned_action_id: str = Field(min_length=1, max_length=300)
    assigned_action_type: str = Field(min_length=1, max_length=200)
    effective_episode_weight: float = Field(gt=0.0, le=1.0)


class LifecycleTastePolicyModel(BaseModel):
    """Hash-bound posterior table learned from independently admitted episodes."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2", "1.3", "1.4", "1.5"] = "1.4"
    policy_id: str
    config: LifecycleTastePolicyConfig
    source_episode_ids: tuple[str, ...]
    source_episode_sha256: tuple[str, ...]
    source_group_keys: tuple[str, ...] = ()
    source_group_count: int = Field(default=0, ge=0)
    source_group_ids: tuple[str, ...] = ()
    training_episode_ids: tuple[str, ...]
    training_episode_sha256: tuple[str, ...]
    training_episode_count: int = Field(ge=0)
    training_source_group_keys: tuple[str, ...] = ()
    training_source_group_count: int = Field(default=0, ge=0)
    effective_training_weight: float = Field(default=0.0, ge=0.0)
    pairwise_comparison_count: int = Field(ge=0)
    source_review_evidence_kinds: tuple[Literal["ai", "legacy-unverified", "mixed"], ...] = ()
    source_ai_reviewed_episode_count: int = Field(default=0, ge=0)
    source_legacy_unverified_episode_count: int = Field(default=0, ge=0)
    ai_review_contract_sha256s: tuple[str, ...] = ()
    human_validity_claim_allowed: Literal[False] = False
    shuffle_algorithm: Literal[
        "not-applicable",
        "blocked-action-type-permutation-v2",
    ] = "not-applicable"
    shuffle_block_count: int = Field(default=0, ge=0)
    shuffled_episode_count: int = Field(default=0, ge=0)
    shuffle_fixed_point_count: int = Field(default=0, ge=0)
    shuffle_assignment_sha256: str | None = Field(default=None, pattern=_SHA256)
    shuffle_assignments: tuple[LifecycleTasteShuffleAssignment, ...] = ()
    trained_stages: tuple[str, ...]
    trained_domain_tags: tuple[str, ...]
    trained_venue_tags: tuple[str, ...]
    feature_posteriors: tuple[LifecycleTasteFeaturePosterior, ...]
    estimator: Literal[
        "factorized-beta-pairwise-v1",
        "signed-factorized-beta-pairwise-v2",
        "signed-factorized-beta-closed-set-v3",
    ] = "signed-factorized-beta-pairwise-v2"
    policy_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def policy_is_closed(self) -> LifecycleTastePolicyModel:
        if self.policy_id != self.config.policy_id:
            raise ValueError("lifecycle Taste policy and config IDs differ")
        if len(self.source_episode_ids) != len(set(self.source_episode_ids)):
            raise ValueError("lifecycle Taste source episode IDs must be unique")
        if self.schema_version in {"1.3", "1.4", "1.5"}:
            if self.source_group_count != len(self.source_group_keys):
                raise ValueError("lifecycle Taste source-group count differs")
            if self.source_group_keys != tuple(sorted(set(self.source_group_keys))):
                raise ValueError("lifecycle Taste source groups must be sorted and unique")
            if bool(self.source_episode_ids) != bool(self.source_group_keys):
                raise ValueError("lifecycle Taste source episodes and source groups disagree")
            if self.source_group_count > len(self.source_episode_ids):
                raise ValueError("lifecycle Taste source groups exceed source episodes")
        elif self.source_group_keys or self.source_group_count:
            raise ValueError("legacy lifecycle Taste policy cannot carry source-group closure")
        if self.schema_version in {"1.4", "1.5"}:
            if self.source_group_ids != tuple(sorted(set(self.source_group_ids))):
                raise ValueError("lifecycle Taste canonical source-group IDs are not closed")
            if bool(self.source_episode_ids) != bool(self.source_group_ids):
                raise ValueError(
                    "lifecycle Taste source episodes and canonical source-group IDs disagree"
                )
            if len(self.source_group_ids) > self.source_group_count:
                raise ValueError(
                    "lifecycle Taste canonical source-group IDs exceed clustered groups"
                )
        elif self.source_group_ids:
            raise ValueError("legacy lifecycle Taste policy cannot carry canonical group IDs")
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
        if list(self.source_review_evidence_kinds) != sorted(
            self.source_review_evidence_kinds
        ) or len(self.source_review_evidence_kinds) != len(set(self.source_review_evidence_kinds)):
            raise ValueError("lifecycle Taste review evidence kinds are not canonical")
        if list(self.ai_review_contract_sha256s) != sorted(self.ai_review_contract_sha256s) or len(
            self.ai_review_contract_sha256s
        ) != len(set(self.ai_review_contract_sha256s)):
            raise ValueError("lifecycle Taste AI review contracts are not canonical")
        if self.source_ai_reviewed_episode_count > len(self.source_episode_ids):
            raise ValueError("lifecycle Taste AI episode count exceeds source episodes")
        if self.source_legacy_unverified_episode_count > len(self.source_episode_ids):
            raise ValueError("lifecycle Taste legacy episode count exceeds source episodes")
        if self.source_ai_reviewed_episode_count and not self.ai_review_contract_sha256s:
            raise ValueError("AI-reviewed lifecycle Taste policy lacks panel contract")
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
        if self.schema_version in {"1.1", "1.2", "1.3", "1.4", "1.5"} and any(
            item.support > self.effective_training_weight + 1e-9 for item in self.feature_posteriors
        ):
            raise ValueError("lifecycle Taste feature support exceeds source-group weight")
        shuffled = self.config.update_mode is LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT
        shuffle_details = (
            self.shuffle_block_count,
            self.shuffled_episode_count,
            self.shuffle_fixed_point_count,
            self.shuffle_assignment_sha256,
            self.shuffle_assignments,
        )
        if shuffled:
            if self.schema_version in {"1.2", "1.3", "1.4", "1.5"}:
                self._validate_shuffle_v2()
            elif self.shuffle_algorithm != "not-applicable" or any(shuffle_details):
                raise ValueError("legacy shuffled-credit policy cannot carry v2 telemetry")
        elif self.shuffle_algorithm != "not-applicable" or any(shuffle_details):
            raise ValueError("non-shuffled policy cannot carry shuffle telemetry")
        expected = content_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        legacy_payload = self.model_dump(mode="json", exclude={"policy_sha256"})
        if self.schema_version not in {"1.3", "1.4", "1.5"}:
            legacy_payload.pop("source_group_keys")
            legacy_payload.pop("source_group_count")
        if self.schema_version not in {"1.4", "1.5"}:
            legacy_payload.pop("source_group_ids")
        for field in (
            "shuffle_algorithm",
            "shuffle_block_count",
            "shuffled_episode_count",
            "shuffle_fixed_point_count",
            "shuffle_assignment_sha256",
            "shuffle_assignments",
            "source_review_evidence_kinds",
            "source_ai_reviewed_episode_count",
            "source_legacy_unverified_episode_count",
            "ai_review_contract_sha256s",
            "human_validity_claim_allowed",
        ):
            if self.schema_version in {"1.0", "1.1"}:
                legacy_payload.pop(field)
        if self.schema_version == "1.0":
            for field in (
                "training_source_group_keys",
                "training_source_group_count",
                "effective_training_weight",
            ):
                legacy_payload.pop(field)
        legacy_expected = (
            content_sha256(legacy_payload) if self.schema_version not in {"1.4", "1.5"} else None
        )
        if self.policy_sha256 not in {expected, legacy_expected}:
            raise ValueError("lifecycle Taste policy hash mismatch")
        return self

    def _validate_shuffle_v2(self) -> None:
        if self.shuffle_algorithm != "blocked-action-type-permutation-v2":
            raise ValueError("shuffled-credit policy requires the blocked v2 algorithm")
        if self.shuffled_episode_count != self.training_episode_count:
            raise ValueError("shuffled-credit telemetry omits training episodes")
        if not self.shuffle_block_count or self.shuffle_assignment_sha256 is None:
            raise ValueError("shuffled-credit policy lacks permutation evidence")
        if len(self.shuffle_assignments) != self.shuffled_episode_count:
            raise ValueError("shuffled-credit assignment ledger is incomplete")
        if self.training_source_group_count != self.training_episode_count:
            raise ValueError("shuffled-credit requires one episode per source group")
        assignment_order = [
            (item.block_sha256, item.recipient_admission_id) for item in self.shuffle_assignments
        ]
        if assignment_order != sorted(assignment_order):
            raise ValueError("shuffled-credit assignment ledger is not canonical")
        if {item.recipient_admission_id for item in self.shuffle_assignments} != set(
            self.training_episode_ids
        ):
            raise ValueError("shuffled-credit recipients differ from training episodes")
        block_ids = {item.block_sha256 for item in self.shuffle_assignments}
        if self.shuffle_block_count != len(block_ids):
            raise ValueError("shuffled-credit block telemetry is inconsistent")
        if {item.recipient_source_group_key for item in self.shuffle_assignments} != set(
            self.training_source_group_keys
        ):
            raise ValueError("shuffled-credit source groups differ from training policy")
        if len({item.recipient_source_group_key for item in self.shuffle_assignments}) != len(
            self.shuffle_assignments
        ):
            raise ValueError("shuffled-credit ledger repeats a source-group unit")
        for block_sha256 in block_ids:
            block = tuple(
                item for item in self.shuffle_assignments if item.block_sha256 == block_sha256
            )
            by_recipient = {item.recipient_admission_id: item for item in block}
            if len(by_recipient) != len(block):
                raise ValueError("shuffled-credit block repeats a recipient")
            if {item.donor_admission_id for item in block} != set(by_recipient):
                raise ValueError("shuffled-credit block is not a donor permutation")
            for item in block:
                donor = by_recipient[item.donor_admission_id]
                if (
                    item.assigned_action_type != donor.original_action_type
                    or item.donor_source_group_key != donor.recipient_source_group_key
                ):
                    raise ValueError("shuffled-credit donor lineage is inconsistent")
            original_marginal: dict[str, float] = defaultdict(float)
            assigned_marginal: dict[str, float] = defaultdict(float)
            for item in block:
                original_marginal[item.original_action_type] += item.effective_episode_weight
                assigned_marginal[item.assigned_action_type] += item.effective_episode_weight
            if original_marginal != assigned_marginal:
                raise ValueError("shuffled-credit weighted action marginal differs")
        if self.shuffle_fixed_point_count != sum(
            item.original_action_type == item.assigned_action_type
            for item in self.shuffle_assignments
        ):
            raise ValueError("shuffled-credit fixed-point telemetry is inconsistent")
        expected_assignment_sha256 = content_sha256(
            [item.model_dump(mode="json") for item in self.shuffle_assignments]
        )
        if self.shuffle_assignment_sha256 != expected_assignment_sha256:
            raise ValueError("shuffled-credit assignment ledger hash differs")

    @property
    def h3_policy_artifact_eligible(self) -> bool:
        """Return policy-level eligibility; study sample/effects remain separate gates."""

        return self.intervention_policy_artifact_eligible and self.config.update_mode in {
            LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
            LifecycleTastePolicyUpdateMode.NO_UPDATE,
            LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT,
        }

    @property
    def intervention_policy_artifact_eligible(self) -> bool:
        """Return common provenance eligibility for confirmatory or diagnostic arms."""

        return (
            self.schema_version in {"1.4", "1.5"}
            and self.source_review_evidence_kinds == ("ai",)
            and self.source_ai_reviewed_episode_count == len(self.source_episode_ids)
            and self.source_legacy_unverified_episode_count == 0
            and len(self.ai_review_contract_sha256s) == 1
        )

    @property
    def h4_adaptive_policy_eligible(self) -> bool:
        """Require learned decision-state support before an H4 treatment run."""

        adaptive = tuple(
            item
            for item in self.feature_posteriors
            if item.feature_kind == "decision-state-action" and item.support > 0
        )
        return (
            self.schema_version == "1.5"
            and self.intervention_policy_artifact_eligible
            and len({item.feature.rpartition("::action::")[2] for item in adaptive}) >= 2
            and len({item.posterior_mean for item in adaptive}) >= 2
        )

    @classmethod
    def create(cls, **values: object) -> LifecycleTastePolicyModel:
        payload = {"schema_version": "1.4", **values}
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

    episodes = tuple(sorted(episodes, key=lambda item: item.admission_id))
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
            episode.candidate.schema_version not in {"1.2", "1.3"}
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
    decision_context_count = sum(item.candidate.decision_context is not None for item in selected)
    if decision_context_count not in {0, len(selected)}:
        raise ValueError("lifecycle Taste training cannot mix context-bound and legacy episodes")
    group_counts: dict[str, int] = defaultdict(int)
    for episode in selected:
        group_counts[_source_group_key(episode)] += 1
    training_preferences, shuffle_telemetry = _training_preferences(
        selected,
        config,
        group_counts,
    )
    observations: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    comparisons = 0
    effective_weight = 0.0
    for episode in selected:
        group_key = _source_group_key(episode)
        alternatives = episode.candidate.alternatives
        preferred_id = training_preferences[episode.admission_id]
        preferred = next(item for item in alternatives if item.action_id == preferred_id)
        competitors = tuple(item for item in alternatives if item.action_id != preferred_id)
        episode_weight = episode.training_weight / group_counts[group_key]
        effective_weight += episode_weight
        attributed_features = set(_episode_action_features(episode, preferred))
        direction = _policy_credit_direction(episode, config)
        if direction is None:
            raise ValueError("lifecycle Taste training episode has no attributable credit")
        episode_winning_features: set[tuple[str, str]] = set()
        episode_losing_features: set[tuple[str, str]] = set()
        for competitor in competitors:
            competitor_features = set(_episode_action_features(episode, competitor))
            winning_features, losing_features = (
                (attributed_features, competitor_features)
                if direction is TasteCreditDirection.BENEFICIAL
                else (competitor_features, attributed_features)
            )
            episode_winning_features.update(winning_features - losing_features)
            episode_losing_features.update(losing_features - winning_features)
            comparisons += 1
        # The candidate set is one correlated observation, not K-1 independent
        # samples.  Credit each unique feature at most once per episode so a
        # winner is not inflated while alternatives are not diluted merely
        # because more feasible actions were enumerated.
        for feature, _ in episode_winning_features:
            observations[feature][0] += episode_weight
        for feature, _ in episode_losing_features:
            observations[feature][1] += episode_weight
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
        schema_version="1.5" if decision_context_count else "1.4",
        policy_id=config.policy_id,
        config=config,
        source_episode_ids=tuple(ids),
        source_episode_sha256=tuple(item.admission_sha256 for item in episodes),
        source_group_keys=tuple(sorted(group_partitions)),
        source_group_count=len(group_partitions),
        source_group_ids=tuple(
            sorted(
                {
                    item.candidate.source_group_id
                    for item in episodes
                    if item.candidate.source_group_id is not None
                }
            )
        ),
        training_episode_ids=tuple(item.admission_id for item in selected),
        training_episode_sha256=tuple(item.admission_sha256 for item in selected),
        training_episode_count=len(selected),
        training_source_group_keys=tuple(sorted(group_counts)),
        training_source_group_count=len(group_counts),
        effective_training_weight=_rounded(effective_weight),
        pairwise_comparison_count=comparisons,
        source_review_evidence_kinds=tuple(
            sorted({item.review_evidence_kind for item in episodes})
        ),
        source_ai_reviewed_episode_count=sum(item.ai_review_count > 0 for item in episodes),
        source_legacy_unverified_episode_count=sum(
            item.legacy_unverified_review_count > 0 for item in episodes
        ),
        ai_review_contract_sha256s=tuple(
            sorted(
                {
                    item.ai_review_contract_sha256
                    for item in episodes
                    if item.ai_review_contract_sha256 is not None
                }
            )
        ),
        human_validity_claim_allowed=False,
        **shuffle_telemetry,
        trained_stages=tuple(sorted({item.candidate.stage for item in selected})),
        trained_domain_tags=tuple(
            sorted({tag.casefold() for item in selected for tag in item.candidate.domain_tags})
        ),
        trained_venue_tags=tuple(
            sorted({tag.casefold() for item in selected for tag in item.candidate.venue_tags})
        ),
        feature_posteriors=posteriors,
        estimator="signed-factorized-beta-closed-set-v3",
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
    return _policy_credit_direction(episode, config) is not None


def _policy_credit_direction(
    episode: AdmittedTasteEpisode,
    config: LifecycleTastePolicyConfig,
) -> TasteCreditDirection | None:
    """Return one auditable sign for the action receiving admitted credit.

    ``preferred_action_id`` identifies the action to which the reviewed credit
    applies. Beneficial credit makes that action the pairwise winner; harmful
    credit makes it the loser. Mixing those directions in one admission would
    make the training label undefined, so the estimator fails closed.
    """

    credit_by_id = {item.credit_id: item for item in episode.candidate.credit_assignments}
    directions = {
        credit_by_id[credit_id].direction
        for credit_id in episode.supported_credit_ids
        if credit_by_id[credit_id].family in config.eligible_outcome_families
        and credit_by_id[credit_id].direction is not TasteCreditDirection.NOT_ATTRIBUTABLE
    }
    if len(directions) > 1:
        raise ValueError("lifecycle Taste admission mixes beneficial and harmful credit")
    return next(iter(directions), None)


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


def _training_preferences(
    episodes: tuple[AdmittedTasteEpisode, ...],
    config: LifecycleTastePolicyConfig,
    group_counts: dict[str, int],
) -> tuple[dict[str, str], dict[str, object]]:
    if config.update_mode is not LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT:
        return (
            {item.admission_id: item.preferred_action_id for item in episodes},
            {
                "shuffle_algorithm": "not-applicable",
                "shuffle_block_count": 0,
                "shuffled_episode_count": 0,
                "shuffle_fixed_point_count": 0,
                "shuffle_assignment_sha256": None,
                "shuffle_assignments": (),
            },
        )

    blocks: dict[tuple[object, ...], list[AdmittedTasteEpisode]] = defaultdict(list)
    if any(count != 1 for count in group_counts.values()):
        raise ValueError("blocked shuffled-credit requires one sampled episode per source group")
    for episode in episodes:
        action_types = [item.action_type for item in episode.candidate.alternatives]
        if len(action_types) != len(set(action_types)):
            raise ValueError("blocked shuffled-credit requires one alternative per action type")
        block_key = (
            episode.candidate.dataset_partition.value,
            episode.candidate.stage,
            tuple(sorted(action_types)),
            _supported_outcome_stratum(episode, config),
            (episode.training_weight / group_counts[_source_group_key(episode)]).hex(),
        )
        blocks[block_key].append(episode)

    assignments: dict[str, str] = {}
    assignment_records: list[LifecycleTasteShuffleAssignment] = []
    fixed_points = 0
    ordered_blocks = sorted(
        ((content_sha256(block_key), block_key, members) for block_key, members in blocks.items()),
        key=lambda item: item[0],
    )
    for block_sha256, _block_key, members in ordered_blocks:
        ordered = sorted(members, key=lambda item: item.admission_id)
        preferred_types = [
            next(
                action.action_type
                for action in item.candidate.alternatives
                if action.action_id == item.preferred_action_id
            )
            for item in ordered
        ]
        if len(ordered) < 2 or len(set(preferred_types)) < 2:
            raise ValueError(
                "blocked shuffled-credit requires at least two episodes and two "
                "preferred action types in every frozen block"
            )
        donor_indices = _seeded_permutation(
            len(ordered),
            seed=config.shuffle_seed,
            block_sha256=block_sha256,
        )
        for index, episode in enumerate(ordered):
            donor = ordered[donor_indices[index]]
            assigned_type = preferred_types[donor_indices[index]]
            assigned_action_id = next(
                action.action_id
                for action in episode.candidate.alternatives
                if action.action_type == assigned_type
            )
            assignments[episode.admission_id] = assigned_action_id
            original_type = preferred_types[index]
            fixed_points += assigned_type == original_type
            assignment_records.append(
                LifecycleTasteShuffleAssignment(
                    block_sha256=block_sha256,
                    recipient_admission_id=episode.admission_id,
                    recipient_source_group_key=_source_group_key(episode),
                    donor_admission_id=donor.admission_id,
                    donor_source_group_key=_source_group_key(donor),
                    original_action_id=episode.preferred_action_id,
                    original_action_type=original_type,
                    assigned_action_id=assigned_action_id,
                    assigned_action_type=assigned_type,
                    effective_episode_weight=(
                        episode.training_weight / group_counts[_source_group_key(episode)]
                    ),
                )
            )

    assignment_payload = [item.model_dump(mode="json") for item in assignment_records]
    return (
        assignments,
        {
            "shuffle_algorithm": "blocked-action-type-permutation-v2",
            "shuffle_block_count": len(blocks),
            "shuffled_episode_count": len(episodes),
            "shuffle_fixed_point_count": fixed_points,
            "shuffle_assignment_sha256": content_sha256(assignment_payload),
            "shuffle_assignments": tuple(assignment_records),
        },
    )


def _seeded_permutation(
    size: int,
    *,
    seed: int,
    block_sha256: str,
) -> list[int]:
    """Return a label-independent deterministic Fisher--Yates permutation."""

    values = list(range(size))
    for upper in range(size - 1, 0, -1):
        digest = hashlib.sha256(
            f"blocked-action-type-permutation-v2:{seed}:{block_sha256}:{upper}".encode()
        ).digest()
        span = upper + 1
        limit = (1 << 256) - ((1 << 256) % span)
        nonce = 0
        value = int.from_bytes(digest, "big")
        while value >= limit:
            nonce += 1
            value = int.from_bytes(
                hashlib.sha256(digest + nonce.to_bytes(8, "big")).digest(),
                "big",
            )
        swap_index = value % span
        values[upper], values[swap_index] = values[swap_index], values[upper]
    return values


def _supported_outcome_stratum(
    episode: AdmittedTasteEpisode,
    config: LifecycleTastePolicyConfig,
) -> tuple[tuple[str, str, str, str, str], ...]:
    credit_by_id = {item.credit_id: item for item in episode.candidate.credit_assignments}
    outcome_by_id = {item.outcome_id: item for item in episode.candidate.outcomes}
    confounder_by_id = {item.confounder_id: item for item in episode.candidate.confounders}
    return tuple(
        sorted(
            {
                (
                    credit.family.value,
                    credit.direction.value,
                    credit.confidence.hex(),
                    outcome_by_id[outcome_id].polarity.value,
                    ",".join(
                        sorted(confounder_by_id[item].resolution for item in credit.confounder_ids)
                    ),
                )
                for credit_id in episode.supported_credit_ids
                for credit in (credit_by_id[credit_id],)
                if credit.family in config.eligible_outcome_families
                for outcome_id in credit.outcome_ids
            }
        )
    )


def _inspect_ai_review_artifacts(
    review: AITasteEpisodeAttributionReview,
    *,
    evidence_root: str | Path,
    findings: list[TasteEpisodeAdmissionFinding],
) -> None:
    root = Path(evidence_root).resolve()
    for binding in review.artifacts:
        path = (root / binding.locator).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            _admission_add(
                findings,
                "ai-review-artifact-outside-root",
                f"AI review artifact leaves evidence root: {binding.locator}",
            )
            continue
        if not path.is_file():
            _admission_add(
                findings,
                "ai-review-artifact-missing",
                f"AI review artifact is missing: {binding.locator}",
            )
            continue
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != binding.sha256:
            _admission_add(
                findings,
                "ai-review-artifact-hash-mismatch",
                f"AI review artifact hash differs: {binding.locator}",
            )

    firewall_binding = review.artifact(AITasteReviewArtifactRole.FIREWALL_REPORT)
    firewall_path = root / firewall_binding.locator
    if not firewall_path.is_file():
        return
    try:
        payload = yaml.safe_load(firewall_path.read_text(encoding="utf-8"))
        firewall = AITasteReviewFirewallReport.model_validate(payload)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        _admission_add(
            findings,
            "ai-review-firewall-invalid",
            f"AI review firewall report is invalid: {exc}",
        )
        return
    if (
        firewall.review_packet_sha256
        != review.artifact(AITasteReviewArtifactRole.REVIEW_PACKET).sha256
        or firewall.input_projection_sha256
        != review.artifact(AITasteReviewArtifactRole.INPUT_PROJECTION).sha256
    ):
        _admission_add(
            findings,
            "ai-review-firewall-binding-mismatch",
            "AI review firewall report binds another visible input",
        )

    expected_prompt_sha256 = content_sha256(
        {
            role.value: review.artifact(role).sha256
            for role in (
                AITasteReviewArtifactRole.SYSTEM_PROMPT,
                AITasteReviewArtifactRole.USER_PROMPT,
            )
        }
    )
    if review.prompt_sha256 != expected_prompt_sha256:
        _admission_add(
            findings,
            "ai-review-prompt-binding-mismatch",
            "AI review prompt hash differs from its prompt artifacts",
        )

    receipt_binding = review.artifact(AITasteReviewArtifactRole.EXECUTION_RECEIPT)
    receipt_path = root / receipt_binding.locator
    if receipt_path.is_file():
        try:
            receipt = AITasteReviewExecutionReceipt.model_validate(
                yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            _admission_add(
                findings,
                "ai-review-execution-receipt-invalid",
                f"AI review execution receipt is invalid: {exc}",
            )
        else:
            expected_receipt_identity = (
                review.provider_id,
                review.model_id,
                review.model_revision,
                review.run_id,
                review.prompt_sha256,
                review.artifact(AITasteReviewArtifactRole.INPUT_PROJECTION).sha256,
                review.artifact(AITasteReviewArtifactRole.RAW_RESPONSE).sha256,
            )
            observed_receipt_identity = (
                receipt.provider_id,
                receipt.model_id,
                receipt.model_revision,
                receipt.run_id,
                receipt.prompt_sha256,
                receipt.input_projection_sha256,
                receipt.raw_response_sha256,
            )
            if observed_receipt_identity != expected_receipt_identity:
                _admission_add(
                    findings,
                    "ai-review-execution-identity-mismatch",
                    "AI review execution receipt differs from the normalized review",
                )

    normalization_binding = review.artifact(AITasteReviewArtifactRole.NORMALIZATION_REPORT)
    normalization_path = root / normalization_binding.locator
    if normalization_path.is_file():
        try:
            normalization = AITasteReviewNormalizationReport.model_validate(
                yaml.safe_load(normalization_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            _admission_add(
                findings,
                "ai-review-normalization-report-invalid",
                f"AI review normalization report is invalid: {exc}",
            )
        else:
            if (
                normalization.run_id != review.run_id
                or normalization.candidate_sha256 != review.candidate_sha256
                or normalization.raw_response_sha256
                != review.artifact(AITasteReviewArtifactRole.RAW_RESPONSE).sha256
                or normalization.normalized_response_sha256 != review.normalized_response_sha256
            ):
                _admission_add(
                    findings,
                    "ai-review-normalization-binding-mismatch",
                    "AI review normalization report differs from the review evidence",
                )


def _episode_action_features(episode, action) -> tuple[tuple[str, str], ...]:  # type: ignore[no-untyped-def]
    return _features(
        stage=episode.candidate.stage,
        domain_tags=episode.candidate.domain_tags,
        venue_tags=episode.candidate.venue_tags,
        action_type=action.action_type,
        tags=action.tags,
        decision_context=(
            ()
            if episode.candidate.decision_context is None
            else tuple(episode.candidate.decision_context.model_dump(mode="json").items())
        ),
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
        decision_context=_state_decision_context(state),
    )


def _features(
    *,
    stage: str,
    domain_tags: tuple[str, ...],
    venue_tags: tuple[str, ...],
    action_type: str,
    tags: tuple[str, ...],
    decision_context: tuple[tuple[str, str], ...] = (),
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
    for name, value in sorted(decision_context):
        normalized_name = _normal(name)
        normalized_value = _normal(value)
        features.append(
            (
                f"decision-state::{normalized_name}::{normalized_value}::action::{normalized_action}",
                "decision-state-action",
            )
        )
    return tuple(features)


def _state_decision_context(state: ResearchState) -> tuple[tuple[str, str], ...]:
    context = state.executor_context
    required = (
        "remaining_experiments",
        "failure_count",
        "no_improvement_streak",
        "score_trend",
        "best_vs_baseline",
    )
    if any(name not in context for name in required):
        return ()
    return tuple((name, str(context[name])) for name in required)


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
        "decision-state-action": 2.0,
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

"""Condition-blind, AI-only preference panels for SciTasteBench H1/H2.

This module consumes only the public study manifest and its reviewer-visible
outputs.  It deliberately has no blind-key or generation-ledger input: private
condition identity remains unavailable until the primary AI review set is
locked by a later, separate workflow.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.benchmark.models import BenchmarkCase, BenchmarkSuite
from scitaste.benchmark.runner import load_benchmark_suite
from scitaste.evaluation.human_outcomes import (
    HumanOutcomeStudyManifest,
    TasteMechanismHypothesis,
    load_human_outcome_study,
)
from scitaste.evaluation.human_study_preparation import BlindedDecisionArtifact

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 64 * 1_048_576
_PRIVATE_NAMES = {"private", "blind-key.json", "generation-ledger.json", "blinding-secret.json"}


class AIBlindPreference(StrEnum):
    X = "X"
    TIE = "tie"
    Y = "Y"


class AIPreferenceDisposition(StrEnum):
    COMPLETED = "completed"
    CANNOT_ASSESS = "cannot-assess"


class AIPreferenceFileBinding(BaseModel):
    """Content binding used only by the AI preference panel."""

    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_public_and_relative(self) -> AIPreferenceFileBinding:
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("AI preference bindings must be relative and non-traversing")
        if any(part.lower() in _PRIVATE_NAMES for part in path.parts):
            raise ValueError("AI preference bindings cannot address private study material")
        return self


class AIPreferenceModelIdentity(BaseModel):
    """Explicit provider/model identity for one nonhuman panel role."""

    model_config = _CONFIG

    reviewer_id: str = Field(pattern=_ID)
    role: Literal["primary-a", "primary-b", "adjudicator"]
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    model_revision: str = Field(min_length=1, max_length=300)
    identity_sha256: str = Field(pattern=_SHA256)
    assignment_identity_sha256: str | None = Field(default=None, pattern=_SHA256)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_identity_verified: Literal[False] = False
    human_qualification_verified: Literal[False] = False
    human_consent_obtained: Literal[False] = False

    @model_validator(mode="after")
    def identity_is_content_derived(self) -> AIPreferenceModelIdentity:
        expected = _canonical_sha256(
            {
                "provider": self.provider,
                "model": self.model,
                "model_revision": self.model_revision,
            }
        )
        if self.identity_sha256 != expected:
            raise ValueError("AI reviewer identity hash does not match provider/model/revision")
        if self.role != "adjudicator" and self.assignment_identity_sha256 is None:
            raise ValueError("primary AI reviewers require a public assignment identity")
        if self.role == "adjudicator" and self.assignment_identity_sha256 is not None:
            raise ValueError("the disputed-only adjudicator cannot claim a primary assignment")
        return self


class AIBlindPreferenceProtocol(BaseModel):
    """No-call protocol defining a two-primary, disputed-only AI panel."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    protocol_id: str = Field(pattern=_ID)
    study_id: str = Field(pattern=_ID)
    benchmark_suite: AIPreferenceFileBinding
    primary_reviewers: tuple[AIPreferenceModelIdentity, AIPreferenceModelIdentity]
    adjudicator: AIPreferenceModelIdentity
    primary_question: str = Field(min_length=1, max_length=10_000)
    decision_standards: tuple[str, ...] = Field(min_length=1, max_length=20)
    tie_rule: str = Field(min_length=1, max_length=10_000)
    cannot_assess_rule: str = Field(min_length=1, max_length=10_000)
    maximum_rationale_characters: int = Field(gt=0, le=40_000)
    condition_identity_hidden: Literal[True] = True
    primary_reviewers_blinded_to_each_other: Literal[True] = True
    primary_outputs_absent_from_adjudicator_request: Literal[True] = True
    disputed_items_only_adjudication: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    human_identity_verified: Literal[False] = False
    human_qualification_verified: Literal[False] = False
    human_consent_obtained: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def reviewer_roles_and_identities_are_distinct(self) -> AIBlindPreferenceProtocol:
        if [item.role for item in self.primary_reviewers] != ["primary-a", "primary-b"]:
            raise ValueError("primary AI reviewers must be ordered primary-a then primary-b")
        if self.adjudicator.role != "adjudicator":
            raise ValueError("AI preference adjudicator must use the adjudicator role")
        reviewers = (*self.primary_reviewers, self.adjudicator)
        if len({item.reviewer_id for item in reviewers}) != 3:
            raise ValueError("AI preference reviewer IDs must be distinct")
        if len({item.identity_sha256 for item in reviewers}) != 3:
            raise ValueError("AI preference provider/model identities must be distinct")
        if len({item.provider for item in self.primary_reviewers}) != 2:
            raise ValueError("the two primary AI reviewers must use different providers")
        assignments = {item.assignment_identity_sha256 for item in self.primary_reviewers}
        if len(assignments) != 2:
            raise ValueError("the two primary AI reviewers must bind different assignments")
        return self

    @computed_field
    @property
    def protocol_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"protocol_sha256"}))


class AIPreferenceVisibleDecision(BaseModel):
    model_config = _CONFIG

    output_id: str = Field(pattern=_ID)
    selected_action_id: str = Field(min_length=1, max_length=300)
    selected_action_description: str = Field(min_length=1, max_length=10_000)
    rationale: str = Field(min_length=1, max_length=40_000)
    confidence: float = Field(ge=0, le=1)
    output_sha256: str = Field(pattern=_SHA256)


class AIPreferenceRequestItem(BaseModel):
    model_config = _CONFIG

    ordinal: int = Field(gt=0, le=100_000)
    comparison_id: str = Field(pattern=_ID)
    hypothesis: TasteMechanismHypothesis
    case_id: str = Field(pattern=_ID)
    source_group: str = Field(pattern=_ID)
    case_context: str = Field(min_length=1, max_length=100_000)
    task: str = Field(min_length=1, max_length=300)
    stage: str = Field(min_length=1, max_length=300)
    output_x: AIPreferenceVisibleDecision
    output_y: AIPreferenceVisibleDecision
    condition_identity_hidden: Literal[True] = True

    @model_validator(mode="after")
    def outputs_differ(self) -> AIPreferenceRequestItem:
        if self.output_x.output_sha256 == self.output_y.output_sha256:
            raise ValueError("AI preference request outputs must differ")
        return self


class AIPreferencePrimaryRequest(BaseModel):
    """One provider-ready request that contains only its assigned blind comparisons."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    protocol_sha256: str = Field(pattern=_SHA256)
    reviewer: AIPreferenceModelIdentity
    primary_question: str
    decision_standards: tuple[str, ...]
    tie_rule: str
    cannot_assess_rule: str
    maximum_rationale_characters: int
    required_response_schema: Literal["scitaste-ai-preference-response-v1"] = (
        "scitaste-ai-preference-response-v1"
    )
    items: tuple[AIPreferenceRequestItem, ...] = Field(min_length=2, max_length=100_000)
    condition_identity_hidden: Literal[True] = True
    other_primary_review_output_absent: Literal[True] = True
    private_blind_key_absent: Literal[True] = True
    private_generation_ledger_absent: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    authorizes_model_calls: Literal[False] = False

    @computed_field
    @property
    def request_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))


class AIPreferenceRequestPack(BaseModel):
    """Public, no-call binding for two identity-distinct primary requests."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    pack_id: str = Field(pattern=_ID)
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    study: AIPreferenceFileBinding
    benchmark_suite: AIPreferenceFileBinding
    benchmark_suite_semantic_sha256: str = Field(pattern=_SHA256)
    protocol: AIPreferenceFileBinding
    protocol_sha256: str = Field(pattern=_SHA256)
    primary_requests: tuple[AIPreferenceFileBinding, AIPreferenceFileBinding]
    primary_request_sha256s: tuple[str, str]
    primary_reviewer_identity_sha256s: tuple[str, str]
    adjudicator_identity_sha256: str = Field(pattern=_SHA256)
    comparison_count: int = Field(gt=0)
    reviewer_count: Literal[2] = 2
    condition_identity_hidden: Literal[True] = True
    primary_reviewers_blinded_to_each_other: Literal[True] = True
    private_blind_key_read: Literal[False] = False
    private_generation_ledger_read: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    human_identity_verified: Literal[False] = False
    human_qualification_verified: Literal[False] = False
    human_consent_obtained: Literal[False] = False
    no_external_action_performed: Literal[True] = True
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @computed_field
    @property
    def pack_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"pack_sha256"}))


class AIRawPreferenceResponseItem(BaseModel):
    """Provider JSON item before deterministic normalization."""

    model_config = _CONFIG

    comparison_id: str = Field(pattern=_ID)
    response: Literal["X", "tie", "Y", "cannot-assess"]
    rationale: str = Field(min_length=1, max_length=40_000)
    missingness_reason_code: str | None = Field(default=None, pattern=_ID)

    @model_validator(mode="after")
    def missingness_matches_response(self) -> AIRawPreferenceResponseItem:
        if (self.response == "cannot-assess") != (self.missingness_reason_code is not None):
            raise ValueError("cannot-assess requires exactly one missingness reason")
        return self


class AIRawPreferenceResponse(BaseModel):
    """Untrusted-but-typed response bytes retained exactly as returned."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    response_schema: Literal["scitaste-ai-preference-response-v1"]
    reviewer_id: str = Field(pattern=_ID)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    responses: tuple[AIRawPreferenceResponseItem, ...] = Field(min_length=2, max_length=100_000)
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False

    @model_validator(mode="after")
    def response_ids_are_unique(self) -> AIRawPreferenceResponse:
        _require_unique((item.comparison_id for item in self.responses), "AI response comparisons")
        return self


class AIReviewUsage(BaseModel):
    """Hash-bound provider token and cost telemetry."""

    model_config = _CONFIG

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    pricing_sha256: str = Field(pattern=_SHA256)
    usage_sha256: str = Field(pattern=_SHA256)
    cost_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def usage_is_coherent_and_self_hashed(self) -> AIReviewUsage:
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("AI review total tokens do not match input plus output")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("AI review cached input tokens exceed input tokens")
        usage_payload = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_input_tokens": self.cached_input_tokens,
        }
        if self.usage_sha256 != _canonical_sha256(usage_payload):
            raise ValueError("AI review usage hash mismatch")
        cost_payload = {
            **usage_payload,
            "cost_usd": self.cost_usd,
            "pricing_sha256": self.pricing_sha256,
        }
        if self.cost_sha256 != _canonical_sha256(cost_payload):
            raise ValueError("AI review cost hash mismatch")
        return self


class AIReviewExecutionReceipt(BaseModel):
    """Caller-supplied evidence that binds one model invocation to raw bytes."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str = Field(pattern=_ID)
    reviewer_id: str = Field(pattern=_ID)
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=300)
    model_revision: str = Field(min_length=1, max_length=300)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    backend_config: AIPreferenceFileBinding
    request: AIPreferenceFileBinding
    request_sha256: str = Field(pattern=_SHA256)
    http_request: AIPreferenceFileBinding
    raw_http_body: AIPreferenceFileBinding
    raw_response: AIPreferenceFileBinding
    provider_request_id: str = Field(min_length=1, max_length=1_000)
    started_at: datetime
    completed_at: datetime
    http_status: int = Field(ge=100, le=599)
    usage: AIReviewUsage
    model_call_observed: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    authorizes_additional_model_calls: Literal[False] = False

    @model_validator(mode="after")
    def receipt_is_temporally_valid(self) -> AIReviewExecutionReceipt:
        if self.started_at.utcoffset() is None or self.completed_at.utcoffset() is None:
            raise ValueError("AI execution receipt timestamps must include a timezone")
        if self.completed_at < self.started_at:
            raise ValueError("AI execution receipt cannot complete before it starts")
        return self


class AINormalizedPreferenceRow(BaseModel):
    """Condition-blind primary result with a self-hash and exact provenance."""

    model_config = _CONFIG

    row_id: str = Field(pattern=_ID)
    comparison_id: str = Field(pattern=_ID)
    hypothesis: TasteMechanismHypothesis
    case_id: str = Field(pattern=_ID)
    source_group: str = Field(pattern=_ID)
    reviewer_id: str = Field(pattern=_ID)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    raw_response_file_sha256: str = Field(pattern=_SHA256)
    execution_receipt_file_sha256: str = Field(pattern=_SHA256)
    disposition: AIPreferenceDisposition
    blinded_preference: AIBlindPreference | None
    selected_output_sha256: str | None = Field(default=None, pattern=_SHA256)
    rationale: str = Field(min_length=1, max_length=40_000)
    missingness_reason_code: str | None = Field(default=None, pattern=_ID)
    condition_identity_hidden: Literal[True] = True
    blinded_to_other_primary_review: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    row_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def row_is_consistent_and_self_hashed(self) -> AINormalizedPreferenceRow:
        completed = self.disposition is AIPreferenceDisposition.COMPLETED
        if completed != (self.blinded_preference is not None):
            raise ValueError("only completed AI preference rows contain a preference")
        if completed == (self.missingness_reason_code is not None):
            raise ValueError("non-completed AI preference rows require a reason")
        if self.blinded_preference in {AIBlindPreference.X, AIBlindPreference.Y}:
            if self.selected_output_sha256 is None:
                raise ValueError("an X/Y AI preference must bind the selected output")
        elif self.selected_output_sha256 is not None:
            raise ValueError("tie or missing AI preference cannot select one output")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"row_sha256"}))
        if self.row_sha256 != expected:
            raise ValueError("normalized AI preference row hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> AINormalizedPreferenceRow:
        payload = dict(values)
        payload.pop("row_sha256", None)
        unsigned = cls.model_construct(row_sha256="0" * 64, **payload)
        return cls(
            **payload,
            row_sha256=_canonical_sha256(unsigned.model_dump(mode="json", exclude={"row_sha256"})),
        )


class AIPreferenceDispute(BaseModel):
    model_config = _CONFIG

    dispute_id: str = Field(pattern=_ID)
    hypothesis: TasteMechanismHypothesis
    case_id: str = Field(pattern=_ID)
    source_group: str = Field(pattern=_ID)
    primary_row_sha256s: tuple[str, str]
    reason: Literal["preference-disagreement", "assessment-disagreement"]


class LockedAIPreferenceReviewSet(BaseModel):
    """Two-primary AI results frozen before any private condition opening."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    lock_id: str = Field(pattern=_ID)
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    protocol_sha256: str = Field(pattern=_SHA256)
    request_pack_sha256: str = Field(pattern=_SHA256)
    normalized_rows: tuple[AINormalizedPreferenceRow, ...] = Field(min_length=4, max_length=100_000)
    raw_responses: tuple[AIPreferenceFileBinding, AIPreferenceFileBinding]
    execution_receipts: tuple[AIPreferenceFileBinding, AIPreferenceFileBinding]
    disputes: tuple[AIPreferenceDispute, ...]
    locked_at: datetime
    all_primary_ai_reviews_locked: Literal[True] = True
    condition_identity_hidden_until_lock: Literal[True] = True
    private_blind_key_read: Literal[False] = False
    private_generation_ledger_read: Literal[False] = False
    adjudication_performed: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    human_identity_verified: Literal[False] = False
    human_qualification_verified: Literal[False] = False
    human_consent_obtained: Literal[False] = False
    no_external_action_performed: Literal[True] = True
    authorizes_model_calls: Literal[False] = False

    @model_validator(mode="after")
    def lock_is_complete(self) -> LockedAIPreferenceReviewSet:
        if self.locked_at.utcoffset() is None:
            raise ValueError("AI preference lock timestamp must include a timezone")
        _require_unique((item.row_id for item in self.normalized_rows), "AI preference row IDs")
        _require_unique(
            (item.comparison_id for item in self.normalized_rows),
            "AI preference comparison IDs",
        )
        return self

    @computed_field
    @property
    def review_set_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"review_set_sha256"}))


class AIAdjudicationRequestItem(BaseModel):
    model_config = _CONFIG

    ordinal: int = Field(gt=0)
    dispute_id: str = Field(pattern=_ID)
    hypothesis: TasteMechanismHypothesis
    case_id: str = Field(pattern=_ID)
    source_group: str = Field(pattern=_ID)
    case_context: str = Field(min_length=1, max_length=100_000)
    task: str = Field(min_length=1, max_length=300)
    stage: str = Field(min_length=1, max_length=300)
    output_x: AIPreferenceVisibleDecision
    output_y: AIPreferenceVisibleDecision
    primary_preferences_absent: Literal[True] = True
    primary_rationales_absent: Literal[True] = True
    condition_identity_hidden: Literal[True] = True


class AIAdjudicationRequest(BaseModel):
    """Third-model request containing only primary disagreements and no primary output."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(pattern=_ID)
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    protocol_sha256: str = Field(pattern=_SHA256)
    locked_primary_review_set_sha256: str = Field(pattern=_SHA256)
    adjudicator: AIPreferenceModelIdentity
    primary_question: str
    decision_standards: tuple[str, ...]
    tie_rule: str
    cannot_assess_rule: str
    required_response_schema: Literal["scitaste-ai-adjudication-response-v1"] = (
        "scitaste-ai-adjudication-response-v1"
    )
    items: tuple[AIAdjudicationRequestItem, ...] = Field(min_length=1, max_length=100_000)
    disputed_items_only: Literal[True] = True
    primary_review_outputs_absent: Literal[True] = True
    condition_identity_hidden: Literal[True] = True
    private_blind_key_absent: Literal[True] = True
    private_generation_ledger_absent: Literal[True] = True
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    authorizes_model_calls: Literal[False] = False

    @computed_field
    @property
    def request_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))


class AIPreferenceLockReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str = Field(pattern=_ID)
    locked_review_set: AIPreferenceFileBinding
    review_set_sha256: str = Field(pattern=_SHA256)
    normalized_row_count: int = Field(gt=0)
    normalized_row_sha256s: tuple[str, ...] = Field(min_length=1)
    raw_responses: tuple[AIPreferenceFileBinding, AIPreferenceFileBinding]
    execution_receipts: tuple[AIPreferenceFileBinding, AIPreferenceFileBinding]
    dispute_count: int = Field(ge=0)
    adjudicator_pack: AIPreferenceFileBinding | None
    adjudicator_request_sha256: str | None = Field(default=None, pattern=_SHA256)
    adjudicator_pack_created_only_for_disputes: Literal[True] = True
    condition_identity_hidden_through_primary_lock: Literal[True] = True
    private_blind_key_read: Literal[False] = False
    private_generation_ledger_read: Literal[False] = False
    reviewer_kind: Literal["ai"] = "ai"
    not_human_review: Literal[True] = True
    human_validity_claim_allowed: Literal[False] = False
    no_external_action_performed: Literal[True] = True
    authorizes_model_calls: Literal[False] = False

    @model_validator(mode="after")
    def adjudicator_binding_matches_disputes(self) -> AIPreferenceLockReport:
        present = self.adjudicator_pack is not None
        if (self.dispute_count > 0) != present:
            raise ValueError("adjudicator pack presence must exactly match primary disputes")
        if present != (self.adjudicator_request_sha256 is not None):
            raise ValueError("adjudicator pack and request hash must be present together")
        return self


def load_ai_blind_preference_protocol(path: str | Path) -> AIBlindPreferenceProtocol:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("AI blind preference protocol must be a mapping")
    return AIBlindPreferenceProtocol.model_validate(payload)


def load_ai_preference_request_pack(path: str | Path) -> AIPreferenceRequestPack:
    return AIPreferenceRequestPack.model_validate_json(Path(path).read_text(encoding="utf-8"))


def compile_ai_preference_request_pack(
    *,
    evidence_root: str | Path,
    study_path_or_dir: str | Path,
    protocol_path: str | Path,
    output_dir: str | Path,
) -> AIPreferenceRequestPack:
    """Compile two isolated provider requests from public study bytes only."""

    root = Path(evidence_root).resolve(strict=True)
    study_file = _resolve_public_study(root, study_path_or_dir)
    protocol_file = _regular_public_file(root, protocol_path)
    target = _new_public_target(root, output_dir)
    study = load_human_outcome_study(study_file)
    protocol = load_ai_blind_preference_protocol(protocol_file)
    if protocol.study_id != study.study_id:
        raise ValueError("AI preference protocol binds another study")
    suite_file = _bound_public_file(root, protocol.benchmark_suite)
    suite = load_benchmark_suite(suite_file)
    _verify_study_suite(study, suite, suite_file)
    cases = {item.case_id: item for item in suite.cases}
    study_file_sha = _sha256(study_file)
    assignments = {item.reviewer_identity_sha256 for item in study.comparisons}
    expected_assignments = {item.assignment_identity_sha256 for item in protocol.primary_reviewers}
    if assignments != expected_assignments:
        raise ValueError("AI protocol reviewer assignments differ from the public study")

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as temporary:
        workspace = Path(temporary)
        request_models: list[AIPreferencePrimaryRequest] = []
        request_bindings: list[AIPreferenceFileBinding] = []
        for reviewer in protocol.primary_reviewers:
            selected = [
                item
                for item in study.comparisons
                if item.reviewer_identity_sha256 == reviewer.assignment_identity_sha256
            ]
            if not selected:
                raise ValueError("AI preference primary reviewer has no public assignment")
            request = AIPreferencePrimaryRequest(
                request_id=f"request-{reviewer.role}-{study.study_sha256[:20]}",
                study_id=study.study_id,
                study_sha256=study.study_sha256,
                protocol_sha256=protocol.protocol_sha256,
                reviewer=reviewer,
                primary_question=protocol.primary_question,
                decision_standards=protocol.decision_standards,
                tie_rule=protocol.tie_rule,
                cannot_assess_rule=protocol.cannot_assess_rule,
                maximum_rationale_characters=protocol.maximum_rationale_characters,
                items=tuple(
                    _request_item(root, comparison, cases[comparison.case_id], ordinal)
                    for ordinal, comparison in enumerate(selected, 1)
                ),
            )
            relative = Path("requests") / f"{reviewer.role}.json"
            _write_json(
                workspace / relative,
                request.model_dump(mode="json", exclude={"request_sha256"}),
            )
            request_models.append(request)
            request_bindings.append(_workspace_binding(root, target, workspace, relative))
        pack = AIPreferenceRequestPack(
            pack_id=f"ai-preference-pack-{study.study_sha256[:20]}",
            study_id=study.study_id,
            study_sha256=study.study_sha256,
            study=_binding(root, study_file),
            benchmark_suite=_binding(root, suite_file),
            benchmark_suite_semantic_sha256=suite.sha256,
            protocol=_binding(root, protocol_file),
            protocol_sha256=protocol.protocol_sha256,
            primary_requests=tuple(request_bindings),  # type: ignore[arg-type]
            primary_request_sha256s=tuple(  # type: ignore[arg-type]
                item.request_sha256 for item in request_models
            ),
            primary_reviewer_identity_sha256s=tuple(  # type: ignore[arg-type]
                item.reviewer.identity_sha256 for item in request_models
            ),
            adjudicator_identity_sha256=protocol.adjudicator.identity_sha256,
            comparison_count=len(study.comparisons),
        )
        _write_json(
            workspace / "PACK.json",
            pack.model_dump(mode="json", exclude={"pack_sha256"}),
        )
        if _sha256(study_file) != study_file_sha:
            raise ValueError("public study changed while compiling AI preference requests")
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        os.replace(workspace, target)
    return pack


def lock_ai_preference_primary_reviews(
    *,
    evidence_root: str | Path,
    request_pack_path_or_dir: str | Path,
    raw_response_paths: tuple[str | Path, str | Path],
    execution_receipt_paths: tuple[str | Path, str | Path],
    output_path: str | Path,
    report_path: str | Path,
    adjudicator_output_dir: str | Path,
    locked_at: datetime | None = None,
) -> tuple[LockedAIPreferenceReviewSet, AIPreferenceLockReport]:
    """Normalize two raw AI responses, lock them, and route only disputes."""

    root = Path(evidence_root).resolve(strict=True)
    pack_file = _resolve_pack(root, request_pack_path_or_dir)
    pack = load_ai_preference_request_pack(pack_file)
    study_file = _bound_public_file(root, pack.study)
    suite_file = _bound_public_file(root, pack.benchmark_suite)
    protocol_file = _bound_public_file(root, pack.protocol)
    study = load_human_outcome_study(study_file)
    suite = load_benchmark_suite(suite_file)
    protocol = load_ai_blind_preference_protocol(protocol_file)
    _verify_study_suite(study, suite, suite_file)
    _verify_pack(pack, study, suite, protocol, root)
    raw_files = tuple(_regular_public_file(root, item) for item in raw_response_paths)
    receipt_files = tuple(_regular_public_file(root, item) for item in execution_receipt_paths)
    output = _new_public_file(root, output_path)
    report_target = _new_public_file(root, report_path)
    if output == report_target:
        raise ValueError("AI preference lock and report outputs must differ")
    lock_time = locked_at or datetime.now(UTC)

    request_by_reviewer = _load_primary_requests(pack, root)
    raw_by_reviewer: dict[str, tuple[AIRawPreferenceResponse, Path]] = {}
    for path in raw_files:
        response = AIRawPreferenceResponse.model_validate_json(path.read_text(encoding="utf-8"))
        if response.reviewer_id in raw_by_reviewer:
            raise ValueError("duplicate AI primary raw response")
        raw_by_reviewer[response.reviewer_id] = (response, path)
    receipt_by_reviewer: dict[str, tuple[AIReviewExecutionReceipt, Path]] = {}
    for path in receipt_files:
        receipt = AIReviewExecutionReceipt.model_validate_json(path.read_text(encoding="utf-8"))
        if receipt.reviewer_id in receipt_by_reviewer:
            raise ValueError("duplicate AI primary execution receipt")
        receipt_by_reviewer[receipt.reviewer_id] = (receipt, path)
    if set(raw_by_reviewer) != set(request_by_reviewer):
        raise ValueError("AI raw responses do not cover the two primary reviewers")
    if set(receipt_by_reviewer) != set(request_by_reviewer):
        raise ValueError("AI execution receipts do not cover the two primary reviewers")

    rows: list[AINormalizedPreferenceRow] = []
    for reviewer_id, request in request_by_reviewer.items():
        response, raw_file = raw_by_reviewer[reviewer_id]
        receipt, receipt_file = receipt_by_reviewer[reviewer_id]
        _verify_response_and_receipt(
            root=root,
            request=request,
            response=response,
            raw_file=raw_file,
            receipt=receipt,
            receipt_file=receipt_file,
        )
        response_by_id = {item.comparison_id: item for item in response.responses}
        for item in request.items:
            raw_item = response_by_id[item.comparison_id]
            preference = (
                None
                if raw_item.response == "cannot-assess"
                else AIBlindPreference(raw_item.response)
            )
            selected_output = (
                item.output_x.output_sha256
                if preference is AIBlindPreference.X
                else (item.output_y.output_sha256 if preference is AIBlindPreference.Y else None)
            )
            rows.append(
                AINormalizedPreferenceRow.create(
                    row_id=(
                        f"ai-row-{_canonical_sha256([pack.pack_sha256, item.comparison_id])[:24]}"
                    ),
                    comparison_id=item.comparison_id,
                    hypothesis=item.hypothesis,
                    case_id=item.case_id,
                    source_group=item.source_group,
                    reviewer_id=reviewer_id,
                    reviewer_identity_sha256=request.reviewer.identity_sha256,
                    request_sha256=request.request_sha256,
                    raw_response_file_sha256=_sha256(raw_file),
                    execution_receipt_file_sha256=_sha256(receipt_file),
                    disposition=(
                        AIPreferenceDisposition.CANNOT_ASSESS
                        if preference is None
                        else AIPreferenceDisposition.COMPLETED
                    ),
                    blinded_preference=preference,
                    selected_output_sha256=selected_output,
                    rationale=raw_item.rationale,
                    missingness_reason_code=raw_item.missingness_reason_code,
                )
            )
    disputes = _find_disputes(rows)
    lock = LockedAIPreferenceReviewSet(
        lock_id=(
            "ai-preference-lock-"
            f"{_canonical_sha256([pack.pack_sha256, lock_time.isoformat()])[:20]}"
        ),
        study_id=study.study_id,
        study_sha256=study.study_sha256,
        protocol_sha256=protocol.protocol_sha256,
        request_pack_sha256=pack.pack_sha256,
        normalized_rows=tuple(sorted(rows, key=lambda item: item.comparison_id)),
        raw_responses=tuple(_binding(root, item) for item in raw_files),  # type: ignore[arg-type]
        execution_receipts=tuple(  # type: ignore[arg-type]
            _binding(root, item) for item in receipt_files
        ),
        disputes=disputes,
        locked_at=lock_time,
    )
    _write_new_json(
        output,
        lock.model_dump(mode="json", exclude={"review_set_sha256"}),
    )

    adjudicator_binding: AIPreferenceFileBinding | None = None
    adjudicator_sha: str | None = None
    if disputes:
        adjudicator_target = _new_public_target(root, adjudicator_output_dir)
        adjudicator = _build_adjudicator_request(
            root=root,
            study=study,
            suite=suite,
            protocol=protocol,
            lock=lock,
        )
        adjudicator_target.mkdir(parents=True, exist_ok=False)
        adjudicator_path = adjudicator_target / "adjudicator.json"
        _write_new_json(
            adjudicator_path,
            adjudicator.model_dump(mode="json", exclude={"request_sha256"}),
        )
        adjudicator_binding = _binding(root, adjudicator_path)
        adjudicator_sha = adjudicator.request_sha256
    report = AIPreferenceLockReport(
        study_id=study.study_id,
        locked_review_set=_binding(root, output),
        review_set_sha256=lock.review_set_sha256,
        normalized_row_count=len(rows),
        normalized_row_sha256s=tuple(item.row_sha256 for item in lock.normalized_rows),
        raw_responses=lock.raw_responses,
        execution_receipts=lock.execution_receipts,
        dispute_count=len(disputes),
        adjudicator_pack=adjudicator_binding,
        adjudicator_request_sha256=adjudicator_sha,
    )
    _write_new_json(report_target, report.model_dump(mode="json"))
    return lock, report


def _request_item(
    root: Path,
    comparison,  # type: ignore[no-untyped-def]
    case: BenchmarkCase,
    ordinal: int,
) -> AIPreferenceRequestItem:
    return AIPreferenceRequestItem(
        ordinal=ordinal,
        comparison_id=comparison.comparison_id,
        hypothesis=comparison.hypothesis,
        case_id=comparison.case_id,
        source_group=comparison.source_group,
        case_context=case.decision_context,
        task=case.task.value,
        stage=case.stage,
        output_x=_visible_decision(root, comparison.x_output.path, comparison.x_output.sha256),
        output_y=_visible_decision(root, comparison.y_output.path, comparison.y_output.sha256),
    )


def _visible_decision(root: Path, path: str, expected_sha256: str) -> AIPreferenceVisibleDecision:
    file = _regular_public_file(root, path)
    if _sha256(file) != expected_sha256:
        raise ValueError("reviewer-visible decision differs from its public study binding")
    artifact = BlindedDecisionArtifact.model_validate_json(file.read_text(encoding="utf-8"))
    return AIPreferenceVisibleDecision(
        output_id=artifact.output_id,
        selected_action_id=artifact.selected_action_id,
        selected_action_description=artifact.selected_action_description,
        rationale=artifact.rationale,
        confidence=artifact.confidence,
        output_sha256=expected_sha256,
    )


def _load_primary_requests(
    pack: AIPreferenceRequestPack, root: Path
) -> dict[str, AIPreferencePrimaryRequest]:
    loaded: dict[str, AIPreferencePrimaryRequest] = {}
    for binding, semantic_sha in zip(
        pack.primary_requests, pack.primary_request_sha256s, strict=True
    ):
        path = _bound_public_file(root, binding)
        request = AIPreferencePrimaryRequest.model_validate_json(path.read_text(encoding="utf-8"))
        if request.request_sha256 != semantic_sha:
            raise ValueError("AI primary request semantic hash mismatch")
        if request.reviewer.reviewer_id in loaded:
            raise ValueError("AI request pack duplicates a primary reviewer")
        loaded[request.reviewer.reviewer_id] = request
    return loaded


def _verify_pack(
    pack: AIPreferenceRequestPack,
    study: HumanOutcomeStudyManifest,
    suite: BenchmarkSuite,
    protocol: AIBlindPreferenceProtocol,
    root: Path,
) -> None:
    if pack.study_id != study.study_id or pack.study_sha256 != study.study_sha256:
        raise ValueError("AI request pack binds another public study")
    if pack.protocol_sha256 != protocol.protocol_sha256:
        raise ValueError("AI request pack binds another AI review protocol")
    if (
        pack.benchmark_suite != protocol.benchmark_suite
        or pack.benchmark_suite_semantic_sha256 != suite.sha256
    ):
        raise ValueError("AI request pack binds another benchmark context suite")
    requests = _load_primary_requests(pack, root)
    if len(requests) != 2:
        raise ValueError("AI request pack must contain exactly two primary requests")
    comparison_ids = {item.comparison_id for request in requests.values() for item in request.items}
    if comparison_ids != {item.comparison_id for item in study.comparisons}:
        raise ValueError("AI request pack does not cover the public study assignments")
    if sum(len(item.items) for item in requests.values()) != pack.comparison_count:
        raise ValueError("AI request pack comparison count mismatch")


def _verify_response_and_receipt(
    *,
    root: Path,
    request: AIPreferencePrimaryRequest,
    response: AIRawPreferenceResponse,
    raw_file: Path,
    receipt: AIReviewExecutionReceipt,
    receipt_file: Path,
) -> None:
    identity = request.reviewer
    if (
        response.reviewer_id != identity.reviewer_id
        or response.reviewer_identity_sha256 != identity.identity_sha256
        or response.request_sha256 != request.request_sha256
    ):
        raise ValueError("AI raw response does not bind its assigned request and identity")
    if {item.comparison_id for item in response.responses} != {
        item.comparison_id for item in request.items
    }:
        raise ValueError("AI raw response does not cover its exact assigned comparisons")
    if any(
        len(item.rationale) > request.maximum_rationale_characters for item in response.responses
    ):
        raise ValueError("AI raw response exceeds the protocol rationale bound")
    if (
        receipt.reviewer_id != identity.reviewer_id
        or receipt.reviewer_identity_sha256 != identity.identity_sha256
        or (receipt.provider, receipt.model, receipt.model_revision)
        != (identity.provider, identity.model, identity.model_revision)
        or receipt.request_sha256 != request.request_sha256
    ):
        raise ValueError("AI execution receipt does not bind the assigned model request")
    request_path = _bound_public_file(root, receipt.request)
    backend_config_path = _bound_public_file(root, receipt.backend_config)
    http_request_path = _bound_public_file(root, receipt.http_request)
    raw_http_path = _bound_public_file(root, receipt.raw_http_body)
    raw_path = _bound_public_file(root, receipt.raw_response)
    if raw_path != raw_file or _sha256(raw_path) != _sha256(raw_file):
        raise ValueError("AI execution receipt does not bind the supplied raw response bytes")
    parsed_request = AIPreferencePrimaryRequest.model_validate_json(
        request_path.read_text(encoding="utf-8")
    )
    if parsed_request != request:
        raise ValueError("AI execution receipt request differs from the request pack")
    if receipt.http_status < 200 or receipt.http_status >= 300:
        raise ValueError("AI primary execution receipt did not observe a successful response")
    evidence_files = {
        receipt_file,
        backend_config_path,
        http_request_path,
        raw_http_path,
        raw_file,
        request_path,
    }
    if len(evidence_files) != 6:
        raise ValueError("AI execution receipt evidence files must be distinct")


def _find_disputes(rows: list[AINormalizedPreferenceRow]) -> tuple[AIPreferenceDispute, ...]:
    grouped: dict[tuple[TasteMechanismHypothesis, str], list[AINormalizedPreferenceRow]] = (
        defaultdict(list)
    )
    for row in rows:
        grouped[(row.hypothesis, row.case_id)].append(row)
    disputes: list[AIPreferenceDispute] = []
    for (hypothesis, case_id), pair in sorted(grouped.items(), key=lambda item: str(item[0])):
        if len(pair) != 2 or len({item.reviewer_id for item in pair}) != 2:
            raise ValueError("every H1/H2 block requires two distinct primary AI rows")
        completed = all(item.disposition is AIPreferenceDisposition.COMPLETED for item in pair)
        preferences = [item.blinded_preference for item in pair]
        agreement = completed and (
            (preferences[0] is AIBlindPreference.TIE and preferences[1] is AIBlindPreference.TIE)
            or (
                pair[0].selected_output_sha256 is not None
                and pair[0].selected_output_sha256 == pair[1].selected_output_sha256
            )
        )
        if agreement:
            continue
        source_groups = {item.source_group for item in pair}
        if len(source_groups) != 1:
            raise ValueError("paired AI reviews do not preserve one source group")
        ordered_pair = sorted(pair, key=lambda item: item.row_id)
        dispute_identity = _canonical_sha256(
            [hypothesis.value, case_id, *(item.row_sha256 for item in ordered_pair)]
        )
        disputes.append(
            AIPreferenceDispute(
                dispute_id=f"ai-dispute-{dispute_identity[:24]}",
                hypothesis=hypothesis,
                case_id=case_id,
                source_group=pair[0].source_group,
                primary_row_sha256s=tuple(  # type: ignore[arg-type]
                    item.row_sha256 for item in ordered_pair
                ),
                reason=("preference-disagreement" if completed else "assessment-disagreement"),
            )
        )
    return tuple(disputes)


def _build_adjudicator_request(
    *,
    root: Path,
    study: HumanOutcomeStudyManifest,
    suite: BenchmarkSuite,
    protocol: AIBlindPreferenceProtocol,
    lock: LockedAIPreferenceReviewSet,
) -> AIAdjudicationRequest:
    comparisons_by_block = {(item.hypothesis, item.case_id): item for item in study.comparisons}
    cases = {item.case_id: item for item in suite.cases}
    items: list[AIAdjudicationRequestItem] = []
    for ordinal, dispute in enumerate(lock.disputes, 1):
        comparison = comparisons_by_block[(dispute.hypothesis, dispute.case_id)]
        case = cases[dispute.case_id]
        visible = sorted(
            (
                _visible_decision(root, comparison.x_output.path, comparison.x_output.sha256),
                _visible_decision(root, comparison.y_output.path, comparison.y_output.sha256),
            ),
            key=lambda item: item.output_sha256,
        )
        items.append(
            AIAdjudicationRequestItem(
                ordinal=ordinal,
                dispute_id=dispute.dispute_id,
                hypothesis=dispute.hypothesis,
                case_id=dispute.case_id,
                source_group=dispute.source_group,
                case_context=case.decision_context,
                task=case.task.value,
                stage=case.stage,
                output_x=visible[0],
                output_y=visible[1],
            )
        )
    return AIAdjudicationRequest(
        request_id=f"adjudicate-{lock.review_set_sha256[:24]}",
        study_id=study.study_id,
        study_sha256=study.study_sha256,
        protocol_sha256=protocol.protocol_sha256,
        locked_primary_review_set_sha256=lock.review_set_sha256,
        adjudicator=protocol.adjudicator,
        primary_question=protocol.primary_question,
        decision_standards=protocol.decision_standards,
        tie_rule=protocol.tie_rule,
        cannot_assess_rule=protocol.cannot_assess_rule,
        items=tuple(items),
    )


def _verify_study_suite(
    study: HumanOutcomeStudyManifest, suite: BenchmarkSuite, suite_file: Path
) -> None:
    commitment = study.treatment_commitment
    if commitment is None:
        raise ValueError("AI preference review requires a treatment-bound public study")
    if _sha256(suite_file) != commitment.benchmark_suite_file_sha256:
        raise ValueError("AI preference benchmark bytes differ from the study commitment")
    if suite.sha256 != commitment.benchmark_suite_semantic_sha256:
        raise ValueError("AI preference benchmark semantics differ from the study commitment")
    case_ids = {item.case_id for item in suite.cases}
    if {item.case_id for item in study.comparisons} != case_ids:
        raise ValueError("AI preference study and benchmark case populations differ")
    source_groups = {item.case_id: item.source_group_id for item in suite.cases}
    if any(source_groups[item.case_id] != item.source_group for item in study.comparisons):
        raise ValueError("AI preference study and benchmark source groups differ")


def _resolve_public_study(root: Path, source: str | Path) -> Path:
    path = Path(source)
    if not path.is_absolute():
        path = root / path
    if path.is_dir():
        public_candidate = path / "public" / "study.json"
        path = public_candidate if public_candidate.is_file() else path / "study.json"
    return _regular_public_file(root, path)


def _resolve_pack(root: Path, source: str | Path) -> Path:
    path = Path(source)
    if not path.is_absolute():
        path = root / path
    if path.is_dir():
        path = path / "PACK.json"
    return _regular_public_file(root, path)


def _regular_public_file(
    root: Path, path: str | Path, maximum_bytes: int = _MAX_INPUT_BYTES
) -> Path:
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    if source.is_symlink():
        raise ValueError("AI preference inputs cannot be symlinks")
    resolved = source.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("AI preference inputs must stay inside the evidence root") from exc
    if any(part.lower() in _PRIVATE_NAMES for part in relative.parts):
        raise ValueError("AI preference panel cannot read private study material before lock")
    if not resolved.is_file() or resolved.stat().st_size > maximum_bytes:
        raise ValueError("AI preference input is not a bounded regular file")
    return resolved


def _bound_public_file(root: Path, binding: AIPreferenceFileBinding) -> Path:
    path = _regular_public_file(root, binding.path)
    if _sha256(path) != binding.sha256:
        raise ValueError("AI preference file differs from its content binding")
    return path


def _new_public_target(root: Path, output: str | Path) -> Path:
    target = Path(output)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("AI preference output must stay inside the evidence root") from exc
    if any(part.lower() in _PRIVATE_NAMES for part in relative.parts):
        raise ValueError("AI preference output cannot enter private study storage")
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    return target


def _new_public_file(root: Path, output: str | Path) -> Path:
    return _new_public_target(root, output)


def _binding(root: Path, path: Path) -> AIPreferenceFileBinding:
    return AIPreferenceFileBinding(path=path.relative_to(root).as_posix(), sha256=_sha256(path))


def _workspace_binding(
    root: Path, target: Path, workspace: Path, relative: Path
) -> AIPreferenceFileBinding:
    return AIPreferenceFileBinding(
        path=(target / relative).relative_to(root).as_posix(),
        sha256=_sha256(workspace / relative),
    )


def _write_new_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_unique(values, label: str) -> None:  # type: ignore[no-untyped-def]
    observed = list(values)
    if len(observed) != len(set(observed)):
        raise ValueError(f"{label} must be unique")


__all__ = [
    "AIAdjudicationRequest",
    "AIBlindPreference",
    "AIBlindPreferenceProtocol",
    "AINormalizedPreferenceRow",
    "AIPreferenceDisposition",
    "AIPreferenceFileBinding",
    "AIPreferenceLockReport",
    "AIPreferenceModelIdentity",
    "AIPreferencePrimaryRequest",
    "AIPreferenceRequestPack",
    "AIRawPreferenceResponse",
    "AIReviewExecutionReceipt",
    "AIReviewUsage",
    "LockedAIPreferenceReviewSet",
    "compile_ai_preference_request_pack",
    "load_ai_blind_preference_protocol",
    "load_ai_preference_request_pack",
    "lock_ai_preference_primary_reviews",
]

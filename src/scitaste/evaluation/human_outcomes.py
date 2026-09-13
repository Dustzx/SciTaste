"""Blinded, dual-human outcome contracts for the H1/H2 Taste mechanism study."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_serializer, model_validator

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_MANIFEST_BYTES = 16 * 1_048_576


class TasteMechanismHypothesis(StrEnum):
    H1_TASTE_ABSTRACTION = "H1_taste_abstraction"
    H2_TASTE_SPECIFICITY = "H2_taste_specificity"


class TasteStudyCondition(StrEnum):
    MATCHED_ABSTRACTED_TASTE = "matched-abstracted-taste"
    SAME_SOURCE_RAW_RAG = "same-source-raw-rag"
    SOURCE_DISJOINT_MISMATCHED_TASTE = "source-disjoint-mismatched-taste"


class HumanPairwisePreference(StrEnum):
    X = "X"
    TIE = "tie"
    Y = "Y"


class HumanReviewDisposition(StrEnum):
    COMPLETED = "completed"
    MISSING = "missing"
    CANNOT_ASSESS = "cannot-assess"


class HumanStudyFileBinding(BaseModel):
    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_relative(self) -> HumanStudyFileBinding:
        _validate_relative_path(self.path)
        return self


class HumanStudyTreatmentCommitment(BaseModel):
    """Public hashes for private treatment/generation evidence opened after review lock."""

    model_config = _CONFIG

    benchmark_suite_file_sha256: str = Field(pattern=_SHA256)
    benchmark_suite_semantic_sha256: str = Field(pattern=_SHA256)
    reference_treatment_manifest_file_sha256: str = Field(pattern=_SHA256)
    reference_treatment_manifest_semantic_sha256: str = Field(pattern=_SHA256)
    generation_ledger_sha256: str = Field(pattern=_SHA256)


class TreatmentGenerationRecord(BaseModel):
    """Private condition-bound generation evidence for one held-out case."""

    model_config = _CONFIG

    record_id: str = Field(pattern=_ID)
    case_id: str = Field(pattern=_ID)
    source_group: str = Field(pattern=_ID)
    condition: TasteStudyCondition
    seed: int = Field(ge=0, le=2**63 - 1)
    candidate_order: Literal["declared", "reversed"]
    benchmark_request_fingerprint: str = Field(pattern=_SHA256)
    treatment_construction_receipt_sha256: str = Field(pattern=_SHA256)
    provider: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=300)
    execution_trace: HumanStudyFileBinding
    output: HumanStudyFileBinding
    generated_at: datetime
    record_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def record_is_closed_and_self_hashed(self) -> TreatmentGenerationRecord:
        if self.generated_at.utcoffset() is None:
            raise ValueError("treatment generation timestamp must include a timezone")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("treatment generation record hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TreatmentGenerationRecord:
        payload = dict(values)
        payload.pop("record_sha256", None)
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


class TreatmentGenerationLedger(BaseModel):
    """Private, precommitted bridge from v3 treatments to reviewer-visible outputs."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    ledger_id: str = Field(pattern=_ID)
    study_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    benchmark_suite: HumanStudyFileBinding
    benchmark_suite_semantic_sha256: str = Field(pattern=_SHA256)
    reference_treatment_manifest: HumanStudyFileBinding
    reference_treatment_manifest_semantic_sha256: str = Field(pattern=_SHA256)
    entries: tuple[TreatmentGenerationRecord, ...] = Field(min_length=3, max_length=100_000)
    created_at: datetime
    conditions_hidden_until_review_lock: Literal[True] = True
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False
    ledger_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def ledger_is_complete_and_self_hashed(self) -> TreatmentGenerationLedger:
        if self.created_at.utcoffset() is None:
            raise ValueError("treatment generation ledger timestamp must include a timezone")
        _require_unique((item.record_id for item in self.entries), "generation record IDs")
        identities = [(item.case_id, item.condition) for item in self.entries]
        if len(identities) != len(set(identities)):
            raise ValueError("treatment generation case/condition identities must be unique")
        by_case: dict[str, list[TreatmentGenerationRecord]] = defaultdict(list)
        for item in self.entries:
            by_case[item.case_id].append(item)
        if any(
            {item.condition for item in items} != set(TasteStudyCondition)
            for items in by_case.values()
        ):
            raise ValueError("every treatment generation case requires the complete triplet")
        if any(len({item.source_group for item in items}) != 1 for items in by_case.values()):
            raise ValueError("a treatment generation case must retain one source group")
        if any(
            len({(item.seed, item.candidate_order, item.provider, item.model) for item in items})
            != 1
            for items in by_case.values()
        ):
            raise ValueError(
                "treatment generation triplets must share seed, order, provider, and model"
            )
        if len({(item.provider, item.model) for item in self.entries}) != 1:
            raise ValueError("one treatment generation ledger cannot mix model identities")
        if any(item.generated_at > self.created_at for item in self.entries):
            raise ValueError("treatment generation ledger cannot precede a generation record")
        outputs = [(item.output.path, item.output.sha256) for item in self.entries]
        traces = [(item.execution_trace.path, item.execution_trace.sha256) for item in self.entries]
        if len(outputs) != len(set(outputs)):
            raise ValueError("treatment generation outputs must be unique per case and condition")
        if len(traces) != len(set(traces)):
            raise ValueError("treatment generation traces must be unique per case and condition")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"ledger_sha256"}))
        if self.ledger_sha256 != expected:
            raise ValueError("treatment generation ledger hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> TreatmentGenerationLedger:
        payload = {"schema_version": "1.0", **values}
        payload.pop("ledger_sha256", None)
        unsigned = cls.model_construct(ledger_sha256="0" * 64, **payload)
        return cls(
            **payload,
            ledger_sha256=_canonical_sha256(
                unsigned.model_dump(mode="json", exclude={"ledger_sha256"})
            ),
        )


class BlindedOutputBinding(HumanStudyFileBinding):
    """Reviewer-visible output identity without its experimental condition."""

    output_id: str = Field(pattern=_ID)
    presentation_profile_sha256: str = Field(pattern=_SHA256)
    context_budget_tokens: int = Field(gt=0, le=10_000_000)
    maximum_output_tokens: int = Field(gt=0, le=1_000_000)


class BlindedHumanComparison(BaseModel):
    """One reviewer-specific, randomized X/Y presentation."""

    model_config = _CONFIG

    comparison_id: str = Field(pattern=_ID)
    hypothesis: TasteMechanismHypothesis
    case_id: str = Field(pattern=_ID)
    source_group: str = Field(pattern=_ID)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    x_output: BlindedOutputBinding
    y_output: BlindedOutputBinding
    conflict_cleared: Literal[True] = True
    calibration_passed: Literal[True] = True
    condition_identity_hidden: Literal[True] = True

    @model_validator(mode="after")
    def presentation_is_matched(self) -> BlindedHumanComparison:
        if self.x_output.sha256 == self.y_output.sha256:
            raise ValueError("blinded comparison outputs must differ")
        if self.x_output.presentation_profile_sha256 != self.y_output.presentation_profile_sha256:
            raise ValueError("blinded comparison presentation profiles must match")
        if self.x_output.context_budget_tokens != self.y_output.context_budget_tokens:
            raise ValueError("blinded comparison context budgets must match")
        if self.x_output.maximum_output_tokens != self.y_output.maximum_output_tokens:
            raise ValueError("blinded comparison output budgets must match")
        return self


class HumanOutcomeStudyManifest(BaseModel):
    """Public reviewer package; it contains no condition mapping."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    study_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    protocol: HumanStudyFileBinding
    rubric: HumanStudyFileBinding
    interface: HumanStudyFileBinding
    study_scope: Literal["pilot", "formal"] | None = None
    preference_analysis_contract: HumanStudyFileBinding | None = None
    power_analysis: HumanStudyFileBinding | None = None
    treatment_commitment: HumanStudyTreatmentCommitment | None = None
    blind_key_sha256: str = Field(pattern=_SHA256)
    comparisons: tuple[BlindedHumanComparison, ...] = Field(min_length=4, max_length=100_000)
    reviewers_per_case_contrast: Literal[2] = 2
    candidate_order_randomized_per_reviewer: Literal[True] = True
    outcome_adjudication_allowed: Literal[False] = False
    model_judge_is_primary: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def assignments_form_complete_dual_review_blocks(self) -> HumanOutcomeStudyManifest:
        analysis_extensions = (
            self.study_scope,
            self.preference_analysis_contract,
        )
        if self.schema_version == "1.0" and any(
            value is not None
            for value in (*analysis_extensions, self.power_analysis, self.treatment_commitment)
        ):
            raise ValueError("human outcome study v1.1 is required for analysis bindings")
        if self.schema_version == "1.1":
            if any(value is None for value in analysis_extensions):
                raise ValueError("human outcome study v1.1 requires scope and analysis contract")
            if self.study_scope == "formal" and self.power_analysis is None:
                raise ValueError("formal human outcome study requires a bound power analysis")
            if self.treatment_commitment is not None:
                raise ValueError("human outcome study v1.2 is required for treatment binding")
        if self.schema_version == "1.2":
            if any(value is None for value in analysis_extensions):
                raise ValueError("human outcome study v1.2 requires scope and analysis contract")
            if self.study_scope == "formal" and self.power_analysis is None:
                raise ValueError("formal human outcome study requires a bound power analysis")
            if self.treatment_commitment is None:
                raise ValueError("human outcome study v1.2 requires a treatment commitment")
        _require_unique((item.comparison_id for item in self.comparisons), "comparison IDs")
        grouped: dict[tuple[TasteMechanismHypothesis, str], list[BlindedHumanComparison]] = (
            defaultdict(list)
        )
        hypotheses_by_case: dict[str, set[TasteMechanismHypothesis]] = defaultdict(set)
        source_group_by_case: dict[str, set[str]] = defaultdict(set)
        for item in self.comparisons:
            grouped[(item.hypothesis, item.case_id)].append(item)
            hypotheses_by_case[item.case_id].add(item.hypothesis)
            source_group_by_case[item.case_id].add(item.source_group)
        expected_hypotheses = set(TasteMechanismHypothesis)
        if any(values != expected_hypotheses for values in hypotheses_by_case.values()):
            raise ValueError("every human outcome case must include both H1 and H2")
        if any(len(values) != 1 for values in source_group_by_case.values()):
            raise ValueError("a human outcome case must keep one source-group identity")
        for key, assignments in grouped.items():
            if len(assignments) != self.reviewers_per_case_contrast:
                raise ValueError(f"human outcome block {key} must have exactly two reviewers")
            reviewers = {item.reviewer_identity_sha256 for item in assignments}
            if len(reviewers) != self.reviewers_per_case_contrast:
                raise ValueError(f"human outcome block {key} reuses a reviewer")
            output_pairs = [
                frozenset((item.x_output.sha256, item.y_output.sha256)) for item in assignments
            ]
            if len(set(output_pairs)) != 1:
                raise ValueError(f"human outcome block {key} does not show the same output pair")
        return self

    @model_serializer(mode="wrap")
    def omit_absent_analysis_extensions(self, handler):  # type: ignore[no-untyped-def]
        """Keep frozen v1.0 reviewer manifests byte-compatible."""

        payload = handler(self)
        if self.schema_version == "1.0":
            payload.pop("study_scope", None)
            payload.pop("preference_analysis_contract", None)
            payload.pop("power_analysis", None)
            payload.pop("treatment_commitment", None)
        elif self.schema_version == "1.1":
            payload.pop("treatment_commitment", None)
        return payload

    @computed_field
    @property
    def assignment_sha256(self) -> str:
        """Hash reviewer-visible assignments without the later key commitment."""

        return _canonical_sha256(
            self.model_dump(
                mode="json",
                exclude={"assignment_sha256", "blind_key_sha256", "study_sha256"},
            )
        )

    @computed_field
    @property
    def study_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"study_sha256"}))


class HumanBlindKeyEntry(BaseModel):
    model_config = _CONFIG

    comparison_id: str = Field(pattern=_ID)
    x_condition: TasteStudyCondition
    y_condition: TasteStudyCondition
    x_generation_trace_sha256: str = Field(pattern=_SHA256)
    y_generation_trace_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def conditions_differ(self) -> HumanBlindKeyEntry:
        if self.x_condition is self.y_condition:
            raise ValueError("blind-key comparison conditions must differ")
        return self


class HumanBlindKey(BaseModel):
    """Private precommitted condition map, kept outside the reviewer package."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str = Field(pattern=_ID)
    assignment_sha256: str = Field(pattern=_SHA256)
    created_at: datetime
    entries: tuple[HumanBlindKeyEntry, ...] = Field(min_length=4, max_length=100_000)

    @model_validator(mode="after")
    def entries_are_unique(self) -> HumanBlindKey:
        _require_unique((item.comparison_id for item in self.entries), "blind-key comparisons")
        if self.created_at.utcoffset() is None:
            raise ValueError("blind-key timestamp must include a timezone")
        return self

    @computed_field
    @property
    def blind_key_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"blind_key_sha256"}))


class LockedHumanOutcomeReview(BaseModel):
    """One immutable reviewer judgment that contains no condition identity."""

    model_config = _CONFIG

    review_id: str = Field(pattern=_ID)
    comparison_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    disposition: HumanReviewDisposition = HumanReviewDisposition.COMPLETED
    preference: HumanPairwisePreference | None
    rationale: str = Field(min_length=1, max_length=4_000)
    missingness_reason_code: str | None = Field(default=None, pattern=_ID)
    locked_at: datetime
    duration_seconds: int | None = Field(default=None, gt=0, le=7 * 24 * 60 * 60)
    conflict_cleared: Literal[True] = True
    independent_review: Literal[True] = True
    blinded_to_condition: Literal[True] = True
    blinded_to_other_reviews: Literal[True] = True
    replacement_of_review_id: Literal[None] = None

    @model_validator(mode="after")
    def lock_time_is_aware(self) -> LockedHumanOutcomeReview:
        if self.locked_at.utcoffset() is None:
            raise ValueError("human review lock timestamp must include a timezone")
        completed = self.disposition is HumanReviewDisposition.COMPLETED
        if completed != (self.preference is not None):
            raise ValueError("only a completed human review may contain a preference")
        if completed == (self.missingness_reason_code is not None):
            raise ValueError("non-completed human reviews require one missingness reason")
        return self


class LockedHumanReviewSet(BaseModel):
    """Complete primary reviews, frozen before the blind key is opened."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    reviews: tuple[LockedHumanOutcomeReview, ...] = Field(min_length=4, max_length=100_000)
    reviewer_sessions: tuple[HumanStudyFileBinding, ...] = Field(default=(), max_length=100)
    reviewer_submissions: tuple[HumanStudyFileBinding, ...] = Field(default=(), max_length=100)
    locked_at: datetime
    all_primary_reviews_locked: Literal[True] = True
    outcome_adjudication_performed: Literal[False] = False

    @model_validator(mode="after")
    def review_set_is_immutable(self) -> LockedHumanReviewSet:
        _require_unique((item.review_id for item in self.reviews), "review IDs")
        _require_unique((item.comparison_id for item in self.reviews), "review comparisons")
        if self.locked_at.utcoffset() is None:
            raise ValueError("review-set lock timestamp must include a timezone")
        if any(item.locked_at > self.locked_at for item in self.reviews):
            raise ValueError("review-set lock cannot precede a contained review")
        collection_bindings = (self.reviewer_sessions, self.reviewer_submissions)
        if self.schema_version == "1.0" and any(collection_bindings):
            raise ValueError("human review set v1.1 is required for collection bindings")
        if self.schema_version == "1.1":
            if any(len(items) != 2 for items in collection_bindings):
                raise ValueError("human review set v1.1 requires two sessions and submissions")
            for label, items in (
                ("reviewer sessions", self.reviewer_sessions),
                ("reviewer submissions", self.reviewer_submissions),
            ):
                identities = {(item.path, item.sha256) for item in items}
                if len(identities) != len(items):
                    raise ValueError(f"{label} must be unique")
        return self

    @model_serializer(mode="wrap")
    def omit_absent_collection_bindings(self, handler):  # type: ignore[no-untyped-def]
        """Keep frozen v1.0 review sets byte-compatible."""

        payload = handler(self)
        if self.schema_version == "1.0":
            payload.pop("reviewer_sessions", None)
            payload.pop("reviewer_submissions", None)
        return payload

    @computed_field
    @property
    def review_set_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"review_set_sha256"}))


class HumanBlindOpening(BaseModel):
    """A post-lock opening that binds the exact precommitted key and review set."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    review_set_sha256: str = Field(pattern=_SHA256)
    blind_key: HumanBlindKey
    generation_ledger: TreatmentGenerationLedger | None = None
    opened_at: datetime
    opened_after_all_primary_reviews_locked: Literal[True] = True

    @model_validator(mode="after")
    def opening_time_is_aware(self) -> HumanBlindOpening:
        if self.opened_at.utcoffset() is None:
            raise ValueError("blind-opening timestamp must include a timezone")
        if self.schema_version == "1.0" and self.generation_ledger is not None:
            raise ValueError("human blind opening v1.1 is required for a generation ledger")
        if self.schema_version == "1.1" and self.generation_ledger is None:
            raise ValueError("human blind opening v1.1 requires a generation ledger")
        return self


class HumanOutcomeFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class UnblindedHumanOutcome(BaseModel):
    model_config = _CONFIG

    review_id: str
    comparison_id: str
    hypothesis: TasteMechanismHypothesis
    case_id: str
    source_group: str
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    disposition: HumanReviewDisposition
    blinded_preference: HumanPairwisePreference | None
    preferred_condition: TasteStudyCondition | None
    tie: bool
    missingness_reason_code: str | None


class HumanOutcomeStudyReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    study_sha256: str = Field(pattern=_SHA256)
    comparison_count: int = Field(ge=0)
    case_count: int = Field(ge=0)
    locked_review_count: int = Field(ge=0)
    observed_preference_count: int = Field(ge=0)
    missing_preference_count: int = Field(ge=0)
    source_group_count: int = Field(ge=0)
    reviewer_visible_bindings_verified: bool
    review_collection_bindings_verified: bool
    complete_dual_review_verified: bool
    ready_to_open_blind_key: bool
    blind_key_commitment_verified: bool
    opening_order_verified: bool
    h1_contrast_verified: bool
    h2_contrast_verified: bool
    shared_triplet_identity_verified: bool
    treatment_generation_chain_verified: bool
    ready_for_primary_analysis: bool
    outcomes: tuple[UnblindedHumanOutcome, ...]
    findings: tuple[HumanOutcomeFinding, ...]
    disagreement_retained: Literal[True] = True
    outcome_adjudication_performed: Literal[False] = False
    automated_judge_used: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_experiment: Literal[False] = False
    no_external_action_performed: Literal[True] = True


def load_human_outcome_study(path: str | Path) -> HumanOutcomeStudyManifest:
    return HumanOutcomeStudyManifest.model_validate(_load_mapping(path, "human outcome study"))


def load_locked_human_reviews(path: str | Path) -> LockedHumanReviewSet:
    return LockedHumanReviewSet.model_validate(_load_mapping(path, "locked human reviews"))


def load_human_blind_opening(path: str | Path) -> HumanBlindOpening:
    return HumanBlindOpening.model_validate(_load_mapping(path, "human blind opening"))


def inspect_human_outcome_study(
    study: HumanOutcomeStudyManifest,
    *,
    evidence_root: str | Path,
    reviews: LockedHumanReviewSet | None = None,
    opening: HumanBlindOpening | None = None,
) -> HumanOutcomeStudyReport:
    """Verify review locking and optionally unblind without computing an effect."""

    root = Path(evidence_root).resolve(strict=True)
    findings: list[HumanOutcomeFinding] = []
    study_sha256 = study.study_sha256
    assignment_sha256 = study.assignment_sha256
    bindings = (
        study.protocol,
        study.rubric,
        study.interface,
        *(
            output
            for comparison in study.comparisons
            for output in (comparison.x_output, comparison.y_output)
        ),
    )
    visible_bindings = all(_binding_matches(item, root, findings) for item in bindings)

    comparisons = {item.comparison_id: item for item in study.comparisons}
    reviews_complete = reviews is not None
    collection_bindings_verified = reviews is None or reviews.schema_version == "1.0"
    if reviews is None:
        _add(findings, "reviews-not-locked", "the complete dual-human review set is absent")
    else:
        collection_required = study.schema_version == "1.2" or study.study_scope == "formal"
        if collection_required and reviews.schema_version != "1.1":
            _add(
                findings,
                "reviews-not-session-bound",
                "formal reviews were not compiled from bound reviewer sessions and submissions",
            )
            reviews_complete = False
            collection_bindings_verified = False
        elif reviews.schema_version == "1.1":
            collection_bindings_verified = all(
                _binding_matches(item, root, findings)
                for item in (*reviews.reviewer_sessions, *reviews.reviewer_submissions)
            )
            if not collection_bindings_verified:
                reviews_complete = False
        if reviews.study_id != study.study_id or reviews.study_sha256 != study_sha256:
            _add(findings, "reviews-study-mismatch", "locked reviews bind another study")
            reviews_complete = False
        review_ids = {item.comparison_id for item in reviews.reviews}
        if review_ids != set(comparisons):
            _add(findings, "reviews-incomplete", "locked reviews do not cover every assignment")
            reviews_complete = False
        for review in reviews.reviews:
            comparison = comparisons.get(review.comparison_id)
            if comparison is None:
                continue
            if review.study_sha256 != study_sha256:
                _add(findings, "review-study-mismatch", review.review_id)
                reviews_complete = False
            if review.reviewer_identity_sha256 != comparison.reviewer_identity_sha256:
                _add(findings, "reviewer-assignment-mismatch", review.review_id)
                reviews_complete = False

    ready_to_open = visible_bindings and reviews_complete
    generation_chain_required = study.schema_version == "1.2" or study.study_scope == "formal"
    generation_chain_verified = not generation_chain_required
    blind_verified = False
    opening_order = False
    h1_verified = False
    h2_verified = False
    outcomes: list[UnblindedHumanOutcome] = []
    if opening is not None:
        key = opening.blind_key
        blind_verified = key.blind_key_sha256 == study.blind_key_sha256
        if not blind_verified:
            _add(findings, "blind-key-commitment-mismatch", "opened key was not precommitted")
        if (
            opening.study_id != study.study_id
            or opening.study_sha256 != study_sha256
            or key.study_id != study.study_id
            or key.assignment_sha256 != assignment_sha256
        ):
            _add(findings, "blind-opening-study-mismatch", "opening binds another study")
            blind_verified = False
        if reviews is None or opening.review_set_sha256 != reviews.review_set_sha256:
            _add(findings, "blind-opening-review-mismatch", "opening binds another review set")
        elif opening.opened_at < reviews.locked_at or key.created_at > min(
            item.locked_at for item in reviews.reviews
        ):
            _add(findings, "blind-opening-order-invalid", "blind key timing violates review lock")
        else:
            opening_order = True

        key_by_comparison = {item.comparison_id: item for item in key.entries}
        if set(key_by_comparison) != set(comparisons):
            _add(findings, "blind-key-coverage-mismatch", "blind key does not cover assignments")
        h1_verified = _contrast_is_valid(
            comparisons,
            key_by_comparison,
            TasteMechanismHypothesis.H1_TASTE_ABSTRACTION,
            {
                TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
                TasteStudyCondition.SAME_SOURCE_RAW_RAG,
            },
            findings,
        )
        h2_verified = _contrast_is_valid(
            comparisons,
            key_by_comparison,
            TasteMechanismHypothesis.H2_TASTE_SPECIFICITY,
            {
                TasteStudyCondition.MATCHED_ABSTRACTED_TASTE,
                TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE,
            },
            findings,
        )
        triplet_verified = _triplet_is_valid(comparisons, key_by_comparison, findings)
        if generation_chain_required:
            generation_chain_verified = _generation_chain_is_valid(
                study,
                reviews,
                opening,
                comparisons,
                key_by_comparison,
                root,
                findings,
            )
        if reviews is not None:
            for review in reviews.reviews:
                comparison = comparisons.get(review.comparison_id)
                entry = key_by_comparison.get(review.comparison_id)
                if comparison is None or entry is None:
                    continue
                preferred = (
                    entry.x_condition
                    if review.preference is HumanPairwisePreference.X
                    else (
                        entry.y_condition
                        if review.preference is HumanPairwisePreference.Y
                        else None
                    )
                )
                outcomes.append(
                    UnblindedHumanOutcome(
                        review_id=review.review_id,
                        comparison_id=review.comparison_id,
                        hypothesis=comparison.hypothesis,
                        case_id=comparison.case_id,
                        source_group=comparison.source_group,
                        reviewer_identity_sha256=review.reviewer_identity_sha256,
                        disposition=review.disposition,
                        blinded_preference=review.preference,
                        preferred_condition=preferred,
                        tie=review.preference is HumanPairwisePreference.TIE,
                        missingness_reason_code=review.missingness_reason_code,
                    )
                )

    else:
        triplet_verified = False

    ready_for_analysis = (
        ready_to_open
        and opening is not None
        and blind_verified
        and opening_order
        and h1_verified
        and h2_verified
        and triplet_verified
        and generation_chain_verified
        and len(outcomes) == len(study.comparisons)
    )
    return HumanOutcomeStudyReport(
        study_id=study.study_id,
        study_sha256=study_sha256,
        comparison_count=len(study.comparisons),
        case_count=len({item.case_id for item in study.comparisons}),
        locked_review_count=len(reviews.reviews) if reviews is not None else 0,
        observed_preference_count=sum(item.preference is not None for item in reviews.reviews)
        if reviews is not None
        else 0,
        missing_preference_count=sum(item.preference is None for item in reviews.reviews)
        if reviews is not None
        else 0,
        source_group_count=len({item.source_group for item in study.comparisons}),
        reviewer_visible_bindings_verified=visible_bindings,
        review_collection_bindings_verified=collection_bindings_verified,
        complete_dual_review_verified=reviews_complete,
        ready_to_open_blind_key=ready_to_open,
        blind_key_commitment_verified=blind_verified,
        opening_order_verified=opening_order,
        h1_contrast_verified=h1_verified,
        h2_contrast_verified=h2_verified,
        shared_triplet_identity_verified=triplet_verified,
        treatment_generation_chain_verified=generation_chain_verified,
        ready_for_primary_analysis=ready_for_analysis,
        outcomes=tuple(outcomes),
        findings=tuple(findings),
    )


def save_human_outcome_study_report(
    report: HumanOutcomeStudyReport,
    path: str | Path,
) -> Path:
    target = Path(path)
    if target.is_symlink():
        raise ValueError("human outcome report cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(report.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _contrast_is_valid(
    comparisons: dict[str, BlindedHumanComparison],
    keys: dict[str, HumanBlindKeyEntry],
    hypothesis: TasteMechanismHypothesis,
    expected_conditions: set[TasteStudyCondition],
    findings: list[HumanOutcomeFinding],
) -> bool:
    valid = True
    for comparison_id, comparison in comparisons.items():
        if comparison.hypothesis is not hypothesis:
            continue
        entry = keys.get(comparison_id)
        if entry is None or {entry.x_condition, entry.y_condition} != expected_conditions:
            _add(findings, f"contrast-{hypothesis.value.lower()}-invalid", comparison_id)
            valid = False
    return valid


def _triplet_is_valid(
    comparisons: dict[str, BlindedHumanComparison],
    keys: dict[str, HumanBlindKeyEntry],
    findings: list[HumanOutcomeFinding],
) -> bool:
    """Require one shared matched output and three distinct arms per natural case."""

    identities: dict[str, dict[TasteStudyCondition, set[tuple[str, str]]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for comparison_id, comparison in comparisons.items():
        entry = keys.get(comparison_id)
        if entry is None:
            continue
        identities[comparison.case_id][entry.x_condition].add(
            (comparison.x_output.sha256, entry.x_generation_trace_sha256)
        )
        identities[comparison.case_id][entry.y_condition].add(
            (comparison.y_output.sha256, entry.y_generation_trace_sha256)
        )
    valid = True
    expected = set(TasteStudyCondition)
    for case_id, by_condition in identities.items():
        if set(by_condition) != expected or any(
            len(values) != 1 for values in by_condition.values()
        ):
            _add(findings, "condition-triplet-identity-invalid", case_id)
            valid = False
            continue
        output_hashes = {next(iter(values))[0] for values in by_condition.values()}
        if len(output_hashes) != len(expected):
            _add(findings, "condition-triplet-output-reused", case_id)
            valid = False
    return valid and set(identities) == {item.case_id for item in comparisons.values()}


def _generation_chain_is_valid(
    study: HumanOutcomeStudyManifest,
    reviews: LockedHumanReviewSet | None,
    opening: HumanBlindOpening,
    comparisons: dict[str, BlindedHumanComparison],
    keys: dict[str, HumanBlindKeyEntry],
    root: Path,
    findings: list[HumanOutcomeFinding],
) -> bool:
    """Bind every reviewed output to its exact v3 case, treatment, request, and trace."""

    from scitaste.benchmark.models import (
        BenchmarkCondition,
        BenchmarkEvidenceTier,
        CandidateOrder,
    )
    from scitaste.benchmark.runner import load_benchmark_suite
    from scitaste.benchmark.treatment_manifest import load_reference_treatment_manifest

    if study.schema_version != "1.2" or study.treatment_commitment is None:
        _add(
            findings,
            "treatment-generation-commitment-missing",
            "formal human review requires a v1.2 treatment commitment",
        )
        return False
    ledger = opening.generation_ledger
    if opening.schema_version != "1.1" or ledger is None:
        _add(
            findings,
            "treatment-generation-ledger-missing",
            "blind opening does not contain the precommitted generation ledger",
        )
        return False
    commitment = study.treatment_commitment
    if (
        ledger.study_id != study.study_id
        or ledger.project_id != study.project_id
        or ledger.ledger_sha256 != commitment.generation_ledger_sha256
        or ledger.benchmark_suite.sha256 != commitment.benchmark_suite_file_sha256
        or ledger.benchmark_suite_semantic_sha256 != commitment.benchmark_suite_semantic_sha256
        or ledger.reference_treatment_manifest.sha256
        != commitment.reference_treatment_manifest_file_sha256
        or ledger.reference_treatment_manifest_semantic_sha256
        != commitment.reference_treatment_manifest_semantic_sha256
    ):
        _add(
            findings,
            "treatment-generation-commitment-mismatch",
            "opened generation ledger differs from its public commitment",
        )
        return False
    if (
        reviews is None
        or ledger.created_at > opening.blind_key.created_at
        or ledger.created_at > min(item.locked_at for item in reviews.reviews)
    ):
        _add(
            findings,
            "treatment-generation-ledger-timing-invalid",
            "generation ledger was not frozen before review locking began",
        )
        return False
    for binding in (ledger.benchmark_suite, ledger.reference_treatment_manifest):
        if not _binding_matches(binding, root, findings):
            return False
    try:
        suite = load_benchmark_suite(root / ledger.benchmark_suite.path)
        treatment = load_reference_treatment_manifest(
            root / ledger.reference_treatment_manifest.path
        )
    except (OSError, ValueError):
        _add(
            findings,
            "treatment-generation-upstream-invalid",
            "benchmark suite or treatment manifest cannot be replayed",
        )
        return False
    if (
        suite.version != "3.0"
        or (
            study.study_scope == "formal"
            and suite.evidence_tier is not BenchmarkEvidenceTier.FORMAL
        )
        or suite.sha256 != ledger.benchmark_suite_semantic_sha256
        or suite.reference_treatment_manifest_sha256 != ledger.reference_treatment_manifest.sha256
        or treatment.manifest.manifest_sha256 != ledger.reference_treatment_manifest_semantic_sha256
        or treatment.manifest.project_id != study.project_id
    ):
        _add(
            findings,
            "treatment-generation-upstream-mismatch",
            "suite, treatment manifest, and generation ledger identities differ",
        )
        return False

    suite_cases = {item.case_id: item for item in suite.cases}
    treatment_cases = {item.case_id: item.mechanism_context for item in treatment.manifest.cases}
    study_case_ids = {item.case_id for item in comparisons.values()}
    ledger_case_ids = {item.case_id for item in ledger.entries}
    if (
        study_case_ids != ledger_case_ids
        or study_case_ids != set(suite_cases)
        or study_case_ids != set(treatment_cases)
        or any(
            case.mechanism_context is None or treatment_cases[case_id] != case.mechanism_context
            for case_id, case in suite_cases.items()
        )
    ):
        _add(
            findings,
            "treatment-generation-case-population-mismatch",
            "review, generation, suite, and treatment case populations differ",
        )
        return False

    benchmark_condition = {
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE: (BenchmarkCondition.MATCHED_ABSTRACTED_TASTE),
        TasteStudyCondition.SAME_SOURCE_RAW_RAG: BenchmarkCondition.RAW_SOURCE_RAG,
        TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE: (BenchmarkCondition.MISMATCHED_TASTE),
    }
    context_name = {
        TasteStudyCondition.MATCHED_ABSTRACTED_TASTE: "matched_abstracted_taste",
        TasteStudyCondition.SAME_SOURCE_RAW_RAG: "raw_source_rag",
        TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE: "mismatched_taste",
    }
    records = {(item.case_id, item.condition): item for item in ledger.entries}
    valid = True
    for record in ledger.entries:
        case = suite_cases[record.case_id]
        context = getattr(case.mechanism_context, context_name[record.condition])
        expected_request = case.to_request(
            benchmark_condition[record.condition],
            seed=record.seed,
            candidate_order=CandidateOrder(record.candidate_order),
        )
        if (
            record.source_group != case.source_group_id
            or record.treatment_construction_receipt_sha256 != context.construction_receipt_sha256
            or record.benchmark_request_fingerprint != expected_request.fingerprint
        ):
            _add(
                findings,
                "treatment-generation-request-mismatch",
                record.record_id,
            )
            valid = False
        for binding in (record.execution_trace, record.output):
            if not _binding_matches(binding, root, findings):
                valid = False

    for comparison_id, comparison in comparisons.items():
        key = keys.get(comparison_id)
        if key is None:
            valid = False
            continue
        for condition, output, trace_sha256 in (
            (key.x_condition, comparison.x_output, key.x_generation_trace_sha256),
            (key.y_condition, comparison.y_output, key.y_generation_trace_sha256),
        ):
            record = records.get((comparison.case_id, condition))
            if record is None or (
                record.source_group != comparison.source_group
                or record.output.path != output.path
                or record.output.sha256 != output.sha256
                or record.record_sha256 != trace_sha256
            ):
                _add(
                    findings,
                    "treatment-generation-reviewed-output-mismatch",
                    comparison_id,
                )
                valid = False
    return valid


def _binding_matches(
    binding: HumanStudyFileBinding,
    root: Path,
    findings: list[HumanOutcomeFinding],
) -> bool:
    current = root
    for part in PurePosixPath(binding.path).parts:
        current /= part
        if current.is_symlink():
            _add(findings, "binding-symlink", binding.path)
            return False
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        _add(findings, "binding-missing", binding.path)
        return False
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        _add(findings, "binding-invalid", binding.path)
        return False
    if hashlib.sha256(resolved.read_bytes()).hexdigest() != binding.sha256:
        _add(findings, "binding-hash-mismatch", binding.path)
        return False
    return True


def _load_mapping(path: str | Path, label: str) -> dict[str, object]:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    raw = source.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 YAML or JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a mapping")
    return payload


def _validate_relative_path(value: str) -> None:
    if "\\" in value or "//" in value:
        raise ValueError("human outcome bindings must use normalized POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("human outcome bindings must use normalized relative paths")


def _require_unique(values, label: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"human outcome {label} must be unique")


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _add(findings: list[HumanOutcomeFinding], code: str, message: str) -> None:
    findings.append(HumanOutcomeFinding(code=code, message=message))


__all__ = [
    "BlindedHumanComparison",
    "BlindedOutputBinding",
    "HumanBlindKey",
    "HumanBlindKeyEntry",
    "HumanBlindOpening",
    "HumanOutcomeFinding",
    "HumanOutcomeStudyManifest",
    "HumanOutcomeStudyReport",
    "HumanPairwisePreference",
    "HumanReviewDisposition",
    "HumanStudyFileBinding",
    "HumanStudyTreatmentCommitment",
    "LockedHumanOutcomeReview",
    "LockedHumanReviewSet",
    "TasteMechanismHypothesis",
    "TasteStudyCondition",
    "TreatmentGenerationLedger",
    "TreatmentGenerationRecord",
    "UnblindedHumanOutcome",
    "inspect_human_outcome_study",
    "load_human_blind_opening",
    "load_human_outcome_study",
    "load_locked_human_reviews",
    "save_human_outcome_study_report",
]

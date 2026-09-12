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
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

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

    schema_version: Literal["1.0"] = "1.0"
    study_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    protocol: HumanStudyFileBinding
    rubric: HumanStudyFileBinding
    interface: HumanStudyFileBinding
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

    schema_version: Literal["1.0"] = "1.0"
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    reviews: tuple[LockedHumanOutcomeReview, ...] = Field(min_length=4, max_length=100_000)
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
        return self

    @computed_field
    @property
    def review_set_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"review_set_sha256"}))


class HumanBlindOpening(BaseModel):
    """A post-lock opening that binds the exact precommitted key and review set."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    review_set_sha256: str = Field(pattern=_SHA256)
    blind_key: HumanBlindKey
    opened_at: datetime
    opened_after_all_primary_reviews_locked: Literal[True] = True

    @model_validator(mode="after")
    def opening_time_is_aware(self) -> HumanBlindOpening:
        if self.opened_at.utcoffset() is None:
            raise ValueError("blind-opening timestamp must include a timezone")
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
    complete_dual_review_verified: bool
    ready_to_open_blind_key: bool
    blind_key_commitment_verified: bool
    opening_order_verified: bool
    h1_contrast_verified: bool
    h2_contrast_verified: bool
    shared_triplet_identity_verified: bool
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
    if reviews is None:
        _add(findings, "reviews-not-locked", "the complete dual-human review set is absent")
    else:
        if reviews.study_id != study.study_id or reviews.study_sha256 != study.study_sha256:
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
            if review.study_sha256 != study.study_sha256:
                _add(findings, "review-study-mismatch", review.review_id)
                reviews_complete = False
            if review.reviewer_identity_sha256 != comparison.reviewer_identity_sha256:
                _add(findings, "reviewer-assignment-mismatch", review.review_id)
                reviews_complete = False

    ready_to_open = visible_bindings and reviews_complete
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
            or opening.study_sha256 != study.study_sha256
            or key.study_id != study.study_id
            or key.assignment_sha256 != study.assignment_sha256
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
        and len(outcomes) == len(study.comparisons)
    )
    return HumanOutcomeStudyReport(
        study_id=study.study_id,
        study_sha256=study.study_sha256,
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
        complete_dual_review_verified=reviews_complete,
        ready_to_open_blind_key=ready_to_open,
        blind_key_commitment_verified=blind_verified,
        opening_order_verified=opening_order,
        h1_contrast_verified=h1_verified,
        h2_contrast_verified=h2_verified,
        shared_triplet_identity_verified=triplet_verified,
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
    "LockedHumanOutcomeReview",
    "LockedHumanReviewSet",
    "TasteMechanismHypothesis",
    "TasteStudyCondition",
    "UnblindedHumanOutcome",
    "inspect_human_outcome_study",
    "load_human_blind_opening",
    "load_human_outcome_study",
    "load_locked_human_reviews",
    "save_human_outcome_study_report",
]

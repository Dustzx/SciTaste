"""Reviewer-facing H1/H2 sessions and immutable submission collection."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scitaste.benchmark.models import BenchmarkSuite
from scitaste.benchmark.runner import load_benchmark_suite
from scitaste.evaluation.human_outcomes import (
    HumanOutcomeStudyManifest,
    HumanPairwisePreference,
    HumanReviewDisposition,
    HumanStudyFileBinding,
    LockedHumanOutcomeReview,
    LockedHumanReviewSet,
    load_human_outcome_study,
)
from scitaste.evaluation.human_study_preparation import BlindedDecisionArtifact

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INPUT_BYTES = 64 * 1_048_576
_MAX_SESSION_BYTES = 256 * 1_048_576
_MISSINGNESS_CODES = {
    "insufficient-domain-expertise",
    "insufficient-visible-evidence",
    "malformed-presentation",
    "other-bounded-reason",
}


class ReviewerVisibleDecision(BaseModel):
    """One condition-free decision presentation."""

    model_config = _CONFIG

    selected_action_id: str = Field(min_length=1, max_length=300)
    selected_action_description: str = Field(min_length=1, max_length=10_000)
    rationale: str = Field(min_length=1, max_length=40_000)
    confidence: float = Field(ge=0, le=1)
    output_sha256: str = Field(pattern=_SHA256)


class ReviewerSessionComparison(BaseModel):
    """A single assigned comparison with only reviewer-permitted content."""

    model_config = _CONFIG

    ordinal: int = Field(gt=0, le=100_000)
    comparison_id: str = Field(pattern=_ID)
    case_context: str = Field(min_length=1, max_length=100_000)
    task: str = Field(min_length=1, max_length=300)
    stage: str = Field(min_length=1, max_length=300)
    output_x: ReviewerVisibleDecision
    output_y: ReviewerVisibleDecision


class HumanReviewerSession(BaseModel):
    """Self-contained, single-reviewer projection of a public blind study."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(pattern=_ID)
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    rubric_sha256: str = Field(pattern=_SHA256)
    interface_sha256: str = Field(pattern=_SHA256)
    primary_question: str = Field(min_length=1, max_length=10_000)
    decision_standards: tuple[str, ...] = Field(min_length=1, max_length=20)
    tie_rule: str = Field(min_length=1, max_length=10_000)
    cannot_assess_rule: str = Field(min_length=1, max_length=10_000)
    comparisons: tuple[ReviewerSessionComparison, ...] = Field(min_length=2, max_length=100_000)
    prepared_at: datetime
    condition_identity_hidden: Literal[True] = True
    other_reviewer_data_absent: Literal[True] = True
    authorizes_human_recruitment: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def session_is_complete(self) -> HumanReviewerSession:
        if self.prepared_at.utcoffset() is None:
            raise ValueError("reviewer session timestamp must include a timezone")
        ids = [item.comparison_id for item in self.comparisons]
        if len(ids) != len(set(ids)):
            raise ValueError("reviewer session comparison IDs must be unique")
        if [item.ordinal for item in self.comparisons] != list(range(1, len(self.comparisons) + 1)):
            raise ValueError("reviewer session ordinals must be contiguous")
        return self

    @computed_field
    @property
    def session_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"session_sha256"}))


class ReviewerSubmissionResponse(BaseModel):
    """One response exported by the browser session."""

    model_config = _CONFIG

    comparison_id: str = Field(pattern=_ID)
    response: Literal["X", "tie", "Y", "cannot-assess"]
    rationale: str = Field(min_length=1, max_length=4_000)
    missingness_reason_code: str | None = Field(default=None, pattern=_ID)
    duration_seconds: int = Field(gt=0, le=7 * 24 * 60 * 60)

    @model_validator(mode="after")
    def missingness_matches_response(self) -> ReviewerSubmissionResponse:
        cannot_assess = self.response == "cannot-assess"
        if cannot_assess != (self.missingness_reason_code is not None):
            raise ValueError("cannot-assess requires exactly one missingness reason")
        if self.missingness_reason_code is not None and (
            self.missingness_reason_code not in _MISSINGNESS_CODES
        ):
            raise ValueError("unknown reviewer missingness reason")
        return self


class HumanReviewerSubmission(BaseModel):
    """Complete browser export, still condition blind and not yet opened."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(pattern=_ID)
    session_sha256: str = Field(pattern=_SHA256)
    study_sha256: str = Field(pattern=_SHA256)
    reviewer_identity_sha256: str = Field(pattern=_SHA256)
    review_started_at: datetime
    submitted_at: datetime
    responses: tuple[ReviewerSubmissionResponse, ...] = Field(min_length=2, max_length=100_000)
    conflict_cleared: Literal[True] = True
    independent_review: Literal[True] = True
    blinded_to_condition: Literal[True] = True
    blinded_to_other_reviews: Literal[True] = True
    explicit_lock_confirmed: Literal[True] = True

    @model_validator(mode="after")
    def submission_is_complete(self) -> HumanReviewerSubmission:
        if self.review_started_at.utcoffset() is None or self.submitted_at.utcoffset() is None:
            raise ValueError("reviewer submission timestamps must include a timezone")
        if self.submitted_at < self.review_started_at:
            raise ValueError("reviewer submission cannot precede its start")
        ids = [item.comparison_id for item in self.responses]
        if len(ids) != len(set(ids)):
            raise ValueError("reviewer submission comparison IDs must be unique")
        return self


class HumanReviewCollectionReport(BaseModel):
    """Evidence binding the two sessions and submissions to the locked set."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str = Field(pattern=_ID)
    study_sha256: str = Field(pattern=_SHA256)
    reviewer_count: Literal[2] = 2
    comparison_count: int = Field(gt=0)
    completed_count: int = Field(ge=0)
    cannot_assess_count: int = Field(ge=0)
    reviewer_sessions: tuple[HumanStudyFileBinding, HumanStudyFileBinding]
    reviewer_submissions: tuple[HumanStudyFileBinding, HumanStudyFileBinding]
    locked_review_set: HumanStudyFileBinding
    review_set_sha256: str = Field(pattern=_SHA256)
    locked_at: datetime
    condition_identity_hidden_until_lock: Literal[True] = True
    no_reviewer_replacement: Literal[True] = True
    no_outcome_adjudication: Literal[True] = True
    no_external_action_performed: Literal[True] = True
    authorizes_human_recruitment: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_api_spend: Literal[False] = False
    authorizes_gpu_work: Literal[False] = False
    authorizes_experiment: Literal[False] = False


def prepare_human_reviewer_session(
    *,
    evidence_root: str | Path,
    study_path: str | Path,
    benchmark_suite_path: str | Path,
    reviewer_identity_sha256: str,
    output_dir: str | Path,
    prepared_at: datetime | None = None,
) -> HumanReviewerSession:
    """Build one self-contained reviewer session without exposing the blind key."""

    root = Path(evidence_root).resolve(strict=True)
    target = _new_target(root, output_dir)
    study_file = _regular_file(root, study_path)
    suite_file = _regular_file(root, benchmark_suite_path)
    study = load_human_outcome_study(study_file)
    suite = load_benchmark_suite(suite_file)
    _verify_study_suite(study, suite, suite_file)
    study_sha256 = study.study_sha256
    assignments = [
        item
        for item in study.comparisons
        if item.reviewer_identity_sha256 == reviewer_identity_sha256
    ]
    if not assignments:
        raise ValueError("reviewer identity has no assignment in this study")
    expected = len(study.comparisons) // study.reviewers_per_case_contrast
    if len(assignments) != expected:
        raise ValueError("reviewer assignment is not a complete half-study block")
    case_by_id = {item.case_id: item for item in suite.cases}
    rubric = _bound_yaml(root, study.rubric)
    _bound_yaml(root, study.interface)
    standards = rubric.get("decision_standard")
    if not isinstance(standards, list) or not standards:
        raise ValueError("review rubric lacks decision standards")
    questions = []
    for item in standards:
        if not isinstance(item, dict) or not isinstance(item.get("question"), str):
            raise ValueError("review rubric has an invalid decision standard")
        questions.append(item["question"])
    timestamp = prepared_at or datetime.now(UTC)
    session_identity = _canonical_sha256([study_sha256, reviewer_identity_sha256])
    session = HumanReviewerSession(
        session_id=f"session-{session_identity[:24]}",
        study_id=study.study_id,
        study_sha256=study_sha256,
        reviewer_identity_sha256=reviewer_identity_sha256,
        rubric_sha256=study.rubric.sha256,
        interface_sha256=study.interface.sha256,
        primary_question=_required_string(rubric, "primary_question"),
        decision_standards=tuple(questions),
        tie_rule=_required_string(rubric, "tie_rule"),
        cannot_assess_rule=_required_string(rubric, "cannot_assess_rule"),
        comparisons=tuple(
            ReviewerSessionComparison(
                ordinal=index,
                comparison_id=assignment.comparison_id,
                case_context=case_by_id[assignment.case_id].decision_context,
                task=case_by_id[assignment.case_id].task.value,
                stage=case_by_id[assignment.case_id].stage,
                output_x=_visible_decision(root, assignment.x_output),
                output_y=_visible_decision(root, assignment.y_output),
            )
            for index, assignment in enumerate(assignments, 1)
        ),
        prepared_at=timestamp,
    )
    payload = session.model_dump(mode="json", exclude={"session_sha256"})
    encoded = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    template = files("scitaste.evaluation").joinpath("reviewer_ui.html").read_text(encoding="utf-8")
    embedded = json.dumps(
        {**payload, "session_sha256": session.session_sha256}, ensure_ascii=False
    ).replace("<", "\\u003c")
    rendered = template.replace("__SCITASTE_REVIEW_SESSION__", embedded)
    if "__SCITASTE_REVIEW_SESSION__" in rendered:
        raise ValueError("reviewer UI template was not fully rendered")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as temporary:
        workspace = Path(temporary)
        (workspace / "session.json").write_text(encoded, encoding="utf-8")
        (workspace / "review.html").write_text(rendered, encoding="utf-8")
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        os.replace(workspace, target)
    return session


def lock_human_reviewer_submissions(
    *,
    evidence_root: str | Path,
    study_path: str | Path,
    benchmark_suite_path: str | Path,
    session_paths: tuple[str | Path, str | Path],
    submission_paths: tuple[str | Path, str | Path],
    output_path: str | Path,
    report_path: str | Path,
    locked_at: datetime | None = None,
) -> tuple[LockedHumanReviewSet, HumanReviewCollectionReport]:
    """Validate two complete exports and atomically freeze the primary review set."""

    root = Path(evidence_root).resolve(strict=True)
    if len(session_paths) != 2 or len(submission_paths) != 2:
        raise ValueError("review collection requires exactly two sessions and submissions")
    study = load_human_outcome_study(_regular_file(root, study_path))
    study_sha256 = study.study_sha256
    suite_file = _regular_file(root, benchmark_suite_path)
    suite = load_benchmark_suite(suite_file)
    _verify_study_suite(study, suite, suite_file)
    target = _new_file_target(root, output_path)
    report_target = _new_file_target(root, report_path)
    if target == report_target:
        raise ValueError("review set and collection report paths must differ")
    session_files = tuple(_regular_file(root, item, _MAX_SESSION_BYTES) for item in session_paths)
    submission_files = tuple(
        _regular_file(root, item, _MAX_SESSION_BYTES) for item in submission_paths
    )
    lock_time = locked_at or datetime.now(UTC)
    review_set = _compile_locked_review_set(
        root=root,
        study=study,
        suite=suite,
        session_files=session_files,
        submission_files=submission_files,
        locked_at=lock_time,
    )
    _atomic_json(target, review_set.model_dump(mode="json", exclude={"review_set_sha256"}))
    review_binding = _binding(root, target)
    report = HumanReviewCollectionReport(
        study_id=study.study_id,
        study_sha256=study_sha256,
        comparison_count=len(review_set.reviews),
        completed_count=sum(item.preference is not None for item in review_set.reviews),
        cannot_assess_count=sum(item.preference is None for item in review_set.reviews),
        reviewer_sessions=review_set.reviewer_sessions,
        reviewer_submissions=review_set.reviewer_submissions,
        locked_review_set=review_binding,
        review_set_sha256=review_set.review_set_sha256,
        locked_at=lock_time,
    )
    _atomic_json(report_target, report.model_dump(mode="json"))
    return review_set, report


def verify_locked_human_review_set(
    *,
    evidence_root: str | Path,
    study: HumanOutcomeStudyManifest,
    benchmark_suite_path: str | Path,
    reviews: LockedHumanReviewSet,
) -> LockedHumanReviewSet:
    """Replay the four bound collection files and reproduce the locked set exactly."""

    root = Path(evidence_root).resolve(strict=True)
    if reviews.schema_version != "1.1":
        raise ValueError("review collection replay requires a session-bound review set")
    suite_file = _regular_file(root, benchmark_suite_path)
    suite = load_benchmark_suite(suite_file)
    _verify_study_suite(study, suite, suite_file)
    session_files = tuple(
        _bound_file(root, item, maximum_bytes=_MAX_SESSION_BYTES)
        for item in reviews.reviewer_sessions
    )
    submission_files = tuple(
        _bound_file(root, item, maximum_bytes=_MAX_SESSION_BYTES)
        for item in reviews.reviewer_submissions
    )
    replayed = _compile_locked_review_set(
        root=root,
        study=study,
        suite=suite,
        session_files=session_files,
        submission_files=submission_files,
        locked_at=reviews.locked_at,
    )
    if replayed != reviews:
        raise ValueError("locked review set differs from replayed sessions and submissions")
    return replayed


def _compile_locked_review_set(
    *,
    root: Path,
    study: HumanOutcomeStudyManifest,
    suite: BenchmarkSuite,
    session_files: tuple[Path, ...],
    submission_files: tuple[Path, ...],
    locked_at: datetime,
) -> LockedHumanReviewSet:
    """Compile a review set in memory so locking and later opening share one replay path."""

    if len(session_files) != 2 or len(submission_files) != 2:
        raise ValueError("review collection requires exactly two sessions and submissions")
    study_sha256 = study.study_sha256
    sessions = tuple(
        HumanReviewerSession.model_validate_json(path.read_text(encoding="utf-8"))
        for path in session_files
    )
    submissions = tuple(
        HumanReviewerSubmission.model_validate_json(path.read_text(encoding="utf-8"))
        for path in submission_files
    )
    by_reviewer = {item.reviewer_identity_sha256: item for item in sessions}
    if len(by_reviewer) != 2:
        raise ValueError("review collection requires two distinct reviewer sessions")
    submission_by_reviewer = {item.reviewer_identity_sha256: item for item in submissions}
    if set(submission_by_reviewer) != set(by_reviewer):
        raise ValueError("review submissions do not match the two reviewer sessions")
    comparisons = {item.comparison_id: item for item in study.comparisons}
    case_by_id = {item.case_id: item for item in suite.cases}
    expected_reviewers = {item.reviewer_identity_sha256 for item in study.comparisons}
    if set(by_reviewer) != expected_reviewers or len(expected_reviewers) != 2:
        raise ValueError("review sessions do not cover the study reviewer assignments")
    all_session_ids: set[str] = set()
    reviews: list[LockedHumanOutcomeReview] = []
    lock_time = locked_at
    if lock_time.utcoffset() is None:
        raise ValueError("review collection lock timestamp must include a timezone")
    session_bindings = tuple(_binding(root, item) for item in session_files)
    submission_bindings = tuple(_binding(root, item) for item in submission_files)
    submission_binding_by_reviewer = {
        submission.reviewer_identity_sha256: binding
        for submission, binding in zip(submissions, submission_bindings, strict=True)
    }
    for session in sessions:
        if session.study_id != study.study_id or session.study_sha256 != study_sha256:
            raise ValueError("reviewer session binds another study")
        assigned = {
            item.comparison_id
            for item in study.comparisons
            if item.reviewer_identity_sha256 == session.reviewer_identity_sha256
        }
        session_ids = {item.comparison_id for item in session.comparisons}
        if session_ids != assigned:
            raise ValueError("reviewer session does not contain its exact assignment block")
        ordered_assignments = [
            item
            for item in study.comparisons
            if item.reviewer_identity_sha256 == session.reviewer_identity_sha256
        ]
        for ordinal, (session_item, assignment) in enumerate(
            zip(session.comparisons, ordered_assignments, strict=True), 1
        ):
            case = case_by_id[assignment.case_id]
            if (
                session_item.ordinal != ordinal
                or session_item.comparison_id != assignment.comparison_id
                or session_item.case_context != case.decision_context
                or session_item.task != case.task.value
                or session_item.stage != case.stage
                or session_item.output_x != _visible_decision(root, assignment.x_output)
                or session_item.output_y != _visible_decision(root, assignment.y_output)
            ):
                raise ValueError("reviewer session content differs from the committed study")
        if (
            session.rubric_sha256 != study.rubric.sha256
            or session.interface_sha256 != study.interface.sha256
        ):
            raise ValueError("reviewer session protocol bindings differ from the study")
        if all_session_ids & session_ids:
            raise ValueError("reviewer sessions overlap")
        all_session_ids.update(session_ids)
        submission = submission_by_reviewer[session.reviewer_identity_sha256]
        if (
            submission.session_id != session.session_id
            or submission.session_sha256 != session.session_sha256
            or submission.study_sha256 != study_sha256
        ):
            raise ValueError("reviewer submission does not bind its exact session")
        if submission.review_started_at < session.prepared_at:
            raise ValueError("reviewer submission starts before its session was prepared")
        if submission.submitted_at > lock_time:
            raise ValueError("review collection lock cannot precede a submission")
        responses = {item.comparison_id: item for item in submission.responses}
        if set(responses) != assigned:
            raise ValueError("reviewer submission does not cover its exact assignment block")
        submission_sha256 = submission_binding_by_reviewer[session.reviewer_identity_sha256].sha256
        for comparison_id in sorted(assigned):
            comparison = comparisons[comparison_id]
            response = responses[comparison_id]
            if comparison.reviewer_identity_sha256 != session.reviewer_identity_sha256:
                raise ValueError("reviewer submission violates the study assignment")
            cannot_assess = response.response == "cannot-assess"
            review_identity = _canonical_sha256([study_sha256, comparison_id, submission_sha256])
            reviews.append(
                LockedHumanOutcomeReview(
                    review_id=f"review-{review_identity[:24]}",
                    comparison_id=comparison_id,
                    study_sha256=study_sha256,
                    reviewer_identity_sha256=session.reviewer_identity_sha256,
                    disposition=(
                        HumanReviewDisposition.CANNOT_ASSESS
                        if cannot_assess
                        else HumanReviewDisposition.COMPLETED
                    ),
                    preference=(
                        None if cannot_assess else HumanPairwisePreference(response.response)
                    ),
                    rationale=response.rationale,
                    missingness_reason_code=response.missingness_reason_code,
                    locked_at=lock_time,
                    duration_seconds=response.duration_seconds,
                )
            )
    if all_session_ids != set(comparisons):
        raise ValueError("reviewer sessions do not cover every study comparison")
    return LockedHumanReviewSet(
        schema_version="1.1",
        study_id=study.study_id,
        study_sha256=study_sha256,
        reviews=tuple(sorted(reviews, key=lambda item: item.comparison_id)),
        reviewer_sessions=session_bindings,
        reviewer_submissions=submission_bindings,
        locked_at=lock_time,
    )


def _verify_study_suite(
    study: HumanOutcomeStudyManifest, suite: BenchmarkSuite, path: Path
) -> None:
    commitment = study.treatment_commitment
    if commitment is None:
        raise ValueError("reviewer sessions require a treatment-bound study")
    if _sha256(path) != commitment.benchmark_suite_file_sha256:
        raise ValueError("reviewer session benchmark suite bytes differ from the study commitment")
    if suite.sha256 != commitment.benchmark_suite_semantic_sha256:
        raise ValueError("reviewer session benchmark suite semantics differ")
    case_ids = {item.case_id for item in suite.cases}
    if {item.case_id for item in study.comparisons} != case_ids:
        raise ValueError("reviewer session study and benchmark case populations differ")


def _visible_decision(root: Path, binding: HumanStudyFileBinding) -> ReviewerVisibleDecision:
    path = _bound_file(root, binding)
    artifact = BlindedDecisionArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    return ReviewerVisibleDecision(
        selected_action_id=artifact.selected_action_id,
        selected_action_description=artifact.selected_action_description,
        rationale=artifact.rationale,
        confidence=artifact.confidence,
        output_sha256=binding.sha256,
    )


def _bound_yaml(root: Path, binding: HumanStudyFileBinding) -> dict[str, object]:
    path = _bound_file(root, binding)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("bound reviewer configuration must be a mapping")
    return payload


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"review rubric lacks {key}")
    return value


def _bound_file(
    root: Path,
    binding: HumanStudyFileBinding,
    *,
    maximum_bytes: int = _MAX_INPUT_BYTES,
) -> Path:
    path = _regular_file(root, binding.path, maximum_bytes)
    if _sha256(path) != binding.sha256:
        raise ValueError("reviewer-visible file binding differs from its committed bytes")
    return path


def _regular_file(
    root: Path,
    path: str | Path,
    maximum_bytes: int = _MAX_INPUT_BYTES,
) -> Path:
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    if source.is_symlink():
        raise ValueError("review collection inputs cannot be symlinks")
    resolved = source.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("review collection inputs must stay inside the evidence root") from exc
    if not resolved.is_file() or resolved.stat().st_size > maximum_bytes:
        raise ValueError("review collection input is not a bounded regular file")
    return resolved


def _new_target(root: Path, output_dir: str | Path) -> Path:
    target = Path(output_dir)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("reviewer session output must stay inside the evidence root") from exc
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    return target


def _new_file_target(root: Path, output: str | Path) -> Path:
    target = Path(output)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("review collection output must stay inside the evidence root") from exc
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    return target


def _binding(root: Path, path: Path) -> HumanStudyFileBinding:
    return HumanStudyFileBinding(path=path.relative_to(root).as_posix(), sha256=_sha256(path))


def _atomic_json(path: Path, payload: object) -> None:
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


__all__ = [
    "HumanReviewCollectionReport",
    "HumanReviewerSession",
    "HumanReviewerSubmission",
    "ReviewerSessionComparison",
    "ReviewerSubmissionResponse",
    "ReviewerVisibleDecision",
    "lock_human_reviewer_submissions",
    "prepare_human_reviewer_session",
    "verify_locked_human_review_set",
]

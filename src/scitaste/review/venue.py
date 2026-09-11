"""Content-bound venue review rounds for project-owned paper revisions."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project import ProjectReview, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import (
    PaperManifest,
    content_sha256,
    validate_entry_id,
    validate_relative_locator,
)
from scitaste.review.obligations import create_obligation
from scitaste.review.parser import ReviewFeedback, parse_feedback
from scitaste.review.routing import ReviewActionRouter
from scitaste.state.research_state import ResearchState
from scitaste.writing.argument import load_paper_argument_contract
from scitaste.writing.venue_taste import inspect_venue_writing_taste

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_MAX_TEXT = 16_000
_MAX_REPORTS = 8
_ICLR_2027_CRITERIA = (
    "specific_question",
    "motivation_and_literature",
    "claim_support_and_rigor",
    "significance_and_community_value",
)

ReviewScope = Literal["development", "independent_pre_submission"]
ReviewRoundStatus = Literal[
    "prepared",
    "reviewed_no_revision_required",
    "revision_required",
    "response_submitted",
    "closed_internal",
    "independent_pre_submission_review_complete",
]


class VenueReviewPacket(BaseModel):
    """Exact anonymous paper bytes and venue constructs supplied to reviewers."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    review_id: str = Field(pattern=_SAFE_ID)
    paper_id: str = Field(pattern=_SAFE_ID)
    paper_directory: str = Field(pattern=_SAFE_ID)
    paper_stage: int = Field(ge=17, le=23)
    paper_status: str = Field(min_length=1, max_length=200)
    paper_manifest_sha256: str = Field(pattern=_SHA256)
    paper_artifact_sha256: dict[str, str] = Field(min_length=1, max_length=64)
    registered_claim_ids: tuple[str, ...] = Field(default=(), max_length=128)
    source_run_id: str | None = Field(default=None, pattern=_SAFE_ID)
    venue_id: str = Field(min_length=1, max_length=100)
    venue_profile_id: str = Field(min_length=1, max_length=200)
    venue_profile_fingerprint: str = Field(pattern=_SHA256)
    review_round: int = Field(ge=1)
    review_scope: ReviewScope
    submission_mode: Literal["anonymous"] = "anonymous"
    submission_eligible: bool
    criteria: tuple[str, ...] = _ICLR_2027_CRITERIA
    reviewer_instruction: str = Field(min_length=1, max_length=2_000)
    official_decision_authority: Literal[False] = False
    scientific_quality_established: Literal[False] = False
    packet_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def packet_is_closed_and_self_hashed(self) -> VenueReviewPacket:
        if self.criteria != _ICLR_2027_CRITERIA:
            raise ValueError("ICLR review packet must preserve the four official questions")
        if len(self.paper_artifact_sha256) != len(set(self.paper_artifact_sha256)):
            raise ValueError("paper artifact labels must be unique")
        if any(not _is_sha256(value) for value in self.paper_artifact_sha256.values()):
            raise ValueError("paper artifact hashes must be SHA-256 values")
        if tuple(sorted(set(self.registered_claim_ids))) != self.registered_claim_ids:
            raise ValueError("registered claim IDs must be sorted and unique")
        if self.review_scope == "independent_pre_submission" and not self.submission_eligible:
            raise ValueError("independent pre-submission review requires a submission-ready bundle")
        expected = content_sha256(self.model_dump(mode="json", exclude={"packet_sha256"}))
        if self.packet_sha256 != expected:
            raise ValueError("venue review packet hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> VenueReviewPacket:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(packet_sha256="0" * 64, **payload)
        return cls(
            **payload,
            packet_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"packet_sha256"})
            ),
        )


class VenueCriterionAssessment(BaseModel):
    model_config = _CONFIG

    criterion: Literal[
        "specific_question",
        "motivation_and_literature",
        "claim_support_and_rigor",
        "significance_and_community_value",
    ]
    assessment: Literal["satisfied", "partially_satisfied", "not_satisfied", "uncertain"]
    rationale: str = Field(min_length=1, max_length=_MAX_TEXT)


class ReviewerIdentity(BaseModel):
    """Disclosure boundary; no model review can masquerade as an expert review."""

    model_config = _CONFIG

    reviewer_id: str = Field(pattern=_SAFE_ID)
    reviewer_kind: Literal["internal_model", "independent_model", "independent_expert"]
    independent: bool
    conflict_status: Literal["cleared", "potential", "unverified"]
    provider: str | None = Field(default=None, max_length=200)
    model_name: str | None = Field(default=None, max_length=200)
    expertise: tuple[str, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def identity_disclosure_is_consistent(self) -> ReviewerIdentity:
        is_model = self.reviewer_kind in {"internal_model", "independent_model"}
        if is_model != (self.provider is not None and self.model_name is not None):
            raise ValueError("model reviewers require provider and model_name only")
        if self.reviewer_kind == "internal_model" and self.independent:
            raise ValueError("an internal model reviewer cannot be marked independent")
        if self.reviewer_kind.startswith("independent_") and not self.independent:
            raise ValueError("independent reviewers must set independent=true")
        if self.independent and self.conflict_status != "cleared":
            raise ValueError("independent review requires a cleared conflict check")
        return self


class VenueReviewReport(BaseModel):
    """Structured ICLR-style review without numerical acceptance prediction."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=_SAFE_ID)
    packet_sha256: str = Field(pattern=_SHA256)
    review_scope: ReviewScope
    reviewer: ReviewerIdentity
    summary: str = Field(min_length=1, max_length=_MAX_TEXT)
    strengths: tuple[str, ...] = Field(min_length=1, max_length=20)
    weaknesses: tuple[str, ...] = Field(default=(), max_length=20)
    criteria: tuple[VenueCriterionAssessment, ...] = Field(min_length=4, max_length=4)
    initial_recommendation: Literal["accept", "reject"]
    decision_reasons: tuple[str, ...] = Field(min_length=1, max_length=2)
    questions: tuple[str, ...] = Field(default=(), max_length=20)
    additional_feedback: tuple[str, ...] = Field(default=(), max_length=20)
    concerns: tuple[ReviewFeedback, ...] = Field(default=(), max_length=40)
    confidence: Literal["low", "medium", "high"]
    ethics_concern: Literal["none", "potential"] = "none"
    ethics_explanation: str | None = Field(default=None, max_length=_MAX_TEXT)
    official_review: Literal[False] = False
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_complete_and_self_hashed(self) -> VenueReviewReport:
        if tuple(item.criterion for item in self.criteria) != _ICLR_2027_CRITERIA:
            raise ValueError("review report must assess the four official questions in order")
        concern_ids = [item.concern_id for item in self.concerns]
        if len(concern_ids) != len(set(concern_ids)):
            raise ValueError("review concern IDs must be unique")
        for concern_id in concern_ids:
            validate_entry_id(concern_id, field_name="concern_id")
        if self.initial_recommendation == "reject" and not self.concerns:
            raise ValueError("a reject recommendation requires a decision-relevant concern")
        if self.ethics_concern == "potential" and not self.ethics_explanation:
            raise ValueError("a potential ethics concern requires an explanation")
        if self.ethics_concern == "none" and self.ethics_explanation is not None:
            raise ValueError("an ethics explanation requires ethics_concern=potential")
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("venue review report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> VenueReviewReport:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


class ReviewConcernResolution(BaseModel):
    model_config = _CONFIG

    concern_id: str = Field(pattern=_SAFE_ID)
    disposition: Literal["addressed", "contested", "accepted_limitation"]
    response: str = Field(min_length=1, max_length=_MAX_TEXT)
    evidence_sha256: dict[str, str] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def evidence_hashes_are_valid(self) -> ReviewConcernResolution:
        for locator, digest in self.evidence_sha256.items():
            validate_relative_locator(locator, field_name="resolution evidence")
            if not _is_sha256(digest):
                raise ValueError("resolution evidence hashes must be SHA-256 values")
        return self


class VenueReviewResponse(BaseModel):
    """Author response bound to the reviewed and revised paper versions."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    response_id: str = Field(pattern=_SAFE_ID)
    packet_sha256: str = Field(pattern=_SHA256)
    source_report_sha256: tuple[str, ...] = Field(min_length=1, max_length=_MAX_REPORTS)
    revised_paper_directory: str = Field(pattern=_SAFE_ID)
    revised_paper_manifest_sha256: str = Field(pattern=_SHA256)
    resolutions: tuple[ReviewConcernResolution, ...] = Field(default=(), max_length=320)
    response_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def response_is_self_hashed(self) -> VenueReviewResponse:
        if tuple(sorted(set(self.source_report_sha256))) != self.source_report_sha256:
            raise ValueError("source report hashes must be sorted and unique")
        concern_ids = [item.concern_id for item in self.resolutions]
        if len(concern_ids) != len(set(concern_ids)):
            raise ValueError("review response concern IDs must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"response_sha256"}))
        if self.response_sha256 != expected:
            raise ValueError("venue review response hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> VenueReviewResponse:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(response_sha256="0" * 64, **payload)
        return cls(
            **payload,
            response_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"response_sha256"})
            ),
        )


class ReviewConcernVerification(BaseModel):
    model_config = _CONFIG

    concern_id: str = Field(pattern=_SAFE_ID)
    status: Literal["closed", "open"]
    rationale: str = Field(min_length=1, max_length=_MAX_TEXT)


class VenueReviewVerification(BaseModel):
    """The original reviewer checks a response against the exact revised paper."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    verification_id: str = Field(pattern=_SAFE_ID)
    source_report_sha256: str = Field(pattern=_SHA256)
    response_sha256: str = Field(pattern=_SHA256)
    revised_paper_manifest_sha256: str = Field(pattern=_SHA256)
    reviewer_id: str = Field(pattern=_SAFE_ID)
    concerns: tuple[ReviewConcernVerification, ...] = Field(default=(), max_length=40)
    final_recommendation: Literal["accept", "reject"]
    changed_from_initial: bool
    change_reason: str = Field(min_length=1, max_length=_MAX_TEXT)
    official_review: Literal[False] = False
    verification_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def verification_is_self_hashed(self) -> VenueReviewVerification:
        concern_ids = [item.concern_id for item in self.concerns]
        if len(concern_ids) != len(set(concern_ids)):
            raise ValueError("verification concern IDs must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"verification_sha256"}))
        if self.verification_sha256 != expected:
            raise ValueError("venue review verification hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> VenueReviewVerification:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(verification_sha256="0" * 64, **payload)
        return cls(
            **payload,
            verification_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"verification_sha256"})
            ),
        )


class VenueReviewRound(BaseModel):
    """Self-hashed projection of immutable packet, report, response, and verification files."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    review_id: str = Field(pattern=_SAFE_ID)
    paper_directory: str = Field(pattern=_SAFE_ID)
    venue_id: str
    round_number: int = Field(ge=1)
    review_scope: ReviewScope
    status: ReviewRoundStatus
    packet_locator: Literal["PACKET.json"] = "PACKET.json"
    packet_sha256: str = Field(pattern=_SHA256)
    report_sha256: dict[str, str] = Field(default_factory=dict, max_length=_MAX_REPORTS)
    response_locator: Literal["RESPONSE.json"] | None = None
    response_sha256: str | None = Field(default=None, pattern=_SHA256)
    verification_sha256: dict[str, str] = Field(default_factory=dict, max_length=_MAX_REPORTS)
    unresolved_concern_ids: tuple[str, ...] = Field(default=(), max_length=320)
    internal_review_complete: bool = False
    independent_expert_report_count: int = Field(default=0, ge=0, le=_MAX_REPORTS)
    independent_pre_submission_review_complete: bool = False
    official_decision_authority: Literal[False] = False
    scientific_quality_established: Literal[False] = False
    record_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def round_projection_is_consistent(self) -> VenueReviewRound:
        if self.status == "prepared" and (
            self.report_sha256 or self.response_sha256 or self.verification_sha256
        ):
            raise ValueError("a prepared review round cannot reference later artifacts")
        if (self.response_locator is None) != (self.response_sha256 is None):
            raise ValueError("review response locator and hash must appear together")
        if self.verification_sha256 and self.response_sha256 is None:
            raise ValueError("review verification requires a response")
        formal = self.status == "independent_pre_submission_review_complete"
        if formal != self.independent_pre_submission_review_complete:
            raise ValueError("independent review status and verdict disagree")
        if formal and (
            self.review_scope != "independent_pre_submission"
            or self.independent_expert_report_count < 2
            or self.unresolved_concern_ids
        ):
            raise ValueError("independent review completion requires two experts and closure")
        if self.internal_review_complete and self.unresolved_concern_ids:
            raise ValueError("internal review cannot be complete with unresolved concerns")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("venue review round hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> VenueReviewRound:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


class ReviewRoutingRecord(BaseModel):
    """Evidence that structured review concerns entered the research state."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    report_sha256: str = Field(pattern=_SHA256)
    input_state_sha256: str = Field(pattern=_SHA256)
    output_state_sha256: str = Field(pattern=_SHA256)
    output_revision: int = Field(ge=1)
    concern_ids: tuple[str, ...]
    action_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...]
    record_sha256: str = Field(pattern=_SHA256)

    @classmethod
    def create(cls, **values: object) -> ReviewRoutingRecord:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def routing_record_is_self_hashed(self) -> ReviewRoutingRecord:
        if not (len(self.concern_ids) == len(self.action_ids) == len(self.obligation_ids)):
            raise ValueError("review routing must preserve one action and obligation per concern")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("review routing record hash mismatch")
        return self


def prepare_venue_review(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    paper_directory: str,
    review_id: str,
    round_number: int,
    review_scope: ReviewScope,
    venue_taste_profile: str | Path,
    expected_revision: int,
    select: bool = False,
) -> tuple[ProjectSnapshot, VenueReviewPacket, VenueReviewRound]:
    """Materialize and register a deterministic review packet without calling a model."""

    validate_entry_id(review_id, field_name="review_id")
    validate_entry_id(paper_directory, field_name="paper_directory")
    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        raise ValueError(
            f"stale project revision {expected_revision}; current is {snapshot.revision}"
        )
    packet = build_venue_review_packet(
        runtime,
        project_id=project_id,
        paper_directory=paper_directory,
        review_id=review_id,
        round_number=round_number,
        review_scope=review_scope,
        venue_taste_profile=venue_taste_profile,
    )
    round_record = VenueReviewRound.create(
        project_id=project_id,
        review_id=review_id,
        paper_directory=paper_directory,
        venue_id=packet.venue_id,
        round_number=round_number,
        review_scope=review_scope,
        status="prepared",
        packet_sha256=packet.packet_sha256,
        report_sha256={},
        response_locator=None,
        response_sha256=None,
        verification_sha256={},
        unresolved_concern_ids=(),
        internal_review_complete=False,
        independent_expert_report_count=0,
        independent_pre_submission_review_complete=False,
    )
    review_root = runtime.projects_root / project_id / "reviews"
    review_root.mkdir(parents=True, exist_ok=True)
    target = review_root / review_id
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    temporary = Path(tempfile.mkdtemp(prefix=".review-", dir=review_root))
    registered = False
    moved = False
    try:
        _write_json(temporary / "PACKET.json", packet)
        _write_json(temporary / "ROUND.json", round_record)
        (temporary / "reports").mkdir()
        (temporary / "verifications").mkdir()
        os.replace(temporary, target)
        moved = True
        round_sha256 = _file_sha256(target / "ROUND.json")
        snapshot = runtime.register_review(
            project_id,
            ProjectReview(
                review_id=review_id,
                paper_directory=paper_directory,
                venue_id=packet.venue_id,
                round_number=round_number,
                status=round_record.status,
                round_locator=f"reviews/{review_id}/ROUND.json",
                round_sha256=round_sha256,
            ),
            expected_revision=expected_revision,
        )
        registered = True
        if select:
            snapshot = runtime.select_review(
                project_id,
                review_id,
                expected_revision=snapshot.revision,
            )
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        elif moved and not registered and target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise
    return snapshot, packet, round_record


def build_venue_review_packet(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    paper_directory: str,
    review_id: str,
    round_number: int,
    review_scope: ReviewScope,
    venue_taste_profile: str | Path,
) -> VenueReviewPacket:
    """Preview the exact review packet without writing project state."""

    validate_entry_id(review_id, field_name="review_id")
    validate_entry_id(paper_directory, field_name="paper_directory")
    snapshot = runtime.open(project_id)
    paper_entry = next(
        (item for item in snapshot.papers if item.directory_name == paper_directory),
        None,
    )
    if paper_entry is None:
        raise ValueError(f"unknown project paper {paper_directory!r}")
    paper = paper_entry.manifest
    if paper.stage < 17:
        raise ValueError("venue review requires a stage-17-or-later paper bundle")
    profile = inspect_venue_writing_taste(venue_taste_profile)
    paper_venue = (paper.model_extra or {}).get("venue_id")
    if paper_venue is not None and paper_venue != profile.profile.venue_id:
        raise ValueError("paper and venue review profile identify different venues")
    paper_root = runtime.projects_root / project_id / "papers" / paper_directory
    artifact_hashes = _paper_artifact_hashes(paper_root, paper)
    claim_ids = _paper_claim_ids(paper_root, paper)
    submission_eligible = bool((paper.model_extra or {}).get("eligible_for_submission", False))
    return VenueReviewPacket.create(
        project_id=project_id,
        review_id=review_id,
        paper_id=paper.paper_id,
        paper_directory=paper_directory,
        paper_stage=paper.stage,
        paper_status=paper.status,
        paper_manifest_sha256=paper_entry.manifest_sha256,
        paper_artifact_sha256=artifact_hashes,
        registered_claim_ids=claim_ids,
        source_run_id=paper.source_run,
        venue_id=profile.profile.venue_id,
        venue_profile_id=profile.profile.profile_id,
        venue_profile_fingerprint=profile.fingerprint,
        review_round=round_number,
        review_scope=review_scope,
        submission_eligible=submission_eligible,
        reviewer_instruction=(
            "Judge the anonymous paper as a complete research claim: identify its question, "
            "motivation and placement, claim support and rigor, and significance. Return only "
            "decision-relevant concerns; separate requested evidence from optional feedback."
        ),
        official_decision_authority=False,
        scientific_quality_established=False,
    )


def import_venue_review_report(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    review_id: str,
    report: VenueReviewReport,
    expected_revision: int,
) -> tuple[ProjectSnapshot, VenueReviewRound]:
    """Admit one immutable report and update the round projection."""

    snapshot, review, root, packet, current = _review_context(
        runtime, project_id, review_id, expected_revision
    )
    if report.packet_sha256 != packet.packet_sha256:
        raise ValueError("review report targets a different paper packet")
    if report.review_scope != packet.review_scope:
        raise ValueError("review report scope differs from its packet")
    unknown_claims = {
        claim_id
        for concern in report.concerns
        for claim_id in concern.target_claim_ids
        if claim_id not in set(packet.registered_claim_ids)
    }
    if unknown_claims:
        raise ValueError(f"review concerns reference unknown claims: {sorted(unknown_claims)}")
    reports = _load_reports(root, current)
    if current.response_sha256 is not None:
        raise ValueError("no reports may be added after an author response")
    if report.report_id in reports:
        raise FileExistsError(root / "reports" / f"{report.report_id}.json")
    if report.reviewer.reviewer_id in {item.reviewer.reviewer_id for item in reports.values()}:
        raise ValueError("one reviewer may submit only one report per round")
    if len(reports) >= _MAX_REPORTS:
        raise ValueError("review round report limit reached")
    report_path = root / "reports" / f"{report.report_id}.json"
    _write_json_exclusive(report_path, report)
    try:
        reports[report.report_id] = report
        updated = _project_round(packet, reports, response=None, verifications={})
        _replace_json(root / "ROUND.json", updated)
        snapshot = runtime.update_review(
            project_id,
            review_id,
            expected_revision=snapshot.revision,
            status=updated.status,
            round_sha256=_file_sha256(root / "ROUND.json"),
        )
    except BaseException:
        report_path.unlink(missing_ok=True)
        _replace_json(root / "ROUND.json", current)
        raise
    assert review.review_id == updated.review_id
    return snapshot, updated


def submit_venue_review_response(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    review_id: str,
    response: VenueReviewResponse,
    expected_revision: int,
) -> tuple[ProjectSnapshot, VenueReviewRound]:
    """Admit a complete response only when it binds all concerns and revised bytes."""

    snapshot, _review, root, packet, current = _review_context(
        runtime, project_id, review_id, expected_revision
    )
    reports = _load_reports(root, current)
    if not reports:
        raise ValueError("a review response requires at least one admitted report")
    if current.response_sha256 is not None:
        raise FileExistsError(root / "RESPONSE.json")
    if response.packet_sha256 != packet.packet_sha256:
        raise ValueError("review response targets a different paper packet")
    expected_reports = tuple(sorted(item.report_sha256 for item in reports.values()))
    if response.source_report_sha256 != expected_reports:
        raise ValueError("review response must bind every admitted report exactly once")
    expected_concerns = {
        concern.concern_id for report in reports.values() for concern in report.concerns
    }
    observed_concerns = {item.concern_id for item in response.resolutions}
    if observed_concerns != expected_concerns:
        raise ValueError("review response must resolve every admitted concern exactly once")
    revised = _paper_entry(snapshot, response.revised_paper_directory)
    if revised.manifest_sha256 != response.revised_paper_manifest_sha256:
        raise ValueError("revised paper manifest hash mismatch")
    if expected_concerns and revised.manifest_sha256 == packet.paper_manifest_sha256:
        raise ValueError("a concern-bearing response must reference a new paper revision")
    _verify_resolution_evidence(
        runtime.projects_root / project_id,
        response.resolutions,
    )
    response_path = root / "RESPONSE.json"
    _write_json_exclusive(response_path, response)
    try:
        updated = _project_round(packet, reports, response=response, verifications={})
        _replace_json(root / "ROUND.json", updated)
        snapshot = runtime.update_review(
            project_id,
            review_id,
            expected_revision=snapshot.revision,
            status=updated.status,
            round_sha256=_file_sha256(root / "ROUND.json"),
        )
    except BaseException:
        response_path.unlink(missing_ok=True)
        _replace_json(root / "ROUND.json", current)
        raise
    return snapshot, updated


def import_venue_review_verification(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    review_id: str,
    verification: VenueReviewVerification,
    expected_revision: int,
) -> tuple[ProjectSnapshot, VenueReviewRound]:
    """Admit original-reviewer verification and derive closure without self-certification."""

    snapshot, _review, root, packet, current = _review_context(
        runtime, project_id, review_id, expected_revision
    )
    reports = _load_reports(root, current)
    response = _load_response(root, current)
    if response is None:
        raise ValueError("review verification requires an admitted response")
    report = next(
        (
            item
            for item in reports.values()
            if item.report_sha256 == verification.source_report_sha256
        ),
        None,
    )
    if report is None:
        raise ValueError("verification references an unknown review report")
    if verification.reviewer_id != report.reviewer.reviewer_id:
        raise ValueError("only the original reviewer can verify its concern resolution")
    if verification.response_sha256 != response.response_sha256:
        raise ValueError("verification targets a different review response")
    if verification.revised_paper_manifest_sha256 != response.revised_paper_manifest_sha256:
        raise ValueError("verification targets a different revised paper")
    expected_concerns = {item.concern_id for item in report.concerns}
    observed_concerns = {item.concern_id for item in verification.concerns}
    if observed_concerns != expected_concerns:
        raise ValueError("verification must cover every concern from its source report")
    verifications = _load_verifications(root, current)
    if report.report_id in verifications:
        raise FileExistsError(root / "verifications" / f"{report.report_id}.json")
    path = root / "verifications" / f"{report.report_id}.json"
    _write_json_exclusive(path, verification)
    try:
        verifications[report.report_id] = verification
        updated = _project_round(packet, reports, response=response, verifications=verifications)
        _replace_json(root / "ROUND.json", updated)
        snapshot = runtime.update_review(
            project_id,
            review_id,
            expected_revision=snapshot.revision,
            status=updated.status,
            round_sha256=_file_sha256(root / "ROUND.json"),
        )
    except BaseException:
        path.unlink(missing_ok=True)
        _replace_json(root / "ROUND.json", current)
        raise
    return snapshot, updated


def inspect_venue_review(
    runtime: ProjectRuntime, project_id: str, review_id: str
) -> VenueReviewRound:
    """Rehash every referenced artifact and return the validated round projection."""

    snapshot = runtime.open(project_id)
    review = next((item for item in snapshot.manifest.reviews if item.review_id == review_id), None)
    if review is None:
        raise ValueError(f"unknown project review {review_id!r}")
    root = runtime.projects_root / project_id / "reviews" / review_id
    round_record = VenueReviewRound.model_validate_json(
        (root / "ROUND.json").read_text(encoding="utf-8")
    )
    if _file_sha256(root / "ROUND.json") != review.round_sha256:
        raise ValueError("registered review round hash has drifted")
    packet = VenueReviewPacket.model_validate_json(
        (root / round_record.packet_locator).read_text(encoding="utf-8")
    )
    if packet.packet_sha256 != round_record.packet_sha256:
        raise ValueError("review packet hash differs from its round projection")
    reports = _load_reports(root, round_record)
    response = _load_response(root, round_record)
    verifications = _load_verifications(root, round_record)
    projected = _project_round(packet, reports, response=response, verifications=verifications)
    if projected.model_dump(mode="json") != round_record.model_dump(mode="json"):
        raise ValueError("review round projection does not match its immutable artifacts")
    return round_record


def load_venue_review_reports(
    runtime: ProjectRuntime,
    project_id: str,
    review_id: str,
) -> tuple[VenueReviewReport, ...]:
    """Return every admitted report after rehashing the complete review round."""

    round_record = inspect_venue_review(runtime, project_id, review_id)
    root = runtime.projects_root / project_id / "reviews" / review_id
    reports = _load_reports(root, round_record)
    return tuple(reports[key] for key in sorted(reports))


def load_venue_review_packet(
    runtime: ProjectRuntime, project_id: str, review_id: str
) -> VenueReviewPacket:
    """Load the exact packet only after the complete registered round verifies."""

    round_record = inspect_venue_review(runtime, project_id, review_id)
    root = runtime.projects_root / project_id / "reviews" / review_id
    packet = VenueReviewPacket.model_validate_json(
        _contained_file(root, round_record.packet_locator).read_text(encoding="utf-8")
    )
    if packet.packet_sha256 != round_record.packet_sha256:
        raise ValueError("review packet hash differs from its verified round")
    return packet


def route_venue_review_to_state(
    report: VenueReviewReport,
    state: ResearchState,
) -> tuple[ResearchState, ReviewRoutingRecord]:
    """Route admitted concerns into research obligations on a copied state."""

    routed = state.model_copy(deep=True)
    existing_concerns = {item.concern_id for item in routed.reviewer_concerns}
    incoming = {item.concern_id for item in report.concerns}
    if existing_concerns & incoming:
        raise ValueError("review report contains an already-routed concern")
    known_claims = {item.claim_id for item in routed.claims}
    unknown = {
        claim_id
        for item in report.concerns
        for claim_id in item.target_claim_ids
        if claim_id not in known_claims
    }
    if unknown:
        raise ValueError(
            f"review concerns reference unknown research-state claims: {sorted(unknown)}"
        )
    concerns = parse_feedback(list(report.concerns))
    router = ReviewActionRouter()
    actions = [router.route(item) for item in concerns]
    obligations = [
        create_obligation(concern, action, routed)
        for concern, action in zip(concerns, actions, strict=True)
    ]
    input_sha256 = content_sha256(state)
    routed.reviewer_concerns.extend(concerns)
    routed.open_research_obligations.extend(obligations)
    routed.revision += 1
    output_sha256 = content_sha256(routed)
    record = ReviewRoutingRecord.create(
        report_sha256=report.report_sha256,
        input_state_sha256=input_sha256,
        output_state_sha256=output_sha256,
        output_revision=routed.revision,
        concern_ids=tuple(item.concern_id for item in concerns),
        action_ids=tuple(item.action_id for item in actions),
        obligation_ids=tuple(item.obligation_id for item in obligations),
    )
    return routed, record


def _project_round(
    packet: VenueReviewPacket,
    reports: dict[str, VenueReviewReport],
    *,
    response: VenueReviewResponse | None,
    verifications: dict[str, VenueReviewVerification],
) -> VenueReviewRound:
    concerns = {item.concern_id for report in reports.values() for item in report.concerns}
    verified_closed = {
        item.concern_id
        for verification in verifications.values()
        for item in verification.concerns
        if item.status == "closed"
    }
    unresolved = tuple(sorted(concerns - verified_closed))
    all_verified = len(verifications) == len(reports) and not unresolved
    all_accept = bool(reports) and all(
        verification.final_recommendation == "accept" for verification in verifications.values()
    )
    internal_complete = all_verified and all_accept
    expert_count = len(
        {
            report.reviewer.reviewer_id
            for report in reports.values()
            if report.reviewer.reviewer_kind == "independent_expert"
            and report.reviewer.independent
            and report.reviewer.conflict_status == "cleared"
        }
    )
    independent_complete = (
        packet.review_scope == "independent_pre_submission"
        and internal_complete
        and expert_count >= 2
    )
    if independent_complete:
        status: ReviewRoundStatus = "independent_pre_submission_review_complete"
    elif internal_complete:
        status = "closed_internal"
    elif response is not None:
        status = "response_submitted"
    elif reports and concerns:
        status = "revision_required"
    elif reports:
        status = "reviewed_no_revision_required"
    else:
        status = "prepared"
    return VenueReviewRound.create(
        project_id=packet.project_id,
        review_id=packet.review_id,
        paper_directory=packet.paper_directory,
        venue_id=packet.venue_id,
        round_number=packet.review_round,
        review_scope=packet.review_scope,
        status=status,
        packet_sha256=packet.packet_sha256,
        report_sha256={
            report_id: report.report_sha256 for report_id, report in sorted(reports.items())
        },
        response_locator="RESPONSE.json" if response is not None else None,
        response_sha256=response.response_sha256 if response is not None else None,
        verification_sha256={
            report_id: verification.verification_sha256
            for report_id, verification in sorted(verifications.items())
        },
        unresolved_concern_ids=unresolved,
        internal_review_complete=internal_complete,
        independent_expert_report_count=expert_count,
        independent_pre_submission_review_complete=independent_complete,
        official_decision_authority=False,
        scientific_quality_established=False,
    )


def _review_context(
    runtime: ProjectRuntime,
    project_id: str,
    review_id: str,
    expected_revision: int,
) -> tuple[ProjectSnapshot, ProjectReview, Path, VenueReviewPacket, VenueReviewRound]:
    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        raise ValueError(
            f"stale project revision {expected_revision}; current is {snapshot.revision}"
        )
    review = next((item for item in snapshot.manifest.reviews if item.review_id == review_id), None)
    if review is None:
        raise ValueError(f"unknown project review {review_id!r}")
    root = runtime.projects_root / project_id / "reviews" / review_id
    current = inspect_venue_review(runtime, project_id, review_id)
    packet = VenueReviewPacket.model_validate_json(
        (root / current.packet_locator).read_text(encoding="utf-8")
    )
    return snapshot, review, root, packet, current


def _load_reports(root: Path, round_record: VenueReviewRound) -> dict[str, VenueReviewReport]:
    reports: dict[str, VenueReviewReport] = {}
    for report_id, digest in round_record.report_sha256.items():
        validate_entry_id(report_id, field_name="report_id")
        path = root / "reports" / f"{report_id}.json"
        report = VenueReviewReport.model_validate_json(path.read_text(encoding="utf-8"))
        if report.report_sha256 != digest:
            raise ValueError(f"review report hash mismatch: {report_id}")
        reports[report_id] = report
    return reports


def _load_response(root: Path, round_record: VenueReviewRound) -> VenueReviewResponse | None:
    if round_record.response_locator is None:
        return None
    path = root / round_record.response_locator
    response = VenueReviewResponse.model_validate_json(path.read_text(encoding="utf-8"))
    if response.response_sha256 != round_record.response_sha256:
        raise ValueError("review response file hash mismatch")
    return response


def _load_verifications(
    root: Path, round_record: VenueReviewRound
) -> dict[str, VenueReviewVerification]:
    values: dict[str, VenueReviewVerification] = {}
    for report_id, digest in round_record.verification_sha256.items():
        validate_entry_id(report_id, field_name="report_id")
        path = root / "verifications" / f"{report_id}.json"
        value = VenueReviewVerification.model_validate_json(path.read_text(encoding="utf-8"))
        if value.verification_sha256 != digest:
            raise ValueError(f"review verification hash mismatch: {report_id}")
        values[report_id] = value
    return values


def _paper_artifact_hashes(root: Path, paper: PaperManifest) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for label, locator in sorted(paper.files.items()):
        path = _contained_file(root, locator)
        hashes[label] = _file_sha256(path)
    return hashes


def _paper_claim_ids(root: Path, paper: PaperManifest) -> tuple[str, ...]:
    locator = paper.files.get("paper-argument-contract")
    if locator is None:
        return ()
    contract = load_paper_argument_contract(_contained_file(root, locator))
    return tuple(sorted(item.claim_id for item in contract.claims))


def _paper_entry(snapshot: ProjectSnapshot, directory_name: str):
    validate_entry_id(directory_name, field_name="revised_paper_directory")
    entry = next(
        (item for item in snapshot.papers if item.directory_name == directory_name),
        None,
    )
    if entry is None:
        raise ValueError(f"unknown revised project paper {directory_name!r}")
    return entry


def _verify_resolution_evidence(
    project_root: Path, resolutions: Iterable[ReviewConcernResolution]
) -> None:
    for resolution in resolutions:
        for locator, expected in resolution.evidence_sha256.items():
            observed = _file_sha256(_contained_file(project_root, locator))
            if observed != expected:
                raise ValueError(f"review response evidence hash mismatch: {locator}")


def _contained_file(root: Path, locator: str) -> Path:
    validate_relative_locator(locator, field_name="artifact locator")
    canonical_root = root.resolve(strict=True)
    candidate = root / PurePosixPath(locator)
    if candidate.is_symlink():
        raise ValueError("review artifacts cannot be symlinks")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(canonical_root)
    except ValueError as exc:
        raise ValueError("review artifact resolves outside its owner") from exc
    if not resolved.is_file():
        raise ValueError("review artifact must be a regular file")
    return resolved


def _write_json(path: Path, value: BaseModel) -> None:
    path.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _write_json_exclusive(path: Path, value: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(value.model_dump_json(indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _replace_json(path: Path, value: BaseModel) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)

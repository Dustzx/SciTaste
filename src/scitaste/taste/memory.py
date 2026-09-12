"""Outcome-gated memory updates for continually improving Scientific Taste."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.data.store import TasteLibrary
from scitaste.schema.decisions import ResearchDecision

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_EVIDENCE_BYTES = 16 * 1_048_576


class TasteMemoryReviewRole(StrEnum):
    PRIMARY = "primary"
    ADJUDICATOR = "adjudicator"


class TasteMemoryReviewVerdict(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


class TasteOutcomeEvidence(BaseModel):
    """A frozen outcome record linked to the exact executed decision."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    evidence_id: str = Field(pattern=_ID)
    decision_id: str = Field(min_length=1, max_length=300)
    executor_result_id: str = Field(min_length=1, max_length=300)
    actual_outcome_sha256: str = Field(pattern=_SHA256)
    outcome_summary: str = Field(min_length=1, max_length=10_000)
    outcome_horizon: str = Field(min_length=1, max_length=300)
    observed_at: datetime
    observation_ids: tuple[str, ...] = Field(min_length=1, max_length=1_000)
    generated_from_execution_record: Literal[True] = True

    @model_validator(mode="after")
    def observations_are_unique(self) -> TasteOutcomeEvidence:
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("Taste outcome observation IDs must be unique")
        if any(not item.strip() or len(item) > 300 for item in self.observation_ids):
            raise ValueError("Taste outcome observation IDs must be bounded")
        if self.observed_at.tzinfo is None:
            raise ValueError("Taste outcome timestamp must include a timezone")
        return self


class TasteMemoryEvidenceBinding(BaseModel):
    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_normalized_and_relative(self) -> TasteMemoryEvidenceBinding:
        candidate = PurePosixPath(self.path)
        if candidate.is_absolute() or ".." in candidate.parts or str(candidate) != self.path:
            raise ValueError("Taste memory evidence path must be normalized and relative")
        return self


class TasteMemoryReview(BaseModel):
    """One independent review of a quarantined reflection and its outcome."""

    model_config = _CONFIG

    review_id: str = Field(pattern=_ID)
    case_id: str = Field(pattern=_ID)
    case_sha256: str = Field(pattern=_SHA256)
    decision_evidence_sha256: str = Field(pattern=_SHA256)
    outcome_evidence_sha256: str = Field(pattern=_SHA256)
    reviewer_id: str = Field(pattern=_ID)
    role: TasteMemoryReviewRole
    verdict: TasteMemoryReviewVerdict
    decision_trace_supported: bool
    outcome_trace_supported: bool
    alternatives_supported: bool
    principle_supported: bool
    transfer_scope_calibrated: bool
    expertise_scope: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=4_000)
    reviewed_at: datetime
    human_performed: Literal[True] = True
    conflict_cleared: Literal[True] = True
    independent_review: Literal[True] = True
    blinded_to_other_reviews: Literal[True] = True

    @model_validator(mode="after")
    def verdict_matches_review_dimensions(self) -> TasteMemoryReview:
        dimensions = (
            self.decision_trace_supported,
            self.outcome_trace_supported,
            self.alternatives_supported,
            self.principle_supported,
            self.transfer_scope_calibrated,
        )
        if self.verdict is TasteMemoryReviewVerdict.ACCEPT and not all(dimensions):
            raise ValueError("accepted Taste memory review requires every review dimension")
        if self.verdict is TasteMemoryReviewVerdict.REJECT and all(dimensions):
            raise ValueError("rejected Taste memory review must identify a failed dimension")
        if self.reviewed_at.tzinfo is None:
            raise ValueError("Taste memory review timestamp must include a timezone")
        return self

    @property
    def semantic_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class TasteMemoryAdmission(BaseModel):
    """Content-bound request to promote one reflection into reusable memory."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    admission_id: str = Field(pattern=_ID)
    case_id: str = Field(pattern=_ID)
    case_sha256: str = Field(pattern=_SHA256)
    reflection_author_id: str = Field(pattern=_ID)
    decision_evidence: TasteMemoryEvidenceBinding
    outcome_evidence: TasteMemoryEvidenceBinding
    reviews: tuple[TasteMemoryReview, ...] = Field(min_length=2, max_length=3)
    authorizes_model_training: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def references_are_closed(self) -> TasteMemoryAdmission:
        if len({item.review_id for item in self.reviews}) != len(self.reviews):
            raise ValueError("Taste memory review IDs must be unique")
        if any(item.case_id != self.case_id for item in self.reviews):
            raise ValueError("Taste memory reviews must reference the admitted case")
        if any(item.case_sha256 != self.case_sha256 for item in self.reviews):
            raise ValueError("Taste memory reviews must bind the admitted case hash")
        if any(
            item.decision_evidence_sha256 != self.decision_evidence.sha256 for item in self.reviews
        ):
            raise ValueError("Taste memory reviews must bind the decision evidence hash")
        if any(
            item.outcome_evidence_sha256 != self.outcome_evidence.sha256 for item in self.reviews
        ):
            raise ValueError("Taste memory reviews must bind the outcome evidence hash")
        return self

    @property
    def semantic_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class TasteMemoryAdmissionFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class TasteMemoryAdmissionReport(BaseModel):
    """Read-only admission result; only ``TasteMemory.admit`` mutates the library."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    admission_id: str
    admission_sha256: str = Field(pattern=_SHA256)
    case_id: str
    case_sha256: str = Field(pattern=_SHA256)
    decision_evidence_verified: bool
    outcome_evidence_verified: bool
    primary_review_count: int = Field(ge=0)
    adjudicator_review_count: int = Field(ge=0)
    accepted_review_ids: tuple[str, ...]
    ready_for_retrieval_admission: bool
    findings: tuple[TasteMemoryAdmissionFinding, ...]
    authorizes_model_training: Literal[False] = False
    authorizes_execution: Literal[False] = False
    no_external_action_performed: Literal[True] = True


class TasteMemory:
    """Create quarantined reflections and admit only independently verified cases."""

    def __init__(self, library: TasteLibrary) -> None:
        self.library = library

    def reflect(
        self,
        decision: ResearchDecision,
        *,
        outcome_summary: str,
        decision_principle: str,
        reflection_author_id: str,
        outcome_horizon: str = "immediate",
        domain_tags: list[str] | None = None,
        venue_tags: list[str] | None = None,
    ) -> TasteCase:
        """Store an executed decision as quarantined—not yet reusable—experience."""

        if decision.executor_result_id is None or decision.actual_outcome is None:
            raise ValueError("Taste reflection requires an executed decision and actual outcome")
        if re.fullmatch(_ID, reflection_author_id) is None:
            raise ValueError("Taste reflection author ID must be a normalized identifier")
        if (
            not outcome_summary.strip()
            or len(outcome_summary) > 10_000
            or not decision_principle.strip()
            or len(decision_principle) > 4_000
        ):
            raise ValueError("Taste reflection requires a bounded outcome and decision principle")
        if not outcome_horizon.strip() or len(outcome_horizon) > 300:
            raise ValueError("Taste reflection outcome horizon must be bounded")

        actual_outcome_sha256 = _canonical_sha256(decision.actual_outcome)
        decision_sha256 = _canonical_sha256(decision.model_dump(mode="json"))
        normalized_domains = list(dict.fromkeys(domain_tags or []))
        normalized_venues = list(dict.fromkeys(venue_tags or []))
        identity = _canonical_sha256(
            {
                "decision_sha256": decision_sha256,
                "outcome_summary": outcome_summary,
                "decision_principle": decision_principle,
                "reflection_author_id": reflection_author_id,
                "outcome_horizon": outcome_horizon,
                "domain_tags": normalized_domains,
                "venue_tags": normalized_venues,
            }
        )[:24]
        candidates = [
            f"{action.type.value}::{action.action_id}" for action in decision.candidate_actions
        ]
        preferred = f"{decision.selected_action.type.value}::{decision.selected_action.action_id}"
        rejected = [
            item
            for item, action in zip(candidates, decision.candidate_actions, strict=True)
            if action.action_id != decision.selected_action.action_id
        ]
        case = TasteCase(
            case_id=f"taste-{identity}",
            stage=decision.stage,
            context_summary=decision.rationale,
            evidence_state=outcome_summary,
            candidate_actions=candidates,
            preferred_action=preferred,
            rejected_actions=rejected,
            decision_principle=decision_principle,
            why_preferred=decision.rationale,
            outcome_summary=outcome_summary,
            provenance=[
                ProvenanceRecord(
                    source_type="decision_log_reflection",
                    locator=decision.state_snapshot_id,
                    version=decision.decision_id,
                    content_hash=decision_sha256,
                    accessed_at=decision.timestamp,
                    derivation_method=(
                        "Outcome-linked project reflection pending independent review."
                    ),
                    metadata={
                        "executor_result_id": decision.executor_result_id,
                        "actual_outcome_sha256": actual_outcome_sha256,
                        "reflection_author_id": reflection_author_id,
                        "admission_state": "quarantined",
                    },
                )
            ],
            confidence=decision.confidence,
            retrieval_eligible=False,
            human_verified=False,
            label_basis="project_reflection_pending_review",
            extractor_version="scitaste-taste-memory-reflection-v2",
            domain_tags=normalized_domains,
            venue_tags=normalized_venues,
            outcome_horizon=outcome_horizon,
            source_action_id=decision.selected_action.action_id,
        )
        try:
            existing = self.library.get(case.case_id)
        except KeyError:
            self.library.add(case)
        else:
            if existing != case:
                raise ValueError("Taste reflection identity already exists with different content")
            return existing
        return case

    def admit(
        self,
        admission: TasteMemoryAdmission,
        *,
        evidence_root: str | Path,
    ) -> TasteCase:
        """Promote one exact quarantined case after outcome and human review gates pass."""

        report = inspect_taste_memory_admission(
            admission,
            library=self.library,
            evidence_root=evidence_root,
        )
        if not report.ready_for_retrieval_admission:
            codes = ", ".join(item.code for item in report.findings)
            raise ValueError(f"Taste memory admission is not ready: {codes}")
        case = self.library.get(admission.case_id)
        admitted = TasteCase.model_validate(
            {
                **case.model_dump(mode="json"),
                "human_verified": True,
                "retrieval_eligible": True,
                "label_basis": "project_outcome_dual_human_verified",
                "provenance": [
                    *case.provenance,
                    ProvenanceRecord(
                        source_type="taste_memory_admission",
                        locator=admission.outcome_evidence.path,
                        version=admission.admission_id,
                        content_hash=admission.outcome_evidence.sha256,
                        derivation_method=(
                            "Outcome-bound reflection admitted by two independent human "
                            "reviews with conditional adjudication."
                        ),
                        metadata={
                            "admission_sha256": admission.semantic_sha256,
                            "review_ids": [item.review_id for item in admission.reviews],
                            "review_sha256": [item.semantic_sha256 for item in admission.reviews],
                        },
                    ),
                ],
            }
        )
        self.library.upsert(admitted)
        return admitted


def inspect_taste_memory_admission(
    admission: TasteMemoryAdmission,
    *,
    library: TasteLibrary,
    evidence_root: str | Path,
) -> TasteMemoryAdmissionReport:
    """Verify one memory admission without mutating the library or external state."""

    findings: list[TasteMemoryAdmissionFinding] = []
    try:
        case = library.get(admission.case_id)
    except KeyError:
        case = None
        _add(findings, "case_not_found", "quarantined Taste case is absent from the library")

    if case is not None:
        observed_case_sha256 = taste_case_sha256(case)
        if observed_case_sha256 != admission.case_sha256:
            _add(findings, "case_hash_mismatch", "stored Taste case differs from the admission")
        if case.retrieval_eligible or case.human_verified:
            _add(
                findings,
                "case_not_quarantined",
                "Taste memory admission accepts only unverified, retrieval-ineligible cases",
            )
        reflection = _reflection_provenance(case)
        if reflection is None:
            _add(
                findings,
                "reflection_provenance_missing",
                "Taste case lacks outcome-linked reflection provenance",
            )
        elif reflection.metadata.get("reflection_author_id") != admission.reflection_author_id:
            _add(
                findings,
                "reflection_author_mismatch",
                "admission author differs from the frozen reflection author",
            )
    else:
        reflection = None

    decision = _load_decision_evidence(
        admission.decision_evidence,
        evidence_root=evidence_root,
        findings=findings,
    )
    if decision is not None and case is not None and reflection is not None:
        _inspect_decision_relationships(
            decision,
            case=case,
            reflection=reflection,
            findings=findings,
        )

    decision_finding_codes = {
        "decision_evidence_unavailable",
        "decision_evidence_file_hash_mismatch",
        "decision_evidence_invalid",
        "decision_hash_mismatch",
        "decision_id_mismatch",
        "decision_not_executed",
        "decision_executor_mismatch",
        "decision_outcome_mismatch",
        "decision_case_mismatch",
    }
    decision_verified = decision is not None and not any(
        item.code in decision_finding_codes for item in findings
    )

    outcome = _load_outcome_evidence(
        admission.outcome_evidence,
        evidence_root=evidence_root,
        findings=findings,
    )
    if outcome is not None and case is not None and reflection is not None:
        if outcome.decision_id != reflection.version:
            _add(findings, "outcome_decision_mismatch", "outcome evidence names another decision")
        if outcome.executor_result_id != reflection.metadata.get("executor_result_id"):
            _add(findings, "outcome_executor_mismatch", "outcome evidence names another result")
        if outcome.actual_outcome_sha256 != reflection.metadata.get("actual_outcome_sha256"):
            _add(findings, "outcome_hash_mismatch", "outcome evidence differs from execution")
        if outcome.outcome_summary != case.outcome_summary:
            _add(findings, "outcome_summary_mismatch", "outcome evidence and reflection differ")
        if outcome.outcome_horizon != case.outcome_horizon:
            _add(findings, "outcome_horizon_mismatch", "outcome horizons differ")
        if decision is not None:
            if outcome.decision_id != decision.decision_id:
                _add(
                    findings,
                    "outcome_decision_mismatch",
                    "outcome evidence differs from decision evidence",
                )
            if outcome.executor_result_id != decision.executor_result_id:
                _add(
                    findings,
                    "outcome_executor_mismatch",
                    "outcome evidence differs from decision evidence",
                )
            if outcome.actual_outcome_sha256 != _canonical_sha256(decision.actual_outcome):
                _add(
                    findings,
                    "outcome_hash_mismatch",
                    "outcome evidence differs from decision evidence",
                )

    outcome_finding_codes = {
        "outcome_evidence_unavailable",
        "outcome_evidence_file_hash_mismatch",
        "outcome_evidence_invalid",
        "outcome_decision_mismatch",
        "outcome_executor_mismatch",
        "outcome_hash_mismatch",
        "outcome_summary_mismatch",
        "outcome_horizon_mismatch",
    }
    outcome_verified = outcome is not None and not any(
        item.code in outcome_finding_codes for item in findings
    )
    if outcome is not None and any(
        review.reviewed_at < outcome.observed_at for review in admission.reviews
    ):
        _add(
            findings,
            "review_predates_outcome",
            "Taste memory review cannot precede the bound outcome observation",
        )

    reviewer_ids = [item.reviewer_id for item in admission.reviews]
    if len(reviewer_ids) != len(set(reviewer_ids)):
        _add(findings, "duplicate_reviewer", "Taste memory reviewers must be distinct")
    if admission.reflection_author_id in reviewer_ids:
        _add(findings, "author_review_conflict", "reflection author cannot review their own case")

    primary = [item for item in admission.reviews if item.role is TasteMemoryReviewRole.PRIMARY]
    adjudicators = [
        item for item in admission.reviews if item.role is TasteMemoryReviewRole.ADJUDICATOR
    ]
    if len(primary) != 2:
        _add(findings, "primary_review_count", "Taste memory admission requires two reviews")
    if len(adjudicators) > 1:
        _add(findings, "adjudicator_count", "Taste memory admission allows one adjudicator")

    primary_accepts = sum(item.verdict is TasteMemoryReviewVerdict.ACCEPT for item in primary)
    if len(primary) == 2 and primary_accepts in {0, 2} and adjudicators:
        _add(
            findings,
            "unneeded_adjudication",
            "unanimous primary reviews cannot be overridden by an adjudicator",
        )
    if len(primary) == 2 and primary_accepts == 1 and len(adjudicators) != 1:
        _add(
            findings,
            "adjudication_required",
            "split primary reviews require one independent adjudicator",
        )

    accepted = primary_accepts == 2 or (
        primary_accepts == 1
        and len(adjudicators) == 1
        and adjudicators[0].verdict is TasteMemoryReviewVerdict.ACCEPT
    )
    if not accepted:
        _add(findings, "human_review_not_accepted", "independent review did not admit the case")

    return TasteMemoryAdmissionReport(
        admission_id=admission.admission_id,
        admission_sha256=admission.semantic_sha256,
        case_id=admission.case_id,
        case_sha256=admission.case_sha256,
        decision_evidence_verified=decision_verified,
        outcome_evidence_verified=outcome_verified,
        primary_review_count=len(primary),
        adjudicator_review_count=len(adjudicators),
        accepted_review_ids=tuple(
            item.review_id
            for item in admission.reviews
            if item.verdict is TasteMemoryReviewVerdict.ACCEPT
        ),
        ready_for_retrieval_admission=not findings,
        findings=tuple(findings),
    )


def taste_case_sha256(case: TasteCase) -> str:
    return _canonical_sha256(case.model_dump(mode="json"))


def load_taste_memory_admission(path: str | Path) -> TasteMemoryAdmission:
    """Load one bounded admission manifest without reading its bound evidence."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("Taste memory admission manifest must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_EVIDENCE_BYTES:
        raise ValueError("Taste memory admission manifest must be a bounded regular file")
    try:
        payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("Taste memory admission manifest must be UTF-8") from exc
    except yaml.YAMLError as exc:
        raise ValueError("Taste memory admission manifest must be valid YAML") from exc
    if not isinstance(payload, dict):
        raise ValueError("Taste memory admission manifest must contain a mapping")
    return TasteMemoryAdmission.model_validate(payload)


def save_taste_memory_admission_report(
    report: TasteMemoryAdmissionReport,
    path: str | Path,
) -> Path:
    """Atomically write a deterministic local admission inspection report."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(report.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(output)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return output


def _load_decision_evidence(
    binding: TasteMemoryEvidenceBinding,
    *,
    evidence_root: str | Path,
    findings: list[TasteMemoryAdmissionFinding],
) -> ResearchDecision | None:
    try:
        raw = _read_bound_evidence(binding, evidence_root=evidence_root)
    except (OSError, ValueError):
        _add(findings, "decision_evidence_unavailable", "decision evidence is unavailable")
        return None
    if hashlib.sha256(raw).hexdigest() != binding.sha256:
        _add(
            findings,
            "decision_evidence_file_hash_mismatch",
            "decision evidence file hash differs",
        )
        return None
    try:
        return ResearchDecision.model_validate_json(raw)
    except ValueError:
        _add(findings, "decision_evidence_invalid", "decision evidence is not valid JSON")
        return None


def _inspect_decision_relationships(
    decision: ResearchDecision,
    *,
    case: TasteCase,
    reflection: ProvenanceRecord,
    findings: list[TasteMemoryAdmissionFinding],
) -> None:
    if _canonical_sha256(decision.model_dump(mode="json")) != reflection.content_hash:
        _add(findings, "decision_hash_mismatch", "decision evidence differs from reflection")
    if decision.decision_id != reflection.version:
        _add(findings, "decision_id_mismatch", "decision evidence names another decision")
    if decision.executor_result_id is None or decision.actual_outcome is None:
        _add(findings, "decision_not_executed", "decision evidence has no completed execution")
    if decision.executor_result_id != reflection.metadata.get("executor_result_id"):
        _add(findings, "decision_executor_mismatch", "decision executor result differs")
    if decision.actual_outcome is not None and _canonical_sha256(
        decision.actual_outcome
    ) != reflection.metadata.get("actual_outcome_sha256"):
        _add(findings, "decision_outcome_mismatch", "decision actual outcome differs")

    candidates = [
        f"{action.type.value}::{action.action_id}" for action in decision.candidate_actions
    ]
    preferred = f"{decision.selected_action.type.value}::{decision.selected_action.action_id}"
    rejected = [
        item
        for item, action in zip(candidates, decision.candidate_actions, strict=True)
        if action.action_id != decision.selected_action.action_id
    ]
    relationships = (
        case.stage == decision.stage,
        case.context_summary == decision.rationale,
        case.candidate_actions == candidates,
        case.preferred_action == preferred,
        case.rejected_actions == rejected,
        case.confidence == decision.confidence,
        case.source_action_id == decision.selected_action.action_id,
        reflection.locator == decision.state_snapshot_id,
    )
    if not all(relationships):
        _add(findings, "decision_case_mismatch", "Taste case differs from decision evidence")


def _load_outcome_evidence(
    binding: TasteMemoryEvidenceBinding,
    *,
    evidence_root: str | Path,
    findings: list[TasteMemoryAdmissionFinding],
) -> TasteOutcomeEvidence | None:
    try:
        raw = _read_bound_evidence(binding, evidence_root=evidence_root)
    except (OSError, ValueError):
        _add(findings, "outcome_evidence_unavailable", "outcome evidence is unavailable")
        return None
    if hashlib.sha256(raw).hexdigest() != binding.sha256:
        _add(findings, "outcome_evidence_file_hash_mismatch", "outcome file hash differs")
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
        return TasteOutcomeEvidence.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _add(findings, "outcome_evidence_invalid", "outcome evidence is not valid JSON")
        return None


def _read_bound_evidence(
    binding: TasteMemoryEvidenceBinding,
    *,
    evidence_root: str | Path,
) -> bytes:
    root = Path(evidence_root).resolve(strict=True)
    requested = root / binding.path
    if requested.is_symlink():
        raise ValueError("symlink")
    resolved = requested.resolve(strict=True)
    resolved.relative_to(root)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_EVIDENCE_BYTES:
        raise ValueError("not a bounded file")
    return resolved.read_bytes()


def _reflection_provenance(case: TasteCase) -> ProvenanceRecord | None:
    return next(
        (item for item in case.provenance if item.source_type == "decision_log_reflection"),
        None,
    )


def _add(
    findings: list[TasteMemoryAdmissionFinding],
    code: str,
    message: str,
) -> None:
    if code not in {item.code for item in findings}:
        findings.append(TasteMemoryAdmissionFinding(code=code, message=message))


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


__all__ = [
    "TasteMemory",
    "TasteMemoryAdmission",
    "TasteMemoryAdmissionFinding",
    "TasteMemoryAdmissionReport",
    "TasteMemoryEvidenceBinding",
    "TasteMemoryReview",
    "TasteMemoryReviewRole",
    "TasteMemoryReviewVerdict",
    "TasteOutcomeEvidence",
    "inspect_taste_memory_admission",
    "load_taste_memory_admission",
    "save_taste_memory_admission_report",
    "taste_case_sha256",
]

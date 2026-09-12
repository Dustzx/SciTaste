"""Admission of audited scientific sources into the Taste abstraction pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.json_content_audit import JsonContentAuditReport
from scitaste.evaluation.taste_corpus_pair import TasteCorpusFileBinding

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 16 * 1_048_576
_MAX_EVIDENCE_BYTES = 64 * 1_048_576


class SourceAdmissionVerdict(StrEnum):
    ADMIT = "admit"
    REJECT = "reject"


class SourceRightsArgument(BaseModel):
    """Rights and attribution argument independent of scientific quality."""

    model_config = _CONFIG

    evidence: TasteCorpusFileBinding | None = None
    license_id: str | None = Field(default=None, max_length=200)
    license_url: str | None = Field(default=None, max_length=2_000)
    attribution: str | None = Field(default=None, max_length=2_000)
    permits_research_analysis: bool = False
    permits_derived_abstraction: bool = False
    pre_body_screen_consistent: bool = False


class SourceQualityArgument(BaseModel):
    """Why a source is strong enough to teach transferable scientific judgment."""

    model_config = _CONFIG

    evidence: TasteCorpusFileBinding | None = None
    quality_tier: str | None = Field(default=None, pattern=_ID)
    venue_or_source: str | None = Field(default=None, max_length=500)
    publication_year: int | None = Field(default=None, ge=1900, le=2200)
    primary_scientific_record: bool = False
    decision_process_observable: bool = False
    quality_rationale: str | None = Field(default=None, max_length=4_000)


class SourceIsolationArgument(BaseModel):
    """Evidence that the source cannot leak into a held-out decision or self study."""

    model_config = _CONFIG

    evidence: TasteCorpusFileBinding | None = None
    source_group_id: str = Field(pattern=_ID)
    checked_against_held_out_cases: bool = False
    checked_against_self_development_evidence: bool = False
    checked_at: datetime | None = None

    @field_validator("checked_at")
    @classmethod
    def checked_time_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("source-isolation timestamp must include a timezone")
        return value


class SourceQualityReview(BaseModel):
    """One independent human judgment of an exact source-quality argument."""

    model_config = _CONFIG

    review_id: str = Field(pattern=_ID)
    item_id: str = Field(pattern=_ID)
    reviewer_id: str = Field(pattern=_ID)
    source_content_sha256: str = Field(pattern=_SHA256)
    quality_evidence_sha256: str = Field(pattern=_SHA256)
    verdict: SourceAdmissionVerdict
    scientific_rigor_supported: bool
    decision_traceability_supported: bool
    transferable_taste_supported: bool
    expertise_scope: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=4_000)
    human_performed: Literal[True] = True
    independent_review: Literal[True] = True
    conflict_cleared: Literal[True] = True
    blinded_to_other_reviews: Literal[True] = True
    blinded_to_downstream_outcomes: Literal[True] = True

    @model_validator(mode="after")
    def verdict_matches_quality_checks(self) -> SourceQualityReview:
        checks = (
            self.scientific_rigor_supported,
            self.decision_traceability_supported,
            self.transferable_taste_supported,
        )
        if self.verdict is SourceAdmissionVerdict.ADMIT and not all(checks):
            raise ValueError("an admitting source-quality review requires every criterion")
        if self.verdict is SourceAdmissionVerdict.REJECT and all(checks):
            raise ValueError("a rejecting source-quality review must name a failed criterion")
        return self


class SourceAdmissionEntry(BaseModel):
    """One audited source and the three independent arguments for admitting it."""

    model_config = _CONFIG

    item_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    curator_id: str = Field(pattern=_ID)
    title: str = Field(min_length=1, max_length=1_000)
    locator: str = Field(min_length=1, max_length=2_000)
    source_content_sha256: str = Field(pattern=_SHA256)
    rights: SourceRightsArgument
    quality: SourceQualityArgument
    isolation: SourceIsolationArgument


class SourceAdmissionProposal(BaseModel):
    """Frozen source population proposed before abstraction or outcome inspection."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    request_id: str = Field(pattern=_ID)
    request_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    content_audit_report: TasteCorpusFileBinding
    content_audit_report_sha256: str = Field(pattern=_SHA256)
    minimum_admitted_sources: int = Field(ge=1, le=10_000)
    held_out_source_group_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    self_development_source_group_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=10_000,
    )
    forbidden_source_content_sha256: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=100_000,
    )
    entries: tuple[SourceAdmissionEntry, ...] = Field(min_length=1, max_length=10_000)
    quality_reviews: tuple[SourceQualityReview, ...] = Field(
        default_factory=tuple,
        max_length=20_000,
    )
    selection_frozen_before_abstraction: Literal[True] = True
    selection_frozen_before_downstream_outcomes: Literal[True] = True
    observed_paper_action_is_not_gold: Literal[True] = True
    processing_performs_no_external_action: Literal[True] = True
    authorizes_projection: Literal[False] = False
    authorizes_ingestion: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def population_and_reviews_are_closed(self) -> SourceAdmissionProposal:
        _require_unique((entry.item_id for entry in self.entries), "source-admission item IDs")
        _require_unique((entry.source_id for entry in self.entries), "source-admission source IDs")
        _require_unique((review.review_id for review in self.quality_reviews), "quality review IDs")
        _require_unique(self.held_out_source_group_ids, "held-out source groups")
        _require_unique(
            self.self_development_source_group_ids,
            "self-development source groups",
        )
        _require_unique(self.forbidden_source_content_sha256, "forbidden source hashes")
        if self.minimum_admitted_sources > len(self.entries):
            raise ValueError("minimum admitted sources exceeds the frozen source population")
        known_items = {entry.item_id for entry in self.entries}
        if any(review.item_id not in known_items for review in self.quality_reviews):
            raise ValueError("source-quality review references an unknown item")
        return self

    @computed_field
    @property
    def proposal_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"proposal_sha256"}))


class SourceAdmissionInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    proposal: SourceAdmissionProposal


class SourceAdmissionFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class SourceAdmissionItemReport(BaseModel):
    model_config = _CONFIG

    item_id: str
    source_id: str
    source_group_id: str
    source_content_sha256: str = Field(pattern=_SHA256)
    audit_binding_verified: bool
    rights_evidence_verified: bool
    rights_supported: bool
    quality_evidence_verified: bool
    dual_independent_quality_review_verified: bool
    source_isolation_evidence_verified: bool
    source_isolation_supported: bool
    disposition: SourceAdmissionVerdict
    blockers: tuple[SourceAdmissionFinding, ...]


class SourceAdmissionReport(BaseModel):
    """Admitted and rejected ledger; never authority to project or execute."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    project_id: str
    request_id: str
    request_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    content_audit_report_sha256: str = Field(pattern=_SHA256)
    frozen_source_count: int = Field(ge=1)
    admitted_source_ids: tuple[str, ...]
    rejected_source_ids: tuple[str, ...]
    minimum_admitted_sources: int = Field(ge=1)
    ready_for_projection_proposal: bool
    items: tuple[SourceAdmissionItemReport, ...]
    blockers: tuple[SourceAdmissionFinding, ...]
    no_source_content_read: Literal[True] = True
    no_external_action_performed: Literal[True] = True
    projection_performed: Literal[False] = False
    ingestion_performed: Literal[False] = False
    model_calls_performed: Literal[False] = False
    human_recruitment_performed: Literal[False] = False
    experiment_performed: Literal[False] = False
    authorizes_projection: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


def load_source_admission_proposal(path: str | Path) -> SourceAdmissionInspection:
    resolved, raw, payload = _load_mapping(path, "source-admission proposal")
    recorded_hash = payload.pop("proposal_sha256", None)
    proposal = SourceAdmissionProposal.model_validate(payload)
    if recorded_hash is not None and recorded_hash != proposal.proposal_sha256:
        raise ValueError("source-admission proposal hash mismatch")
    return SourceAdmissionInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        proposal=proposal,
    )


def inspect_source_admission(
    inspection: SourceAdmissionInspection,
    *,
    evidence_root: str | Path,
) -> SourceAdmissionReport:
    """Compile rights, quality, and isolation evidence without reading source bodies."""

    root = Path(evidence_root).resolve(strict=True)
    proposal = inspection.proposal
    global_findings: list[SourceAdmissionFinding] = []
    audit = _load_bound_audit(proposal, root, global_findings)
    audit_items = {item.item_id: item for item in audit.items} if audit is not None else {}
    proposed_ids = {entry.item_id for entry in proposal.entries}
    if audit is not None and proposed_ids != set(audit_items):
        _add(
            global_findings,
            "audited_population_mismatch",
            "the admission population must retain every audited source exactly once",
        )
    if audit is not None and not audit.ready_for_source_admission_proposal:
        _add(
            global_findings,
            "content_audit_not_ready",
            "the bound content audit did not clear source-admission proposal readiness",
        )

    reviews_by_item: dict[str, list[SourceQualityReview]] = defaultdict(list)
    for review in proposal.quality_reviews:
        reviews_by_item[review.item_id].append(review)
    forbidden_groups = {
        *proposal.held_out_source_group_ids,
        *proposal.self_development_source_group_ids,
    }
    forbidden_hashes = set(proposal.forbidden_source_content_sha256)
    item_reports: list[SourceAdmissionItemReport] = []
    for entry in proposal.entries:
        findings: list[SourceAdmissionFinding] = []
        audited = audit_items.get(entry.item_id)
        audit_verified = bool(
            audited is not None
            and audited.exact_bytes_verified
            and audited.observed_sha256 == entry.source_content_sha256
        )
        if not audit_verified:
            _add(findings, "audit_binding_failed", "source bytes do not match the audit item")

        rights_evidence = _binding_verified(entry.rights.evidence, root)
        rights_supported = bool(
            rights_evidence
            and entry.rights.license_id
            and entry.rights.attribution
            and entry.rights.permits_research_analysis
            and entry.rights.permits_derived_abstraction
            and entry.rights.pre_body_screen_consistent
        )
        if not rights_supported:
            _add(findings, "rights_not_supported", "rights or attribution evidence is incomplete")

        quality_evidence = _binding_verified(entry.quality.evidence, root)
        if not quality_evidence:
            _add(findings, "quality_evidence_failed", "source-quality evidence is unavailable")
        reviews = reviews_by_item[entry.item_id]
        reviewer_ids = {review.reviewer_id for review in reviews}
        expected_quality_sha = entry.quality.evidence.sha256 if entry.quality.evidence else None
        review_verified = bool(
            quality_evidence
            and len(reviews) == 2
            and len(reviewer_ids) == 2
            and entry.curator_id not in reviewer_ids
            and all(
                review.verdict is SourceAdmissionVerdict.ADMIT
                and review.source_content_sha256 == entry.source_content_sha256
                and review.quality_evidence_sha256 == expected_quality_sha
                for review in reviews
            )
            and entry.quality.quality_tier
            and entry.quality.primary_scientific_record
            and entry.quality.decision_process_observable
            and entry.quality.quality_rationale
        )
        if not review_verified:
            _add(
                findings,
                "dual_quality_review_failed",
                "exactly two independent admitting quality reviews are required",
            )

        isolation_evidence = _binding_verified(entry.isolation.evidence, root)
        isolation_supported = bool(
            isolation_evidence
            and entry.isolation.checked_against_held_out_cases
            and entry.isolation.checked_against_self_development_evidence
            and entry.isolation.checked_at is not None
            and entry.isolation.source_group_id not in forbidden_groups
            and entry.source_content_sha256 not in forbidden_hashes
        )
        if not isolation_supported:
            _add(
                findings,
                "source_isolation_failed",
                "source-group or content isolation from held-out/self evidence failed",
            )
        disposition = (
            SourceAdmissionVerdict.ADMIT
            if audit_verified and rights_supported and review_verified and isolation_supported
            else SourceAdmissionVerdict.REJECT
        )
        item_reports.append(
            SourceAdmissionItemReport(
                item_id=entry.item_id,
                source_id=entry.source_id,
                source_group_id=entry.isolation.source_group_id,
                source_content_sha256=entry.source_content_sha256,
                audit_binding_verified=audit_verified,
                rights_evidence_verified=rights_evidence,
                rights_supported=rights_supported,
                quality_evidence_verified=quality_evidence,
                dual_independent_quality_review_verified=review_verified,
                source_isolation_evidence_verified=isolation_evidence,
                source_isolation_supported=isolation_supported,
                disposition=disposition,
                blockers=tuple(findings),
            )
        )

    admitted = tuple(
        item.source_id for item in item_reports if item.disposition is SourceAdmissionVerdict.ADMIT
    )
    rejected = tuple(
        item.source_id for item in item_reports if item.disposition is SourceAdmissionVerdict.REJECT
    )
    ready = not global_findings and len(admitted) >= proposal.minimum_admitted_sources
    return SourceAdmissionReport(
        proposal_id=proposal.proposal_id,
        proposal_sha256=proposal.proposal_sha256,
        project_id=proposal.project_id,
        request_id=proposal.request_id,
        request_sha256=proposal.request_sha256,
        receipt_sha256=proposal.receipt_sha256,
        content_audit_report_sha256=proposal.content_audit_report_sha256,
        frozen_source_count=len(proposal.entries),
        admitted_source_ids=admitted,
        rejected_source_ids=rejected,
        minimum_admitted_sources=proposal.minimum_admitted_sources,
        ready_for_projection_proposal=ready,
        items=tuple(item_reports),
        blockers=tuple(global_findings),
    )


def save_source_admission_report(report: SourceAdmissionReport, path: str | Path) -> Path:
    return _write_new_json(path, report.model_dump_json(indent=2) + "\n")


def _load_bound_audit(
    proposal: SourceAdmissionProposal,
    root: Path,
    findings: list[SourceAdmissionFinding],
) -> JsonContentAuditReport | None:
    binding = proposal.content_audit_report
    path = _resolve_binding(binding, root)
    if path is None:
        _add(findings, "content_audit_binding_failed", "content-audit file binding failed")
        return None
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("audit report is not an object")
        recorded_hash = payload.pop("report_sha256", None)
        report = JsonContentAuditReport.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError):
        _add(findings, "content_audit_invalid", "content-audit report could not be verified")
        return None
    if recorded_hash != report.report_sha256:
        _add(findings, "content_audit_self_hash_failed", "content-audit self hash differs")
        return None
    expected = (
        proposal.project_id,
        proposal.request_id,
        proposal.request_sha256,
        proposal.receipt_sha256,
        proposal.content_audit_report_sha256,
    )
    observed = (
        report.project_id,
        report.request_id,
        report.request_sha256,
        report.receipt_sha256,
        report.report_sha256,
    )
    if observed != expected:
        _add(findings, "content_audit_identity_drift", "content-audit identities have drifted")
        return None
    return report


def _binding_verified(binding: TasteCorpusFileBinding | None, root: Path) -> bool:
    return binding is not None and _resolve_binding(binding, root) is not None


def _resolve_binding(binding: TasteCorpusFileBinding, root: Path) -> Path | None:
    candidate = Path(binding.path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    unresolved = root / candidate
    relative = unresolved.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            return None
    path = unresolved.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_EVIDENCE_BYTES:
        return None
    return path if hashlib.sha256(path.read_bytes()).hexdigest() == binding.sha256 else None


def _load_mapping(path: str | Path, label: str) -> tuple[Path, bytes, dict[str, object]]:
    source = Path(path).resolve(strict=True)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError(f"{label} is not a bounded regular file")
    raw = source.read_bytes()
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"{label} must be valid YAML or JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a mapping")
    return source, raw, payload


def _write_new_json(path: str | Path, text: str) -> Path:
    target = Path(path)
    if target.is_symlink() or target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _require_unique(values: Iterable[str], label: str) -> None:
    observed = tuple(values)
    if len(observed) != len(set(observed)):
        raise ValueError(f"{label} must be unique")


def _add(findings: list[SourceAdmissionFinding], code: str, message: str) -> None:
    findings.append(SourceAdmissionFinding(code=code, message=message))


__all__ = [
    "SourceAdmissionEntry",
    "SourceAdmissionFinding",
    "SourceAdmissionInspection",
    "SourceAdmissionItemReport",
    "SourceAdmissionProposal",
    "SourceAdmissionReport",
    "SourceAdmissionVerdict",
    "SourceIsolationArgument",
    "SourceQualityArgument",
    "SourceQualityReview",
    "SourceRightsArgument",
    "inspect_source_admission",
    "load_source_admission_proposal",
    "save_source_admission_report",
]

"""Human-governed abstraction of source evidence into paired Taste corpora."""

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
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.evaluation.taste_corpus_pair import (
    OutcomeInformationAvailability,
    TasteCorpusEntry,
    TasteCorpusFileBinding,
    TasteCorpusManifest,
    TasteCorpusPairInspection,
    TasteCorpusPairManifest,
    TasteCorpusQualificationQuery,
    TasteCorpusRelation,
    inspect_taste_corpus_pair,
    save_taste_corpus_pair_report,
)
from scitaste.taste.semantic_models import (
    GROUNDED_TASTE_ABSTRACTION_NODE,
    TASTE_ABSTRACTION_NODE,
    GroundedTasteCaseAbstraction,
    TasteAbstractionInput,
    TasteCaseAbstraction,
    validate_grounded_abstraction_against_projection,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_PACKAGE_BYTES = 16 * 1_048_576
_MAX_SOURCE_BYTES = 64 * 1_048_576


class TasteAbstractionOrigin(StrEnum):
    HUMAN_AUTHORED = "human-authored"
    MODEL_ASSISTED = "model-assisted"


class TasteAbstractionReviewRole(StrEnum):
    PRIMARY = "primary"
    ADJUDICATOR = "adjudicator"


class TasteAbstractionReviewerKind(StrEnum):
    HUMAN = "human"
    AI = "ai"


class TasteAbstractionVerdict(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


class TasteSourceRecord(BaseModel):
    """One frozen high-quality source selected before abstraction review."""

    model_config = _CONFIG

    source_id: str = Field(pattern=_ID)
    pair_slot_id: str = Field(pattern=_ID)
    relation: TasteCorpusRelation
    stage: str = Field(min_length=1, max_length=100)
    decision_role: str = Field(min_length=1, max_length=300)
    source_group: str = Field(pattern=_ID)
    artifact: TasteCorpusFileBinding
    abstraction_input: TasteCorpusFileBinding | None = None
    quality_evidence: TasteCorpusFileBinding
    quality_tier: str = Field(pattern=_ID)
    quality_rationale: str = Field(min_length=1, max_length=4_000)
    source_type: str = Field(min_length=1, max_length=200)
    locator: str = Field(min_length=1, max_length=2_000)
    title: str = Field(min_length=1, max_length=1_000)
    accessed_at: datetime
    license_id: str = Field(min_length=1, max_length=200)
    license_url: str | None = Field(default=None, max_length=2_000)
    redistributable: bool
    personal_data_removed: Literal[True] = True
    domain_tags: tuple[str, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def domains_are_bounded_and_unique(self) -> TasteSourceRecord:
        if len(self.domain_tags) != len(set(item.casefold() for item in self.domain_tags)):
            raise ValueError("Taste source domain tags must be unique")
        if any(not item or len(item) > 200 for item in self.domain_tags):
            raise ValueError("Taste source domain tags must be bounded non-empty strings")
        return self


class TasteAbstractionCandidate(BaseModel):
    """One content-bound transformation proposed for independent human review."""

    model_config = _CONFIG

    candidate_id: str = Field(pattern=_ID)
    source_id: str = Field(pattern=_ID)
    author_id: str = Field(pattern=_ID)
    origin: TasteAbstractionOrigin
    derivation_method: str = Field(min_length=1, max_length=4_000)
    abstraction: GroundedTasteCaseAbstraction | TasteCaseAbstraction
    model_trace: TasteCorpusFileBinding | None = None

    @model_validator(mode="after")
    def assistance_trace_matches_origin(self) -> TasteAbstractionCandidate:
        if self.origin is TasteAbstractionOrigin.MODEL_ASSISTED and self.model_trace is None:
            raise ValueError("model-assisted Taste abstraction requires a bound model trace")
        if self.origin is TasteAbstractionOrigin.HUMAN_AUTHORED and self.model_trace is not None:
            raise ValueError("human-authored Taste abstraction cannot declare a model trace")
        return self

    @property
    def semantic_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class TasteAbstractionReview(BaseModel):
    """One condition-blinded human or explicitly non-human abstraction audit."""

    model_config = _CONFIG

    review_id: str = Field(pattern=_ID)
    candidate_id: str = Field(pattern=_ID)
    candidate_sha256: str = Field(pattern=_SHA256)
    reviewer_id: str = Field(pattern=_ID)
    role: TasteAbstractionReviewRole
    verdict: TasteAbstractionVerdict
    source_fidelity_supported: bool
    action_grounding_supported: bool
    principle_generalization_supported: bool
    scientific_value_supported: bool
    outcome_handling_supported: bool
    grounding_trace_supported: bool | None = None
    transfer_boundary_supported: bool | None = None
    expertise_scope: str = Field(min_length=1, max_length=1_000)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=4_000)
    reviewer_kind: TasteAbstractionReviewerKind = TasteAbstractionReviewerKind.HUMAN
    human_performed: bool = True
    not_human_review: bool = False
    model_identifier: str | None = Field(default=None, max_length=500)
    raw_review_sha256: str | None = Field(default=None, pattern=_SHA256)
    conflict_cleared: Literal[True] = True
    independent_review: Literal[True] = True
    blinded_to_other_reviews: Literal[True] = True
    relation_label_blinded: Literal[True] = True

    @model_validator(mode="after")
    def verdict_matches_criteria(self) -> TasteAbstractionReview:
        checks = (
            self.source_fidelity_supported,
            self.action_grounding_supported,
            self.principle_generalization_supported,
            self.scientific_value_supported,
            self.outcome_handling_supported,
        )
        if self.verdict is TasteAbstractionVerdict.ACCEPT and not all(checks):
            raise ValueError("accepted Taste abstraction review requires every criterion")
        if self.verdict is TasteAbstractionVerdict.REJECT and all(checks):
            raise ValueError("rejected Taste abstraction review must identify a failed criterion")
        if self.reviewer_kind is TasteAbstractionReviewerKind.HUMAN:
            if (
                not self.human_performed
                or self.not_human_review
                or self.model_identifier is not None
                or self.raw_review_sha256 is not None
            ):
                raise ValueError("human Taste review carries inconsistent provenance")
        elif (
            self.human_performed
            or not self.not_human_review
            or not self.model_identifier
            or self.raw_review_sha256 is None
        ):
            raise ValueError("AI Taste review requires model and raw-response provenance")
        return self


class TasteCorpusCurationPackage(BaseModel):
    """Frozen source selection, abstractions, and independent verification."""

    model_config = _CONFIG

    schema_version: Literal["1.1", "1.2", "1.3"] = "1.1"
    package_id: str = Field(pattern=_ID)
    task_id: str = Field(pattern=_ID)
    task_domain_tags: tuple[str, ...] = Field(min_length=1, max_length=20)
    held_out_source_groups: tuple[str, ...] = Field(min_length=1, max_length=100)
    forbidden_source_content_sha256: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=10_000,
    )
    provenance_tier: str = Field(pattern=_ID)
    curation_tier: Literal[
        "dual-human-verified",
        "grounded-dual-human-verified",
        "grounded-dual-ai-reviewed",
    ] = "dual-human-verified"
    outcome_information_availability: OutcomeInformationAvailability
    source_selection_frozen: Literal[True] = True
    sources: tuple[TasteSourceRecord, ...] = Field(min_length=2, max_length=10_000)
    candidates: tuple[TasteAbstractionCandidate, ...] = Field(
        min_length=2,
        max_length=10_000,
    )
    historical_model_invocation_count: int = Field(default=0, ge=0, le=10_000)
    reviews: tuple[TasteAbstractionReview, ...] = Field(min_length=4, max_length=100_000)
    qualification_queries: tuple[TasteCorpusQualificationQuery, ...] = Field(
        min_length=1,
        max_length=100,
    )
    package_processing_performs_no_external_action: Literal[True] = True
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def identities_and_pair_slots_are_closed(self) -> TasteCorpusCurationPackage:
        _require_unique((item.source_id for item in self.sources), "source IDs")
        _require_unique((item.candidate_id for item in self.candidates), "candidate IDs")
        _require_unique((item.abstraction.case_id for item in self.candidates), "case IDs")
        _require_unique((item.review_id for item in self.reviews), "review IDs")
        _require_unique((item.query_id for item in self.qualification_queries), "query IDs")
        for label, values in (
            ("task domains", self.task_domain_tags),
            ("held-out source groups", self.held_out_source_groups),
            ("forbidden content hashes", self.forbidden_source_content_sha256),
        ):
            _require_unique(values, label)
        if any(not item or len(item) > 200 for item in self.task_domain_tags):
            raise ValueError("Taste curation task domains must be bounded non-empty strings")
        if any(source.quality_tier != self.provenance_tier for source in self.sources):
            raise ValueError("Taste source quality tiers must match the package provenance tier")
        expected_domains = {item.casefold() for item in self.task_domain_tags}
        if any(
            {item.casefold() for item in query.query.domain_tags} != expected_domains
            for query in self.qualification_queries
        ):
            raise ValueError("Taste qualification queries must bind the exact task domains")
        known_sources = {item.source_id for item in self.sources}
        source_by_id = {item.source_id: item for item in self.sources}
        candidate_sources = [item.source_id for item in self.candidates]
        if set(candidate_sources) != known_sources or len(candidate_sources) != len(known_sources):
            raise ValueError("Taste curation requires exactly one candidate per source")
        known_candidates = {item.candidate_id for item in self.candidates}
        if any(item.candidate_id not in known_candidates for item in self.reviews):
            raise ValueError("Taste curation reviews must reference known candidates")
        if any(
            candidate.origin is TasteAbstractionOrigin.MODEL_ASSISTED
            and source_by_id[candidate.source_id].abstraction_input is None
            for candidate in self.candidates
        ):
            raise ValueError("model-assisted Taste abstraction requires a bound source projection")
        review_kinds = {item.reviewer_kind for item in self.reviews}
        if len(review_kinds) != 1:
            raise ValueError("one Taste curation package cannot mix human and AI reviews")
        if self.schema_version == "1.1":
            if review_kinds != {TasteAbstractionReviewerKind.HUMAN}:
                raise ValueError("legacy Taste curation requires human review")
        if self.schema_version in {"1.2", "1.3"}:
            expected_tier = {
                "1.2": "grounded-dual-human-verified",
                "1.3": "grounded-dual-ai-reviewed",
            }[self.schema_version]
            expected_kind = {
                "1.2": TasteAbstractionReviewerKind.HUMAN,
                "1.3": TasteAbstractionReviewerKind.AI,
            }[self.schema_version]
            if self.curation_tier != expected_tier or review_kinds != {expected_kind}:
                raise ValueError(
                    "Taste curation schema, tier, and reviewer provenance differ"
                )
            if any(
                not isinstance(candidate.abstraction, GroundedTasteCaseAbstraction)
                for candidate in self.candidates
            ):
                raise ValueError("formal Taste curation requires grounded abstractions")
            if any(source.abstraction_input is None for source in self.sources):
                raise ValueError("formal Taste curation requires every source projection")
        observed_model_invocations = sum(
            candidate.origin is TasteAbstractionOrigin.MODEL_ASSISTED
            for candidate in self.candidates
        )
        if self.historical_model_invocation_count != observed_model_invocations:
            raise ValueError(
                "historical_model_invocation_count must equal the number of "
                "model-assisted Taste candidates"
            )
        slots: dict[TasteCorpusRelation, set[str]] = defaultdict(set)
        for source in self.sources:
            if source.pair_slot_id in slots[source.relation]:
                raise ValueError("Taste curation pair slots must be unique within each arm")
            slots[source.relation].add(source.pair_slot_id)
        if set(slots) != {TasteCorpusRelation.MATCHED, TasteCorpusRelation.MISMATCHED}:
            raise ValueError("Taste curation requires matched and mismatched source arms")
        if slots[TasteCorpusRelation.MATCHED] != slots[TasteCorpusRelation.MISMATCHED]:
            raise ValueError("Taste curation arms must contain identical pair slots")
        return self

    @property
    def semantic_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        if self.schema_version in {"1.1", "1.2"}:
            legacy_only_fields = {
                "reviewer_kind",
                "human_performed",
                "not_human_review",
                "model_identifier",
                "raw_review_sha256",
            }
            payload["reviews"] = [
                {
                    key: value
                    for key, value in review.items()
                    if key not in legacy_only_fields
                }
                for review in payload["reviews"]
            ]
        return _canonical_sha256(payload)


class TasteCorpusCurationInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    package: TasteCorpusCurationPackage


class TasteCorpusCurationFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class TasteCorpusCurationReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    package_id: str
    package_sha256: str = Field(pattern=_SHA256)
    source_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    historical_model_invocation_count: int = Field(ge=0)
    grounded_candidate_count: int = Field(ge=0)
    primary_review_count: int = Field(ge=0)
    adjudication_count: int = Field(ge=0)
    source_bindings_verified: bool
    quality_evidence_verified: bool
    abstraction_input_bindings_verified: bool
    model_trace_bindings_verified: bool
    grounding_traces_verified: bool
    transfer_boundaries_verified: bool
    pair_structure_verified: bool
    dual_human_review_verified: bool
    dual_ai_review_verified: bool = False
    reviewer_kind: TasteAbstractionReviewerKind = TasteAbstractionReviewerKind.HUMAN
    human_validity_claim_allowed: bool = True
    accepted_candidate_ids: tuple[str, ...]
    ready_to_materialize: bool
    ready_for_formal_taste_method: bool
    blockers: tuple[TasteCorpusCurationFinding, ...]
    no_external_action_performed: Literal[True] = True
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def review_provenance_is_explicit(self) -> TasteCorpusCurationReport:
        if self.dual_human_review_verified and self.dual_ai_review_verified:
            raise ValueError("Taste curation cannot be both human- and AI-verified")
        if self.reviewer_kind is TasteAbstractionReviewerKind.HUMAN:
            if self.dual_ai_review_verified or not self.human_validity_claim_allowed:
                raise ValueError("human Taste curation report has inconsistent provenance")
        elif self.dual_human_review_verified or self.human_validity_claim_allowed:
            raise ValueError("AI Taste curation report cannot claim human validity")
        return self


class TasteCorpusMaterializationReceipt(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    package_id: str
    package_sha256: str = Field(pattern=_SHA256)
    matched_corpus_path: str
    matched_corpus_sha256: str = Field(pattern=_SHA256)
    placebo_corpus_path: str
    placebo_corpus_sha256: str = Field(pattern=_SHA256)
    pair_manifest_path: str
    pair_manifest_sha256: str = Field(pattern=_SHA256)
    qualification_report_path: str
    qualification_report_sha256: str = Field(pattern=_SHA256)
    pair_qualified: Literal[True] = True
    no_external_action_performed: Literal[True] = True
    authorizes_execution: Literal[False] = False


def load_taste_corpus_curation_package(path: str | Path) -> TasteCorpusCurationInspection:
    source = Path(path)
    raw = _read_bounded_file(source, root=None, maximum_bytes=_MAX_PACKAGE_BYTES)
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError("Taste corpus curation package must be valid YAML or JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Taste corpus curation package must contain a mapping")
    payload = _migrate_curation_payload(payload)
    return TasteCorpusCurationInspection(
        path=source.resolve(strict=True),
        file_sha256=hashlib.sha256(raw).hexdigest(),
        package=TasteCorpusCurationPackage.model_validate(payload),
    )


def _migrate_curation_payload(payload: dict[object, object]) -> dict[object, object]:
    """Migrate the ambiguous v1.0 no-action fields into explicit v1.1 semantics."""

    if payload.get("schema_version") != "1.0":
        return payload
    migrated = dict(payload)
    legacy_action_fields = (
        "no_dataset_download",
        "no_api_call",
        "no_ssh",
        "no_gpu_or_model_execution",
        "no_experiment_execution",
    )
    invalid = [name for name in legacy_action_fields if migrated.get(name, True) is not True]
    if invalid:
        raise ValueError("Taste curation v1.0 action flags must be true to migrate")
    for name in legacy_action_fields:
        migrated.pop(name, None)
    candidates = migrated.get("candidates")
    model_count = (
        sum(
            isinstance(item, dict) and item.get("origin") == "model-assisted" for item in candidates
        )
        if isinstance(candidates, list)
        else 0
    )
    migrated["schema_version"] = "1.1"
    migrated.setdefault("historical_model_invocation_count", model_count)
    migrated["package_processing_performs_no_external_action"] = True
    return migrated


def build_taste_abstraction_input(
    source: TasteSourceRecord,
    *,
    candidate_id: str,
    case_id: str,
    outcome_information_availability: OutcomeInformationAvailability,
    evidence_root: str | Path,
) -> TasteAbstractionInput:
    """Project one bound source into the exact relation-blind model-node input."""

    if source.abstraction_input is None:
        raise ValueError("Taste source has no bound abstraction input")
    root = Path(evidence_root).resolve(strict=True)
    raw = _read_bounded_file(
        Path(source.abstraction_input.path),
        root=root,
        maximum_bytes=_MAX_SOURCE_BYTES,
    )
    if hashlib.sha256(raw).hexdigest() != source.abstraction_input.sha256:
        raise ValueError("Taste abstraction input binding hash mismatch")
    try:
        projection = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Taste abstraction input must be UTF-8 text") from exc
    return TasteAbstractionInput(
        source_id=source.source_id,
        candidate_id=candidate_id,
        case_id=case_id,
        stage=source.stage,
        decision_role=source.decision_role,
        source_projection=projection,
        source_projection_sha256=source.abstraction_input.sha256,
        domain_tags=source.domain_tags,
        outcome_information_availability=outcome_information_availability.value,
    )


def inspect_taste_corpus_curation(
    inspection: TasteCorpusCurationInspection,
    *,
    evidence_root: str | Path,
) -> TasteCorpusCurationReport:
    """Inspect frozen sources and provenance-explicit reviews without external actions."""

    package = inspection.package
    root = Path(evidence_root).resolve(strict=True)
    blockers: list[TasteCorpusCurationFinding] = []
    sources_verified = True
    quality_verified = True
    abstraction_inputs_verified = True
    traces_verified = True
    grounding_verified = True
    source_by_id = {item.source_id: item for item in package.sources}
    candidate_by_id = {item.candidate_id: item for item in package.candidates}
    grounded_count = sum(
        isinstance(item.abstraction, GroundedTasteCaseAbstraction) for item in package.candidates
    )

    for source in package.sources:
        if not _binding_matches(
            source.artifact,
            root=root,
            blockers=blockers,
            owner=source.source_id,
        ):
            sources_verified = False
        if not _binding_matches(
            source.quality_evidence,
            root=root,
            blockers=blockers,
            owner=f"{source.source_id}:quality",
        ):
            quality_verified = False
    for candidate in package.candidates:
        source = source_by_id[candidate.source_id]
        needs_projection = candidate.origin is TasteAbstractionOrigin.MODEL_ASSISTED or isinstance(
            candidate.abstraction,
            GroundedTasteCaseAbstraction,
        )
        if needs_projection:
            if source.abstraction_input is None:
                abstraction_inputs_verified = False
                _add(
                    blockers,
                    "source:abstraction_input_missing",
                    source.source_id,
                )
            elif not _binding_matches(
                source.abstraction_input,
                root=root,
                blockers=blockers,
                owner=f"{source.source_id}:abstraction-input",
            ):
                abstraction_inputs_verified = False
        if isinstance(candidate.abstraction, GroundedTasteCaseAbstraction):
            try:
                grounding_input = build_taste_abstraction_input(
                    source,
                    candidate_id=candidate.candidate_id,
                    case_id=candidate.abstraction.case_id,
                    outcome_information_availability=package.outcome_information_availability,
                    evidence_root=root,
                )
            except (OSError, ValueError) as exc:
                grounding_verified = False
                _add(
                    blockers,
                    "grounding:source_projection_invalid",
                    f"{candidate.candidate_id}: {exc}",
                )
            else:
                for finding in validate_grounded_abstraction_against_projection(
                    candidate.abstraction,
                    grounding_input,
                ):
                    grounding_verified = False
                    _add(
                        blockers,
                        "grounding:trace_invalid",
                        f"{candidate.candidate_id}: {finding}",
                    )
        if candidate.origin is TasteAbstractionOrigin.MODEL_ASSISTED:
            if not _inspect_model_trace(
                candidate,
                source=source,
                outcome_information_availability=package.outcome_information_availability,
                root=root,
                blockers=blockers,
            ):
                traces_verified = False

    pair_structure = _inspect_pair_structure(package, source_by_id, blockers)
    accepted = _inspect_reviews(package, candidate_by_id, blockers)
    review_verified = len(accepted) == len(package.candidates) and not any(
        item.code.startswith("review:") for item in blockers
    )
    all_grounded = grounded_count == len(package.candidates)
    reviewer_kind = package.reviews[0].reviewer_kind
    transfer_verified = all_grounded and all(
        bool(candidate.abstraction.transfer_boundary.applies_when)
        and bool(candidate.abstraction.transfer_boundary.fails_when)
        and bool(candidate.abstraction.transfer_boundary.counterfactual_probe)
        for candidate in package.candidates
        if isinstance(candidate.abstraction, GroundedTasteCaseAbstraction)
    )
    formal_method_ready = (
        package.schema_version in {"1.2", "1.3"}
        and all_grounded
        and grounding_verified
        and transfer_verified
        and review_verified
    )
    ready = (
        sources_verified
        and quality_verified
        and abstraction_inputs_verified
        and traces_verified
        and pair_structure
        and review_verified
        and (formal_method_ready if package.schema_version in {"1.2", "1.3"} else True)
        and not blockers
    )
    return TasteCorpusCurationReport(
        schema_version="1.1",
        package_id=package.package_id,
        package_sha256=package.semantic_sha256,
        source_count=len(package.sources),
        candidate_count=len(package.candidates),
        historical_model_invocation_count=package.historical_model_invocation_count,
        grounded_candidate_count=grounded_count,
        primary_review_count=sum(
            item.role is TasteAbstractionReviewRole.PRIMARY for item in package.reviews
        ),
        adjudication_count=sum(
            item.role is TasteAbstractionReviewRole.ADJUDICATOR for item in package.reviews
        ),
        source_bindings_verified=sources_verified,
        quality_evidence_verified=quality_verified,
        abstraction_input_bindings_verified=abstraction_inputs_verified,
        model_trace_bindings_verified=traces_verified,
        grounding_traces_verified=all_grounded and grounding_verified,
        transfer_boundaries_verified=transfer_verified,
        pair_structure_verified=pair_structure,
        dual_human_review_verified=(
            review_verified and reviewer_kind is TasteAbstractionReviewerKind.HUMAN
        ),
        dual_ai_review_verified=(
            review_verified and reviewer_kind is TasteAbstractionReviewerKind.AI
        ),
        reviewer_kind=reviewer_kind,
        human_validity_claim_allowed=(
            reviewer_kind is TasteAbstractionReviewerKind.HUMAN
        ),
        accepted_candidate_ids=tuple(sorted(accepted)),
        ready_to_materialize=ready,
        ready_for_formal_taste_method=formal_method_ready and ready,
        blockers=tuple(blockers),
    )


def materialize_taste_corpus_pair(
    inspection: TasteCorpusCurationInspection,
    *,
    evidence_root: str | Path,
    output_dir: str | Path,
) -> TasteCorpusMaterializationReceipt:
    """Materialize an immutable pair only after curation and retrieval qualification."""

    root = Path(evidence_root).resolve(strict=True)
    report = inspect_taste_corpus_curation(inspection, evidence_root=root)
    if not report.ready_to_materialize:
        codes = ", ".join(item.code for item in report.blockers)
        raise ValueError(f"Taste corpus curation is not ready: {codes}")
    package = inspection.package
    target = _safe_output_dir(output_dir, root=root)
    paths = {
        "matched": target / "matched_corpus.json",
        "placebo": target / "placebo_corpus.json",
        "pair": target / "pair_manifest.json",
        "qualification": target / "qualification_report.json",
    }
    existing = [str(path) for path in paths.values() if path.exists() or path.is_symlink()]
    if existing:
        raise FileExistsError("Taste corpus output is immutable; targets exist: " + repr(existing))

    created: list[Path] = []
    try:
        candidates = {item.source_id: item for item in package.candidates}
        reviews: dict[str, list[TasteAbstractionReview]] = defaultdict(list)
        for item in package.reviews:
            reviews[item.candidate_id].append(item)
        for relation, label in (
            (TasteCorpusRelation.MATCHED, "matched"),
            (TasteCorpusRelation.MISMATCHED, "placebo"),
        ):
            entries = tuple(
                _compile_entry(package, source, candidates[source.source_id], reviews)
                for source in sorted(
                    (item for item in package.sources if item.relation is relation),
                    key=lambda item: item.pair_slot_id,
                )
            )
            corpus = TasteCorpusManifest(
                corpus_id=f"{package.package_id}-{label}",
                task_id=package.task_id,
                relation=relation,
                task_domain_tags=package.task_domain_tags,
                held_out_source_groups=package.held_out_source_groups,
                forbidden_source_content_sha256=package.forbidden_source_content_sha256,
                provenance_tier=package.provenance_tier,
                curation_tier=package.curation_tier,
                outcome_information_availability=package.outcome_information_availability,
                entries=entries,
            )
            _atomic_json(paths[label], corpus.model_dump(mode="json"))
            created.append(paths[label])

        pair = TasteCorpusPairManifest(
            pair_id=f"{package.package_id}-pair",
            authorization_scope="local-static-qualification-only",
            task_id=package.task_id,
            matched_corpus=TasteCorpusFileBinding(
                path=paths["matched"].relative_to(root).as_posix(),
                sha256=_file_sha256(paths["matched"]),
            ),
            placebo_corpus=TasteCorpusFileBinding(
                path=paths["placebo"].relative_to(root).as_posix(),
                sha256=_file_sha256(paths["placebo"]),
            ),
            only_permitted_difference="source_domain_relation",
            qualification_queries=package.qualification_queries,
            zero_retrieval_invalidates_pair=True,
            no_dataset_download=True,
            no_api_call=True,
            no_ssh=True,
            no_gpu_or_model_execution=True,
            no_experiment_execution=True,
            authorizes_execution=False,
        )
        _atomic_json(paths["pair"], pair.model_dump(mode="json"))
        created.append(paths["pair"])
        pair_inspection = TasteCorpusPairInspection(
            path=paths["pair"],
            file_sha256=_file_sha256(paths["pair"]),
            manifest=pair,
        )
        qualification = inspect_taste_corpus_pair(pair_inspection, evidence_root=root)
        if not qualification.qualified:
            codes = ", ".join(item.code for item in qualification.blockers)
            raise ValueError(f"materialized Taste corpus pair did not qualify: {codes}")
        save_taste_corpus_pair_report(qualification, paths["qualification"])
        created.append(paths["qualification"])
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        try:
            target.rmdir()
        except OSError:
            pass
        raise
    return TasteCorpusMaterializationReceipt(
        package_id=package.package_id,
        package_sha256=package.semantic_sha256,
        matched_corpus_path=paths["matched"].relative_to(root).as_posix(),
        matched_corpus_sha256=_file_sha256(paths["matched"]),
        placebo_corpus_path=paths["placebo"].relative_to(root).as_posix(),
        placebo_corpus_sha256=_file_sha256(paths["placebo"]),
        pair_manifest_path=paths["pair"].relative_to(root).as_posix(),
        pair_manifest_sha256=_file_sha256(paths["pair"]),
        qualification_report_path=paths["qualification"].relative_to(root).as_posix(),
        qualification_report_sha256=_file_sha256(paths["qualification"]),
        pair_qualified=True,
    )


def save_taste_corpus_curation_report(
    report: TasteCorpusCurationReport,
    path: str | Path,
) -> Path:
    target = Path(path)
    _atomic_json(target, report.model_dump(mode="json"), allow_existing=True)
    return target


def _inspect_pair_structure(
    package: TasteCorpusCurationPackage,
    source_by_id: dict[str, TasteSourceRecord],
    blockers: list[TasteCorpusCurationFinding],
) -> bool:
    valid = True
    task_domains = {item.casefold() for item in package.task_domain_tags}
    held_out = set(package.held_out_source_groups)
    forbidden = set(package.forbidden_source_content_sha256)
    candidates = {item.source_id: item for item in package.candidates}
    arm_groups: dict[TasteCorpusRelation, set[str]] = defaultdict(set)
    arm_hashes: dict[TasteCorpusRelation, set[str]] = defaultdict(set)
    arm_locators: dict[TasteCorpusRelation, set[str]] = defaultdict(set)
    by_slot: dict[str, dict[TasteCorpusRelation, TasteSourceRecord]] = defaultdict(dict)
    for source in package.sources:
        by_slot[source.pair_slot_id][source.relation] = source
        candidate = candidates[source.source_id]
        abstraction = candidate.abstraction
        source_domains = {item.casefold() for item in source.domain_tags}
        overlaps = bool(task_domains & source_domains)
        expected = source.relation is TasteCorpusRelation.MATCHED
        if overlaps != expected:
            valid = False
            _add(blockers, "pair:domain_relation_invalid", source.source_id)
        if source.source_group in held_out:
            valid = False
            _add(blockers, "pair:held_out_source_group", source.source_id)
        if source.artifact.sha256 in forbidden:
            valid = False
            _add(blockers, "pair:held_out_content_hash", source.source_id)
        if package.outcome_information_availability is OutcomeInformationAvailability.AVAILABLE:
            if not abstraction.outcome_summary:
                valid = False
                _add(blockers, "pair:outcome_summary_missing", candidate.candidate_id)
        elif abstraction.outcome_summary is not None:
            valid = False
            _add(blockers, "pair:withheld_outcome_disclosed", candidate.candidate_id)
        arm_groups[source.relation].add(source.source_group)
        arm_hashes[source.relation].add(source.artifact.sha256)
        arm_locators[source.relation].add(source.locator)

    for slot, arms in by_slot.items():
        matched = arms[TasteCorpusRelation.MATCHED]
        placebo = arms[TasteCorpusRelation.MISMATCHED]
        matched_candidate = candidates[matched.source_id]
        placebo_candidate = candidates[placebo.source_id]
        if (
            matched.stage,
            matched.decision_role,
            len(matched_candidate.abstraction.candidate_actions),
        ) != (
            placebo.stage,
            placebo.decision_role,
            len(placebo_candidate.abstraction.candidate_actions),
        ):
            valid = False
            _add(blockers, "pair:slot_contract_mismatch", slot)

    for label, left, right in (
        (
            "source_group_overlap",
            arm_groups[TasteCorpusRelation.MATCHED],
            arm_groups[TasteCorpusRelation.MISMATCHED],
        ),
        (
            "content_hash_overlap",
            arm_hashes[TasteCorpusRelation.MATCHED],
            arm_hashes[TasteCorpusRelation.MISMATCHED],
        ),
        (
            "locator_overlap",
            arm_locators[TasteCorpusRelation.MATCHED],
            arm_locators[TasteCorpusRelation.MISMATCHED],
        ),
    ):
        overlap = left & right
        if overlap:
            valid = False
            _add(blockers, f"pair:{label}", repr(sorted(overlap)))
    if set(source_by_id) != set(candidates):
        valid = False
        _add(blockers, "pair:source_candidate_identity_mismatch", package.package_id)
    return valid


def _inspect_reviews(
    package: TasteCorpusCurationPackage,
    candidate_by_id: dict[str, TasteAbstractionCandidate],
    blockers: list[TasteCorpusCurationFinding],
) -> set[str]:
    grouped: dict[str, list[TasteAbstractionReview]] = defaultdict(list)
    for review in package.reviews:
        grouped[review.candidate_id].append(review)
    accepted: set[str] = set()
    for candidate_id, candidate in candidate_by_id.items():
        reviews = grouped[candidate_id]
        primaries = [item for item in reviews if item.role is TasteAbstractionReviewRole.PRIMARY]
        adjudicators = [
            item for item in reviews if item.role is TasteAbstractionReviewRole.ADJUDICATOR
        ]
        expected_hash = candidate.semantic_sha256
        if any(item.candidate_sha256 != expected_hash for item in reviews):
            _add(blockers, "review:candidate_hash_mismatch", candidate_id)
        if package.schema_version in {"1.2", "1.3"} and any(
            item.grounding_trace_supported is not True
            or item.transfer_boundary_supported is not True
            for item in reviews
        ):
            _add(
                blockers,
                "review:grounding_or_transfer_not_supported",
                candidate_id,
            )
        reviewer_ids = [item.reviewer_id for item in reviews]
        if len(reviewer_ids) != len(set(reviewer_ids)):
            _add(blockers, "review:reviewer_reused", candidate_id)
        if candidate.author_id in reviewer_ids:
            _add(blockers, "review:author_is_reviewer", candidate_id)
        if len(primaries) != 2:
            _add(blockers, "review:requires_two_primaries", candidate_id)
            continue
        primary_verdicts = {item.verdict for item in primaries}
        if len(primary_verdicts) == 1:
            if adjudicators:
                _add(blockers, "review:unnecessary_adjudicator", candidate_id)
            if primary_verdicts == {TasteAbstractionVerdict.ACCEPT}:
                accepted.add(candidate_id)
            else:
                _add(blockers, "review:candidate_rejected", candidate_id)
            continue
        if len(adjudicators) != 1:
            _add(blockers, "review:split_requires_one_adjudicator", candidate_id)
            continue
        if adjudicators[0].verdict is TasteAbstractionVerdict.ACCEPT:
            accepted.add(candidate_id)
        else:
            _add(blockers, "review:adjudicator_rejected", candidate_id)
    extra = set(grouped) - set(candidate_by_id)
    if extra:
        _add(blockers, "review:unknown_candidate", repr(sorted(extra)))
    return accepted


def _compile_entry(
    package: TasteCorpusCurationPackage,
    source: TasteSourceRecord,
    candidate: TasteAbstractionCandidate,
    reviews: dict[str, list[TasteAbstractionReview]],
) -> TasteCorpusEntry:
    abstraction = candidate.abstraction
    grounded = abstraction if isinstance(abstraction, GroundedTasteCaseAbstraction) else None
    grounding_sha256 = (
        _canonical_sha256(
            {
                "grounding": [item.model_dump(mode="json") for item in grounded.grounding],
                "transfer_boundary": grounded.transfer_boundary.model_dump(mode="json"),
            }
        )
        if grounded is not None
        else None
    )
    accepted_reviews = sorted(
        item.review_id
        for item in reviews[candidate.candidate_id]
        if item.verdict is TasteAbstractionVerdict.ACCEPT
    )
    reviewer_kind = package.reviews[0].reviewer_kind
    provenance = ProvenanceRecord(
        source_type=source.source_type,
        locator=source.locator,
        title=source.title,
        content_hash=source.artifact.sha256,
        accessed_at=source.accessed_at,
        license_id=source.license_id,
        license_url=source.license_url,
        access_scope="frozen-source-abstraction",
        derivation_method=(
            f"{candidate.derivation_method} Independently {reviewer_kind.value}-reviewed "
            f"under {package.package_id}."
        ),
        redistributable=source.redistributable,
        personal_data_removed=source.personal_data_removed,
        metadata={
            "source_group": source.source_group,
            "source_id": source.source_id,
            "pair_slot_id": source.pair_slot_id,
            "candidate_id": candidate.candidate_id,
            "candidate_sha256": candidate.semantic_sha256,
            "accepted_review_ids": accepted_reviews,
            "quality_evidence_path": source.quality_evidence.path,
            "quality_evidence_sha256": source.quality_evidence.sha256,
            "quality_tier": source.quality_tier,
            "quality_rationale": source.quality_rationale,
            "curation_package_id": package.package_id,
            "abstraction_contract": (
                "grounded-contrastive-v1" if grounded is not None else "legacy-summary-v1"
            ),
            "taste_grounding_sha256": grounding_sha256,
            "grounding_targets": (
                [item.target.value for item in grounded.grounding] if grounded is not None else []
            ),
            "deliberately_discarded_details": (
                list(grounded.transfer_boundary.deliberately_discarded_details)
                if grounded is not None
                else []
            ),
        },
    )
    case = TasteCase(
        case_id=abstraction.case_id,
        stage=source.stage,
        context_summary=abstraction.context_summary,
        problem_pattern=abstraction.problem_pattern,
        evidence_state=abstraction.evidence_state,
        reviewer_context=abstraction.reviewer_context,
        candidate_actions=list(abstraction.candidate_actions),
        preferred_action=abstraction.preferred_action,
        rejected_actions=list(abstraction.rejected_actions),
        decision_principle=abstraction.decision_principle,
        why_preferred=abstraction.why_preferred,
        applicability_conditions=(
            list(grounded.transfer_boundary.applies_when) if grounded is not None else []
        ),
        failure_conditions=(
            list(grounded.transfer_boundary.fails_when) if grounded is not None else []
        ),
        counterfactual_probe=(
            grounded.transfer_boundary.counterfactual_probe if grounded is not None else None
        ),
        taste_grounding_sha256=grounding_sha256,
        outcome_summary=abstraction.outcome_summary,
        provenance=[provenance],
        confidence=abstraction.confidence,
        domain_tags=list(source.domain_tags),
        label_basis=(
            "dual_human_verified_external_source"
            if reviewer_kind is TasteAbstractionReviewerKind.HUMAN
            else "dual_ai_reviewed_external_source"
        ),
        extractor_version=(
            "scitaste-grounded-taste-abstraction-v1"
            if grounded is not None
            else "scitaste-taste-abstraction-v1"
        ),
        human_verified=(reviewer_kind is TasteAbstractionReviewerKind.HUMAN),
        retrieval_eligible=True,
    )
    return TasteCorpusEntry(
        pair_slot_id=source.pair_slot_id,
        decision_role=source.decision_role,
        source_group=source.source_group,
        source_content_sha256=source.artifact.sha256,
        case=case,
    )


def _binding_matches(
    binding: TasteCorpusFileBinding,
    *,
    root: Path,
    blockers: list[TasteCorpusCurationFinding],
    owner: str,
) -> bool:
    try:
        raw = _read_bounded_file(Path(binding.path), root=root, maximum_bytes=_MAX_SOURCE_BYTES)
    except (OSError, ValueError) as exc:
        _add(blockers, "source:binding_invalid", f"{owner}: {exc}")
        return False
    observed = hashlib.sha256(raw).hexdigest()
    if observed != binding.sha256:
        _add(blockers, "source:hash_mismatch", owner)
        return False
    return True


def _inspect_model_trace(
    candidate: TasteAbstractionCandidate,
    *,
    source: TasteSourceRecord,
    outcome_information_availability: OutcomeInformationAvailability,
    root: Path,
    blockers: list[TasteCorpusCurationFinding],
) -> bool:
    """Verify that model assistance is an exact accepted runtime ledger entry."""

    assert candidate.model_trace is not None
    assert source.abstraction_input is not None
    start = len(blockers)
    try:
        raw = _read_bounded_file(
            Path(candidate.model_trace.path),
            root=root,
            maximum_bytes=_MAX_SOURCE_BYTES,
        )
    except (OSError, ValueError) as exc:
        _add(blockers, "model_trace:binding_invalid", f"{candidate.candidate_id}: {exc}")
        return False
    if hashlib.sha256(raw).hexdigest() != candidate.model_trace.sha256:
        _add(blockers, "model_trace:file_hash_mismatch", candidate.candidate_id)
        return False

    # Local imports avoid coupling the curation schema to model-node initialization.
    from scitaste.model_nodes.models import NodeResult, NodeResultStatus
    from scitaste.model_nodes.runtime import RuntimeOutcome
    from scitaste.taste.semantic import (
        GroundedTasteAbstractionNode,
        TasteAbstractionNode,
        is_verified_model_generation_entry,
        load_verified_taste_abstraction_ledger,
    )

    try:
        entry, verified_path, verified_raw = load_verified_taste_abstraction_ledger(
            candidate.model_trace.path,
            evidence_root=root,
        )
    except (OSError, ValueError):
        _add(blockers, "model_trace:ledger_invalid", candidate.candidate_id)
        return False
    if verified_path.resolve(strict=True) != (root / candidate.model_trace.path).resolve(
        strict=True
    ):
        _add(blockers, "model_trace:ledger_path_mismatch", candidate.candidate_id)
    if verified_raw != raw:
        _add(blockers, "model_trace:ledger_bytes_mismatch", candidate.candidate_id)
    if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
        _add(blockers, "model_trace:not_accepted", candidate.candidate_id)
        return False
    expected_node_name = (
        GROUNDED_TASTE_ABSTRACTION_NODE
        if isinstance(candidate.abstraction, GroundedTasteCaseAbstraction)
        else TASTE_ABSTRACTION_NODE
    )
    if entry.intent.node_name != expected_node_name:
        _add(blockers, "model_trace:wrong_node", candidate.candidate_id)
    if not is_verified_model_generation_entry(entry):
        _add(blockers, "model_trace:not_actual_model_assistance", candidate.candidate_id)

    try:
        node_input = TasteAbstractionInput.model_validate_json(
            json.dumps(entry.intent.node_input, ensure_ascii=False, allow_nan=False),
            strict=True,
        )
    except ValueError:
        _add(blockers, "model_trace:input_invalid", candidate.candidate_id)
        return False
    try:
        expected_input = build_taste_abstraction_input(
            source,
            candidate_id=candidate.candidate_id,
            case_id=candidate.abstraction.case_id,
            outcome_information_availability=outcome_information_availability,
            evidence_root=root,
        )
    except (OSError, ValueError):
        _add(blockers, "model_trace:source_projection_invalid", candidate.candidate_id)
        return False
    if node_input != expected_input:
        _add(blockers, "model_trace:source_or_identity_mismatch", candidate.candidate_id)

    context = entry.intent.context
    if (
        context.stage != source.stage
        or context.state_snapshot_id != source.abstraction_input.sha256
        or context.evidence_ids != [source.source_id]
        or context.claim_ids
        or context.section_ids
        or context.candidate_actions
        or context.metadata
    ):
        _add(blockers, "model_trace:context_mismatch", candidate.candidate_id)
    if (
        entry.intent.policy.allowed_tool_names
        or entry.intent.policy.allowed_action_types
        or entry.intent.profile.admission.allowed_tool_names
        or entry.intent.profile.admission.max_tool_call_proposals != 0
    ):
        _add(blockers, "model_trace:authority_not_empty", candidate.candidate_id)

    output_type = (
        GroundedTasteCaseAbstraction
        if expected_node_name == GROUNDED_TASTE_ABSTRACTION_NODE
        else TasteCaseAbstraction
    )
    node_type = (
        GroundedTasteAbstractionNode
        if expected_node_name == GROUNDED_TASTE_ABSTRACTION_NODE
        else TasteAbstractionNode
    )
    result_type = NodeResult[output_type]
    try:
        result = result_type.model_validate_json(
            json.dumps(entry.result, ensure_ascii=False, allow_nan=False),
            strict=True,
        )
    except ValueError:
        _add(blockers, "model_trace:result_invalid", candidate.candidate_id)
        return False
    if (
        result.status is not NodeResultStatus.ACCEPTED
        or result.node_name != expected_node_name
        or result.policy_id != entry.intent.policy.policy_id
        or result.proposal != candidate.abstraction
        or result.request.input_payload
        != {
            "context": context.model_dump(mode="json"),
            "input": node_input.model_dump(mode="json"),
        }
        or result.request.node_name != expected_node_name
        or result.request.prompt_version != node_type.prompt_version
        or result.request.system_instruction != node_type.system_instruction
        or result.request.output_schema != output_type.model_json_schema(mode="validation")
        or result.request.fingerprint != entry.request_fingerprint
        or result.request.fingerprint != entry.intent.expected_request_fingerprint
        or result.request.policy_fingerprint != entry.intent.policy.fingerprint
        or result.request.profile_fingerprint != entry.intent.profile.fingerprint
        or result.request.expected_backend != entry.intent.policy.expected_backend
        or result.request.expected_model != entry.intent.policy.expected_model
        or result.response.backend != entry.intent.policy.expected_backend
        or result.response.model != entry.intent.policy.expected_model
        or result.response.request_fingerprint != result.request.fingerprint
        or result.response.raw_response is None
        or result.response.tool_calls
        or entry.recording_sha256 is None
        or entry.replayed
    ):
        _add(blockers, "model_trace:proposal_mismatch", candidate.candidate_id)
    return len(blockers) == start


def _read_bounded_file(path: Path, *, root: Path | None, maximum_bytes: int) -> bytes:
    candidate = path if root is None or path.is_absolute() else root / path
    resolved = candidate.resolve(strict=True)
    if candidate.is_symlink() or not resolved.is_file():
        raise ValueError("bound evidence must be a regular non-symlink file")
    if root is not None:
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("bound evidence escapes the evidence root") from exc
    size = resolved.stat().st_size
    if size < 1 or size > maximum_bytes:
        raise ValueError("bound evidence has invalid size")
    return resolved.read_bytes()


def _safe_output_dir(output_dir: str | Path, *, root: Path) -> Path:
    raw = Path(output_dir)
    candidate = raw if raw.is_absolute() else root / raw
    if candidate.is_symlink():
        raise ValueError("Taste corpus output directory cannot be a symlink")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Taste corpus output directory escapes the evidence root") from exc
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _atomic_json(path: Path, value: object, *, allow_existing: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not allow_existing and (path.exists() or path.is_symlink()):
        raise FileExistsError(path)
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _require_unique(values: Iterable[str], label: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"Taste curation {label} must be unique")


def _add(
    blockers: list[TasteCorpusCurationFinding],
    code: str,
    message: str,
) -> None:
    blockers.append(TasteCorpusCurationFinding(code=code, message=message))


__all__ = [
    "GroundedTasteCaseAbstraction",
    "TasteAbstractionCandidate",
    "TasteAbstractionOrigin",
    "TasteAbstractionReview",
    "TasteAbstractionReviewRole",
    "TasteAbstractionReviewerKind",
    "TasteAbstractionVerdict",
    "TasteCaseAbstraction",
    "TasteCorpusCurationFinding",
    "TasteCorpusCurationInspection",
    "TasteCorpusCurationPackage",
    "TasteCorpusCurationReport",
    "TasteCorpusMaterializationReceipt",
    "TasteSourceRecord",
    "build_taste_abstraction_input",
    "inspect_taste_corpus_curation",
    "load_taste_corpus_curation_package",
    "materialize_taste_corpus_pair",
    "save_taste_corpus_curation_report",
]

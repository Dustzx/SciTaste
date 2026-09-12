"""No-run qualification for matched and mismatched Scientific Taste corpora."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.data.models import TasteCase
from scitaste.evaluation.native_condition_preflight import CorpusParityDimension
from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.taste.retriever import (
    TasteDomainRelation,
    TasteQuery,
    retrieve_taste_cases,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_MANIFEST_BYTES = 2 * 1_048_576


class TasteCorpusRelation(StrEnum):
    MATCHED = "task-domain-matched"
    MISMATCHED = "source-disjoint-domain-mismatched"


class OutcomeInformationAvailability(StrEnum):
    AVAILABLE = "available"
    WITHHELD = "withheld"


class TasteCorpusEntry(BaseModel):
    """One precedent plus experimental source identity and pair slot."""

    model_config = _CONFIG

    pair_slot_id: str = Field(pattern=_ID)
    decision_role: str = Field(min_length=1, max_length=300)
    source_group: str = Field(pattern=_ID)
    source_content_sha256: str = Field(pattern=_SHA256)
    case: TasteCase

    @model_validator(mode="after")
    def source_identity_is_bound_to_provenance(self) -> TasteCorpusEntry:
        matching = [
            item for item in self.case.provenance if item.content_hash == self.source_content_sha256
        ]
        if not matching:
            raise ValueError("Taste corpus source hash must occur in case provenance")
        if not any(item.metadata.get("source_group") == self.source_group for item in matching):
            raise ValueError("Taste corpus source group must occur beside the bound source hash")
        return self


class TasteCorpusManifest(BaseModel):
    """One task-specific corpus arm; it never authorizes acquisition or execution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str = Field(pattern=_ID)
    task_id: str = Field(pattern=_ID)
    relation: TasteCorpusRelation
    task_domain_tags: tuple[str, ...] = Field(min_length=1, max_length=20)
    held_out_source_groups: tuple[str, ...] = Field(min_length=1, max_length=100)
    forbidden_source_content_sha256: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=10_000,
    )
    provenance_tier: str = Field(pattern=_ID)
    curation_tier: str = Field(pattern=_ID)
    outcome_information_availability: OutcomeInformationAvailability
    entries: tuple[TasteCorpusEntry, ...] = Field(min_length=1, max_length=10_000)
    authorizes_acquisition: Literal[False] = False
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def identities_are_closed(self) -> TasteCorpusManifest:
        collections = (
            ("task domains", self.task_domain_tags),
            ("held-out source groups", self.held_out_source_groups),
            ("forbidden content hashes", self.forbidden_source_content_sha256),
        )
        for label, values in collections:
            if len(values) != len(set(values)):
                raise ValueError(f"Taste corpus {label} must be unique")
        if any(not item or len(item) > 200 for item in self.task_domain_tags):
            raise ValueError("Taste corpus task domains must be bounded non-empty strings")
        if any(not re.fullmatch(_ID, item) for item in self.held_out_source_groups):
            raise ValueError("Taste corpus held-out source groups must be valid IDs")
        if any(not re.fullmatch(_SHA256, item) for item in self.forbidden_source_content_sha256):
            raise ValueError("Taste corpus forbidden content hashes must be SHA-256 values")
        case_ids = [item.case.case_id for item in self.entries]
        slots = [item.pair_slot_id for item in self.entries]
        source_hashes = [item.source_content_sha256 for item in self.entries]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Taste corpus case IDs must be unique")
        if len(slots) != len(set(slots)):
            raise ValueError("Taste corpus pair slots must be unique")
        if len(source_hashes) != len(set(source_hashes)):
            raise ValueError("Taste corpus source content hashes must be unique")
        return self


class TasteCorpusFileBinding(BaseModel):
    model_config = _CONFIG

    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_safe(self) -> TasteCorpusFileBinding:
        candidate = PurePosixPath(self.path)
        if candidate.is_absolute() or candidate.as_posix() != self.path:
            raise ValueError("Taste corpus binding must use a normalized relative path")
        if ".." in candidate.parts or not candidate.parts:
            raise ValueError("Taste corpus binding cannot escape the evidence root")
        return self


class TasteCorpusQualificationQuery(BaseModel):
    model_config = _CONFIG

    query_id: str = Field(pattern=_ID)
    decision_role: str = Field(min_length=1, max_length=300)
    query: TasteQuery
    retrieval_limit: int = Field(ge=1, le=20)
    context_token_budget: int = Field(ge=128, le=100_000)

    @model_validator(mode="after")
    def query_is_role_and_domain_conditioned(self) -> TasteCorpusQualificationQuery:
        if self.query.stage is None:
            raise ValueError("Taste corpus qualification queries require a stage")
        if not self.query.domain_tags:
            raise ValueError("Taste corpus qualification queries require task domains")
        return self


class TasteCorpusPairManifest(BaseModel):
    """Pairing contract whose only intervention is the corpus-domain relation."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    pair_id: str = Field(pattern=_ID)
    authorization_scope: Literal["local-static-qualification-only"]
    task_id: str = Field(pattern=_ID)
    matched_corpus: TasteCorpusFileBinding
    placebo_corpus: TasteCorpusFileBinding
    only_permitted_difference: Literal["source_domain_relation"]
    qualification_queries: tuple[TasteCorpusQualificationQuery, ...] = Field(
        min_length=1,
        max_length=100,
    )
    zero_retrieval_invalidates_pair: Literal[True] = True
    no_dataset_download: Literal[True] = True
    no_api_call: Literal[True] = True
    no_ssh: Literal[True] = True
    no_gpu_or_model_execution: Literal[True] = True
    no_experiment_execution: Literal[True] = True
    authorizes_execution: Literal[False] = False

    @model_validator(mode="after")
    def pair_bindings_are_distinct_and_queries_unique(self) -> TasteCorpusPairManifest:
        if self.matched_corpus.path == self.placebo_corpus.path:
            raise ValueError("matched and placebo corpora must be separate bound files")
        query_ids = [item.query_id for item in self.qualification_queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("Taste corpus qualification query IDs must be unique")
        return self

    @property
    def proposal_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class TasteCorpusPairInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: TasteCorpusPairManifest


class TasteCorpusPairFinding(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z0-9]+(?:[a-z0-9_:-]*[a-z0-9])?$")
    message: str = Field(min_length=1, max_length=4_000)


class TasteCorpusRetrievalObservation(BaseModel):
    model_config = _CONFIG

    query_id: str
    matched_case_ids: tuple[str, ...]
    placebo_case_ids: tuple[str, ...]
    matched_pair_slots: tuple[str, ...]
    placebo_pair_slots: tuple[str, ...]
    matched_count: int = Field(ge=0)
    placebo_count: int = Field(ge=0)
    retrieval_limit: int = Field(ge=1)
    context_token_budget: int = Field(ge=128)


class TasteCorpusPairReport(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    pair_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    corpus_bindings_verified: bool
    matched_corpus_sha256: str = Field(pattern=_SHA256)
    placebo_corpus_sha256: str = Field(pattern=_SHA256)
    matched_corpus_id: str | None = None
    placebo_corpus_id: str | None = None
    parity_status: dict[CorpusParityDimension, ReadinessStatus]
    contamination_free: bool
    retrieval_observations: tuple[TasteCorpusRetrievalObservation, ...]
    qualified: bool
    blockers: tuple[TasteCorpusPairFinding, ...]
    no_external_action_performed: Literal[True] = True
    authorizes_execution: Literal[False] = False


def load_taste_corpus_pair_manifest(path: str | Path) -> TasteCorpusPairInspection:
    source, raw = _read_bounded_regular_file(Path(path), root=None)
    return TasteCorpusPairInspection(
        path=source,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=TasteCorpusPairManifest.model_validate(_yaml_mapping(raw, "corpus pair")),
    )


def inspect_taste_corpus_pair(
    inspection: TasteCorpusPairInspection,
    *,
    evidence_root: str | Path,
) -> TasteCorpusPairReport:
    """Qualify two bound local corpora without network, models, or experiment execution."""

    manifest = inspection.manifest
    blockers: list[TasteCorpusPairFinding] = []
    corpora: dict[TasteCorpusRelation, TasteCorpusManifest] = {}
    root = Path(evidence_root).resolve(strict=True)
    for relation, binding in (
        (TasteCorpusRelation.MATCHED, manifest.matched_corpus),
        (TasteCorpusRelation.MISMATCHED, manifest.placebo_corpus),
    ):
        try:
            _, raw = _read_bounded_regular_file(Path(binding.path), root=root)
            observed = hashlib.sha256(raw).hexdigest()
            if observed != binding.sha256:
                raise ValueError(f"{relation.value} corpus SHA-256 mismatch")
            corpus = TasteCorpusManifest.model_validate(
                _yaml_mapping(raw, f"{relation.value} corpus")
            )
            if corpus.relation is not relation:
                raise ValueError(f"{relation.value} corpus declares another relation")
            corpora[relation] = corpus
        except (OSError, ValueError) as exc:
            _add(blockers, f"corpus_binding_invalid:{relation.name.lower()}", str(exc))

    bindings_verified = len(corpora) == 2
    parity = {dimension: ReadinessStatus.BLOCKED for dimension in CorpusParityDimension}
    observations: list[TasteCorpusRetrievalObservation] = []
    contamination_free = False
    if bindings_verified:
        matched = corpora[TasteCorpusRelation.MATCHED]
        placebo = corpora[TasteCorpusRelation.MISMATCHED]
        _inspect_shared_contract(manifest, matched, placebo, blockers)
        contamination_free = _inspect_contamination(matched, placebo, blockers)
        parity.update(_inspect_parity(manifest, matched, placebo, observations, blockers))

    qualified = (
        bindings_verified
        and contamination_free
        and all(status is ReadinessStatus.VERIFIED for status in parity.values())
        and not blockers
    )
    return TasteCorpusPairReport(
        pair_id=manifest.pair_id,
        proposal_sha256=manifest.proposal_sha256,
        corpus_bindings_verified=bindings_verified,
        matched_corpus_sha256=manifest.matched_corpus.sha256,
        placebo_corpus_sha256=manifest.placebo_corpus.sha256,
        matched_corpus_id=(
            corpora[TasteCorpusRelation.MATCHED].corpus_id if bindings_verified else None
        ),
        placebo_corpus_id=(
            corpora[TasteCorpusRelation.MISMATCHED].corpus_id if bindings_verified else None
        ),
        parity_status=parity,
        contamination_free=contamination_free,
        retrieval_observations=tuple(observations),
        qualified=qualified,
        blockers=tuple(blockers),
    )


def save_taste_corpus_pair_report(report: TasteCorpusPairReport, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _inspect_shared_contract(
    pair: TasteCorpusPairManifest,
    matched: TasteCorpusManifest,
    placebo: TasteCorpusManifest,
    blockers: list[TasteCorpusPairFinding],
) -> None:
    if pair.task_id != matched.task_id or pair.task_id != placebo.task_id:
        _add(blockers, "task_identity_mismatch", "pair and corpus task identities differ")
    shared = (
        ("task domains", matched.task_domain_tags, placebo.task_domain_tags),
        (
            "held-out source groups",
            matched.held_out_source_groups,
            placebo.held_out_source_groups,
        ),
        (
            "forbidden source hashes",
            matched.forbidden_source_content_sha256,
            placebo.forbidden_source_content_sha256,
        ),
    )
    for label, left, right in shared:
        if left != right:
            _add(blockers, "shared_contract_mismatch", f"corpus {label} differ")
    expected_domains = {item.casefold() for item in matched.task_domain_tags}
    for query in pair.qualification_queries:
        if {item.casefold() for item in query.query.domain_tags} != expected_domains:
            _add(
                blockers,
                "qualification_query_domain_mismatch",
                f"qualification query {query.query_id} does not bind the exact task domains",
            )


def _inspect_contamination(
    matched: TasteCorpusManifest,
    placebo: TasteCorpusManifest,
    blockers: list[TasteCorpusPairFinding],
) -> bool:
    clean = True
    task_domains = {item.casefold() for item in matched.task_domain_tags}
    held_out_groups = set(matched.held_out_source_groups)
    forbidden_hashes = set(matched.forbidden_source_content_sha256)
    by_relation = (
        (matched, True),
        (placebo, False),
    )
    for corpus, should_match in by_relation:
        for entry in corpus.entries:
            case_domains = {item.casefold() for item in entry.case.domain_tags}
            overlaps = bool(task_domains & case_domains)
            if overlaps != should_match:
                clean = False
                _add(
                    blockers,
                    "domain_relation_invalid",
                    f"case {entry.case.case_id} violates {corpus.relation.value}",
                )
            if entry.source_group in held_out_groups:
                clean = False
                _add(
                    blockers,
                    "held_out_source_group_leakage",
                    f"case {entry.case.case_id} reuses a held-out task source group",
                )
            if entry.source_content_sha256 in forbidden_hashes:
                clean = False
                _add(
                    blockers,
                    "held_out_content_leakage",
                    f"case {entry.case.case_id} reuses held-out task content",
                )
            if not entry.case.retrieval_eligible or not entry.case.human_verified:
                clean = False
                _add(
                    blockers,
                    "case_not_qualified",
                    f"case {entry.case.case_id} is not human-verified and retrieval-eligible",
                )
            if not all(
                item.license_id and item.derivation_method and item.personal_data_removed is True
                for item in entry.case.provenance
            ):
                clean = False
                _add(
                    blockers,
                    "provenance_incomplete",
                    f"case {entry.case.case_id} lacks license, derivation, or privacy evidence",
                )

    matched_groups = {item.source_group for item in matched.entries}
    placebo_groups = {item.source_group for item in placebo.entries}
    matched_hashes = {item.source_content_sha256 for item in matched.entries}
    placebo_hashes = {item.source_content_sha256 for item in placebo.entries}
    matched_locators = {
        provenance.locator for item in matched.entries for provenance in item.case.provenance
    }
    placebo_locators = {
        provenance.locator for item in placebo.entries for provenance in item.case.provenance
    }
    overlaps = (
        (
            "cross_corpus_case_id_overlap",
            {item.case.case_id for item in matched.entries}
            & {item.case.case_id for item in placebo.entries},
        ),
        ("cross_corpus_source_group_overlap", matched_groups & placebo_groups),
        ("cross_corpus_content_overlap", matched_hashes & placebo_hashes),
        ("cross_corpus_locator_overlap", matched_locators & placebo_locators),
    )
    for code, values in overlaps:
        if values:
            clean = False
            _add(blockers, code, f"matched and placebo corpora overlap: {sorted(values)!r}")
    return clean


def _inspect_parity(
    pair: TasteCorpusPairManifest,
    matched: TasteCorpusManifest,
    placebo: TasteCorpusManifest,
    observations: list[TasteCorpusRetrievalObservation],
    blockers: list[TasteCorpusPairFinding],
) -> dict[CorpusParityDimension, ReadinessStatus]:
    result = {dimension: ReadinessStatus.BLOCKED for dimension in CorpusParityDimension}
    matched_slots = {item.pair_slot_id: item for item in matched.entries}
    placebo_slots = {item.pair_slot_id: item for item in placebo.entries}
    stages_roles_match = set(matched_slots) == set(placebo_slots) and all(
        (
            matched_slots[slot].case.stage,
            matched_slots[slot].decision_role,
            len(matched_slots[slot].case.candidate_actions),
        )
        == (
            placebo_slots[slot].case.stage,
            placebo_slots[slot].decision_role,
            len(placebo_slots[slot].case.candidate_actions),
        )
        for slot in matched_slots.keys() & placebo_slots.keys()
    )
    if stages_roles_match:
        result[CorpusParityDimension.STAGE_DECISION_ROLE] = ReadinessStatus.VERIFIED
    else:
        _add(blockers, "stage_decision_role_mismatch", "paired case roles or stages differ")

    matched_eligible = sum(item.case.retrieval_eligible for item in matched.entries)
    placebo_eligible = sum(item.case.retrieval_eligible for item in placebo.entries)
    if matched_eligible == placebo_eligible == len(matched.entries) == len(placebo.entries):
        result[CorpusParityDimension.ELIGIBLE_CASE_COUNT] = ReadinessStatus.VERIFIED
    else:
        _add(blockers, "eligible_case_count_mismatch", "eligible corpus counts differ")

    if matched.provenance_tier == placebo.provenance_tier:
        result[CorpusParityDimension.PROVENANCE_TIER] = ReadinessStatus.VERIFIED
    else:
        _add(blockers, "provenance_tier_mismatch", "corpus provenance tiers differ")
    if matched.curation_tier == placebo.curation_tier:
        result[CorpusParityDimension.CURATION_TIER] = ReadinessStatus.VERIFIED
    else:
        _add(blockers, "curation_tier_mismatch", "corpus curation tiers differ")

    outcome_shape_ok = (
        matched.outcome_information_availability is placebo.outcome_information_availability
        and _outcome_shape_matches_declaration(matched)
        and _outcome_shape_matches_declaration(placebo)
    )
    if outcome_shape_ok:
        result[CorpusParityDimension.OUTCOME_INFORMATION_AVAILABILITY] = ReadinessStatus.VERIFIED
    else:
        _add(
            blockers,
            "outcome_information_mismatch",
            "corpus outcome-information declarations or case fields differ",
        )

    retrieval_ok = True
    context_budget_ok = True
    matched_by_id = {item.case.case_id: item for item in matched.entries}
    placebo_by_id = {item.case.case_id: item for item in placebo.entries}
    for specification in pair.qualification_queries:
        matched_results = retrieve_taste_cases(
            [item.case for item in matched.entries],
            specification.query,
            domain_relation=TasteDomainRelation.MATCHED,
            limit=specification.retrieval_limit,
        )
        placebo_results = retrieve_taste_cases(
            [item.case for item in placebo.entries],
            specification.query,
            domain_relation=TasteDomainRelation.MISMATCHED,
            limit=specification.retrieval_limit,
        )
        matched_entries = [matched_by_id[item.case.case_id] for item in matched_results]
        placebo_entries = [placebo_by_id[item.case.case_id] for item in placebo_results]
        matched_retrieved_slots = tuple(item.pair_slot_id for item in matched_entries)
        placebo_retrieved_slots = tuple(item.pair_slot_id for item in placebo_entries)
        observations.append(
            TasteCorpusRetrievalObservation(
                query_id=specification.query_id,
                matched_case_ids=tuple(item.case.case_id for item in matched_results),
                placebo_case_ids=tuple(item.case.case_id for item in placebo_results),
                matched_pair_slots=matched_retrieved_slots,
                placebo_pair_slots=placebo_retrieved_slots,
                matched_count=len(matched_results),
                placebo_count=len(placebo_results),
                retrieval_limit=specification.retrieval_limit,
                context_token_budget=specification.context_token_budget,
            )
        )
        expected = specification.retrieval_limit
        role_stage_ok = all(
            item.decision_role == specification.decision_role
            and item.case.stage.casefold() == specification.query.stage.casefold()
            for item in (*matched_entries, *placebo_entries)
        )
        if not (
            len(matched_results) == len(placebo_results) == expected
            and matched_retrieved_slots == placebo_retrieved_slots
            and role_stage_ok
        ):
            retrieval_ok = False
            _add(
                blockers,
                "retrieval_parity_failed",
                f"query {specification.query_id} did not retrieve the same nonzero pair slots",
            )
        if specification.context_token_budget < expected * 128:
            context_budget_ok = False
            _add(
                blockers,
                "context_budget_too_small",
                f"query {specification.query_id} allocates fewer than 128 tokens per case",
            )
    if retrieval_ok:
        result[CorpusParityDimension.RETRIEVED_CASE_COUNT] = ReadinessStatus.VERIFIED
    if context_budget_ok:
        result[CorpusParityDimension.CONTEXT_TOKEN_BUDGET] = ReadinessStatus.VERIFIED
    return result


def _outcome_shape_matches_declaration(corpus: TasteCorpusManifest) -> bool:
    has_outcomes = [item.case.outcome_summary is not None for item in corpus.entries]
    if corpus.outcome_information_availability is OutcomeInformationAvailability.AVAILABLE:
        return all(has_outcomes)
    return not any(has_outcomes)


def _read_bounded_regular_file(path: Path, *, root: Path | None) -> tuple[Path, bytes]:
    if root is None:
        requested = path
    else:
        if path.is_absolute():
            raise ValueError("Taste corpus evidence path must be relative")
        requested = root / path
    if requested.is_symlink():
        raise ValueError("Taste corpus evidence cannot be a symbolic link")
    resolved = requested.resolve(strict=True)
    if root is not None and not resolved.is_relative_to(root):
        raise ValueError("Taste corpus evidence escapes the evidence root")
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("Taste corpus evidence must be a bounded regular file")
    raw = resolved.read_bytes()
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise ValueError("Taste corpus evidence exceeds the byte ceiling")
    return resolved, raw


def _yaml_mapping(raw: bytes, label: str) -> dict[str, object]:
    try:
        value = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 YAML") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a YAML mapping")
    return value


def _add(blockers: list[TasteCorpusPairFinding], code: str, message: str) -> None:
    blockers.append(TasteCorpusPairFinding(code=code, message=message[:4_000]))


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "OutcomeInformationAvailability",
    "TasteCorpusEntry",
    "TasteCorpusFileBinding",
    "TasteCorpusManifest",
    "TasteCorpusPairFinding",
    "TasteCorpusPairInspection",
    "TasteCorpusPairManifest",
    "TasteCorpusPairReport",
    "TasteCorpusQualificationQuery",
    "TasteCorpusRelation",
    "TasteCorpusRetrievalObservation",
    "inspect_taste_corpus_pair",
    "load_taste_corpus_pair_manifest",
    "save_taste_corpus_pair_report",
]

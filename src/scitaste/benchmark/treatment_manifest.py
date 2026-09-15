"""Replayable construction manifest for SciTasteBench v3 mechanism contexts."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.benchmark.models import (
    MechanismContextBundle,
    ReferenceTreatmentArm,
    ReferenceTreatmentContext,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_MANIFEST_BYTES = 64 * 1_048_576
_MAX_SUPPORT_BYTES = 256 * 1_048_576


class TreatmentSupportRole(StrEnum):
    """Scientific role of one exact treatment-construction artifact."""

    SOURCE_PROJECTION_RECEIPT = "source_projection_receipt"
    TASTE_CURATION_PACKAGE = "taste_curation_package"
    TASTE_CURATION_REPORT = "taste_curation_report"
    MATCHED_TASTE_CORPUS = "matched_taste_corpus"
    MISMATCHED_TASTE_CORPUS = "mismatched_taste_corpus"
    TASTE_CORPUS_PAIR_REPORT = "taste_corpus_pair_report"
    TOKENIZER_ARTIFACT = "tokenizer_artifact"
    RETRIEVAL_QUERY = "retrieval_query"
    RENDER_TEMPLATE = "render_template"
    TOKENIZATION_TRACE = "tokenization_trace"


class TreatmentSupportArtifact(BaseModel):
    """Content-addressed local evidence used by one or more treatment arms."""

    model_config = _CONFIG

    artifact_id: str = Field(pattern=_ID)
    role: TreatmentSupportRole
    path: str = Field(min_length=1, max_length=2_000)
    file_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_normalized_and_relative(self) -> TreatmentSupportArtifact:
        pure = PurePosixPath(self.path)
        if (
            pure.is_absolute()
            or not pure.parts
            or pure.as_posix() != self.path
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise ValueError("treatment support path must be normalized and relative")
        return self


class TreatmentConstructionRecord(BaseModel):
    """Canonical receipt inputs for one rendered and token-accounted arm."""

    model_config = _CONFIG

    arm: ReferenceTreatmentArm
    rendered_context_sha256: str = Field(pattern=_SHA256)
    source_artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    support_artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    token_sequence_sha256: str = Field(pattern=_SHA256)
    observed_token_count: int = Field(ge=1, le=100_000)
    tokenizer_id: str = Field(min_length=1, max_length=300)
    tokenizer_revision: str = Field(min_length=1, max_length=300)
    tokenizer_artifact_sha256: str = Field(pattern=_SHA256)
    retrieval_query_sha256: str = Field(pattern=_SHA256)
    render_template_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def identities_are_unique(self) -> TreatmentConstructionRecord:
        if len(self.source_artifact_ids) != len(set(self.source_artifact_ids)):
            raise ValueError("construction source artifact IDs must be unique")
        if len(self.support_artifact_ids) != len(set(self.support_artifact_ids)):
            raise ValueError("construction support artifact IDs must be unique")
        return self

    @property
    def receipt_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        return _canonical_sha256(payload)


class TreatmentTokenizationTrace(BaseModel):
    """Exact token sequence observed for one rendered treatment context."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    arm: ReferenceTreatmentArm
    rendered_context_sha256: str = Field(pattern=_SHA256)
    tokenizer_id: str = Field(min_length=1, max_length=300)
    tokenizer_revision: str = Field(min_length=1, max_length=300)
    tokenizer_artifact_sha256: str = Field(pattern=_SHA256)
    add_special_tokens: bool
    token_ids: tuple[int, ...] = Field(min_length=1, max_length=100_000)

    @property
    def token_sequence_sha256(self) -> str:
        return _canonical_sha256(list(self.token_ids))


class ReferenceTreatmentCaseManifest(BaseModel):
    """One held-out case with exact contexts and construction receipts."""

    model_config = _CONFIG

    case_id: str = Field(pattern=_ID)
    mechanism_context: MechanismContextBundle
    constructions: tuple[TreatmentConstructionRecord, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def contexts_match_construction_receipts(self) -> ReferenceTreatmentCaseManifest:
        by_arm = {item.arm: item for item in self.constructions}
        required = set(ReferenceTreatmentArm)
        if set(by_arm) != required:
            raise ValueError("treatment case requires exactly one construction per arm")
        for context in _contexts(self.mechanism_context):
            receipt = by_arm[context.arm]
            observed_source_ids = tuple(item.artifact_id for item in context.sources)
            if (
                receipt.rendered_context_sha256 != context.rendered_context_sha256
                or receipt.source_artifact_ids != observed_source_ids
                or receipt.observed_token_count != context.observed_token_count
                or receipt.tokenizer_id != context.tokenizer_id
                or receipt.tokenizer_revision != context.tokenizer_revision
                or receipt.tokenizer_artifact_sha256 != context.tokenizer_artifact_sha256
                or receipt.retrieval_query_sha256 != context.retrieval_query_sha256
                or receipt.render_template_sha256 != context.render_template_sha256
                or receipt.receipt_sha256 != context.construction_receipt_sha256
            ):
                raise ValueError("treatment context differs from its construction receipt")
        return self


class ReferenceTreatmentManifest(BaseModel):
    """Closed v3 treatment population; it authorizes no acquisition or execution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    manifest_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    support_artifacts: tuple[TreatmentSupportArtifact, ...] = Field(
        min_length=10,
        max_length=10_000,
    )
    cases: tuple[ReferenceTreatmentCaseManifest, ...] = Field(
        min_length=1,
        max_length=10_000,
    )
    source_selection_frozen: Literal[True] = True
    conditions_blinded_in_rendered_context: Literal[True] = True
    no_external_action_performed: Literal[True] = True
    authorizes_acquisition: Literal[False] = False
    authorizes_model_calls: Literal[False] = False
    authorizes_human_recruitment: Literal[False] = False
    authorizes_experiment: Literal[False] = False

    @model_validator(mode="after")
    def population_and_support_are_closed(self) -> ReferenceTreatmentManifest:
        artifact_ids = [item.artifact_id for item in self.support_artifacts]
        case_ids = [item.case_id for item in self.cases]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("treatment support artifact IDs must be unique")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("treatment manifest case IDs must be unique")
        support = {item.artifact_id: item for item in self.support_artifacts}
        required_global = {
            TreatmentSupportRole.SOURCE_PROJECTION_RECEIPT,
            TreatmentSupportRole.TASTE_CURATION_PACKAGE,
            TreatmentSupportRole.TASTE_CURATION_REPORT,
            TreatmentSupportRole.MATCHED_TASTE_CORPUS,
            TreatmentSupportRole.MISMATCHED_TASTE_CORPUS,
            TreatmentSupportRole.TASTE_CORPUS_PAIR_REPORT,
            TreatmentSupportRole.TOKENIZER_ARTIFACT,
            TreatmentSupportRole.RETRIEVAL_QUERY,
            TreatmentSupportRole.RENDER_TEMPLATE,
            TreatmentSupportRole.TOKENIZATION_TRACE,
        }
        observed_global = {item.role for item in self.support_artifacts}
        if not required_global.issubset(observed_global):
            missing = sorted(item.value for item in required_global - observed_global)
            raise ValueError(f"treatment manifest lacks required support roles: {missing}")
        common_roles = {
            TreatmentSupportRole.SOURCE_PROJECTION_RECEIPT,
            TreatmentSupportRole.TOKENIZER_ARTIFACT,
            TreatmentSupportRole.RETRIEVAL_QUERY,
            TreatmentSupportRole.RENDER_TEMPLATE,
            TreatmentSupportRole.TOKENIZATION_TRACE,
        }
        abstracted_roles = common_roles | {
            TreatmentSupportRole.TASTE_CURATION_PACKAGE,
            TreatmentSupportRole.TASTE_CURATION_REPORT,
            TreatmentSupportRole.MATCHED_TASTE_CORPUS,
            TreatmentSupportRole.MISMATCHED_TASTE_CORPUS,
            TreatmentSupportRole.TASTE_CORPUS_PAIR_REPORT,
        }
        for case in self.cases:
            for construction in case.constructions:
                try:
                    bound = tuple(support[item] for item in construction.support_artifact_ids)
                except KeyError as exc:
                    raise ValueError("construction references an unknown support artifact") from exc
                roles = {item.role for item in bound}
                required = (
                    common_roles
                    if construction.arm is ReferenceTreatmentArm.RAW_SOURCE_RAG
                    else abstracted_roles
                )
                if not required.issubset(roles):
                    missing = sorted(item.value for item in required - roles)
                    raise ValueError(
                        f"{construction.arm.value} construction lacks support roles: {missing}"
                    )
                role_hashes = {item.role: item.file_sha256 for item in bound}
                if (
                    role_hashes[TreatmentSupportRole.TOKENIZER_ARTIFACT]
                    != construction.tokenizer_artifact_sha256
                    or role_hashes[TreatmentSupportRole.RETRIEVAL_QUERY]
                    != construction.retrieval_query_sha256
                    or role_hashes[TreatmentSupportRole.RENDER_TEMPLATE]
                    != construction.render_template_sha256
                ):
                    raise ValueError("construction protocol hashes differ from support artifacts")
        return self

    @property
    def manifest_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        return _canonical_sha256(payload)


class ReferenceTreatmentManifestInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: ReferenceTreatmentManifest


class ReferenceTreatmentManifestReport(BaseModel):
    model_config = _CONFIG

    manifest_id: str
    manifest_sha256: str = Field(pattern=_SHA256)
    case_count: int = Field(ge=1)
    support_count: int = Field(ge=1)
    support_bindings_verified: bool
    construction_semantics_verified: bool
    exact_case_population_verified: bool
    exact_contexts_verified: bool
    ready_for_v3_compilation: bool
    blocker_codes: tuple[str, ...]
    no_external_action_performed: Literal[True] = True
    authorizes_experiment: Literal[False] = False


def load_reference_treatment_manifest(path: str | Path) -> ReferenceTreatmentManifestInspection:
    """Load a bounded self-hashed treatment manifest without opening its supports."""

    source = Path(path)
    if source.is_symlink():
        raise ValueError("reference treatment manifest must not be a symlink")
    resolved = source.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("reference treatment manifest must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("reference treatment manifest must be UTF-8 YAML or JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("reference treatment manifest must contain a mapping")
    recorded = payload.pop("manifest_sha256", None)
    manifest = ReferenceTreatmentManifest.model_validate(payload)
    if recorded != manifest.manifest_sha256:
        raise ValueError("reference treatment manifest semantic hash mismatch")
    return ReferenceTreatmentManifestInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=manifest,
    )


def inspect_reference_treatment_manifest(
    inspection: ReferenceTreatmentManifestInspection,
    *,
    evidence_root: str | Path | None,
    expected_contexts: dict[str, MechanismContextBundle],
) -> ReferenceTreatmentManifestReport:
    """Replay file identity and exact curation-package context membership."""

    manifest = inspection.manifest
    blockers: list[str] = []
    supports_verified = True
    if evidence_root is None:
        supports_verified = False
        blockers.append("support:unobserved")
    else:
        for artifact in manifest.support_artifacts:
            problem = _support_problem(evidence_root, artifact)
            if problem is not None:
                supports_verified = False
                blockers.append(f"support:{artifact.artifact_id}:{problem}")
        if supports_verified:
            blockers.extend(_semantic_support_blockers(manifest, evidence_root))

    semantic_verified = supports_verified and not any(
        code.startswith("semantic:") for code in blockers
    )

    observed = {item.case_id: item.mechanism_context for item in manifest.cases}
    exact_population = set(observed) == set(expected_contexts)
    if not exact_population:
        blockers.append("population:case_identity_mismatch")
    exact_contexts = exact_population and all(
        observed[case_id] == context for case_id, context in expected_contexts.items()
    )
    if not exact_contexts:
        blockers.append("population:mechanism_context_mismatch")

    unique = tuple(dict.fromkeys(blockers))
    return ReferenceTreatmentManifestReport(
        manifest_id=manifest.manifest_id,
        manifest_sha256=manifest.manifest_sha256,
        case_count=len(manifest.cases),
        support_count=len(manifest.support_artifacts),
        support_bindings_verified=supports_verified,
        construction_semantics_verified=semantic_verified,
        exact_case_population_verified=exact_population,
        exact_contexts_verified=exact_contexts,
        ready_for_v3_compilation=not unique,
        blocker_codes=unique,
    )


def save_reference_treatment_manifest(
    manifest: ReferenceTreatmentManifest,
    path: str | Path,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **manifest.model_dump(mode="json"),
        "manifest_sha256": manifest.manifest_sha256,
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def _contexts(bundle: MechanismContextBundle) -> tuple[ReferenceTreatmentContext, ...]:
    return (
        bundle.raw_source_rag,
        bundle.matched_abstracted_taste,
        bundle.mismatched_taste,
    )


def _support_problem(
    evidence_root: str | Path,
    artifact: TreatmentSupportArtifact,
) -> str | None:
    try:
        root = Path(evidence_root).resolve(strict=True)
        candidate = root.joinpath(*PurePosixPath(artifact.path).parts)
        if any(path.is_symlink() for path in (root, *candidate.parents, candidate)):
            return "symlink_forbidden"
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file() or resolved.stat().st_size > _MAX_SUPPORT_BYTES:
            return "not_bounded_file"
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != artifact.file_sha256:
            return "hash_mismatch"
    except (OSError, ValueError):
        return "missing_or_escaped"
    return None


def _semantic_support_blockers(
    manifest: ReferenceTreatmentManifest,
    evidence_root: str | Path,
) -> list[str]:
    """Replay source identities, corpus identities, and exact token traces."""

    from scitaste.evaluation.native_condition_preflight import CorpusParityDimension
    from scitaste.evaluation.prelaunch import ReadinessStatus
    from scitaste.evaluation.source_projection import load_source_projection_receipt
    from scitaste.evaluation.taste_corpus_curation import TasteCorpusCurationReport
    from scitaste.evaluation.taste_corpus_pair import (
        TasteCorpusManifest,
        TasteCorpusPairReport,
        TasteCorpusRelation,
    )

    root = Path(evidence_root).resolve(strict=True)
    by_id = {item.artifact_id: item for item in manifest.support_artifacts}
    blockers: list[str] = []

    projection_items: dict[str, dict[str, object]] = {}
    for artifact in manifest.support_artifacts:
        if artifact.role is not TreatmentSupportRole.SOURCE_PROJECTION_RECEIPT:
            continue
        try:
            receipt = load_source_projection_receipt(root / artifact.path)
        except (OSError, ValueError):
            blockers.append(f"semantic:{artifact.artifact_id}:invalid_projection_receipt")
            continue
        receipt_items: dict[str, object] = {}
        for item in receipt.items:
            if item.source_id in receipt_items:
                blockers.append(f"semantic:{artifact.artifact_id}:duplicate_projection_source")
            receipt_items[item.source_id] = item
        projection_items[artifact.artifact_id] = receipt_items

    corpora: dict[str, object] = {}
    for artifact in manifest.support_artifacts:
        expected_relation = {
            TreatmentSupportRole.MATCHED_TASTE_CORPUS: TasteCorpusRelation.MATCHED,
            TreatmentSupportRole.MISMATCHED_TASTE_CORPUS: TasteCorpusRelation.MISMATCHED,
        }.get(artifact.role)
        if expected_relation is None:
            continue
        try:
            payload = json.loads((root / artifact.path).read_text(encoding="utf-8"))
            corpus = TasteCorpusManifest.model_validate(payload)
        except (OSError, ValueError):
            blockers.append(f"semantic:{artifact.artifact_id}:invalid_taste_corpus")
            continue
        if corpus.relation is not expected_relation:
            blockers.append(f"semantic:{artifact.artifact_id}:wrong_corpus_relation")
            continue
        corpora[artifact.artifact_id] = corpus

    curation_reports: dict[str, object] = {}
    for artifact in manifest.support_artifacts:
        if artifact.role is not TreatmentSupportRole.TASTE_CURATION_REPORT:
            continue
        try:
            report = TasteCorpusCurationReport.model_validate_json(
                (root / artifact.path).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            blockers.append(f"semantic:{artifact.artifact_id}:invalid_curation_report")
            continue
        if (
            not report.ready_to_materialize
            or not report.ready_for_formal_taste_method
            or not report.source_bindings_verified
            or not report.abstraction_input_bindings_verified
            or not report.grounding_traces_verified
            or not report.transfer_boundaries_verified
            or not (
                report.dual_human_review_verified
                or report.dual_ai_review_verified
            )
            or report.blockers
        ):
            blockers.append(f"semantic:{artifact.artifact_id}:curation_not_formal_ready")
            continue
        curation_reports[artifact.artifact_id] = report

    pair_reports: dict[str, object] = {}
    for artifact in manifest.support_artifacts:
        if artifact.role is not TreatmentSupportRole.TASTE_CORPUS_PAIR_REPORT:
            continue
        try:
            report = TasteCorpusPairReport.model_validate_json(
                (root / artifact.path).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            blockers.append(f"semantic:{artifact.artifact_id}:invalid_pair_report")
            continue
        parity_complete = set(report.parity_status) == set(CorpusParityDimension) and all(
            status is ReadinessStatus.VERIFIED for status in report.parity_status.values()
        )
        if (
            not report.qualified
            or not report.contamination_free
            or not parity_complete
            or report.blockers
        ):
            blockers.append(f"semantic:{artifact.artifact_id}:pair_not_qualified")
            continue
        pair_reports[artifact.artifact_id] = report

    for case in manifest.cases:
        contexts = {context.arm: context for context in _contexts(case.mechanism_context)}
        for construction in case.constructions:
            context = contexts[construction.arm]
            bound_support = [by_id[item] for item in construction.support_artifact_ids]
            bound_projection_items: dict[str, object] = {}
            for artifact in bound_support:
                if artifact.role is TreatmentSupportRole.SOURCE_PROJECTION_RECEIPT:
                    bound_projection_items.update(projection_items.get(artifact.artifact_id, {}))
            for source in context.sources:
                projection = bound_projection_items.get(source.artifact_id)
                if projection is None or (
                    projection.source_group_id,
                    projection.source_locator,
                    projection.source_content_sha256,
                ) != (
                    source.source_group_id,
                    source.source_locator,
                    source.source_content_sha256,
                ):
                    blockers.append(
                        f"semantic:{case.case_id}:{construction.arm.value}:projection_identity"
                    )

            trace_artifacts = [
                item
                for item in bound_support
                if item.role is TreatmentSupportRole.TOKENIZATION_TRACE
            ]
            if len(trace_artifacts) != 1:
                blockers.append(
                    f"semantic:{case.case_id}:{construction.arm.value}:token_trace_count"
                )
            else:
                trace_artifact = trace_artifacts[0]
                try:
                    trace = TreatmentTokenizationTrace.model_validate_json(
                        (root / trace_artifact.path).read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    blockers.append(
                        f"semantic:{case.case_id}:{construction.arm.value}:invalid_token_trace"
                    )
                else:
                    if (
                        trace.arm is not construction.arm
                        or trace.rendered_context_sha256 != context.rendered_context_sha256
                        or trace.tokenizer_id != context.tokenizer_id
                        or trace.tokenizer_revision != context.tokenizer_revision
                        or trace.tokenizer_artifact_sha256 != context.tokenizer_artifact_sha256
                        or len(trace.token_ids) != context.observed_token_count
                        or trace.token_sequence_sha256 != construction.token_sequence_sha256
                    ):
                        blockers.append(
                            f"semantic:{case.case_id}:{construction.arm.value}:token_trace_mismatch"
                        )

            if construction.arm is ReferenceTreatmentArm.RAW_SOURCE_RAG:
                continue
            corpus_role = (
                TreatmentSupportRole.MATCHED_TASTE_CORPUS
                if construction.arm is ReferenceTreatmentArm.MATCHED_ABSTRACTED_TASTE
                else TreatmentSupportRole.MISMATCHED_TASTE_CORPUS
            )
            bound_corpora = [item for item in bound_support if item.role is corpus_role]
            if not bound_corpora:
                blockers.append(f"semantic:{case.case_id}:{construction.arm.value}:corpus_unbound")
                continue
            bound_curation_reports = [
                item
                for item in bound_support
                if item.role is TreatmentSupportRole.TASTE_CURATION_REPORT
            ]
            bound_pair_reports = [
                item
                for item in bound_support
                if item.role is TreatmentSupportRole.TASTE_CORPUS_PAIR_REPORT
            ]
            if len(bound_curation_reports) != 1 or len(bound_pair_reports) != 1:
                blockers.append(
                    f"semantic:{case.case_id}:{construction.arm.value}:report_binding_count"
                )
                continue
            curation_report = curation_reports.get(bound_curation_reports[0].artifact_id)
            pair_report = pair_reports.get(bound_pair_reports[0].artifact_id)
            bound_corpus_objects = tuple(
                corpus
                for artifact in bound_corpora
                if (corpus := corpora.get(artifact.artifact_id)) is not None
            )
            matched_artifacts = [
                item
                for item in bound_support
                if item.role is TreatmentSupportRole.MATCHED_TASTE_CORPUS
            ]
            mismatched_artifacts = [
                item
                for item in bound_support
                if item.role is TreatmentSupportRole.MISMATCHED_TASTE_CORPUS
            ]
            reports_match = (
                curation_report is not None
                and curation_report.package_id == _corpus_curation_package_id(bound_corpus_objects)
                and pair_report is not None
                and len(matched_artifacts) == 1
                and len(mismatched_artifacts) == 1
                and pair_report.matched_corpus_sha256 == matched_artifacts[0].file_sha256
                and pair_report.placebo_corpus_sha256 == mismatched_artifacts[0].file_sha256
            )
            if not reports_match:
                blockers.append(f"semantic:{case.case_id}:{construction.arm.value}:report_identity")
            available = []
            for corpus_artifact in bound_corpora:
                corpus = corpora.get(corpus_artifact.artifact_id)
                if corpus is None:
                    continue
                for entry in corpus.entries:
                    for provenance in entry.case.provenance:
                        source_id = provenance.metadata.get("source_id")
                        if isinstance(source_id, str):
                            available.append(
                                (
                                    source_id,
                                    entry.source_group,
                                    provenance.locator,
                                    entry.source_content_sha256,
                                    corpus.provenance_tier,
                                    corpus.curation_tier,
                                    corpus.outcome_information_availability.value,
                                )
                            )
            required = {
                (
                    source.artifact_id,
                    source.source_group_id,
                    source.source_locator,
                    source.source_content_sha256,
                    context.provenance_tier,
                    context.curation_tier,
                    context.outcome_information_availability,
                )
                for source in context.sources
            }
            if not required.issubset(set(available)):
                blockers.append(f"semantic:{case.case_id}:{construction.arm.value}:corpus_identity")
    return blockers


def _corpus_curation_package_id(corpora: tuple[object, ...]) -> str | None:
    observed: set[str] = set()
    for corpus in corpora:
        for entry in corpus.entries:
            for provenance in entry.case.provenance:
                value = provenance.metadata.get("curation_package_id")
                if isinstance(value, str):
                    observed.add(value)
    return next(iter(observed)) if len(observed) == 1 else None


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "ReferenceTreatmentCaseManifest",
    "ReferenceTreatmentManifest",
    "ReferenceTreatmentManifestInspection",
    "ReferenceTreatmentManifestReport",
    "TreatmentConstructionRecord",
    "TreatmentSupportArtifact",
    "TreatmentSupportRole",
    "TreatmentTokenizationTrace",
    "inspect_reference_treatment_manifest",
    "load_reference_treatment_manifest",
    "save_reference_treatment_manifest",
]

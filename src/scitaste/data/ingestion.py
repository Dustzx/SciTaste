"""Offline, license-aware normalization for external Phase 3 corpora.

The importer intentionally accepts local JSON/JSONL snapshots only.  It does not
download source material, infer a licence, or turn unannotated prose into a taste
case.  A taste case must contain an explicit decision precedent.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from scitaste.data.models import KnowledgeDocument, ProvenanceRecord, TasteCase
from scitaste.data.store import KnowledgeLibrary, TasteLibrary


class SourceType(StrEnum):
    OPENREVIEW = "openreview"
    ARIES = "aries"
    CASIMIR = "casimir"
    ACCEPTED_PAPERS = "accepted_papers"


class RecordKind(StrEnum):
    KNOWLEDGE = "knowledge"
    TASTE = "taste"


class LicenseStatus(StrEnum):
    PERMITTED = "permitted"
    UNKNOWN = "unknown"
    RESTRICTED = "restricted"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LicenseDeclaration(_StrictModel):
    status: LicenseStatus = LicenseStatus.UNKNOWN
    identifier: str | None = None
    locator: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def permitted_license_is_traceable(self) -> LicenseDeclaration:
        if self.status == LicenseStatus.PERMITTED and not (self.identifier and self.locator):
            raise ValueError("permitted licenses require identifier and locator")
        return self


class CorpusSource(_StrictModel):
    source_id: str = Field(min_length=1)
    source_type: SourceType
    path: str = Field(min_length=1)
    format: str = "auto"
    default_record_kind: RecordKind | None = None
    license: LicenseDeclaration = Field(default_factory=LicenseDeclaration)
    accessed_at: datetime | None = None
    defaults: dict[str, Any] = Field(default_factory=dict)


class IngestionConfig(_StrictModel):
    schema_version: str = "1.0"
    allow_unknown_licenses: bool = False
    sources: list[CorpusSource] = Field(min_length=1)


class RejectedInput(_StrictModel):
    source_id: str
    record_index: int
    locator: str
    reason: str


class DuplicateInput(_StrictModel):
    source_id: str
    record_index: int
    locator: str
    record_kind: RecordKind
    content_hash: str


class NormalizedCorpus(_StrictModel):
    source_count: int
    input_record_count: int
    knowledge_documents: list[KnowledgeDocument]
    taste_cases: list[TasteCase]
    rejected: list[RejectedInput]
    duplicates: list[DuplicateInput]
    license_summary: dict[str, int]


def normalize_corpus(manifest_path: str | Path) -> NormalizedCorpus:
    """Normalize configured local snapshots without writing library records."""

    manifest = Path(manifest_path).resolve()
    raw_config = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    config = IngestionConfig.model_validate(raw_config)
    knowledge: list[KnowledgeDocument] = []
    taste: list[TasteCase] = []
    rejected: list[RejectedInput] = []
    duplicates: list[DuplicateInput] = []
    seen: dict[RecordKind, set[str]] = {RecordKind.KNOWLEDGE: set(), RecordKind.TASTE: set()}
    license_counts: Counter[str] = Counter()
    input_count = 0

    for source in config.sources:
        source_path = _resolve_local_path(manifest.parent, source.path)
        records = _load_records(source_path, source.format)
        accessed_at = source.accessed_at or datetime.fromtimestamp(source_path.stat().st_mtime, UTC)
        for index, raw in enumerate(records, 1):
            input_count += 1
            locator = _input_locator(source_path, index, raw)
            declaration = _record_license(raw, source.license)
            license_counts[declaration.status.value] += 1
            if declaration.status == LicenseStatus.RESTRICTED or (
                declaration.status == LicenseStatus.UNKNOWN and not config.allow_unknown_licenses
            ):
                rejected.append(
                    RejectedInput(
                        source_id=source.source_id,
                        record_index=index,
                        locator=locator,
                        reason=f"license status is {declaration.status.value}",
                    )
                )
                continue
            try:
                kind = _record_kind(raw, source)
                record, content_hash = _normalize_record(
                    raw, source, kind, declaration, accessed_at, locator, index
                )
            except (TypeError, ValueError, ValidationError) as exc:
                rejected.append(
                    RejectedInput(
                        source_id=source.source_id,
                        record_index=index,
                        locator=locator,
                        reason=_compact_error(exc),
                    )
                )
                continue
            if content_hash in seen[kind]:
                duplicates.append(
                    DuplicateInput(
                        source_id=source.source_id,
                        record_index=index,
                        locator=locator,
                        record_kind=kind,
                        content_hash=content_hash,
                    )
                )
                continue
            seen[kind].add(content_hash)
            if kind == RecordKind.KNOWLEDGE:
                knowledge.append(record)  # type: ignore[arg-type]
            else:
                taste.append(record)  # type: ignore[arg-type]

    return NormalizedCorpus(
        source_count=len(config.sources),
        input_record_count=input_count,
        knowledge_documents=knowledge,
        taste_cases=taste,
        rejected=rejected,
        duplicates=duplicates,
        license_summary=dict(sorted(license_counts.items())),
    )


def ingest_corpus(manifest_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Normalize and persist separate libraries; return a CLI-friendly report."""

    corpus = normalize_corpus(manifest_path)
    root = Path(output_dir)
    knowledge_store = KnowledgeLibrary(root / "knowledge" / "records.jsonl")
    taste_store = TasteLibrary(root / "taste" / "records.jsonl")
    existing_knowledge = _existing_hashes(knowledge_store.all())
    existing_taste = _existing_hashes(taste_store.all())
    imported_knowledge = _persist_new(
        corpus.knowledge_documents, knowledge_store, existing_knowledge
    )
    imported_taste = _persist_new(corpus.taste_cases, taste_store, existing_taste)
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "source_count": corpus.source_count,
        "input_record_count": corpus.input_record_count,
        "knowledge_imported": imported_knowledge,
        "taste_imported": imported_taste,
        "knowledge_count": len(knowledge_store),
        "taste_count": len(taste_store),
        "duplicate_count": len(corpus.duplicates)
        + len(corpus.knowledge_documents)
        + len(corpus.taste_cases)
        - imported_knowledge
        - imported_taste,
        "rejected_count": len(corpus.rejected),
        "license_summary": corpus.license_summary,
        "knowledge_path": str(knowledge_store.path),
        "taste_path": str(taste_store.path),
        "rejections": [item.model_dump(mode="json") for item in corpus.rejected],
    }
    _atomic_json(root / "ingestion_manifest.json", report)
    return report


def _resolve_local_path(base: Path, configured: str) -> Path:
    if "://" in configured:
        raise ValueError(f"only local corpus paths are allowed: {configured!r}")
    path = Path(configured)
    path = (base / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _load_records(path: Path, configured_format: str) -> list[dict[str, Any]]:
    data_format = (
        path.suffix.removeprefix(".").lower() if configured_format == "auto" else configured_format
    )
    if data_format == "jsonl":
        records = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path} line {line_number} must be an object")
            records.append(value)
        return records
    if data_format != "json":
        raise ValueError(f"unsupported local corpus format {data_format!r}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, list):
        records = value
    elif isinstance(value, dict):
        records = next(
            (value[key] for key in ("records", "items", "data", "notes") if key in value),
            [value],
        )
    else:
        raise ValueError(f"{path} must contain an object or array")
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValueError(f"{path} record collection must be an array of objects")
    return records


def _record_license(raw: dict[str, Any], default: LicenseDeclaration) -> LicenseDeclaration:
    override = raw.get("license")
    if override is None:
        return default
    if isinstance(override, str):
        return default.model_copy(update={"identifier": override})
    if not isinstance(override, dict):
        raise ValueError("record license must be a string or object")
    return LicenseDeclaration.model_validate({**default.model_dump(), **override})


def _record_kind(raw: dict[str, Any], source: CorpusSource) -> RecordKind:
    value = raw.get("record_kind") or raw.get("entry_type") or source.default_record_kind
    aliases = {
        "knowledge_document": RecordKind.KNOWLEDGE,
        "paper": RecordKind.KNOWLEDGE,
        "accepted_paper": RecordKind.KNOWLEDGE,
        "taste_case": RecordKind.TASTE,
        "review": RecordKind.TASTE,
        "rebuttal": RecordKind.TASTE,
        "meta_review": RecordKind.TASTE,
        "revision": RecordKind.TASTE,
    }
    if isinstance(value, RecordKind):
        return value
    normalized = str(value).casefold() if value is not None else ""
    try:
        return RecordKind(normalized)
    except ValueError:
        pass
    if normalized in aliases:
        return aliases[normalized]
    raise ValueError("record_kind must explicitly identify knowledge or taste")


def _normalize_record(
    raw: dict[str, Any],
    source: CorpusSource,
    kind: RecordKind,
    license_declaration: LicenseDeclaration,
    accessed_at: datetime,
    locator: str,
    index: int,
) -> tuple[KnowledgeDocument | TasteCase, str]:
    defaults = source.defaults
    if kind == RecordKind.KNOWLEDGE:
        core = {
            "title": _text(_pick(raw, defaults, "title", "paper_title")),
            "abstract": _text(_pick(raw, defaults, "abstract"), required=False),
            "content": _text(
                _pick(raw, defaults, "full_text", "text", "body", "paper_text", "content")
            ),
            "domain_tags": _strings(_pick(raw, defaults, "domain_tags", default=[])),
            "method_tags": _strings(_pick(raw, defaults, "method_tags", default=[])),
        }
        content_hash = _content_hash(core)
        provenance = _provenance(
            raw, source, kind, license_declaration, accessed_at, locator, index, content_hash
        )
        identifier = _identifier(
            raw,
            "document_id",
            "paper_id",
            fallback=f"{source.source_id}-knowledge-{content_hash[-12:]}",
        )
        return (
            KnowledgeDocument(document_id=identifier, provenance=[provenance], **core),
            content_hash,
        )

    core = {
        "stage": _text(_pick(raw, defaults, "stage")),
        "context_summary": _text(_pick(raw, defaults, "context_summary", "context", "situation")),
        "problem_pattern": _optional_text(_pick(raw, defaults, "problem_pattern")),
        "evidence_state": _optional_text(_pick(raw, defaults, "evidence_state")),
        "reviewer_context": _optional_text(_pick(raw, defaults, "reviewer_context", "review")),
        "candidate_actions": _strings(_pick(raw, defaults, "candidate_actions", "options")),
        "preferred_action": _text(_pick(raw, defaults, "preferred_action", "selected_action")),
        "rejected_actions": _strings(_pick(raw, defaults, "rejected_actions", default=[])),
        "decision_principle": _text(_pick(raw, defaults, "decision_principle", "principle")),
        "why_preferred": _text(_pick(raw, defaults, "why_preferred", "rationale")),
        "outcome_summary": _optional_text(_pick(raw, defaults, "outcome_summary", "outcome")),
        "confidence": float(_pick(raw, defaults, "confidence", default=0.5)),
        "domain_tags": _strings(_pick(raw, defaults, "domain_tags", default=[])),
        "venue_tags": _strings(_pick(raw, defaults, "venue_tags", "venues", default=[])),
        "rhetorical_role": _optional_text(_pick(raw, defaults, "rhetorical_role")),
        "figure_role": _optional_text(_pick(raw, defaults, "figure_role")),
        "label_basis": _text(_pick(raw, defaults, "label_basis", default="annotated")),
        "extractor_version": _optional_text(_pick(raw, defaults, "extractor_version")),
        "human_verified": _boolean(_pick(raw, defaults, "human_verified", default=False)),
        "outcome_horizon": _optional_text(_pick(raw, defaults, "outcome_horizon")),
        "source_action_id": _optional_text(_pick(raw, defaults, "source_action_id")),
    }
    content_hash = _content_hash(core)
    provenance = _provenance(
        raw, source, kind, license_declaration, accessed_at, locator, index, content_hash
    )
    identifier = _identifier(
        raw, "case_id", fallback=f"{source.source_id}-taste-{content_hash[-12:]}"
    )
    return TasteCase(case_id=identifier, provenance=[provenance], **core), content_hash


def _provenance(
    raw: dict[str, Any],
    source: CorpusSource,
    kind: RecordKind,
    declaration: LicenseDeclaration,
    accessed_at: datetime,
    locator: str,
    index: int,
    content_hash: str,
) -> ProvenanceRecord:
    metadata = {
        "source_id": source.source_id,
        "source_family": source.source_type.value,
        "record_kind": kind.value,
        "record_index": index,
        "license_status": declaration.status.value,
        "license_identifier": declaration.identifier,
        "license_locator": declaration.locator,
    }
    return ProvenanceRecord(
        source_type=source.source_type.value,
        locator=locator,
        title=_optional_text(_pick(raw, source.defaults, "title", "paper_title")),
        version=_optional_text(_pick(raw, source.defaults, "version")),
        content_hash=content_hash,
        accessed_at=accessed_at,
        license_id=declaration.identifier,
        license_url=declaration.locator,
        access_scope="local_snapshot",
        derivation_method=_optional_text(_pick(raw, source.defaults, "derivation_method")),
        redistributable=declaration.status == LicenseStatus.PERMITTED,
        personal_data_removed=_optional_boolean(
            _pick(raw, source.defaults, "personal_data_removed", default=None)
        ),
        metadata=metadata,
    )


def _pick(raw: dict[str, Any], defaults: dict[str, Any], *names: str, default: Any = None) -> Any:
    nested = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    for container in (raw, nested, defaults):
        for name in names:
            if name in container and container[name] is not None:
                value = container[name]
                if isinstance(value, dict) and "value" in value:
                    return value["value"]
                return value
    return default


def _identifier(raw: dict[str, Any], *names: str, fallback: str) -> str:
    for name in (*names, "id"):
        if raw.get(name):
            return str(raw[name])
    return fallback


def _text(value: Any, *, required: bool = True) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = _normalize_text(str(value)) if value is not None else ""
    if required and not text:
        raise ValueError("required text field is missing")
    return text


def _optional_text(value: Any) -> str | None:
    text = _text(value, required=False)
    return text or None


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError("expected a list of strings")
    return [_text(item) for item in value]


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected a boolean")
    return value


def _optional_boolean(value: Any) -> bool | None:
    return None if value is None else _boolean(value)


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _content_hash(core: dict[str, Any]) -> str:
    payload = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def _input_locator(path: Path, index: int, raw: dict[str, Any]) -> str:
    explicit = raw.get("source_locator") or raw.get("url")
    return str(explicit) if explicit else f"{path.as_uri()}#record={index}"


def _compact_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:500]


def _existing_hashes(records: list[KnowledgeDocument] | list[TasteCase]) -> set[str]:
    return {
        item.content_hash
        for record in records
        for item in record.provenance
        if item.content_hash is not None
    }


def _persist_new(records: list[Any], store: Any, existing_hashes: set[str]) -> int:
    imported = 0
    existing_ids = {getattr(record, store.id_field) for record in store.all()}
    for record in records:
        content_hash = record.provenance[0].content_hash
        identifier = getattr(record, store.id_field)
        if content_hash in existing_hashes:
            continue
        if identifier in existing_ids:
            raise ValueError(f"record id {identifier!r} has conflicting content")
        store.add(record)
        existing_hashes.add(content_hash)
        existing_ids.add(identifier)
        imported += 1
    return imported


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise

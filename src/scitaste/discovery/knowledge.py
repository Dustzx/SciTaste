"""Strict, project-owned Knowledge context for native Discovery retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.data.models import KnowledgeDocument
from scitaste.data.retrieval import rank_knowledge_documents
from scitaste.data.store import KnowledgeLibrary
from scitaste.discovery.landscape import LandscapeCategory, LandscapeFinding
from scitaste.project.models import content_sha256

_MAX_CONFIG_BYTES = 1_000_000
_CONTEXT_LOCATOR = "native_execution/context/DISCOVERY_KNOWLEDGE.json"
_KNOWLEDGE_LOCATOR = "native_execution/context/libraries/knowledge/records.jsonl"
_PLAN_LOCATOR = "native_execution/context/discovery_knowledge_plan.json"


class DiscoveryKnowledgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiscoveryKnowledgeEntry(DiscoveryKnowledgeModel):
    """One factual document and its explicit landscape projection."""

    category: LandscapeCategory
    statement: str = Field(min_length=1, max_length=4_000)
    document: KnowledgeDocument

    @model_validator(mode="after")
    def content_is_bounded(self) -> DiscoveryKnowledgeEntry:
        document = self.document
        text_fields = (document.document_id, document.title, document.abstract, document.content)
        if not self.statement.strip() or any(
            not item.strip() for item in (document.document_id, document.title, document.content)
        ):
            raise ValueError("discovery knowledge identity and content must not be blank")
        if any(len(item) > 20_000 for item in text_fields):
            raise ValueError("discovery knowledge text exceeds the per-field limit")
        if len(document.document_id) > 200 or len(document.title) > 1_000:
            raise ValueError("discovery knowledge identity exceeds its stricter limit")
        for tags in (document.domain_tags, document.method_tags):
            if len(tags) > 20 or any(not tag.strip() or len(tag) > 200 for tag in tags):
                raise ValueError("discovery knowledge tags must be bounded non-empty strings")
            if len({tag.casefold() for tag in tags}) != len(tags):
                raise ValueError("discovery knowledge tags must be distinct")
        if len(document.provenance) > 20:
            raise ValueError("discovery knowledge provenance exceeds the entry limit")
        return self


class DiscoveryKnowledgeConfig(DiscoveryKnowledgeModel):
    """Versioned local corpus allowed to enter one Discovery run."""

    schema_version: Literal["1.0"] = "1.0"
    entries: tuple[DiscoveryKnowledgeEntry, ...] = Field(min_length=1, max_length=40)

    @field_validator("entries")
    @classmethod
    def document_ids_are_unique(
        cls,
        values: tuple[DiscoveryKnowledgeEntry, ...],
    ) -> tuple[DiscoveryKnowledgeEntry, ...]:
        identifiers = [entry.document.document_id for entry in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("discovery knowledge document identifiers must be unique")
        return values


class DiscoveryKnowledgePlan(DiscoveryKnowledgeModel):
    """Deterministic retrieval result admitted before any semantic proposal."""

    schema_version: Literal["1.0"] = "1.0"
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query: str = Field(min_length=1, max_length=4_000)
    domain_tags: tuple[str, ...] = Field(max_length=20)
    limit: int = Field(ge=1, le=20)
    retrieved_document_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    retrieval_scores: dict[str, float] = Field(min_length=1, max_length=20)
    findings: tuple[LandscapeFinding, ...] = Field(min_length=1, max_length=20)
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **payload: Any) -> DiscoveryKnowledgePlan:
        unsigned = cls.model_construct(plan_sha256="0" * 64, **payload)
        return cls.model_validate(
            {
                **payload,
                "plan_sha256": content_sha256(
                    unsigned.model_dump(mode="json", exclude={"plan_sha256"})
                ),
            }
        )

    @model_validator(mode="after")
    def hash_and_sources_match(self) -> DiscoveryKnowledgePlan:
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("discovery knowledge plan hash mismatch")
        source_ids = [finding.source_ids for finding in self.findings]
        if source_ids != [[identifier] for identifier in self.retrieved_document_ids]:
            raise ValueError("discovery knowledge findings do not match retrieved documents")
        if list(self.retrieval_scores) != list(self.retrieved_document_ids) or any(
            not math.isfinite(score) or score <= 0 for score in self.retrieval_scores.values()
        ):
            raise ValueError("discovery knowledge scores do not match retrieved documents")
        return self


class DiscoveryKnowledgeReference(DiscoveryKnowledgeModel):
    """Self-hashed reference to an immutable, run-owned Knowledge context."""

    schema_version: Literal["1.0"] = "1.0"
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_locator: Literal["native_execution/context/DISCOVERY_KNOWLEDGE.json"] = _CONTEXT_LOCATOR
    knowledge_records_locator: Literal[
        "native_execution/context/libraries/knowledge/records.jsonl"
    ] = _KNOWLEDGE_LOCATOR
    knowledge_records_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_locator: Literal["native_execution/context/discovery_knowledge_plan.json"] = _PLAN_LOCATOR
    plan_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_count: int = Field(ge=1, le=40)
    retrieved_document_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **payload: Any) -> DiscoveryKnowledgeReference:
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls.model_validate(
            {
                **payload,
                "record_sha256": content_sha256(
                    unsigned.model_dump(mode="json", exclude={"record_sha256"})
                ),
            }
        )

    @model_validator(mode="after")
    def reference_hash_matches(self) -> DiscoveryKnowledgeReference:
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("discovery knowledge reference hash mismatch")
        for locator in (
            self.context_locator,
            self.knowledge_records_locator,
            self.plan_locator,
        ):
            _validate_locator(locator)
        return self


@dataclass(frozen=True)
class PreparedDiscoveryKnowledge:
    library: KnowledgeLibrary
    plan: DiscoveryKnowledgePlan
    reference: DiscoveryKnowledgeReference


@dataclass(frozen=True)
class DiscoveryKnowledgeBinding:
    source_path: Path
    source_config_sha256: str
    config: DiscoveryKnowledgeConfig
    fingerprint: str

    def plan(
        self,
        query: str,
        *,
        domain_tags: list[str],
        limit: int = 5,
    ) -> DiscoveryKnowledgePlan:
        results = rank_knowledge_documents(
            (entry.document for entry in self.config.entries),
            query,
            domain_tags=domain_tags,
            limit=limit,
        )
        if not results:
            raise ValueError("registered Discovery knowledge returned no relevant document")
        by_id = {entry.document.document_id: entry for entry in self.config.entries}
        identifiers = tuple(result.document.document_id for result in results)
        return DiscoveryKnowledgePlan.create(
            schema_version="1.0",
            binding_sha256=self.fingerprint,
            source_config_sha256=self.source_config_sha256,
            query=query.strip(),
            domain_tags=tuple(domain_tags),
            limit=limit,
            retrieved_document_ids=identifiers,
            retrieval_scores={result.document.document_id: result.score for result in results},
            findings=tuple(
                LandscapeFinding(
                    category=by_id[identifier].category,
                    statement=by_id[identifier].statement,
                    source_ids=[identifier],
                )
                for identifier in identifiers
            ),
        )

    def prepare(
        self,
        run_root: str | Path,
        plan: DiscoveryKnowledgePlan,
    ) -> PreparedDiscoveryKnowledge:
        root = _owned_root(run_root)
        if plan.binding_sha256 != self.fingerprint:
            raise ValueError("Discovery knowledge plan belongs to another binding")
        receipt_path = root / _CONTEXT_LOCATOR
        if receipt_path.is_file():
            reference = _load_reference(receipt_path)
            expected = (
                self.fingerprint,
                self.source_config_sha256,
                plan.plan_sha256,
                plan.retrieved_document_ids,
            )
            observed = (
                reference.binding_sha256,
                reference.source_config_sha256,
                reference.plan_sha256,
                reference.retrieved_document_ids,
            )
            if observed != expected:
                raise ValueError("Discovery knowledge context differs from the requested binding")
            return verify_discovery_knowledge_context(root, reference, expected_plan=plan)
        if receipt_path.exists():
            raise ValueError("Discovery knowledge context receipt is not a regular file")
        context_root = receipt_path.parent
        if context_root.is_symlink() or context_root.exists():
            raise ValueError("incomplete Discovery knowledge context requires manual inspection")
        native_root = context_root.parent
        native_root.mkdir(parents=True, exist_ok=True)
        if native_root.is_symlink() or not native_root.is_dir():
            raise ValueError("Discovery native execution root must be an owned directory")
        temporary = Path(tempfile.mkdtemp(prefix=".knowledge-context-", dir=native_root))
        try:
            knowledge_path = temporary / "libraries/knowledge/records.jsonl"
            library = KnowledgeLibrary(knowledge_path)
            for entry in self.config.entries:
                library.upsert(entry.document)
            plan_path = temporary / "discovery_knowledge_plan.json"
            _atomic_text(plan_path, plan.model_dump_json(indent=2) + "\n")
            reference = DiscoveryKnowledgeReference.create(
                schema_version="1.0",
                binding_sha256=self.fingerprint,
                source_config_sha256=self.source_config_sha256,
                plan_sha256=plan.plan_sha256,
                context_locator=_CONTEXT_LOCATOR,
                knowledge_records_locator=_KNOWLEDGE_LOCATOR,
                knowledge_records_sha256=_file_sha256(knowledge_path),
                plan_locator=_PLAN_LOCATOR,
                plan_file_sha256=_file_sha256(plan_path),
                knowledge_count=len(self.config.entries),
                retrieved_document_ids=plan.retrieved_document_ids,
            )
            _atomic_text(
                temporary / "DISCOVERY_KNOWLEDGE.json",
                reference.model_dump_json(indent=2) + "\n",
            )
            os.replace(temporary, context_root)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return verify_discovery_knowledge_context(root, reference, expected_plan=plan)


def load_discovery_knowledge_binding(path: str | Path) -> DiscoveryKnowledgeBinding:
    """Load one exact local corpus without accepting duplicate or unknown fields."""

    source = Path(path).expanduser()
    if source.is_symlink():
        raise ValueError("Discovery knowledge configuration cannot be a symlink")
    source = source.resolve(strict=True)
    if not source.is_file():
        raise ValueError("Discovery knowledge configuration must be a regular file")
    raw = source.read_bytes()
    if len(raw) > _MAX_CONFIG_BYTES:
        raise ValueError("Discovery knowledge configuration exceeds the size limit")
    try:
        parsed = yaml.load(raw.decode("utf-8"), Loader=_UniqueKeyLoader)
        config = DiscoveryKnowledgeConfig.model_validate_json(
            json.dumps(parsed, ensure_ascii=False, allow_nan=False),
            strict=True,
        )
    except (TypeError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError("invalid Discovery knowledge configuration") from exc
    source_sha256 = hashlib.sha256(raw).hexdigest()
    fingerprint = content_sha256(
        {
            "schema_version": "1.0",
            "source_config_sha256": source_sha256,
            "config": config.model_dump(mode="json"),
        }
    )
    return DiscoveryKnowledgeBinding(
        source_path=source,
        source_config_sha256=source_sha256,
        config=config,
        fingerprint=fingerprint,
    )


def verify_discovery_knowledge_context(
    run_root: str | Path,
    reference: DiscoveryKnowledgeReference,
    *,
    expected_plan: DiscoveryKnowledgePlan | None = None,
) -> PreparedDiscoveryKnowledge:
    """Verify the copied corpus, retrieval plan, and self-hashed context receipt."""

    root = _owned_root(run_root)
    receipt_path = _verified_file(root, reference.context_locator)
    persisted_reference = _load_reference(receipt_path)
    if persisted_reference != reference:
        raise ValueError("Discovery knowledge receipt differs from its project reference")
    knowledge_path = _verified_file(
        root,
        reference.knowledge_records_locator,
        reference.knowledge_records_sha256,
    )
    plan_path = _verified_file(root, reference.plan_locator, reference.plan_file_sha256)
    try:
        plan = DiscoveryKnowledgePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid project-owned Discovery knowledge plan") from exc
    if plan.plan_sha256 != reference.plan_sha256:
        raise ValueError("Discovery knowledge plan differs from its context reference")
    if (
        plan.binding_sha256 != reference.binding_sha256
        or plan.source_config_sha256 != reference.source_config_sha256
        or plan.retrieved_document_ids != reference.retrieved_document_ids
    ):
        raise ValueError("Discovery knowledge plan identity differs from its context reference")
    if expected_plan is not None and plan != expected_plan:
        raise ValueError("project-owned Discovery knowledge plan differs from the request")
    library = KnowledgeLibrary(knowledge_path)
    documents = library.all()
    if len(documents) != reference.knowledge_count:
        raise ValueError("Discovery knowledge document count differs from its context")
    known = {document.document_id for document in documents}
    if set(reference.retrieved_document_ids) - known:
        raise ValueError("Discovery knowledge plan references an absent document")
    reproduced = rank_knowledge_documents(
        documents,
        plan.query,
        domain_tags=list(plan.domain_tags),
        limit=plan.limit,
    )
    reproduced_ids = tuple(item.document.document_id for item in reproduced)
    reproduced_scores = {item.document.document_id: item.score for item in reproduced}
    if reproduced_ids != plan.retrieved_document_ids or reproduced_scores != plan.retrieval_scores:
        raise ValueError("Discovery knowledge plan cannot be reproduced from its copied corpus")
    return PreparedDiscoveryKnowledge(library=library, plan=plan, reference=reference)


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate configuration key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_reference(path: Path) -> DiscoveryKnowledgeReference:
    try:
        return DiscoveryKnowledgeReference.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid project-owned Discovery knowledge reference") from exc


def _owned_root(path: str | Path) -> Path:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Discovery knowledge run root must be an owned directory")
    return root.resolve(strict=True)


def _verified_file(
    root: Path,
    locator: str,
    expected_sha256: str | None = None,
) -> Path:
    _validate_locator(locator)
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Discovery knowledge locator contains a symlink: {locator}")
    if not current.is_file():
        raise ValueError(f"Discovery knowledge locator is not a regular file: {locator}")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Discovery knowledge locator escapes its run") from exc
    if expected_sha256 is not None and _file_sha256(resolved) != expected_sha256:
        raise ValueError(f"Discovery knowledge artifact hash mismatch: {locator}")
    return resolved


def _validate_locator(locator: str) -> str:
    path = PurePosixPath(locator)
    if (
        "\\" in locator
        or "//" in locator
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Discovery knowledge locators must be normalized relative paths")
    return locator


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


__all__ = [
    "DiscoveryKnowledgeBinding",
    "DiscoveryKnowledgeConfig",
    "DiscoveryKnowledgeEntry",
    "DiscoveryKnowledgePlan",
    "DiscoveryKnowledgeReference",
    "PreparedDiscoveryKnowledge",
    "load_discovery_knowledge_binding",
    "verify_discovery_knowledge_context",
]

"""Local JSONL stores with hard separation between knowledge and taste records."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Generic, TypeVar

import yaml
from pydantic import BaseModel

from scitaste.data.models import KnowledgeDocument, TasteCase

RecordT = TypeVar("RecordT", bound=BaseModel)


class DuplicateRecordError(ValueError):
    """Raised when add() would silently replace an existing library record."""


class _JsonlStore(Generic[RecordT]):
    model_type: type[RecordT]
    id_field: str

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def add(self, record: RecordT) -> None:
        self._validate_type(record)
        records = self._load_map()
        identifier = str(getattr(record, self.id_field))
        if identifier in records:
            raise DuplicateRecordError(identifier)
        records[identifier] = record
        self._write(records)

    def upsert(self, record: RecordT) -> None:
        self._validate_type(record)
        records = self._load_map()
        records[str(getattr(record, self.id_field))] = record
        self._write(records)

    def get(self, identifier: str) -> RecordT:
        try:
            return self._load_map()[identifier]
        except KeyError as exc:
            raise KeyError(f"unknown record {identifier!r}") from exc

    def all(self) -> list[RecordT]:
        return list(self._load_map().values())

    def __len__(self) -> int:
        return len(self._load_map())

    def _validate_type(self, record: RecordT) -> None:
        if not isinstance(record, self.model_type):
            raise TypeError(f"{type(self).__name__} accepts only {self.model_type.__name__}")

    def _load_map(self) -> dict[str, RecordT]:
        if not self.path.exists():
            return {}
        records: dict[str, RecordT] = {}
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = self.model_type.model_validate_json(line)
            except ValueError as exc:
                raise ValueError(f"invalid {self.path.name} line {line_number}") from exc
            identifier = str(getattr(record, self.id_field))
            if identifier in records:
                raise ValueError(f"duplicate id {identifier!r} in {self.path}")
            records[identifier] = record
        return records

    def _write(self, records: dict[str, RecordT]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        contents = "".join(
            records[identifier].model_dump_json() + "\n" for identifier in sorted(records)
        )
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary).replace(self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


class KnowledgeLibrary(_JsonlStore[KnowledgeDocument]):
    """Typed factual store; it cannot accept TasteCase objects."""

    model_type = KnowledgeDocument
    id_field = "document_id"


class TasteLibrary(_JsonlStore[TasteCase]):
    """Typed decision-precedent store; it cannot accept knowledge documents."""

    model_type = TasteCase
    id_field = "case_id"


def build_libraries(config_path: str | Path, output_dir: str | Path) -> dict[str, int | str]:
    """Build both stores from one manifest while preserving separate schemas/files."""

    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise ValueError("library build config must be a mapping")
    root = Path(output_dir)
    knowledge = KnowledgeLibrary(root / "knowledge" / "records.jsonl")
    taste = TasteLibrary(root / "taste" / "records.jsonl")
    for raw in config.get("knowledge_documents", []):
        knowledge.upsert(KnowledgeDocument.model_validate(raw))
    for raw in config.get("taste_cases", []):
        taste.upsert(TasteCase.model_validate(raw))
    manifest = {
        "schema_version": "1.0",
        "knowledge_count": len(knowledge),
        "taste_count": len(taste),
        "knowledge_path": str(knowledge.path),
        "taste_path": str(taste.path),
    }
    (root / "library_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest

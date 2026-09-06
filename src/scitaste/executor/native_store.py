"""Project-owned, content-bound evidence for first-party action execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.project.models import content_sha256
from scitaste.schema.actions import ResearchAction
from scitaste.state.research_state import ResearchState

_RECORD_NAME = re.compile(r"^(?P<sequence>[0-9]{6})-(?P<token>[0-9a-f]{12})\.json$")


class NativeExecutionRecord(BaseModel):
    """One immutable native action record chained to its predecessor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    sequence: int = Field(ge=1)
    previous_record_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    project_id: str = Field(min_length=1)
    state_revision: int = Field(ge=0)
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: ResearchAction
    action_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capability: str = Field(min_length=1)
    input_sha256: dict[str, str] = Field(default_factory=dict)
    artifact_sha256: dict[str, str] = Field(default_factory=dict)
    result: ExecutionResult
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("input_sha256", "artifact_sha256")
    @classmethod
    def locator_hashes_are_valid(cls, value: dict[str, str]) -> dict[str, str]:
        for locator, digest in value.items():
            _validate_locator(locator)
            if not _is_sha256(digest):
                raise ValueError("native execution file hashes must be SHA-256 values")
        return value

    @model_validator(mode="after")
    def hashes_match(self) -> NativeExecutionRecord:
        if self.action_sha256 != content_sha256(self.action.model_dump(mode="json")):
            raise ValueError("native execution action hash mismatch")
        if self.result.action_id != self.action.action_id:
            raise ValueError("native execution result belongs to another action")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("native execution record hash mismatch")
        return self


class NativeExecutionVerification(BaseModel):
    """Verified head of one native action record chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_count: int = Field(ge=0)
    head_record_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    head_record_locator: str | None = None


class NativeExecutionStore:
    """Append and verify native action evidence beneath one project run."""

    def __init__(self, workspace: str | Path, *, artifact_root: str | Path) -> None:
        self.workspace = Path(workspace)
        self.artifact_root = Path(artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        if self.artifact_root.is_symlink():
            raise ValueError("native execution artifact root cannot be a symlink")
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.workspace.is_symlink():
            raise ValueError("native execution workspace cannot be a symlink")
        self._relative_to_root(self.workspace)
        self.records_root = self.workspace / "records"
        self.artifacts_root = self.workspace / "artifacts"
        self.records_root.mkdir(exist_ok=True)
        self.artifacts_root.mkdir(exist_ok=True)
        if self.records_root.is_symlink() or self.artifacts_root.is_symlink():
            raise ValueError("native execution storage directories cannot be symlinks")
        self.verify()

    def locator(self, path: str | Path) -> str:
        return self._relative_to_root(Path(path)).as_posix()

    def artifact_directory(self, result_id: str) -> Path:
        token = hashlib.sha256(result_id.encode()).hexdigest()[:16]
        target = self.artifacts_root / token
        target.mkdir(mode=0o700, exist_ok=True)
        if target.is_symlink() or not target.is_dir():
            raise ValueError("native execution artifact directory is not an owned directory")
        return target

    def write_artifact_json(self, result_id: str, name: str, payload: object) -> Path:
        if Path(name).name != name or name in {"", ".", ".."}:
            raise ValueError("native execution artifact name must be one safe path segment")
        path = self.artifact_directory(result_id) / name
        _write_exclusive_json(path, payload)
        return path

    def publish(
        self,
        *,
        state: ResearchState,
        action: ResearchAction,
        capability: str,
        result: ExecutionResult,
        input_paths: tuple[Path, ...] = (),
    ) -> tuple[NativeExecutionRecord, str]:
        records = self._load_verified_records()
        sequence = len(records) + 1
        previous = records[-1][1].record_sha256 if records else None
        inputs = self._hash_paths(input_paths)
        artifacts = self._hash_result_artifacts(result)
        payload = {
            "schema_version": "1.0",
            "sequence": sequence,
            "previous_record_sha256": previous,
            "project_id": state.project_id,
            "state_revision": state.revision,
            "state_sha256": content_sha256(state.model_dump(mode="json")),
            "action": action.model_dump(mode="json"),
            "action_sha256": content_sha256(action.model_dump(mode="json")),
            "capability": capability,
            "input_sha256": inputs,
            "artifact_sha256": artifacts,
            "result": result.model_dump(mode="json"),
        }
        record = NativeExecutionRecord(
            **payload,
            record_sha256=content_sha256(payload),
        )
        token = hashlib.sha256(action.action_id.encode()).hexdigest()[:12]
        path = self.records_root / f"{sequence:06d}-{token}.json"
        _write_exclusive_json(path, record.model_dump(mode="json"))
        return record, self.locator(path)

    def verify(self) -> NativeExecutionVerification:
        records = self._load_verified_records()
        if not records:
            return NativeExecutionVerification(record_count=0)
        path, record = records[-1]
        return NativeExecutionVerification(
            record_count=len(records),
            head_record_sha256=record.record_sha256,
            head_record_locator=self.locator(path),
        )

    def entries(self) -> tuple[tuple[str, NativeExecutionRecord], ...]:
        """Return the verified record chain with project-relative locators."""

        return tuple((self.locator(path), record) for path, record in self._load_verified_records())

    def recover_successful(
        self,
        *,
        state: ResearchState,
        action: ResearchAction,
        capability: str,
    ) -> tuple[NativeExecutionRecord, str] | None:
        """Reuse one exact successful action during explicit workflow recovery."""

        state_sha256 = content_sha256(state.model_dump(mode="json"))
        action_sha256 = content_sha256(action.model_dump(mode="json"))
        for path, record in reversed(self._load_verified_records()):
            if (
                record.project_id == state.project_id
                and record.state_sha256 == state_sha256
                and record.action_sha256 == action_sha256
                and record.capability == capability
                and record.result.status is ExecutionStatus.SUCCEEDED
            ):
                return record, self.locator(path)
        return None

    def _load_verified_records(self) -> list[tuple[Path, NativeExecutionRecord]]:
        records: list[tuple[Path, NativeExecutionRecord]] = []
        previous: str | None = None
        project_id: str | None = None
        for expected_sequence, path in enumerate(sorted(self.records_root.glob("*.json")), 1):
            if path.is_symlink() or not path.is_file():
                raise ValueError("native execution records must be regular files")
            match = _RECORD_NAME.fullmatch(path.name)
            if match is None or int(match.group("sequence")) != expected_sequence:
                raise ValueError("native execution record sequence is not contiguous")
            try:
                record = NativeExecutionRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                raise ValueError(f"invalid native execution record: {path.name}") from exc
            expected_token = hashlib.sha256(record.action.action_id.encode()).hexdigest()[:12]
            if match.group("token") != expected_token:
                raise ValueError("native execution record filename does not match its action")
            if record.sequence != expected_sequence:
                raise ValueError("native execution record sequence mismatch")
            if record.previous_record_sha256 != previous:
                raise ValueError("native execution predecessor hash mismatch")
            if project_id is not None and record.project_id != project_id:
                raise ValueError("native execution records mix project identities")
            self._verify_hashes(record.input_sha256)
            self._verify_hashes(record.artifact_sha256)
            records.append((path, record))
            previous = record.record_sha256
            project_id = record.project_id
        return records

    def _hash_paths(self, paths: tuple[Path, ...]) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for path in paths:
            locator = self.locator(path)
            if locator in hashes:
                raise ValueError("native execution input paths must be unique")
            hashes[locator] = _verified_file_sha256(self.artifact_root, locator)
        return hashes

    def _hash_result_artifacts(self, result: ExecutionResult) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for locator in result.artifacts:
            _validate_locator(locator)
            if locator in hashes:
                raise ValueError("native execution artifact locators must be unique")
            hashes[locator] = _verified_file_sha256(self.artifact_root, locator)
        return hashes

    def _verify_hashes(self, hashes: dict[str, str]) -> None:
        for locator, expected in hashes.items():
            if _verified_file_sha256(self.artifact_root, locator) != expected:
                raise ValueError(f"native execution artifact hash mismatch: {locator}")

    def _relative_to_root(self, path: Path) -> Path:
        root = self.artifact_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        try:
            return resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("native execution path escapes its artifact root") from exc


def _verified_file_sha256(root: Path, locator: str) -> str:
    _validate_locator(locator)
    resolved_root = root.resolve(strict=True)
    path = root / locator
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"native execution locator contains a symlink: {locator}")
    if not path.is_file():
        raise ValueError(f"native execution locator is not a regular file: {locator}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"native execution locator escapes its artifact root: {locator}") from exc
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_exclusive_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _validate_locator(locator: str) -> str:
    if "\\" in locator or "//" in locator:
        raise ValueError("native execution locators must use normalized POSIX separators")
    path = PurePosixPath(locator)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("native execution locators must be normalized relative paths")
    return locator


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "NativeExecutionRecord",
    "NativeExecutionStore",
    "NativeExecutionVerification",
]

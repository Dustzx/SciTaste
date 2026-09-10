"""Project-owned research workspace and turn history for the local interface."""

from __future__ import annotations

import json
import os
import secrets
import stat
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.generative_ui.audit import AuditIntegrityError
from scitaste.generative_ui.generation import (
    GeneratedWorkspaceDocument,
    WorkspaceGenerationRequest,
)
from scitaste.generative_ui.intent import FreeQuestionRequest, QuickIntentRequest
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, Sha256
from scitaste.project.models import validate_entry_id, validate_project_id

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_MAX_STORE_FILE_BYTES = 4 * 1024 * 1024


class ResearchTurnPrompt(BaseModel):
    """User-visible local prompt retained as inert text for conversation continuity."""

    model_config = _MODEL_CONFIG

    kind: Literal["quick", "free_question"]
    text: str = Field(min_length=1, max_length=1000)


class ResearchTurnRecord(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    workspace_id: SafeIdentifier
    turn_id: SafeIdentifier
    ordinal: int = Field(ge=1)
    parent_turn_id: SafeIdentifier | None = None
    created_at: datetime
    prompt: ResearchTurnPrompt
    request_fingerprint: Sha256
    generation_id: SafeIdentifier | None = None
    document: GeneratedWorkspaceDocument

    @model_validator(mode="after")
    def document_is_bound_to_turn(self) -> ResearchTurnRecord:
        if self.document.project_id != self.project_id:
            raise ValueError("turn document must belong to its project")
        observed_generation = (
            self.document.renderer.surface_id if self.document.renderer is not None else None
        )
        if observed_generation != self.generation_id:
            raise ValueError("turn generation identity does not match its document")
        if self.ordinal == 1 and self.parent_turn_id is not None:
            raise ValueError("first turn cannot have a parent")
        if self.ordinal > 1 and self.parent_turn_id is None:
            raise ValueError("follow-up turn requires its parent")
        return self


class ResearchWorkspaceRecord(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    workspace_id: SafeIdentifier
    title: str = Field(min_length=1, max_length=120)
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=1)
    latest_turn_id: SafeIdentifier
    turn_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def latest_turn_is_registered(self) -> ResearchWorkspaceRecord:
        if self.latest_turn_id != self.turn_ids[-1]:
            raise ValueError("latest turn must be the final registered turn")
        if len(self.turn_ids) != len(set(self.turn_ids)) or self.revision != len(self.turn_ids):
            raise ValueError("workspace revision must match its unique turn sequence")
        if self.updated_at < self.created_at:
            raise ValueError("workspace update time cannot precede creation")
        return self


class ResearchTurnSummary(BaseModel):
    model_config = _MODEL_CONFIG

    turn_id: SafeIdentifier
    ordinal: int = Field(ge=1)
    created_at: datetime
    prompt: ResearchTurnPrompt
    generation_id: SafeIdentifier | None = None
    status: str = Field(min_length=1, max_length=64)


class ResearchWorkspaceSummary(BaseModel):
    model_config = _MODEL_CONFIG

    workspace_id: SafeIdentifier
    title: str = Field(min_length=1, max_length=120)
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=1)
    latest_turn_id: SafeIdentifier
    latest_status: str = Field(min_length=1, max_length=64)


class ResearchWorkspaceCatalog(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: ProjectIdentifier
    workspaces: tuple[ResearchWorkspaceSummary, ...]

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class ResearchWorkspaceDetail(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    workspace: ResearchWorkspaceRecord
    turns: tuple[ResearchTurnSummary, ...]


class ResearchWorkspaceTurnDocument(BaseModel):
    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    workspace: ResearchWorkspaceRecord
    turn: ResearchTurnRecord

    @model_validator(mode="after")
    def turn_is_registered(self) -> ResearchWorkspaceTurnDocument:
        if self.turn.project_id != self.workspace.project_id:
            raise ValueError("turn and workspace projects must match")
        if self.turn.workspace_id != self.workspace.workspace_id:
            raise ValueError("turn and workspace identities must match")
        if self.turn.turn_id not in self.workspace.turn_ids:
            raise ValueError("turn must be registered by its workspace")
        return self


class ResearchWorkspaceStore:
    """Append-only turns with an atomically replaced project-local index."""

    def __init__(self, projects_root: Path) -> None:
        self._projects_root = projects_root

    def create(
        self,
        project_id: str,
        request: WorkspaceGenerationRequest,
        document: GeneratedWorkspaceDocument,
    ) -> ResearchWorkspaceTurnDocument:
        root = self._root(project_id, create=True)
        for _ in range(8):
            workspace_id = f"workspace-{secrets.token_hex(8)}"
            directory = root / workspace_id
            try:
                directory.mkdir(mode=0o700)
                break
            except FileExistsError:
                continue
        else:  # pragma: no cover - cryptographic collision defense
            raise AuditIntegrityError("could not allocate a research workspace identity")
        now = datetime.now(UTC)
        turn = _turn_record(
            project_id=project_id,
            workspace_id=workspace_id,
            ordinal=1,
            parent_turn_id=None,
            created_at=now,
            request=request,
            document=document,
        )
        workspace = ResearchWorkspaceRecord(
            project_id=project_id,
            workspace_id=workspace_id,
            title=_workspace_title(turn.prompt.text),
            created_at=now,
            updated_at=now,
            revision=1,
            latest_turn_id=turn.turn_id,
            turn_ids=(turn.turn_id,),
        )
        _write_immutable(directory / f"{turn.turn_id}.json", _model_bytes(turn))
        _replace_regular(directory / "workspace.json", _model_bytes(workspace))
        return ResearchWorkspaceTurnDocument(workspace=workspace, turn=turn)

    def append(
        self,
        project_id: str,
        workspace_id: str,
        request: WorkspaceGenerationRequest,
        document: GeneratedWorkspaceDocument,
    ) -> ResearchWorkspaceTurnDocument:
        directory = self._workspace_directory(project_id, workspace_id)
        workspace = self._load_workspace(directory)
        if workspace.project_id != project_id:
            raise AuditIntegrityError("research workspace belongs to another project")
        now = datetime.now(UTC)
        ordinal = workspace.revision + 1
        turn = _turn_record(
            project_id=project_id,
            workspace_id=workspace_id,
            ordinal=ordinal,
            parent_turn_id=workspace.latest_turn_id,
            created_at=now,
            request=request,
            document=document,
        )
        updated = workspace.model_copy(
            update={
                "updated_at": now,
                "revision": ordinal,
                "latest_turn_id": turn.turn_id,
                "turn_ids": (*workspace.turn_ids, turn.turn_id),
            }
        )
        updated = ResearchWorkspaceRecord.model_validate(updated.model_dump(mode="json"))
        _write_immutable(directory / f"{turn.turn_id}.json", _model_bytes(turn))
        _replace_regular(directory / "workspace.json", _model_bytes(updated))
        return ResearchWorkspaceTurnDocument(workspace=updated, turn=turn)

    def catalog(self, project_id: str) -> ResearchWorkspaceCatalog:
        root = self._root(project_id, create=False)
        if not root.exists():
            return ResearchWorkspaceCatalog(project_id=project_id, workspaces=())
        summaries: list[ResearchWorkspaceSummary] = []
        for directory in root.iterdir():
            if directory.is_symlink() or not directory.is_dir():
                continue
            try:
                validate_entry_id(directory.name, field_name="workspace_id")
                workspace = self._load_workspace(directory)
                latest = self._load_turn(directory, workspace.latest_turn_id)
            except (AuditIntegrityError, ValueError) as exc:
                raise AuditIntegrityError(
                    "research workspace catalog contains invalid state"
                ) from exc
            summaries.append(
                ResearchWorkspaceSummary(
                    workspace_id=workspace.workspace_id,
                    title=workspace.title,
                    created_at=workspace.created_at,
                    updated_at=workspace.updated_at,
                    revision=workspace.revision,
                    latest_turn_id=workspace.latest_turn_id,
                    latest_status=latest.document.status,
                )
            )
        summaries.sort(key=lambda item: (item.updated_at, item.workspace_id), reverse=True)
        return ResearchWorkspaceCatalog(project_id=project_id, workspaces=tuple(summaries))

    def detail(self, project_id: str, workspace_id: str) -> ResearchWorkspaceDetail:
        directory = self._workspace_directory(project_id, workspace_id)
        workspace = self._load_workspace(directory)
        turns = tuple(
            _turn_summary(self._load_turn(directory, turn_id)) for turn_id in workspace.turn_ids
        )
        return ResearchWorkspaceDetail(workspace=workspace, turns=turns)

    def turn(
        self,
        project_id: str,
        workspace_id: str,
        turn_id: str,
    ) -> ResearchWorkspaceTurnDocument:
        directory = self._workspace_directory(project_id, workspace_id)
        workspace = self._load_workspace(directory)
        validate_entry_id(turn_id, field_name="turn_id")
        if turn_id not in workspace.turn_ids:
            raise FileNotFoundError("research turn was not found")
        turn = self._load_turn(directory, turn_id)
        return ResearchWorkspaceTurnDocument(workspace=workspace, turn=turn)

    def _root(self, project_id: str, *, create: bool) -> Path:
        validate_project_id(project_id)
        projects_root = self._projects_root.resolve(strict=True)
        project = self._projects_root / project_id
        if project.is_symlink():
            raise AuditIntegrityError("research workspace project cannot be a symbolic link")
        resolved_project = project.resolve(strict=True)
        try:
            resolved_project.relative_to(projects_root)
        except ValueError as exc:
            raise AuditIntegrityError("research workspace project escapes projects root") from exc
        root = resolved_project / ".generative-ui" / "workspaces"
        if root.is_symlink() or root.parent.is_symlink():
            raise AuditIntegrityError("research workspace root cannot be a symbolic link")
        if create:
            root.mkdir(parents=True, exist_ok=True)
        return root

    def _workspace_directory(self, project_id: str, workspace_id: str) -> Path:
        validate_entry_id(workspace_id, field_name="workspace_id")
        directory = self._root(project_id, create=False) / workspace_id
        if directory.is_symlink() or not directory.is_dir():
            raise FileNotFoundError("research workspace was not found")
        return directory

    @staticmethod
    def _load_workspace(directory: Path) -> ResearchWorkspaceRecord:
        workspace = ResearchWorkspaceRecord.model_validate_json(
            _read_regular(directory / "workspace.json")
        )
        if workspace.workspace_id != directory.name:
            raise AuditIntegrityError("research workspace path does not match its identity")
        return workspace

    @staticmethod
    def _load_turn(directory: Path, turn_id: str) -> ResearchTurnRecord:
        turn = ResearchTurnRecord.model_validate_json(_read_regular(directory / f"{turn_id}.json"))
        if turn.workspace_id != directory.name or turn.turn_id != turn_id:
            raise AuditIntegrityError("research turn path does not match its identity")
        return turn


def _turn_record(
    *,
    project_id: str,
    workspace_id: str,
    ordinal: int,
    parent_turn_id: str | None,
    created_at: datetime,
    request: WorkspaceGenerationRequest,
    document: GeneratedWorkspaceDocument,
) -> ResearchTurnRecord:
    intent = request.intent_request
    if isinstance(intent, QuickIntentRequest):
        prompt = ResearchTurnPrompt(kind="quick", text=intent.quick_intent_id)
    elif isinstance(intent, FreeQuestionRequest):
        prompt = ResearchTurnPrompt(kind="free_question", text=intent.question)
    else:  # pragma: no cover - closed discriminated union
        raise TypeError("unsupported research turn intent")
    return ResearchTurnRecord(
        project_id=project_id,
        workspace_id=workspace_id,
        turn_id=f"turn-{ordinal:04d}",
        ordinal=ordinal,
        parent_turn_id=parent_turn_id,
        created_at=created_at,
        prompt=prompt,
        request_fingerprint=request.fingerprint,
        generation_id=document.renderer.surface_id if document.renderer is not None else None,
        document=document,
    )


def _workspace_title(prompt: str) -> str:
    compact = " ".join(prompt.split())
    return compact if len(compact) <= 96 else compact[:95].rstrip() + "…"


def _turn_summary(turn: ResearchTurnRecord) -> ResearchTurnSummary:
    return ResearchTurnSummary(
        turn_id=turn.turn_id,
        ordinal=turn.ordinal,
        created_at=turn.created_at,
        prompt=turn.prompt,
        generation_id=turn.generation_id,
        status=turn.document.status,
    )


def _fingerprint(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _model_bytes(model: BaseModel) -> bytes:
    return _canonical_bytes(model.model_dump(mode="json"))


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_immutable(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise AuditIntegrityError("research turn files cannot be symbolic links")
    if path.exists():
        if _read_regular(path) != content:
            raise AuditIntegrityError("research turn history is immutable")
        return
    _write_temporary_and_replace(path, content)


def _replace_regular(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise AuditIntegrityError("research workspace manifest cannot be a symbolic link")
    _write_temporary_and_replace(path, content)


def _write_temporary_and_replace(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _read_regular(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not hasattr(os, "O_NOFOLLOW") and path.is_symlink():
        raise AuditIntegrityError("research workspace files cannot be symbolic links")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AuditIntegrityError("research workspace is incomplete") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_STORE_FILE_BYTES:
            raise AuditIntegrityError("research workspace file is invalid")
        content = os.read(descriptor, _MAX_STORE_FILE_BYTES + 1)
        if len(content) > _MAX_STORE_FILE_BYTES:
            raise AuditIntegrityError("research workspace file is too large")
        return content
    finally:
        os.close(descriptor)


__all__ = [
    "ResearchTurnPrompt",
    "ResearchTurnRecord",
    "ResearchTurnSummary",
    "ResearchWorkspaceCatalog",
    "ResearchWorkspaceDetail",
    "ResearchWorkspaceRecord",
    "ResearchWorkspaceStore",
    "ResearchWorkspaceSummary",
    "ResearchWorkspaceTurnDocument",
]

"""Bounded multi-file research patches for benchmark task workspaces.

Models may propose replacement text for exact editable files, but they never
receive filesystem or process authority.  The controller snapshots selected
source, deterministically admits a proposal against current bytes, and applies
an accepted replacement transaction only under an explicit mutation switch.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.task_runtime import (
    BenchmarkTaskRuntimeSpec,
    PreparedBenchmarkWorkspace,
    hash_protected_surface,
)
from scitaste.project.models import content_sha256, validate_entry_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_FILE_BYTES = 1_048_576
_MAX_CONTEXT_BYTES = 1_048_576


class BenchmarkPatchPolicy(BaseModel):
    """Controller-owned limits; a model cannot widen this policy."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str = "benchmark-replacement-v1"
    maximum_files_per_patch: int = Field(default=12, ge=1, le=50)
    maximum_replacement_bytes_per_file: int = Field(
        default=262_144,
        ge=1,
        le=_MAX_FILE_BYTES,
    )
    maximum_replacement_bytes_total: int = Field(
        default=524_288,
        ge=1,
        le=5_242_880,
    )
    allowed_suffixes: tuple[str, ...] = (".json", ".py", ".yaml", ".yml")

    @field_validator("policy_id")
    @classmethod
    def policy_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="policy_id")

    @field_validator("allowed_suffixes")
    @classmethod
    def suffixes_are_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or len(values) > 32:
            raise ValueError("benchmark patch policy requires allowed suffixes")
        if any(not value.startswith(".") or "/" in value for value in values):
            raise ValueError("benchmark patch suffixes must be simple extensions")
        if tuple(sorted(set(values))) != values:
            raise ValueError("benchmark patch suffixes must be unique and sorted")
        return values

    @model_validator(mode="after")
    def total_limit_can_hold_one_file(self) -> BenchmarkPatchPolicy:
        if self.maximum_replacement_bytes_total < self.maximum_replacement_bytes_per_file:
            raise ValueError("total replacement limit cannot be smaller than the per-file limit")
        return self

    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


class BenchmarkEditableFileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    sha256: str = Field(pattern=_SHA256)
    size_bytes: int = Field(ge=1, le=_MAX_FILE_BYTES)
    content: str = Field(min_length=1, max_length=_MAX_FILE_BYTES)

    @model_validator(mode="after")
    def content_matches_identity(self) -> BenchmarkEditableFileSnapshot:
        encoded = self.content.encode("utf-8")
        if len(encoded) != self.size_bytes:
            raise ValueError("editable snapshot byte size mismatch")
        if hashlib.sha256(encoded).hexdigest() != self.sha256:
            raise ValueError("editable snapshot hash mismatch")
        _relative_locator(self.path, label="editable snapshot path")
        return self


class BenchmarkPatchContext(BaseModel):
    """Exact caller-selected code supplied to a future patch-generation node."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    spec_id: str
    spec_fingerprint: str = Field(pattern=_SHA256)
    editable_surface_sha256: str = Field(pattern=_SHA256)
    files: tuple[BenchmarkEditableFileSnapshot, ...] = Field(min_length=1, max_length=50)
    context_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def context_is_self_hashed(self) -> BenchmarkPatchContext:
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("benchmark patch context paths must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"context_sha256"}))
        if self.context_sha256 != expected:
            raise ValueError("benchmark patch context hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkPatchContext:
        payload = {"schema_version": "1.0", **values}
        payload.pop("context_sha256", None)
        unsigned = cls.model_construct(context_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"context_sha256"}))
        return cls(**payload, context_sha256=digest)


class BenchmarkPatchEdit(BaseModel):
    """One replacement against exact predecessor bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    expected_sha256: str = Field(pattern=_SHA256)
    replacement: str = Field(min_length=1, max_length=_MAX_FILE_BYTES)
    replacement_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def replacement_identity_matches(self) -> BenchmarkPatchEdit:
        _relative_locator(self.path, label="benchmark patch path")
        observed = hashlib.sha256(self.replacement.encode("utf-8")).hexdigest()
        if observed != self.replacement_sha256:
            raise ValueError("benchmark replacement hash mismatch")
        return self


class BenchmarkPatchProducer(BaseModel):
    """Proposal provenance; this grants neither mutation nor execution."""

    model_config = _CONFIG

    mode: Literal["registered", "model"]
    producer_id: str
    provider: str | None = None
    model: str | None = None
    request_sha256: str | None = Field(default=None, pattern=_SHA256)
    response_sha256: str | None = Field(default=None, pattern=_SHA256)

    @field_validator("producer_id")
    @classmethod
    def producer_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="producer_id")

    @model_validator(mode="after")
    def provenance_matches_mode(self) -> BenchmarkPatchProducer:
        model_fields = (self.provider, self.model, self.request_sha256, self.response_sha256)
        if self.mode == "model" and any(value is None for value in model_fields):
            raise ValueError("model benchmark patches require complete call provenance")
        if self.mode == "registered" and any(value is not None for value in model_fields):
            raise ValueError("registered benchmark patches cannot claim model provenance")
        return self


class BenchmarkPatchProposal(BaseModel):
    """Untrusted semantic/code proposal against one exact editable surface."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: str
    spec_id: str
    spec_fingerprint: str = Field(pattern=_SHA256)
    policy_fingerprint: str = Field(pattern=_SHA256)
    context_sha256: str = Field(pattern=_SHA256)
    iteration: int = Field(ge=1, le=1_000)
    base_editable_surface_sha256: str = Field(pattern=_SHA256)
    hypothesis: str = Field(min_length=1, max_length=4_000)
    expected_effect: str = Field(min_length=1, max_length=4_000)
    edits: tuple[BenchmarkPatchEdit, ...] = Field(min_length=1, max_length=50)
    producer: BenchmarkPatchProducer
    authority: Literal["proposal-only"] = "proposal-only"

    @field_validator("proposal_id", "spec_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "id")))

    @model_validator(mode="after")
    def edit_paths_are_unique(self) -> BenchmarkPatchProposal:
        paths = tuple(item.path for item in self.edits)
        if len(paths) != len(set(paths)):
            raise ValueError("benchmark patch paths must be unique")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class BenchmarkPatchViolation(BaseModel):
    model_config = _CONFIG

    code: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    message: str = Field(min_length=1, max_length=1_000)
    path: str | None = None


class BenchmarkPatchAdmission(BaseModel):
    """Deterministic proposal verdict; acceptance still confers no run authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    proposal_sha256: str = Field(pattern=_SHA256)
    spec_fingerprint: str = Field(pattern=_SHA256)
    policy_fingerprint: str = Field(pattern=_SHA256)
    observed_editable_surface_sha256: str = Field(pattern=_SHA256)
    protected_surface_sha256: str = Field(pattern=_SHA256)
    decision: Literal["accepted", "rejected"]
    replacement_file_count: int = Field(ge=0)
    replacement_total_bytes: int = Field(ge=0)
    violations: tuple[BenchmarkPatchViolation, ...]
    mutation_authorized: Literal[False] = False
    execution_authorized: Literal[False] = False
    admission_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def verdict_and_hash_are_consistent(self) -> BenchmarkPatchAdmission:
        if (self.decision == "accepted") == bool(self.violations):
            raise ValueError("benchmark patch verdict and violations disagree")
        expected = content_sha256(self.model_dump(mode="json", exclude={"admission_sha256"}))
        if self.admission_sha256 != expected:
            raise ValueError("benchmark patch admission hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkPatchAdmission:
        payload = {"schema_version": "1.0", **values}
        payload.pop("admission_sha256", None)
        unsigned = cls.model_construct(admission_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"admission_sha256"}))
        return cls(**payload, admission_sha256=digest)


class AppliedBenchmarkEdit(BaseModel):
    model_config = _CONFIG

    path: str
    before_sha256: str = Field(pattern=_SHA256)
    after_sha256: str = Field(pattern=_SHA256)
    before_bytes: int = Field(ge=1)
    after_bytes: int = Field(ge=1)


class BenchmarkPatchApplicationReceipt(BaseModel):
    """Portable evidence for one atomic controller-owned source transition."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    proposal_sha256: str = Field(pattern=_SHA256)
    admission_sha256: str = Field(pattern=_SHA256)
    spec_fingerprint: str = Field(pattern=_SHA256)
    policy_fingerprint: str = Field(pattern=_SHA256)
    workspace_locator: str
    iteration: int = Field(ge=1)
    editable_surface_before_sha256: str = Field(pattern=_SHA256)
    editable_surface_after_sha256: str = Field(pattern=_SHA256)
    protected_surface_sha256: str = Field(pattern=_SHA256)
    edits: tuple[AppliedBenchmarkEdit, ...] = Field(min_length=1, max_length=50)
    model_invocation_performed_by_application: Literal[False] = False
    benchmark_execution_performed: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_self_hashed(self) -> BenchmarkPatchApplicationReceipt:
        _relative_locator(self.workspace_locator, label="workspace locator")
        if self.editable_surface_before_sha256 == self.editable_surface_after_sha256:
            raise ValueError("applied benchmark patch must change the editable surface")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("benchmark patch application receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkPatchApplicationReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"receipt_sha256"}))
        return cls(**payload, receipt_sha256=digest)


class BenchmarkPatchRollbackReceipt(BaseModel):
    """Evidence that a non-best candidate was restored to its exact predecessor."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    proposal_sha256: str = Field(pattern=_SHA256)
    application_receipt_sha256: str = Field(pattern=_SHA256)
    context_sha256: str = Field(pattern=_SHA256)
    spec_fingerprint: str = Field(pattern=_SHA256)
    workspace_locator: str
    editable_surface_before_sha256: str = Field(pattern=_SHA256)
    editable_surface_after_sha256: str = Field(pattern=_SHA256)
    protected_surface_sha256: str = Field(pattern=_SHA256)
    restored_paths: tuple[str, ...] = Field(min_length=1, max_length=50)
    model_invocation_performed_by_rollback: Literal[False] = False
    benchmark_execution_performed_by_rollback: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_self_hashed(self) -> BenchmarkPatchRollbackReceipt:
        _relative_locator(self.workspace_locator, label="workspace locator")
        if len(self.restored_paths) != len(set(self.restored_paths)):
            raise ValueError("benchmark rollback paths must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("benchmark patch rollback receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> BenchmarkPatchRollbackReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        digest = content_sha256(unsigned.model_dump(mode="json", exclude={"receipt_sha256"}))
        return cls(**payload, receipt_sha256=digest)


def snapshot_benchmark_editable_files(
    spec: BenchmarkTaskRuntimeSpec,
    prepared: PreparedBenchmarkWorkspace,
    workspace: str | Path,
    *,
    selected_paths: tuple[str, ...],
    maximum_context_bytes: int = _MAX_CONTEXT_BYTES,
) -> BenchmarkPatchContext:
    """Read only exact caller-selected editable UTF-8 files for model context."""

    if not selected_paths or len(selected_paths) != len(set(selected_paths)):
        raise ValueError("selected editable paths must be non-empty and unique")
    if maximum_context_bytes < 1 or maximum_context_bytes > _MAX_CONTEXT_BYTES:
        raise ValueError("benchmark patch context byte limit is invalid")
    root = _workspace_root(workspace)
    _verify_prepared_workspace(spec, prepared, root)
    surface_sha256, surface_paths = hash_editable_surface(spec, root)
    surface = set(surface_paths)
    snapshots: list[BenchmarkEditableFileSnapshot] = []
    total = 0
    for locator in selected_paths:
        _relative_locator(locator, label="selected editable path")
        if locator not in surface:
            raise ValueError(f"selected path is not on the exact editable surface: {locator}")
        path = root.joinpath(*PurePosixPath(locator).parts)
        raw = path.read_bytes()
        if not raw or len(raw) > _MAX_FILE_BYTES:
            raise ValueError(f"selected editable file has an invalid size: {locator}")
        total += len(raw)
        if total > maximum_context_bytes:
            raise ValueError("selected editable files exceed the model context byte limit")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"selected editable file is not UTF-8: {locator}") from exc
        snapshots.append(
            BenchmarkEditableFileSnapshot(
                path=locator,
                sha256=hashlib.sha256(raw).hexdigest(),
                size_bytes=len(raw),
                content=content,
            )
        )
    return BenchmarkPatchContext.create(
        spec_id=spec.spec_id,
        spec_fingerprint=spec.fingerprint,
        editable_surface_sha256=surface_sha256,
        files=tuple(snapshots),
    )


def inspect_benchmark_patch(
    proposal: BenchmarkPatchProposal,
    context: BenchmarkPatchContext,
    spec: BenchmarkTaskRuntimeSpec,
    prepared: PreparedBenchmarkWorkspace,
    policy: BenchmarkPatchPolicy,
    *,
    workspace: str | Path,
) -> BenchmarkPatchAdmission:
    """Admit replacements against exact current bytes without modifying them."""

    root = _workspace_root(workspace)
    observed_surface, editable_paths = hash_editable_surface(spec, root)
    protected_surface = hash_protected_surface(spec, root)
    editable = set(editable_paths)
    violations: list[BenchmarkPatchViolation] = []

    def reject(code: str, message: str, path: str | None = None) -> None:
        violations.append(BenchmarkPatchViolation(code=code, message=message, path=path))

    if prepared.spec_id != spec.spec_id or prepared.spec_fingerprint != spec.fingerprint:
        reject("workspace-spec-mismatch", "prepared workspace belongs to another task spec")
    if prepared.workspace_locator != root.name:
        reject("workspace-locator-mismatch", "workspace locator differs from its receipt")
    if protected_surface != prepared.protected_surface_sha256:
        reject("protected-surface-drift", "non-editable task source changed after preparation")
    if proposal.spec_id != spec.spec_id or proposal.spec_fingerprint != spec.fingerprint:
        reject("proposal-spec-mismatch", "proposal belongs to another task spec")
    if context.spec_id != spec.spec_id or context.spec_fingerprint != spec.fingerprint:
        reject("context-spec-mismatch", "patch context belongs to another task spec")
    if proposal.context_sha256 != context.context_sha256:
        reject("proposal-context-mismatch", "proposal does not bind its exact source context")
    if context.editable_surface_sha256 != observed_surface:
        reject("context-surface-drift", "selected source context is stale")
    if proposal.policy_fingerprint != policy.fingerprint:
        reject("proposal-policy-mismatch", "proposal does not bind the controller policy")
    if proposal.base_editable_surface_sha256 != observed_surface:
        reject("editable-surface-drift", "editable files changed after proposal context")
    if len(proposal.edits) > policy.maximum_files_per_patch:
        reject("replacement-file-limit", "proposal exceeds the replacement file limit")

    replacement_total = 0
    for edit in proposal.edits:
        raw = edit.replacement.encode("utf-8")
        replacement_total += len(raw)
        if edit.path not in editable:
            reject("path-not-editable", "proposal path is outside the editable surface", edit.path)
            continue
        target = root.joinpath(*PurePosixPath(edit.path).parts)
        if target.is_symlink() or not target.is_file():
            reject("target-not-regular", "proposal target is not a regular file", edit.path)
            continue
        current = target.read_bytes()
        current_sha256 = hashlib.sha256(current).hexdigest()
        if current_sha256 != edit.expected_sha256:
            reject("target-hash-mismatch", "proposal predecessor hash is stale", edit.path)
        if current_sha256 == edit.replacement_sha256:
            reject("replacement-noop", "replacement bytes are unchanged", edit.path)
        if len(raw) > policy.maximum_replacement_bytes_per_file:
            reject(
                "replacement-file-bytes",
                "replacement exceeds the per-file byte limit",
                edit.path,
            )
        if Path(edit.path).suffix not in policy.allowed_suffixes:
            reject("replacement-suffix", "replacement file type is not allowed", edit.path)
        syntax_error = _syntax_error(edit.path, edit.replacement)
        if syntax_error is not None:
            reject("replacement-syntax", syntax_error, edit.path)
    if replacement_total > policy.maximum_replacement_bytes_total:
        reject("replacement-total-bytes", "proposal exceeds the total replacement byte limit")

    return BenchmarkPatchAdmission.create(
        proposal_sha256=proposal.fingerprint,
        spec_fingerprint=spec.fingerprint,
        policy_fingerprint=policy.fingerprint,
        observed_editable_surface_sha256=observed_surface,
        protected_surface_sha256=protected_surface,
        decision="rejected" if violations else "accepted",
        replacement_file_count=len(proposal.edits),
        replacement_total_bytes=replacement_total,
        violations=tuple(violations),
    )


def apply_benchmark_patch(
    proposal: BenchmarkPatchProposal,
    admission: BenchmarkPatchAdmission,
    spec: BenchmarkTaskRuntimeSpec,
    policy: BenchmarkPatchPolicy,
    *,
    workspace: str | Path,
    receipt_path: str | Path,
    allow_mutation: bool = False,
) -> BenchmarkPatchApplicationReceipt:
    """Atomically replace admitted source files and retain a self-hashed receipt."""

    if not allow_mutation:
        raise ValueError("benchmark patch application requires explicit authorization")
    if admission.decision != "accepted":
        raise ValueError("rejected benchmark patch cannot be applied")
    if admission.proposal_sha256 != proposal.fingerprint:
        raise ValueError("benchmark patch admission belongs to another proposal")
    if admission.spec_fingerprint != spec.fingerprint:
        raise ValueError("benchmark patch admission belongs to another task spec")
    if admission.policy_fingerprint != policy.fingerprint:
        raise ValueError("benchmark patch admission belongs to another policy")
    root = _workspace_root(workspace)
    before, _ = hash_editable_surface(spec, root)
    protected_before = hash_protected_surface(spec, root)
    if before != admission.observed_editable_surface_sha256:
        raise ValueError("editable benchmark surface changed after admission")
    if protected_before != admission.protected_surface_sha256:
        raise ValueError("protected benchmark surface changed after admission")
    record = Path(receipt_path)
    if record.exists() or record.is_symlink():
        raise FileExistsError(record)
    try:
        record.resolve().relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("benchmark patch receipt must be outside the mutable workspace")
    record.parent.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix=".benchmark-patch.", dir=root.parent))
    staged: list[tuple[Path, Path, Path, int, bytes]] = []
    applied: list[Path] = []
    try:
        for index, edit in enumerate(proposal.edits):
            target = root.joinpath(*PurePosixPath(edit.path).parts)
            original = target.read_bytes()
            if hashlib.sha256(original).hexdigest() != edit.expected_sha256:
                raise ValueError(f"benchmark patch target changed before apply: {edit.path}")
            mode = stat.S_IMODE(target.stat().st_mode)
            backup = transaction / f"{index}.before"
            replacement = transaction / f"{index}.after"
            backup.write_bytes(original)
            replacement.write_bytes(edit.replacement.encode("utf-8"))
            backup.chmod(mode)
            replacement.chmod(mode)
            staged.append((target, backup, replacement, mode, original))
        for target, _, replacement, _, _ in staged:
            os.replace(replacement, target)
            applied.append(target)
        after, _ = hash_editable_surface(spec, root)
        protected_after = hash_protected_surface(spec, root)
        if protected_after != protected_before:
            raise ValueError("benchmark patch changed protected task source")
        edit_records = tuple(
            AppliedBenchmarkEdit(
                path=edit.path,
                before_sha256=edit.expected_sha256,
                after_sha256=edit.replacement_sha256,
                before_bytes=len(original),
                after_bytes=len(edit.replacement.encode("utf-8")),
            )
            for edit, (_, _, _, _, original) in zip(proposal.edits, staged, strict=True)
        )
        receipt = BenchmarkPatchApplicationReceipt.create(
            proposal_sha256=proposal.fingerprint,
            admission_sha256=admission.admission_sha256,
            spec_fingerprint=spec.fingerprint,
            policy_fingerprint=policy.fingerprint,
            workspace_locator=root.name,
            iteration=proposal.iteration,
            editable_surface_before_sha256=before,
            editable_surface_after_sha256=after,
            protected_surface_sha256=protected_after,
            edits=edit_records,
        )
        _atomic_json_write(record, receipt.model_dump(mode="json"))
        return receipt
    except BaseException:
        for target, backup, _, mode, _ in reversed(staged):
            if target in applied and backup.exists():
                os.replace(backup, target)
                target.chmod(mode)
        record.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(transaction, ignore_errors=True)


def rollback_benchmark_patch(
    proposal: BenchmarkPatchProposal,
    context: BenchmarkPatchContext,
    application: BenchmarkPatchApplicationReceipt,
    spec: BenchmarkTaskRuntimeSpec,
    *,
    workspace: str | Path,
    receipt_path: str | Path,
    allow_mutation: bool = False,
) -> BenchmarkPatchRollbackReceipt:
    """Restore exact predecessor bytes after a failed or non-improving development run."""

    if not allow_mutation:
        raise ValueError("benchmark patch rollback requires explicit authorization")
    if application.proposal_sha256 != proposal.fingerprint:
        raise ValueError("benchmark rollback application belongs to another proposal")
    if application.spec_fingerprint != spec.fingerprint:
        raise ValueError("benchmark rollback application belongs to another task spec")
    if proposal.context_sha256 != context.context_sha256:
        raise ValueError("benchmark rollback proposal belongs to another source context")
    root = _workspace_root(workspace)
    before, _ = hash_editable_surface(spec, root)
    protected = hash_protected_surface(spec, root)
    if before != application.editable_surface_after_sha256:
        raise ValueError("editable benchmark surface changed after patch application")
    if protected != application.protected_surface_sha256:
        raise ValueError("protected benchmark surface changed after patch application")
    snapshots = {item.path: item for item in context.files}
    records = {item.path: item for item in application.edits}
    if set(records) != {item.path for item in proposal.edits}:
        raise ValueError("benchmark application receipt does not cover the proposal")
    record = Path(receipt_path)
    if record.exists() or record.is_symlink():
        raise FileExistsError(record)
    try:
        record.resolve().relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("benchmark rollback receipt must be outside the mutable workspace")
    record.parent.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix=".benchmark-rollback.", dir=root.parent))
    staged: list[tuple[Path, Path, Path, int]] = []
    changed: list[Path] = []
    try:
        for index, edit in enumerate(proposal.edits):
            snapshot = snapshots.get(edit.path)
            if snapshot is None or snapshot.sha256 != edit.expected_sha256:
                raise ValueError("benchmark rollback context lacks exact predecessor bytes")
            target = root.joinpath(*PurePosixPath(edit.path).parts)
            current = target.read_bytes()
            if hashlib.sha256(current).hexdigest() != records[edit.path].after_sha256:
                raise ValueError(f"benchmark rollback target changed: {edit.path}")
            mode = stat.S_IMODE(target.stat().st_mode)
            backup = transaction / f"{index}.patched"
            predecessor = transaction / f"{index}.predecessor"
            backup.write_bytes(current)
            predecessor.write_bytes(snapshot.content.encode("utf-8"))
            backup.chmod(mode)
            predecessor.chmod(mode)
            staged.append((target, backup, predecessor, mode))
        for target, _, predecessor, _ in staged:
            os.replace(predecessor, target)
            changed.append(target)
        after, _ = hash_editable_surface(spec, root)
        if after != application.editable_surface_before_sha256:
            raise ValueError("benchmark rollback did not restore the predecessor surface")
        if hash_protected_surface(spec, root) != protected:
            raise ValueError("benchmark rollback changed protected task source")
        receipt = BenchmarkPatchRollbackReceipt.create(
            proposal_sha256=proposal.fingerprint,
            application_receipt_sha256=application.receipt_sha256,
            context_sha256=context.context_sha256,
            spec_fingerprint=spec.fingerprint,
            workspace_locator=root.name,
            editable_surface_before_sha256=before,
            editable_surface_after_sha256=after,
            protected_surface_sha256=protected,
            restored_paths=tuple(edit.path for edit in proposal.edits),
        )
        _atomic_json_write(record, receipt.model_dump(mode="json"))
        return receipt
    except BaseException:
        for target, backup, _, mode in reversed(staged):
            if target in changed and backup.exists():
                os.replace(backup, target)
                target.chmod(mode)
        record.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(transaction, ignore_errors=True)


def hash_editable_surface(
    spec: BenchmarkTaskRuntimeSpec,
    workspace: str | Path,
) -> tuple[str, tuple[str, ...]]:
    """Hash only source files that a task specification permits changing."""

    root = _workspace_root(workspace)
    candidates: list[tuple[str, Path]] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("benchmark workspace cannot contain symbolic links")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("benchmark workspace contains a non-regular entry")
        relative = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatchcase(relative, pattern) for pattern in spec.editable_globs):
            candidates.append((relative, path))
    candidates.sort(key=lambda item: item[0])
    if not candidates:
        raise ValueError("benchmark workspace editable surface is empty")
    digest = hashlib.sha256(b"SCITASTE_BENCHMARK_EDITABLE_SURFACE_V1\0")
    for relative, path in candidates:
        raw = path.read_bytes()
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest(), tuple(relative for relative, _ in candidates)


def _syntax_error(locator: str, content: str) -> str | None:
    suffix = Path(locator).suffix
    try:
        if suffix == ".py":
            ast.parse(content, filename=locator)
        elif suffix == ".json":
            json.loads(content)
        elif suffix in {".yaml", ".yml"}:
            yaml.safe_load(content)
    except (SyntaxError, json.JSONDecodeError, yaml.YAMLError) as exc:
        return f"replacement does not parse as {suffix}: {type(exc).__name__}"
    return None


def _workspace_root(workspace: str | Path) -> Path:
    root = Path(workspace)
    if root.is_symlink():
        raise ValueError("benchmark workspace cannot be a symbolic link")
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("benchmark workspace must be a directory")
    return resolved


def _verify_prepared_workspace(
    spec: BenchmarkTaskRuntimeSpec,
    prepared: PreparedBenchmarkWorkspace,
    root: Path,
) -> None:
    if prepared.spec_id != spec.spec_id or prepared.spec_fingerprint != spec.fingerprint:
        raise ValueError("prepared workspace belongs to another benchmark task spec")
    if prepared.workspace_locator != root.name:
        raise ValueError("prepared workspace locator mismatch")
    if hash_protected_surface(spec, root) != prepared.protected_surface_sha256:
        raise ValueError("protected benchmark source changed after workspace preparation")


def _relative_locator(value: str, *, label: str) -> str:
    if "\\" in value or "//" in value:
        raise ValueError(f"{label} must use normalized POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a normalized relative path")
    return value


def _atomic_json_write(path: Path, payload: object) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


__all__ = [
    "AppliedBenchmarkEdit",
    "BenchmarkEditableFileSnapshot",
    "BenchmarkPatchAdmission",
    "BenchmarkPatchApplicationReceipt",
    "BenchmarkPatchContext",
    "BenchmarkPatchEdit",
    "BenchmarkPatchPolicy",
    "BenchmarkPatchProducer",
    "BenchmarkPatchProposal",
    "BenchmarkPatchRollbackReceipt",
    "BenchmarkPatchViolation",
    "apply_benchmark_patch",
    "hash_editable_surface",
    "inspect_benchmark_patch",
    "rollback_benchmark_patch",
    "snapshot_benchmark_editable_files",
]

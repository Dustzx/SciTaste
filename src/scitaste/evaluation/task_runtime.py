"""Content-bound benchmark workspaces for autonomous research cells.

The formal evaluation runner must not hand an agent an arbitrary checkout or
let the development loop see held-out test bytes.  This module turns an
acquired benchmark task into an immutable runtime contract and, only under an
explicit materialization switch, copies its model-visible tree into a bounded
cell-owned workspace.  It does not install an environment, unpack data, run a
model, or execute a benchmark.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_SPEC_BYTES = 1_048_576
_MAX_EVIDENCE_BYTES = 64 * 1024 * 1024


class RuntimeEvidenceBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    file_sha256: str = Field(pattern=_SHA256)
    semantic_field: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$",
    )
    semantic_sha256: str | None = Field(default=None, pattern=_SHA256)

    @field_validator("locator")
    @classmethod
    def locator_is_safe(cls, value: str) -> str:
        return _relative_locator(value, label="runtime evidence locator")

    @model_validator(mode="after")
    def semantic_binding_is_complete(self) -> RuntimeEvidenceBinding:
        if (self.semantic_field is None) != (self.semantic_sha256 is None):
            raise ValueError("semantic evidence requires both a field and SHA-256")
        return self


class BenchmarkTaskRuntimeSpec(BaseModel):
    """Exact source, split, edit, command, and readiness boundary for one task."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    spec_id: str
    project_id: str
    benchmark_id: str
    task_id: str
    source_checkout: str
    repository_commit: str = Field(pattern=_COMMIT)
    require_clean_checkout: Literal[True] = True
    task_root: str
    visible_root: str
    visible_tree_sha256: str = Field(pattern=_SHA256)
    maximum_visible_files: int = Field(default=10_000, ge=1, le=100_000)
    maximum_visible_bytes: int = Field(default=2_147_483_648, ge=1, le=10_737_418_240)
    research_problem: RuntimeEvidenceBinding
    read_only_manifest: RuntimeEvidenceBinding
    environment_manifest: RuntimeEvidenceBinding
    objective_entrypoint: RuntimeEvidenceBinding
    editable_globs: tuple[str, ...] = Field(min_length=1, max_length=50)
    dataset_directories: tuple[str, ...] = Field(min_length=1, max_length=20)
    writable_output_directories: tuple[str, ...] = Field(min_length=1, max_length=20)
    development_command: tuple[str, ...] = Field(min_length=1, max_length=50)
    heldout_command: tuple[str, ...] = Field(min_length=1, max_length=50)
    heldout_materialization_paths: tuple[str, ...] = Field(min_length=1, max_length=20)
    primary_metric: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
    metric_direction: Literal["higher", "lower"]
    baseline_development_score: float
    baseline_heldout_score: float
    asset_receipt: RuntimeEvidenceBinding
    archive_qualification: RuntimeEvidenceBinding
    license_evidence: RuntimeEvidenceBinding | None = None
    source_status: ReadinessStatus
    archive_status: ReadinessStatus
    license_status: ReadinessStatus
    ingestion_status: ReadinessStatus
    environment_status: ReadinessStatus
    scorer_status: ReadinessStatus
    agent_network_access: Literal[False] = False
    heldout_visible_during_development: Literal[False] = False
    model_execution_authorized: Literal[False] = False
    benchmark_execution_authorized: Literal[False] = False

    @field_validator("spec_id", "benchmark_id", "task_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "id")))

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("source_checkout", "task_root", "visible_root")
    @classmethod
    def source_locators_are_safe(cls, value: str, info: object) -> str:
        return _relative_locator(value, label=str(getattr(info, "field_name", "locator")))

    @field_validator(
        "editable_globs",
        "dataset_directories",
        "writable_output_directories",
        "heldout_materialization_paths",
    )
    @classmethod
    def workspace_paths_are_safe(cls, values: tuple[str, ...], info: object) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError(f"{getattr(info, 'field_name', 'paths')} must be unique")
        for value in values:
            _relative_locator(value, label=str(getattr(info, "field_name", "path")))
        return values

    @field_validator("development_command", "heldout_command")
    @classmethod
    def commands_are_shell_free(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or "\x00" in value for value in values):
            raise ValueError("benchmark commands require non-empty arguments")
        return values

    @model_validator(mode="after")
    def split_and_readiness_contract_is_closed(self) -> BenchmarkTaskRuntimeSpec:
        if self.development_command == self.heldout_command:
            raise ValueError("development and held-out commands must be distinct")
        if set(self.editable_globs) & set(self.heldout_materialization_paths):
            raise ValueError("held-out paths cannot be editable")
        if set(self.dataset_directories) & set(self.writable_output_directories):
            raise ValueError("dataset and writable output directories must be distinct")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class BenchmarkTaskRuntimeInspection(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    spec_id: str
    spec_sha256: str = Field(pattern=_SHA256)
    spec_fingerprint: str = Field(pattern=_SHA256)
    observed_repository_commit: str | None = Field(default=None, pattern=_COMMIT)
    checkout_clean: bool | None = None
    observed_visible_tree_sha256: str | None = Field(default=None, pattern=_SHA256)
    editable_file_count: int = Field(ge=0)
    visible_file_count: int = Field(ge=0)
    visible_total_bytes: int = Field(ge=0)
    ready_for_workspace_materialization: bool
    ready_for_development_execution: bool
    blocker_codes: tuple[str, ...]
    no_materialization_performed: Literal[True] = True
    no_environment_installation_performed: Literal[True] = True
    no_archive_extraction_performed: Literal[True] = True
    no_model_or_benchmark_execution_performed: Literal[True] = True


class PreparedBenchmarkWorkspace(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    spec_id: str
    spec_fingerprint: str = Field(pattern=_SHA256)
    workspace_locator: str
    workspace_tree_sha256: str = Field(pattern=_SHA256)
    protected_surface_sha256: str = Field(pattern=_SHA256)
    visible_file_count: int = Field(ge=1)
    visible_total_bytes: int = Field(ge=1)
    editable_files: tuple[str, ...] = Field(min_length=1)
    read_only_files: tuple[str, ...] = Field(min_length=1)
    heldout_materialized: Literal[False] = False
    datasets_materialized: Literal[False] = False
    environment_installed: Literal[False] = False
    model_or_benchmark_executed: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_self_hashed(self) -> PreparedBenchmarkWorkspace:
        _relative_locator(self.workspace_locator, label="workspace locator")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("prepared benchmark workspace receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> PreparedBenchmarkWorkspace:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        return cls(
            **payload,
            receipt_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


def load_benchmark_task_runtime_spec(path: str | Path) -> BenchmarkTaskRuntimeSpec:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("benchmark runtime spec must be a regular file")
    raw = candidate.read_bytes()
    if not raw or len(raw) > _MAX_SPEC_BYTES:
        raise ValueError("benchmark runtime spec has an invalid size")
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError("benchmark runtime spec must contain one mapping")
    return BenchmarkTaskRuntimeSpec.model_validate(payload)


def inspect_benchmark_task_runtime(
    spec: BenchmarkTaskRuntimeSpec,
    *,
    workspace_root: str | Path,
    spec_sha256: str,
) -> BenchmarkTaskRuntimeInspection:
    """Verify exact local source/evidence bytes without preparing or running the task."""

    root = Path(workspace_root).resolve(strict=True)
    blockers: list[str] = []
    checkout = _resolve_under(root, spec.source_checkout, directory=True)
    observed_commit: str | None = None
    clean: bool | None = None
    visible_digest: str | None = None
    visible_files: tuple[Path, ...] = ()
    visible_bytes = 0
    editable_files: tuple[str, ...] = ()

    if checkout is None:
        blockers.append("source-checkout-unavailable")
    else:
        try:
            observed_commit = _git(checkout, "rev-parse", "HEAD")
            clean = not bool(_git(checkout, "status", "--porcelain=v1", "--untracked-files=all"))
        except ValueError:
            blockers.append("source-checkout-git-invalid")
        else:
            if observed_commit != spec.repository_commit:
                blockers.append("source-commit-mismatch")
            if spec.require_clean_checkout and not clean:
                blockers.append("source-checkout-dirty")
        visible = _resolve_under(checkout, spec.visible_root, directory=True)
        task_root = _resolve_under(checkout, spec.task_root, directory=True)
        if visible is None or task_root is None:
            blockers.append("task-source-layout-unavailable")
        elif not visible.is_relative_to(task_root):
            blockers.append("visible-root-outside-task")
        else:
            try:
                visible_digest, visible_files, visible_bytes = hash_benchmark_tree(visible)
            except ValueError:
                blockers.append("visible-tree-unsafe")
            else:
                if len(visible_files) > spec.maximum_visible_files:
                    blockers.append("visible-tree-file-limit-exceeded")
                if visible_bytes > spec.maximum_visible_bytes:
                    blockers.append("visible-tree-byte-limit-exceeded")
                if visible_digest != spec.visible_tree_sha256:
                    blockers.append("visible-tree-drift")
                relative = tuple(path.relative_to(visible).as_posix() for path in visible_files)
                editable_files = tuple(
                    path
                    for path in relative
                    if any(fnmatch.fnmatchcase(path, pattern) for pattern in spec.editable_globs)
                )
                if not editable_files:
                    blockers.append("editable-surface-empty")
                for hidden in spec.heldout_materialization_paths:
                    if (visible / hidden).exists():
                        blockers.append("heldout-content-visible-during-development")

        for label, binding in (
            ("research-problem", spec.research_problem),
            ("read-only-manifest", spec.read_only_manifest),
            ("environment-manifest", spec.environment_manifest),
        ):
            _verify_binding(checkout, binding, blockers, label=label)

    for label, binding in (
        ("asset-receipt", spec.asset_receipt),
        ("archive-qualification", spec.archive_qualification),
        ("license-evidence", spec.license_evidence),
        ("objective-entrypoint", spec.objective_entrypoint),
    ):
        if binding is not None:
            _verify_binding(root, binding, blockers, label=label)

    source_blockers = tuple(sorted(set(blockers)))
    materialization_ready = not source_blockers and spec.source_status is ReadinessStatus.VERIFIED
    readiness = (
        spec.archive_status,
        spec.license_status,
        spec.ingestion_status,
        spec.environment_status,
        spec.scorer_status,
    )
    development_ready = materialization_ready and all(
        status is ReadinessStatus.VERIFIED for status in readiness
    )
    readiness_blockers = [
        f"readiness:{name}:{status.value}"
        for name, status in (
            ("source", spec.source_status),
            ("archive", spec.archive_status),
            ("license", spec.license_status),
            ("ingestion", spec.ingestion_status),
            ("environment", spec.environment_status),
            ("scorer", spec.scorer_status),
        )
        if status is not ReadinessStatus.VERIFIED
    ]
    return BenchmarkTaskRuntimeInspection(
        spec_id=spec.spec_id,
        spec_sha256=spec_sha256,
        spec_fingerprint=spec.fingerprint,
        observed_repository_commit=observed_commit,
        checkout_clean=clean,
        observed_visible_tree_sha256=visible_digest,
        editable_file_count=len(editable_files),
        visible_file_count=len(visible_files),
        visible_total_bytes=visible_bytes,
        ready_for_workspace_materialization=materialization_ready,
        ready_for_development_execution=development_ready,
        blocker_codes=tuple((*source_blockers, *readiness_blockers)),
    )


def prepare_benchmark_workspace(
    spec: BenchmarkTaskRuntimeSpec,
    inspection: BenchmarkTaskRuntimeInspection,
    *,
    workspace_root: str | Path,
    destination: str | Path,
    allow_materialization: bool = False,
) -> PreparedBenchmarkWorkspace:
    """Copy only the model-visible tree and enforce its exact edit surface."""

    if not allow_materialization:
        raise ValueError("benchmark workspace materialization requires explicit authorization")
    if inspection.spec_fingerprint != spec.fingerprint:
        raise ValueError("benchmark workspace inspection belongs to another specification")
    if not inspection.ready_for_workspace_materialization:
        raise ValueError("benchmark task source is not ready for workspace materialization")
    root = Path(workspace_root).resolve(strict=True)
    checkout = _resolve_under(root, spec.source_checkout, directory=True)
    if checkout is None:
        raise ValueError("benchmark source checkout is unavailable")
    visible = _resolve_under(checkout, spec.visible_root, directory=True)
    if visible is None:
        raise ValueError("benchmark visible source tree is unavailable")
    target = Path(destination)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        shutil.copytree(visible, temporary / "workspace", symlinks=False)
        prepared = temporary / "workspace"
        _, files, copied_bytes = hash_benchmark_tree(prepared)
        if len(files) > spec.maximum_visible_files:
            raise ValueError("benchmark visible file limit exceeded during materialization")
        if copied_bytes > spec.maximum_visible_bytes:
            raise ValueError("benchmark visible byte limit exceeded during materialization")
        editable: list[str] = []
        read_only: list[str] = []
        for path in files:
            relative = path.relative_to(prepared).as_posix()
            if any(fnmatch.fnmatchcase(relative, pattern) for pattern in spec.editable_globs):
                editable.append(relative)
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
            else:
                read_only.append(relative)
                path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        for locator in spec.dataset_directories:
            dataset = prepared / locator
            if dataset.exists() and not dataset.is_dir():
                raise ValueError("benchmark dataset directory collides with a file")
            dataset.mkdir(parents=True, exist_ok=True)
            dataset.chmod(dataset.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        for locator in spec.writable_output_directories:
            output = prepared / locator
            if output.exists() and not output.is_dir():
                raise ValueError("benchmark writable output collides with a file")
            output.mkdir(parents=True, exist_ok=True)
        observed_sha256, observed_files, observed_bytes = hash_benchmark_tree(prepared)
        protected_sha256 = hash_protected_surface(spec, prepared)
        os.replace(prepared, target)
        receipt = PreparedBenchmarkWorkspace.create(
            spec_id=spec.spec_id,
            spec_fingerprint=spec.fingerprint,
            workspace_locator=target.name,
            workspace_tree_sha256=observed_sha256,
            protected_surface_sha256=protected_sha256,
            visible_file_count=len(observed_files),
            visible_total_bytes=observed_bytes,
            editable_files=tuple(sorted(editable)),
            read_only_files=tuple(sorted(read_only)),
        )
        _atomic_json_write(
            target.parent / f"{target.name}.receipt.json",
            receipt.model_dump(mode="json"),
        )
        return receipt
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def hash_benchmark_tree(root: str | Path) -> tuple[str, tuple[Path, ...], int]:
    """Hash a regular, symlink-free task tree including file modes and paths."""

    directory = Path(root).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("benchmark tree root must be a directory")
    files: list[Path] = []
    for path in sorted(
        directory.rglob("*"),
        key=lambda item: item.relative_to(directory).as_posix(),
    ):
        if path.is_symlink():
            raise ValueError("benchmark tree cannot contain symbolic links")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("benchmark tree contains a non-regular entry")
        files.append(path)
    if not files:
        raise ValueError("benchmark tree contains no files")
    digest = hashlib.sha256(b"SCITASTE_BENCHMARK_VISIBLE_TREE_V1\0")
    total = 0
    for path in files:
        relative = path.relative_to(directory).as_posix().encode()
        size = path.stat().st_size
        mode = stat.S_IMODE(path.stat().st_mode)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(mode.to_bytes(4, "big"))
        digest.update(size.to_bytes(8, "big"))
        observed = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                observed += len(chunk)
                digest.update(chunk)
        if observed != size:
            raise ValueError("benchmark source changed while it was hashed")
        total += size
    return digest.hexdigest(), tuple(files), total


def hash_protected_surface(spec: BenchmarkTaskRuntimeSpec, root: str | Path) -> str:
    """Hash immutable task source while excluding datasets, outputs, and editable files."""

    directory = Path(root).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("benchmark workspace root must be a directory")
    excluded_roots = (*spec.dataset_directories, *spec.writable_output_directories)
    protected: list[tuple[str, Path]] = []
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("benchmark workspace cannot contain symbolic links")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("benchmark workspace contains a non-regular entry")
        relative = path.relative_to(directory).as_posix()
        if any(_is_at_or_under(relative, locator) for locator in excluded_roots):
            continue
        if any(fnmatch.fnmatchcase(relative, pattern) for pattern in spec.editable_globs):
            continue
        protected.append((relative, path))
    protected.sort(key=lambda item: item[0])
    if not protected:
        raise ValueError("benchmark protected source surface is empty")
    digest = hashlib.sha256(b"SCITASTE_BENCHMARK_PROTECTED_SURFACE_V1\0")
    for relative, path in protected:
        raw = path.read_bytes()
        encoded = relative.encode("utf-8")
        mode = stat.S_IMODE(path.stat().st_mode)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(mode.to_bytes(4, "big"))
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _verify_binding(
    root: Path | None,
    binding: RuntimeEvidenceBinding,
    blockers: list[str],
    *,
    label: str,
) -> None:
    if root is None:
        blockers.append(f"{label}-root-unavailable")
        return
    path = _resolve_under(root, binding.locator, directory=False)
    if path is None or path.stat().st_size > _MAX_EVIDENCE_BYTES:
        blockers.append(f"{label}-unavailable")
        return
    if _file_sha256(path) != binding.file_sha256:
        blockers.append(f"{label}-hash-mismatch")
        return
    if binding.semantic_sha256 is not None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            blockers.append(f"{label}-semantic-content-invalid")
            return
        if not isinstance(payload, dict):
            blockers.append(f"{label}-semantic-content-invalid")
            return
        assert binding.semantic_field is not None
        observed = payload.get(binding.semantic_field)
        if observed != binding.semantic_sha256:
            blockers.append(f"{label}-semantic-hash-mismatch")


def _resolve_under(root: Path, locator: str, *, directory: bool) -> Path | None:
    candidate = root.joinpath(*PurePosixPath(locator).parts)
    if candidate.is_symlink():
        return None
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(root):
        return None
    if directory and not resolved.is_dir():
        return None
    if not directory and not resolved.is_file():
        return None
    return resolved


def _relative_locator(value: str, *, label: str) -> str:
    if "\\" in value or "//" in value:
        raise ValueError(f"{label} must use normalized POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a normalized relative path")
    return value


def _is_at_or_under(path: str, root: str) -> bool:
    return path == root or path.startswith(f"{root}/")


def _git(root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if process.returncode:
        raise ValueError(process.stderr.strip() or "git inspection failed")
    return process.stdout.strip()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    "BenchmarkTaskRuntimeInspection",
    "BenchmarkTaskRuntimeSpec",
    "PreparedBenchmarkWorkspace",
    "RuntimeEvidenceBinding",
    "hash_benchmark_tree",
    "hash_protected_surface",
    "inspect_benchmark_task_runtime",
    "load_benchmark_task_runtime_spec",
    "prepare_benchmark_workspace",
]

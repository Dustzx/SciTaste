"""Recoverable migration of legacy output roots into one project-owned archive."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scitaste.project.models import ProjectManifest, ProjectRun, validate_entry_id
from scitaste.project.runtime import ProjectRuntime

ARCHIVE_PROJECT_ID = "scitaste-legacy-output-archive"
_RESERVED_DIRECTORIES = frozenset({"papers", "projects"})


@dataclass(frozen=True)
class TreeFingerprint:
    sha256: str
    regular_files: int
    directories: int
    symbolic_links: int
    bytes: int


@dataclass(frozen=True)
class ReferenceRewrite:
    locator: str
    old_target: str
    new_target: str


@dataclass(frozen=True)
class MigrationPlanEntry:
    name: str
    source_locator: str
    destination_locator: str
    fingerprint: TreeFingerprint
    reference_rewrites: tuple[ReferenceRewrite, ...]


def discover_legacy_directories(outputs_root: str | Path) -> tuple[str, ...]:
    """Return unowned top-level output directories in stable order."""

    root = Path(outputs_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    return tuple(
        child.name
        for child in sorted(root.iterdir(), key=lambda item: item.name)
        if child.is_dir() and not child.is_symlink() and child.name not in _RESERVED_DIRECTORIES
    )


def fingerprint_tree(root: str | Path) -> TreeFingerprint:
    """Hash one tree without following links or exposing file content."""

    source = Path(root)
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"tree root must be a physical directory: {source}")
    digest = hashlib.sha256()
    counts = {"regular_files": 0, "directories": 0, "symbolic_links": 0, "bytes": 0}

    def visit(directory: Path, relative: Path) -> None:
        counts["directories"] += 1
        _update_tree_digest(digest, "directory", relative.as_posix(), b"")
        with os.scandir(directory) as entries:
            ordered = sorted(entries, key=lambda item: item.name)
        for entry in ordered:
            path = Path(entry.path)
            child_relative = relative / entry.name
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                visit(path, child_relative)
            elif stat.S_ISREG(metadata.st_mode):
                counts["regular_files"] += 1
                counts["bytes"] += metadata.st_size
                _update_tree_digest(
                    digest,
                    "file",
                    child_relative.as_posix(),
                    str(metadata.st_size).encode("ascii"),
                )
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            elif stat.S_ISLNK(metadata.st_mode):
                counts["symbolic_links"] += 1
                _update_tree_digest(
                    digest,
                    "symlink",
                    child_relative.as_posix(),
                    os.readlink(path).encode("utf-8"),
                )
            else:
                raise ValueError(f"unsupported special filesystem entry: {path}")

    visit(source, Path("."))
    return TreeFingerprint(sha256=digest.hexdigest(), **counts)


def plan_legacy_output_migration(
    outputs_root: str | Path,
    *,
    directory_names: tuple[str, ...] | None = None,
) -> tuple[MigrationPlanEntry, ...]:
    """Build a content-bound, read-only migration plan."""

    root = Path(outputs_root).expanduser().resolve()
    names = directory_names if directory_names is not None else discover_legacy_directories(root)
    if len(set(names)) != len(names):
        raise ValueError("legacy directory names must be unique")
    source_roots: dict[str, Path] = {}
    fingerprints: dict[str, TreeFingerprint] = {}
    for name in sorted(names):
        validate_entry_id(name, field_name="legacy directory")
        if name in _RESERVED_DIRECTORIES:
            raise ValueError(f"reserved output directory cannot be archived: {name}")
        source = root / name
        if not source.is_dir() or source.is_symlink():
            raise FileNotFoundError(source)
        fingerprint = fingerprint_tree(source)
        if fingerprint.symbolic_links:
            raise ValueError(f"legacy source contains symbolic links and requires review: {source}")
        source_roots[name] = source.resolve()
        fingerprints[name] = fingerprint

    rewrites = _plan_reference_rewrites(root, source_roots)
    entries = []
    for name in sorted(names):
        entries.append(
            MigrationPlanEntry(
                name=name,
                source_locator=name,
                destination_locator=(
                    f"projects/{ARCHIVE_PROJECT_ID}/runs/{name}/payload"
                ),
                fingerprint=fingerprints[name],
                reference_rewrites=tuple(rewrites.get(name, ())),
            )
        )
    return tuple(entries)


def migrate_legacy_outputs(
    outputs_root: str | Path,
    plan: tuple[MigrationPlanEntry, ...],
) -> dict[str, Any]:
    """Apply a precomputed plan using atomic same-filesystem moves."""

    root = Path(outputs_root).expanduser().resolve()
    runtime = ProjectRuntime(root)
    project = root / "projects" / ARCHIVE_PROJECT_ID
    if not project.exists():
        snapshot = runtime.create(
            ProjectManifest.model_validate(
                {
                    "project_id": ARCHIVE_PROJECT_ID,
                    "title": "SciTaste legacy output archive",
                    "research_direction": (
                        "Preserve pre-project-layout output roots with verified content identity."
                    ),
                    "target_domain": "research-artifact-governance",
                    "status": "archived",
                    "publication_ready": False,
                    "stage_semantics": "legacy-output-archive",
                    "retrieval_eligible": False,
                    "archive_policy": "atomic-move-with-tree-hash-and-reference-rewrite",
                }
            ),
            readme=_archive_readme(),
            stages_document=_archive_stages_document(),
        )
    else:
        snapshot = runtime.open(ARCHIVE_PROJECT_ID)

    migrated: list[dict[str, Any]] = []
    for planned in plan:
        source = root / planned.source_locator
        payload = root / planned.destination_locator
        run = next(
            (item for item in snapshot.manifest.runs if item.run_id == planned.name),
            None,
        )
        if run is None:
            if not source.is_dir() or source.is_symlink():
                raise FileNotFoundError(source)
            current = fingerprint_tree(source)
            _require_same_fingerprint(planned.fingerprint, current, source)
            snapshot = runtime.begin_run(
                ARCHIVE_PROJECT_ID,
                ProjectRun.model_validate(
                    {
                        "run_id": planned.name,
                        "provider": "historical",
                        "model": "historical-unknown",
                        "condition": "legacy-root-artifact",
                        "seed": 0,
                        "status": "migrating",
                        "evidence_scope": "historical-preservation-only",
                        "original_locator": planned.source_locator,
                        "pre_move_fingerprint": asdict(planned.fingerprint),
                        "reference_rewrites": [
                            asdict(rewrite) for rewrite in planned.reference_rewrites
                        ],
                    }
                ),
                expected_revision=snapshot.revision,
            )
            run = next(item for item in snapshot.manifest.runs if item.run_id == planned.name)
        expected = TreeFingerprint(**run.model_extra["pre_move_fingerprint"])
        recorded_rewrites = tuple(
            ReferenceRewrite(**item) for item in run.model_extra.get("reference_rewrites", [])
        )
        if source.exists() and payload.exists():
            raise FileExistsError(
                f"both migration source and destination exist: {source}, {payload}"
            )
        if source.exists():
            current = fingerprint_tree(source)
            _require_same_fingerprint(expected, current, source)
            os.replace(source, payload)
        if not payload.is_dir() or payload.is_symlink():
            raise FileNotFoundError(payload)
        after = fingerprint_tree(payload)
        _require_same_fingerprint(expected, after, payload)
        for rewrite in recorded_rewrites:
            _apply_reference_rewrite(root, rewrite)
        record_locator = f"projects/{ARCHIVE_PROJECT_ID}/runs/{planned.name}/ARCHIVE.json"
        archive_record = {
            "schema_version": "1.0",
            "archive_project_id": ARCHIVE_PROJECT_ID,
            "run_id": planned.name,
            "migrated_at": datetime.now(UTC).isoformat(),
            "original_locator": planned.source_locator,
            "payload_locator": planned.destination_locator,
            "fingerprint": asdict(after),
            "reference_rewrites": [asdict(item) for item in recorded_rewrites],
            "recovery": {
                "operation": "atomic rename payload back to original_locator",
                "precondition": "original_locator must not exist",
                "reference_action": "restore each recorded old_target atomically",
            },
        }
        _atomic_json(root / record_locator, archive_record)
        if run.status != "archived" or run.stage_path != "payload":
            snapshot = runtime.update_run(
                ARCHIVE_PROJECT_ID,
                planned.name,
                expected_revision=snapshot.revision,
                status="archived",
                stage_path="payload",
                artifact=f"runs/{planned.name}/ARCHIVE.json",
                post_move_fingerprint=asdict(after),
                archived_at=archive_record["migrated_at"],
            )
        migrated.append(archive_record)

    migration_manifest = {
        "schema_version": "1.0",
        "archive_project_id": ARCHIVE_PROJECT_ID,
        "updated_at": datetime.now(UTC).isoformat(),
        "entry_count": len(snapshot.manifest.runs),
        "entries": [
            {
                "run_id": run.run_id,
                "original_locator": run.model_extra.get("original_locator"),
                "payload_locator": (
                    f"projects/{ARCHIVE_PROJECT_ID}/runs/{run.run_id}/payload"
                ),
                "status": run.status,
                "tree_sha256": (
                    run.model_extra.get("post_move_fingerprint")
                    or run.model_extra.get("pre_move_fingerprint", {})
                ).get("sha256"),
            }
            for run in snapshot.manifest.runs
        ],
    }
    _atomic_json(project / "MIGRATION.json", migration_manifest)
    return {
        "archive_project_id": ARCHIVE_PROJECT_ID,
        "project_revision": snapshot.revision,
        "migrated_count": len(migrated),
        "entries": migrated,
    }


def verify_legacy_output_archive(outputs_root: str | Path) -> dict[str, Any]:
    """Rehash every archived payload and validate its recovery/reference record."""

    root = Path(outputs_root).expanduser().resolve()
    snapshot = ProjectRuntime(root).open(ARCHIVE_PROJECT_ID)
    if snapshot.warnings:
        raise ValueError(f"archive project has runtime warnings: {snapshot.warnings}")
    verified: list[dict[str, Any]] = []
    total_files = 0
    total_bytes = 0
    for run in snapshot.manifest.runs:
        if run.status != "archived" or run.stage_path != "payload" or run.artifact is None:
            raise ValueError(f"archive run is not finalized: {run.run_id}")
        source = root / str(run.model_extra["original_locator"])
        if os.path.lexists(source):
            raise FileExistsError(f"archived source locator has been reused: {source}")
        payload = root / "projects" / ARCHIVE_PROJECT_ID / "runs" / run.run_id / "payload"
        expected = TreeFingerprint(**run.model_extra["post_move_fingerprint"])
        actual = fingerprint_tree(payload)
        _require_same_fingerprint(expected, actual, payload)
        record_path = root / "projects" / ARCHIVE_PROJECT_ID / run.artifact
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("fingerprint") != asdict(actual):
            raise ValueError(f"archive record fingerprint mismatch: {record_path}")
        for item in record.get("reference_rewrites", []):
            rewrite = ReferenceRewrite(**item)
            link = root / rewrite.locator
            if not link.is_symlink() or os.readlink(link) != rewrite.new_target:
                raise ValueError(f"archive reference rewrite is not active: {link}")
        total_files += actual.regular_files
        total_bytes += actual.bytes
        verified.append({"run_id": run.run_id, "fingerprint": asdict(actual)})
    return {
        "archive_project_id": ARCHIVE_PROJECT_ID,
        "project_revision": snapshot.revision,
        "verified_count": len(verified),
        "regular_files": total_files,
        "bytes": total_bytes,
        "entries": verified,
    }


def _plan_reference_rewrites(
    outputs_root: Path,
    source_roots: dict[str, Path],
) -> dict[str, list[ReferenceRewrite]]:
    rewrites: dict[str, list[ReferenceRewrite]] = {}
    projects = outputs_root / "projects"
    if not projects.is_dir():
        return rewrites
    for link in sorted(projects.rglob("*")):
        if not link.is_symlink():
            continue
        literal = os.readlink(link)
        # Normalize the literal target without following another symlink. An indirect
        # stage alias should keep pointing at its project-owned run alias; rewriting
        # the latter is sufficient and preserves that navigation topology.
        resolved = Path(os.path.abspath(link.parent / literal))
        for name, source in source_roots.items():
            try:
                suffix = resolved.relative_to(source)
            except ValueError:
                continue
            destination = (
                outputs_root
                / "projects"
                / ARCHIVE_PROJECT_ID
                / "runs"
                / name
                / "payload"
                / suffix
            )
            rewrites.setdefault(name, []).append(
                ReferenceRewrite(
                    locator=link.relative_to(outputs_root).as_posix(),
                    old_target=literal,
                    new_target=os.path.relpath(destination, start=link.parent),
                )
            )
            break
    return rewrites


def _apply_reference_rewrite(outputs_root: Path, rewrite: ReferenceRewrite) -> None:
    link = outputs_root / rewrite.locator
    if not link.is_symlink():
        raise FileNotFoundError(f"expected project reference symlink: {link}")
    current = os.readlink(link)
    if current == rewrite.new_target:
        return
    if current != rewrite.old_target:
        raise ValueError(f"project reference changed since planning: {link}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{link.name}.", suffix=".tmp", dir=link.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        os.symlink(rewrite.new_target, temporary)
        os.replace(temporary, link)
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def _require_same_fingerprint(
    expected: TreeFingerprint,
    actual: TreeFingerprint,
    path: Path,
) -> None:
    if expected != actual:
        raise ValueError(f"tree fingerprint changed during migration: {path}")


def _update_tree_digest(
    digest: Any,
    kind: str,
    locator: str,
    metadata: bytes,
) -> None:
    for value in (kind.encode("ascii"), locator.encode("utf-8"), metadata):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _archive_readme() -> str:
    return """# SciTaste legacy output archive

This project preserves output directories created before project ownership became
the canonical layout. Every run owns one unchanged `payload/` tree plus an
`ARCHIVE.json` containing its pre/post-move fingerprint and reference rewrite map.

These artifacts are historical evidence. They are not current acceptance claims,
retrieval inputs, or publication-ready papers.
"""


def _archive_stages_document() -> str:
    return """# Archive semantics

This project does not use AutoResearchClaw stage numbers. Each registered run is
one historical top-level output directory retained under `runs/<name>/payload/`.
The content tree is moved atomically and verified before the run becomes archived.
"""

"""Bind one venue paper bundle to an admitted scientific evaluation result."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from scitaste.project import (
    PaperScientificEvidenceBinding,
    ProjectEvaluationResultBundle,
    ProjectRuntime,
)
from scitaste.project.models import validate_entry_id, validate_project_id

_BINDING_NAME = "SCIENTIFIC_EVIDENCE_BINDING.json"


@dataclass(frozen=True)
class MaterializedPaperScientificEvidence:
    """One deterministic sidecar created without a provider or execution call."""

    path: Path
    binding: PaperScientificEvidenceBinding


def materialize_paper_scientific_evidence(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    paper_id: str,
    result_id: str,
    paper_root: Path,
    artifact_paths: tuple[Path, ...],
) -> MaterializedPaperScientificEvidence:
    """Reverify the selected formal result and bind every existing paper artifact."""

    validate_project_id(project_id)
    validate_entry_id(paper_id, field_name="paper_id")
    validate_entry_id(result_id, field_name="result_id")
    result = require_selected_scientific_evidence(
        runtime,
        project_id=project_id,
        result_id=result_id,
    )

    root = paper_root.resolve(strict=True)
    bindings: dict[str, str] = {}
    for path in artifact_paths:
        resolved = path.resolve(strict=True)
        try:
            locator = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError("paper scientific-evidence artifact escapes its bundle") from exc
        if locator == _BINDING_NAME:
            raise ValueError("paper evidence sidecar cannot bind itself")
        if locator in bindings:
            raise ValueError("paper scientific-evidence artifacts must be unique")
        bindings[locator] = _regular_file_sha256(path)
    if not bindings:
        raise ValueError("paper scientific evidence requires paper artifacts")

    binding = PaperScientificEvidenceBinding.create(
        project_id=project_id,
        paper_id=paper_id,
        evaluation_id=result.evaluation_id,
        result_id=result.result_id,
        result_bundle_sha256=result.bundle_sha256,
        result_set_sha256=result.result_set_sha256,
        assessment_sha256=result.assessment_sha256,
        scientific_evidence_complete=True,
        headline_eligible=True,
        scientific_effectiveness_established=(result.scientific_effectiveness_established),
        bound_artifact_sha256=bindings,
    )
    target = root / _BINDING_NAME
    _write_exclusive_json(target, binding.model_dump(mode="json"))
    return MaterializedPaperScientificEvidence(path=target, binding=binding)


def require_selected_scientific_evidence(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    result_id: str,
) -> ProjectEvaluationResultBundle:
    """Reverify one selected result before a dry-run or paper materialization."""

    validate_project_id(project_id)
    validate_entry_id(result_id, field_name="result_id")
    snapshot = runtime.open(project_id)
    if snapshot.manifest.current_evaluation_result != result_id:
        raise ValueError("paper must bind the project's currently selected evaluation result")
    result = runtime.open_evaluation_result(project_id, result_id)
    if not result.scientific_evidence_complete or not result.headline_eligible:
        raise ValueError("paper scientific evidence requires a complete headline-eligible result")
    return result


def _regular_file_sha256(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not hasattr(os, "O_NOFOLLOW") and path.is_symlink():
        raise ValueError("paper scientific-evidence artifact cannot be a symbolic link")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("paper scientific-evidence artifact must be a regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("paper scientific-evidence artifact must be a regular file")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _write_exclusive_json(path: Path, payload: object) -> None:
    content = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


__all__ = [
    "MaterializedPaperScientificEvidence",
    "materialize_paper_scientific_evidence",
    "require_selected_scientific_evidence",
]

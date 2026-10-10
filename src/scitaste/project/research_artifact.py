"""Register a completed development artifact without changing current paper/run aliases."""

import hashlib
from pathlib import Path

from scitaste.project.models import ProjectRun
from scitaste.project.runtime import ProjectRuntime


def register_artifact(
    *,
    project: Path,
    artifact: Path,
    provider: str,
    model: str,
    condition: str,
    status: str,
    run_id: str | None = None,
):
    project = project.resolve(strict=True)
    if artifact.is_symlink():
        raise ValueError("Register the real immutable artifact, not a mutable alias")
    artifact = artifact.resolve(strict=True)
    locator = artifact.relative_to(project).as_posix()
    if not artifact.is_file():
        raise ValueError("Artifact must be a file")
    row = ProjectRun(
        run_id=run_id or artifact.parent.name,
        provider=provider,
        model=model,
        condition=condition,
        seed=0,
        seed_semantics="registration placeholder; not a provider or experiment seed",
        status=status,
        artifact=locator,
        artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        evidence_scope="development artifact only; not formal evidence or semantic approval",
        formal_evidence_eligible=False,
    )
    runtime = ProjectRuntime(project.parent.parent)
    snapshot = runtime.open(project.name)
    existing = next((item for item in snapshot.manifest.runs if item.run_id == row.run_id), None)
    if existing:
        if existing.model_dump() != row.model_dump():
            raise ValueError("Artifact registration conflicts with an existing run")
        return snapshot.manifest.revision
    updated = runtime.begin_run(project.name, row, expected_revision=snapshot.manifest.revision)
    return updated.manifest.revision

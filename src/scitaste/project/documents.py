"""Bounded living project documents; summaries never grant execution authority."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.project.models import ProjectRun, validate_relative_locator
from scitaste.project.runtime import ProjectRuntime, _atomic_text, _locked

INDEX = "docs/project/INDEX.json"
RUN_ID = "project-living-documents"


def scaffold_documents(project: Path, manifest) -> None:
    """Only for the new, unpublished project scaffold; no historical migration."""
    from datetime import UTC, datetime

    packet = ProjectDocuments(
        project_id=manifest.project_id,
        updated_at=datetime.now(UTC).isoformat(),
        author="project-scaffold",
        focus=manifest.title[:300],
        summary="Project created; phase summaries have not been supplied. No execution inferred.",
        phases=[
            DocumentPhase(
                phase=phase,
                title=phase,
                status="not-documented",
                current="No phase-specific evidence summarized yet.",
                next_steps=["Summarize current work and cite project-owned evidence."],
                references=[],
            )
            for phase in ("idea", "experiments", "writing", "review", "resources")
        ],
    )
    for phase in packet.phases:
        directory = project / "docs/project" / phase.phase
        directory.mkdir(parents=True)
        _atomic_text(directory / "CURRENT.md", phase.current + "\n")
        _atomic_text(directory / "PLAN.md", phase.next_steps[0] + "\n")
    _atomic_text(project / INDEX, packet.model_dump_json(indent=2) + "\n")
    _atomic_text(
        project / "docs/project/SUBMISSION_PLAN.md",
        "# 项目投稿交付计划\n\n"
        f"目标会议: {manifest.target_venue or '尚未选择'}\n\n"
        "尚未配置内部交付日和交付里程碑; 不得推断投稿已完成。\n\n"
        "使用 `scitaste project submission-plan set` 配置项目计划，"  # noqa: RUF001
        "使用 `scitaste project submission-plan status` 查询进度。\n",
    )


class DocumentPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phase: Literal["idea", "experiments", "writing", "review", "resources"]
    title: str = Field(min_length=1, max_length=120)
    status: str = Field(min_length=1, max_length=160)
    current: str = Field(min_length=1, max_length=3000)
    next_steps: list[str] = Field(max_length=8)
    references: list[str] = Field(max_length=12)


class ProjectDocuments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    updated_at: str = Field(min_length=1, max_length=80)
    author: str = Field(min_length=1, max_length=120)
    focus: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=3000)
    phases: list[DocumentPhase] = Field(min_length=1, max_length=5)
    reference_sha256: dict[str, str] = Field(default_factory=dict)
    execution_authority: Literal[False] = False
    live_monitoring: Literal[False] = False


def load_documents(project: Path) -> ProjectDocuments | None:
    path = project / INDEX
    if not path.exists():
        return None
    path.resolve(strict=True).relative_to(project.resolve(strict=True))
    if path.stat().st_size > 64_000:
        raise ValueError("Project document index exceeds size limit")
    result = ProjectDocuments.model_validate_json(path.read_text())
    if result.project_id != project.name:
        raise ValueError("Project document identity mismatch")
    return result


def publish_documents(
    runtime: ProjectRuntime,
    documents: ProjectDocuments,
    *,
    expected_index_sha256: str | None = None,
) -> None:
    """Keep two working files per phase and one append-only history container.

    References are project-local, never fetched or executed. Existing unrelated
    documents are neither migrated nor deleted. A caller must supply a complete
    concise revision rather than append another timestamped working document.
    """
    # model_copy(update=...) skips validation; never publish an unreadable index.
    documents = ProjectDocuments.model_validate(documents.model_dump())
    runtime.open(documents.project_id)
    project = runtime.projects_root / documents.project_id
    if len({item.phase for item in documents.phases}) != len(documents.phases):
        raise ValueError("Duplicate document phase")
    reference_hashes = {}
    for item in documents.phases:
        if any(not text.strip() or len(text) > 1000 for text in item.next_steps):
            raise ValueError("Next steps must be concise and nonempty")
        for locator in item.references:
            validate_relative_locator(locator, field_name="document reference")
            path = (project / locator).resolve(strict=True)
            path.relative_to(project.resolve())
            if not path.is_file():
                raise ValueError("Reference must be an existing project file")
            reference_hashes[locator] = hashlib.sha256(path.read_bytes()).hexdigest()
    documents = documents.model_copy(update={"reference_sha256": reference_hashes})
    raw = documents.model_dump_json(indent=2) + "\n"
    if len(raw.encode()) > 64_000:
        raise ValueError("Summarize before publishing; document index exceeds limit")
    directory = project / "docs/project"
    directory.resolve().relative_to(project.resolve())
    directory.mkdir(parents=True, exist_ok=True)
    for path in (
        directory / ".lock",
        directory / "INDEX.json",
        directory / "archive/revisions.jsonl",
    ):
        path.resolve().relative_to(project.resolve())
    for item in documents.phases:
        folder = directory / item.phase
        for path in (folder / "CURRENT.md", folder / "PLAN.md"):
            path.resolve().relative_to(project.resolve())
        if folder.exists() and any(
            p.name not in {"CURRENT.md", "PLAN.md"} for p in folder.iterdir()
        ):
            raise ValueError("Managed phases permit only CURRENT.md and PLAN.md")
    with _locked(directory / ".lock"):
        index = project / INDEX
        if expected_index_sha256 is not None:
            actual = hashlib.sha256(index.read_bytes()).hexdigest() if index.exists() else ""
            if actual != expected_index_sha256:
                raise ValueError(
                    "Project summary changed during publication; reload before updating"
                )
        if index.exists():
            previous = index.read_text()
            if previous == raw:
                return
            old = ProjectDocuments.model_validate_json(previous)
            if {p.phase for p in old.phases} - {p.phase for p in documents.phases}:
                raise ValueError("Retain retired phases with explicit status; do not orphan files")
            archive = directory / "archive/revisions.jsonl"
            archive.parent.mkdir(exist_ok=True)
            if archive.exists() and archive.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("Archive needs explicit compaction; never delete cited history")
            with archive.open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "sha256": hashlib.sha256(previous.encode()).hexdigest(),
                            "document": json.loads(previous),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        for item in documents.phases:
            folder = directory / item.phase
            folder.mkdir(exist_ok=True)
            refs = "\n".join(f"- `{ref}`" for ref in item.references)
            _atomic_text(
                folder / "CURRENT.md",
                (f"# {item.title}\n\n{item.status}\n\n{item.current}\n\n## References\n\n{refs}\n"),
            )
            steps = "\n".join(f"- {step}" for step in item.next_steps)
            _atomic_text(folder / "PLAN.md", f"# {item.title}: next steps\n\n{steps}\n")
        _atomic_text(index, raw)
        snapshot = runtime.open(documents.project_id)
        if RUN_ID not in {run.run_id for run in snapshot.manifest.runs}:
            runtime.begin_run(
                documents.project_id,
                ProjectRun(
                    run_id=RUN_ID,
                    provider="project-documentation",
                    model="author-declared",
                    condition="living-project-summary",
                    seed=0,
                    status="documented-not-executed",
                    artifact=INDEX,
                    evidence_scope="Planning summary, not execution or scientific evidence",
                    formal_evidence_eligible=False,
                ),
                expected_revision=snapshot.revision,
            )
        else:
            runtime.update_run(
                documents.project_id,
                RUN_ID,
                expected_revision=snapshot.revision,
                status="documented-not-executed",
                artifact=INDEX,
            )

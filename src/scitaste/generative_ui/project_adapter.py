"""Trusted adapter from project-owned artifacts to UI snapshot evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from scitaste.generative_ui.models import EvidenceRef, SnapshotBinding
from scitaste.generative_ui.registry import EvidenceKind
from scitaste.project import ProjectRuntime
from scitaste.project.models import ProjectSnapshot, content_sha256


class ProjectSnapshotAdapter:
    """Resolve and hash authoritative project evidence for declarative surfaces.

    The adapter accepts a runtime and project identity rather than a caller-authored
    ``ProjectSnapshot``. This keeps project lookup, path containment, and evidence
    hashing on the trusted side of the renderer boundary.
    """

    def __init__(self, runtime: ProjectRuntime) -> None:
        self.runtime = runtime

    def build_binding(self, project_id: str) -> SnapshotBinding:
        """Build a content-addressed binding from the runtime's current revision."""

        snapshot = self.runtime.open(project_id)
        invalid_evaluations = [
            warning
            for warning in snapshot.warnings
            if warning.startswith("registered evaluation is missing or invalid:")
        ]
        if invalid_evaluations:
            raise ValueError(
                "project evaluation evidence failed integrity validation: "
                + "; ".join(invalid_evaluations)
            )
        invalid_results = [
            warning
            for warning in snapshot.warnings
            if warning.startswith("registered evaluation result is missing or invalid:")
        ]
        if invalid_results:
            raise ValueError(
                "project evaluation-result evidence failed integrity validation: "
                + "; ".join(invalid_results)
            )
        project_root = self.runtime.outputs_root / snapshot.project_locator
        refs: list[EvidenceRef] = []

        manifest_ref = self._ref(
            snapshot=snapshot,
            project_root=project_root,
            evidence_id="project-manifest",
            kind=EvidenceKind.PROJECT_MANIFEST,
            locator="PROJECT.json",
            label="Project manifest",
        )
        if manifest_ref.sha256 != snapshot.manifest_sha256:
            raise ValueError("project manifest changed while its snapshot was being bound")
        refs.append(manifest_ref)

        for index, run in enumerate(snapshot.manifest.runs, start=1):
            locator = _project_relative(snapshot, snapshot.run_locators[run.run_id])
            refs.append(
                self._ref(
                    snapshot=snapshot,
                    project_root=project_root,
                    evidence_id=_evidence_id("run", locator),
                    kind=EvidenceKind.RUN_RECORD,
                    locator=locator,
                    label=f"Run record {index}",
                )
            )
            projection = (run.model_extra or {}).get("generative_ui_projection")
            if projection == "iclr-evidence-program-v1":
                if run.artifact is None:
                    raise ValueError("ICLR evidence-program run must declare its artifact")
                refs.append(
                    self._ref(
                        snapshot=snapshot,
                        project_root=project_root,
                        evidence_id=_evidence_id("artifact", run.artifact),
                        kind=EvidenceKind.ARTIFACT,
                        locator=run.artifact,
                        label="ICLR evidence program",
                    )
                )
            if projection == "project-program-directive-v1":
                if run.artifact is None:
                    raise ValueError("planning-directive run must declare its artifact")
                refs.append(
                    self._ref(
                        snapshot=snapshot,
                        project_root=project_root,
                        evidence_id=_evidence_id("artifact", run.artifact),
                        kind=EvidenceKind.ARTIFACT,
                        locator=run.artifact,
                        label="Published project planning directive",
                    )
                )

        if snapshot.current_stage_locator is not None:
            locator = _project_relative(snapshot, snapshot.current_stage_locator)
            refs.append(
                self._ref(
                    snapshot=snapshot,
                    project_root=project_root,
                    evidence_id=_evidence_id("stage", locator),
                    kind=EvidenceKind.STAGE_RECORD,
                    locator=locator,
                    label="Current stage record",
                )
            )

        for paper_index, paper in enumerate(snapshot.papers, start=1):
            manifest_locator = f"papers/{paper.directory_name}/MANIFEST.json"
            paper_ref = self._ref(
                snapshot=snapshot,
                project_root=project_root,
                evidence_id=_evidence_id("paper", manifest_locator),
                kind=EvidenceKind.PAPER,
                locator=manifest_locator,
                label=f"Paper record {paper_index}",
            )
            if paper_ref.sha256 != paper.manifest_sha256:
                raise ValueError(
                    f"paper manifest changed while its snapshot was being bound: "
                    f"{paper.directory_name}"
                )
            refs.append(paper_ref)
            for artifact_index, artifact_locator in enumerate(
                paper.manifest.files.values(), start=1
            ):
                locator = f"papers/{paper.directory_name}/{artifact_locator}"
                refs.append(
                    self._ref(
                        snapshot=snapshot,
                        project_root=project_root,
                        evidence_id=_evidence_id("artifact", locator),
                        kind=EvidenceKind.ARTIFACT,
                        locator=locator,
                        label=f"Paper artifact {paper_index}.{artifact_index}",
                    )
                )

        for review_index, review in enumerate(snapshot.manifest.reviews, start=1):
            refs.append(
                self._ref(
                    snapshot=snapshot,
                    project_root=project_root,
                    evidence_id=_evidence_id("review", review.round_locator),
                    kind=EvidenceKind.REVIEW,
                    locator=review.round_locator,
                    label=f"Review round {review_index}",
                )
            )

        for evaluation_index, evaluation in enumerate(snapshot.manifest.evaluations, start=1):
            refs.append(
                self._ref(
                    snapshot=snapshot,
                    project_root=project_root,
                    evidence_id=_evidence_id("evaluation", evaluation.record_locator),
                    kind=EvidenceKind.EVALUATION,
                    locator=evaluation.record_locator,
                    label=f"Evaluation proposal {evaluation_index}",
                )
            )

        for result_index, result in enumerate(snapshot.manifest.evaluation_results, start=1):
            self.runtime.open_evaluation_result(snapshot.project_id, result.result_id)
            refs.append(
                self._ref(
                    snapshot=snapshot,
                    project_root=project_root,
                    evidence_id=_evidence_id("evaluation-result", result.record_locator),
                    kind=EvidenceKind.EVALUATION_RESULT,
                    locator=result.record_locator,
                    label=f"Evaluation result {result_index}",
                )
            )

        binding = SnapshotBinding.from_trusted_evidence(
            project_id=snapshot.project_id,
            snapshot_revision=snapshot.revision,
            evidence_refs=refs,
        )
        current = self.runtime.open(project_id)
        if current.snapshot_sha256 != snapshot.snapshot_sha256:
            raise ValueError("project revision changed while its snapshot was being bound")
        return binding

    @staticmethod
    def _ref(
        *,
        snapshot: ProjectSnapshot,
        project_root: Path,
        evidence_id: str,
        kind: EvidenceKind,
        locator: str,
        label: str,
    ) -> EvidenceRef:
        return EvidenceRef(
            evidence_id=evidence_id,
            project_id=snapshot.project_id,
            kind=kind,
            locator=locator,
            sha256=_content_digest(project_root, locator),
            label=label,
        )


def _project_relative(snapshot: ProjectSnapshot, locator: str) -> str:
    prefix = PurePosixPath(snapshot.project_locator)
    path = PurePosixPath(locator)
    try:
        relative = path.relative_to(prefix)
    except ValueError as exc:
        raise ValueError(f"snapshot locator is outside its project: {locator}") from exc
    return relative.as_posix()


def _evidence_id(prefix: str, locator: str) -> str:
    digest = hashlib.sha256(locator.encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _content_digest(project_root: Path, locator: str) -> str:
    root = project_root.resolve(strict=True)
    candidate = project_root / PurePosixPath(locator)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"evidence locator resolves outside its project: {locator}") from exc

    if resolved.is_file():
        return hashlib.sha256(resolved.read_bytes()).hexdigest()
    if not resolved.is_dir():
        raise ValueError(f"evidence locator is not a regular file or directory: {locator}")

    entries: list[dict[str, str]] = []
    for path in sorted(resolved.rglob("*")):
        relative = path.relative_to(resolved).as_posix()
        if path.is_symlink():
            raise ValueError(f"nested evidence symlinks are not allowed: {locator}/{relative}")
        if path.is_dir():
            entries.append({"path": relative, "type": "directory"})
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        else:
            raise ValueError(f"unsupported evidence entry: {locator}/{relative}")
    return content_sha256(entries)

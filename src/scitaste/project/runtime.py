"""Atomic project ownership, optimistic revisions, and stable artifact aliases."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from scitaste.project.models import (
    PaperManifest,
    ProjectEvaluation,
    ProjectEvaluationBundle,
    ProjectManifest,
    ProjectPaperEntry,
    ProjectReview,
    ProjectRun,
    ProjectSnapshot,
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)

_MAX_EVALUATION_ARTIFACT_BYTES = 16 * 1024 * 1024


class ProjectRevisionConflictError(ValueError):
    """Raised when a writer operates on a stale project revision."""


class ProjectRuntime:
    """Manage one canonical ``outputs/projects/<project-id>`` ownership tree."""

    def __init__(self, outputs_root: str | Path) -> None:
        self.outputs_root = Path(outputs_root).expanduser().resolve()
        self.projects_root = self.outputs_root / "projects"

    def create(
        self,
        manifest: ProjectManifest,
        *,
        readme: str | None = None,
        stages_document: str | None = None,
    ) -> ProjectSnapshot:
        """Atomically create a complete project scaffold without replacing existing data."""

        target = self._project_path(manifest.project_id)
        self.projects_root.mkdir(parents=True, exist_ok=True)
        with _locked(self.projects_root / ".projects.lock"):
            if _lexists(target):
                raise FileExistsError(target)
            temporary = Path(tempfile.mkdtemp(prefix=".project-", dir=self.projects_root))
            try:
                for name in ("runs", "stages", "papers", "reviews", "evaluations"):
                    (temporary / name).mkdir()
                _atomic_json(temporary / "PROJECT.json", manifest.model_dump(mode="json"))
                _atomic_text(
                    temporary / "README.md",
                    readme if readme is not None else _default_readme(manifest),
                )
                _atomic_text(
                    temporary / "STAGES.md",
                    stages_document
                    if stages_document is not None
                    else _default_stages_document(manifest),
                )
                os.replace(temporary, target)
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        return self.open(manifest.project_id)

    def open(self, project_id: str) -> ProjectSnapshot:
        """Read and validate a project without changing historical directories."""

        project = self._project_path(project_id)
        manifest = self._load_manifest(project)
        return self._snapshot(project, manifest)

    def update(
        self,
        project_id: str,
        *,
        expected_revision: int,
        **changes: Any,
    ) -> ProjectSnapshot:
        """Atomically update project metadata under an optimistic revision guard."""

        if {"project_id", "revision", "runs", "reviews", "evaluations"} & changes.keys():
            raise ValueError(
                "project identity, revision, runs, reviews, and evaluations use dedicated "
                "operations"
            )
        if {
            "current_run",
            "current_paper",
            "current_review",
            "current_evaluation",
        } & changes.keys():
            raise ValueError(
                "use select_run, select_paper, select_review, or select_evaluation to update "
                "current aliases"
            )
        project = self._project_path(project_id)
        with _locked(project / ".project.lock"):
            manifest = self._replace_manifest(
                project,
                expected_revision=expected_revision,
                changes=changes,
            )
        return self._snapshot(project, manifest)

    def begin_run(
        self,
        project_id: str,
        run: ProjectRun,
        *,
        expected_revision: int,
    ) -> ProjectSnapshot:
        """Register a new project-owned run directory and increment project revision."""

        project = self._project_path(project_id)
        run_dir = project / "runs" / run.run_id
        with _locked(project / ".project.lock"):
            manifest = self._load_manifest(project)
            self._require_revision(manifest, expected_revision)
            if run.run_id in {item.run_id for item in manifest.runs} or _lexists(run_dir):
                raise FileExistsError(run_dir)
            run_dir.mkdir(parents=True)
            if run.stage_path is not None:
                (run_dir / run.stage_path).mkdir(parents=True)
            try:
                manifest = self._replace_manifest(
                    project,
                    expected_revision=expected_revision,
                    changes={"runs": [*manifest.runs, run]},
                )
            except BaseException:
                shutil.rmtree(run_dir, ignore_errors=True)
                raise
        return self._snapshot(project, manifest)

    def select_run(
        self,
        project_id: str,
        run_id: str,
        *,
        expected_revision: int,
    ) -> ProjectSnapshot:
        """Select a registered run and atomically replace its stage-navigation aliases."""

        validate_entry_id(run_id, field_name="run_id")
        project = self._project_path(project_id)
        with _locked(project / ".project.lock"):
            manifest = self._load_manifest(project)
            self._require_revision(manifest, expected_revision)
            try:
                run = next(item for item in manifest.runs if item.run_id == run_id)
            except StopIteration as exc:
                raise ValueError(f"unknown project run {run_id!r}") from exc
            run_dir = project / "runs" / run_id
            if not run_dir.exists():
                raise FileNotFoundError(run_dir)
            stage_source = run_dir / (run.stage_path or ".")
            if not stage_source.exists():
                raise FileNotFoundError(stage_source)
            stages = project / "stages"
            stages.mkdir(parents=True, exist_ok=True)
            stage_alias = stages / run_id
            current_alias = stages / "current"
            _require_replaceable_symlink(stage_alias)
            _require_replaceable_symlink(current_alias)
            relative_target = f"../runs/{run_id}"
            if run.stage_path:
                relative_target += f"/{run.stage_path}"
            _replace_symlink(stage_alias, relative_target)
            _replace_symlink(current_alias, run_id)
            manifest = self._replace_manifest(
                project,
                expected_revision=expected_revision,
                changes={"current_run": run_id},
            )
        return self._snapshot(project, manifest)

    def update_run(
        self,
        project_id: str,
        registered_run_id: str,
        *,
        expected_revision: int,
        **changes: Any,
    ) -> ProjectSnapshot:
        """Update metadata for one registered run under the project revision guard."""

        validate_entry_id(registered_run_id, field_name="run_id")
        if "run_id" in changes:
            raise ValueError("run identity cannot be changed")
        project = self._project_path(project_id)
        with _locked(project / ".project.lock"):
            manifest = self._load_manifest(project)
            self._require_revision(manifest, expected_revision)
            matches = [item for item in manifest.runs if item.run_id == registered_run_id]
            if not matches:
                raise ValueError(f"unknown project run {registered_run_id!r}")
            payload = matches[0].model_dump(mode="json")
            payload.update(changes)
            updated = ProjectRun.model_validate(payload)
            runs = [updated if item.run_id == registered_run_id else item for item in manifest.runs]
            manifest = self._replace_manifest(
                project,
                expected_revision=expected_revision,
                changes={"runs": runs},
            )
        return self._snapshot(project, manifest)

    def register_paper(
        self,
        project_id: str,
        paper: PaperManifest,
        *,
        directory_name: str,
        expected_revision: int,
    ) -> ProjectSnapshot:
        """Register an already materialized, project-owned paper bundle."""

        validate_entry_id(directory_name, field_name="paper directory")
        project = self._project_path(project_id)
        if paper.project_id != project_id:
            raise ValueError("paper project_id must match the owning project")
        paper_dir = project / "papers" / directory_name
        with _locked(project / ".project.lock"):
            manifest = self._load_manifest(project)
            self._require_revision(manifest, expected_revision)
            if paper.source_run is not None and paper.source_run not in {
                item.run_id for item in manifest.runs
            }:
                raise ValueError("paper source_run must reference a registered project run")
            paper_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = paper_dir / "MANIFEST.json"
            if _lexists(manifest_path):
                raise FileExistsError(manifest_path)
            for locator in paper.files.values():
                artifact = _contained_path(paper_dir, locator)
                if not artifact.is_file():
                    raise FileNotFoundError(artifact)
            _atomic_json(manifest_path, paper.model_dump(mode="json"))
            manifest = self._replace_manifest(
                project,
                expected_revision=expected_revision,
                changes={},
            )
        return self._snapshot(project, manifest)

    def select_paper(
        self,
        project_id: str,
        directory_name: str,
        *,
        expected_revision: int,
        global_latest: bool = True,
    ) -> ProjectSnapshot:
        """Select a validated paper bundle for both project and optional global navigation."""

        validate_entry_id(directory_name, field_name="paper directory")
        project = self._project_path(project_id)
        paper_dir = project / "papers" / directory_name
        paper = self._load_paper(paper_dir / "MANIFEST.json")
        if paper.project_id != project_id:
            raise ValueError("paper manifest belongs to another project")
        global_lock = self.outputs_root / ".outputs.lock"
        with _locked(global_lock), _locked(project / ".project.lock"):
            manifest = self._load_manifest(project)
            self._require_revision(manifest, expected_revision)
            current_alias = project / "papers" / "current"
            _require_replaceable_symlink(current_alias)
            latest_alias = self.outputs_root / "papers" / "latest"
            if global_latest:
                latest_alias.parent.mkdir(parents=True, exist_ok=True)
                _require_replaceable_symlink(latest_alias)
            _replace_symlink(current_alias, directory_name)
            if global_latest:
                _replace_symlink(
                    latest_alias,
                    f"../projects/{project_id}/papers/{directory_name}",
                )
            manifest = self._replace_manifest(
                project,
                expected_revision=expected_revision,
                changes={"current_paper": f"papers/{directory_name}"},
            )
        return self._snapshot(project, manifest)

    def register_review(
        self,
        project_id: str,
        review: ProjectReview,
        *,
        expected_revision: int,
    ) -> ProjectSnapshot:
        """Register one already materialized review-round projection."""

        project = self._project_path(project_id)
        review_dir = project / "reviews" / review.review_id
        round_path = project / review.round_locator
        with _locked(project / ".project.lock"):
            manifest = self._load_manifest(project)
            self._require_revision(manifest, expected_revision)
            if review.review_id in {item.review_id for item in manifest.reviews}:
                raise FileExistsError(review_dir)
            paper_path = project / "papers" / review.paper_directory / "MANIFEST.json"
            if not paper_path.is_file():
                raise FileNotFoundError(paper_path)
            if not review_dir.is_dir() or review_dir.is_symlink():
                raise FileNotFoundError(review_dir)
            contained_round = _contained_project_path(project, review.round_locator)
            if contained_round != round_path.resolve(strict=True):
                raise ValueError("review round locator does not resolve to its canonical path")
            observed = hashlib.sha256(round_path.read_bytes()).hexdigest()
            if observed != review.round_sha256:
                raise ValueError("review round hash does not match the materialized record")
            manifest = self._replace_manifest(
                project,
                expected_revision=expected_revision,
                changes={"reviews": [*manifest.reviews, review]},
            )
        return self._snapshot(project, manifest)

    def update_review(
        self,
        project_id: str,
        review_id: str,
        *,
        expected_revision: int,
        **changes: Any,
    ) -> ProjectSnapshot:
        """Update the pointer for one review after rehashing its round projection."""

        validate_entry_id(review_id, field_name="review_id")
        if {"review_id", "paper_directory", "venue_id", "round_number"} & changes.keys():
            raise ValueError("review identity cannot be changed")
        project = self._project_path(project_id)
        with _locked(project / ".project.lock"):
            manifest = self._load_manifest(project)
            self._require_revision(manifest, expected_revision)
            matches = [item for item in manifest.reviews if item.review_id == review_id]
            if not matches:
                raise ValueError(f"unknown project review {review_id!r}")
            payload = matches[0].model_dump(mode="json")
            payload.update(changes)
            updated = ProjectReview.model_validate(payload)
            round_path = _contained_project_path(project, updated.round_locator)
            observed = hashlib.sha256(round_path.read_bytes()).hexdigest()
            if observed != updated.round_sha256:
                raise ValueError("review round hash does not match the materialized record")
            reviews = [
                updated if item.review_id == review_id else item for item in manifest.reviews
            ]
            manifest = self._replace_manifest(
                project,
                expected_revision=expected_revision,
                changes={"reviews": reviews},
            )
        return self._snapshot(project, manifest)

    def select_review(
        self,
        project_id: str,
        review_id: str,
        *,
        expected_revision: int,
    ) -> ProjectSnapshot:
        """Select a registered review round for stable project navigation."""

        validate_entry_id(review_id, field_name="review_id")
        project = self._project_path(project_id)
        with _locked(project / ".project.lock"):
            manifest = self._load_manifest(project)
            self._require_revision(manifest, expected_revision)
            matches = [item for item in manifest.reviews if item.review_id == review_id]
            if not matches:
                raise ValueError(f"unknown project review {review_id!r}")
            round_path = _contained_project_path(project, matches[0].round_locator)
            observed = hashlib.sha256(round_path.read_bytes()).hexdigest()
            if observed != matches[0].round_sha256:
                raise ValueError("registered review round hash has drifted")
            current_alias = project / "reviews" / "current"
            _require_replaceable_symlink(current_alias)
            _replace_symlink(current_alias, review_id)
            manifest = self._replace_manifest(
                project,
                expected_revision=expected_revision,
                changes={"current_review": review_id},
            )
        return self._snapshot(project, manifest)

    def publish_evaluation(
        self,
        project_id: str,
        bundle: ProjectEvaluationBundle,
        *,
        artifact_payloads: dict[str, bytes],
        expected_revision: int,
    ) -> ProjectSnapshot:
        """Atomically publish and register one immutable no-run evaluation proposal."""

        if bundle.project_id != project_id:
            raise ValueError("evaluation bundle project_id must match the owning project")
        project = self._project_path(project_id)
        evaluations_root = project / "evaluations"
        evaluation_dir = evaluations_root / bundle.evaluation_id
        expected_locators = {item.locator for item in bundle.files.values()}
        if set(artifact_payloads) != expected_locators:
            raise ValueError("evaluation payloads must exactly cover bound artifact locators")
        for label, binding in bundle.files.items():
            payload = artifact_payloads[binding.locator]
            if not payload or len(payload) > _MAX_EVALUATION_ARTIFACT_BYTES:
                raise ValueError(f"evaluation artifact {label!r} has an invalid size")
            if len(payload) != binding.size_bytes:
                raise ValueError(f"evaluation artifact {label!r} size mismatch")
            if hashlib.sha256(payload).hexdigest() != binding.sha256:
                raise ValueError(f"evaluation artifact {label!r} hash mismatch")

        with _locked(project / ".project.lock"):
            manifest = self._load_manifest(project)
            self._require_revision(manifest, expected_revision)
            if bundle.evaluation_id in {
                item.evaluation_id for item in manifest.evaluations
            } or _lexists(evaluation_dir):
                raise FileExistsError(evaluation_dir)
            evaluations_root.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".evaluation-", dir=evaluations_root))
            published = False
            try:
                for locator, payload in artifact_payloads.items():
                    _atomic_bytes(temporary / PurePosixPath(locator), payload)
                record_bytes = _json_bytes(bundle.model_dump(mode="json"))
                _atomic_bytes(temporary / "EVALUATION.json", record_bytes)
                _verify_evaluation_bundle(temporary, bundle)
                os.replace(temporary, evaluation_dir)
                published = True
                blocker_count = len(
                    set(
                        (
                            *bundle.readiness_blocker_codes,
                            *bundle.authorization_blocker_codes,
                            *bundle.critic_blocking_codes,
                            *bundle.cell_plan_blockers,
                        )
                    )
                )
                entry = ProjectEvaluation(
                    evaluation_id=bundle.evaluation_id,
                    manifest_id=bundle.manifest_id,
                    protocol_id=bundle.protocol_id,
                    study_scope=bundle.study_scope,
                    status=bundle.status,
                    proposal_sha256=bundle.proposal_sha256,
                    planned_cells=bundle.planned_cells,
                    api_resources=bundle.api_resources,
                    gpu_resources=bundle.gpu_resources,
                    ready_for_author_review=bundle.ready_for_author_review,
                    execution_authorized=bundle.execution_authorized,
                    blocker_count=blocker_count,
                    record_locator=(f"evaluations/{bundle.evaluation_id}/EVALUATION.json"),
                    record_sha256=hashlib.sha256(record_bytes).hexdigest(),
                )
                manifest = self._replace_manifest(
                    project,
                    expected_revision=expected_revision,
                    changes={"evaluations": [*manifest.evaluations, entry]},
                )
            except BaseException:
                shutil.rmtree(evaluation_dir if published else temporary, ignore_errors=True)
                raise
        return self._snapshot(project, manifest)

    def select_evaluation(
        self,
        project_id: str,
        evaluation_id: str,
        *,
        expected_revision: int,
    ) -> ProjectSnapshot:
        """Select one verified proposal for stable project-home navigation."""

        validate_entry_id(evaluation_id, field_name="evaluation_id")
        project = self._project_path(project_id)
        with _locked(project / ".project.lock"):
            manifest = self._load_manifest(project)
            self._require_revision(manifest, expected_revision)
            matches = [item for item in manifest.evaluations if item.evaluation_id == evaluation_id]
            if not matches:
                raise ValueError(f"unknown project evaluation {evaluation_id!r}")
            record_path = _contained_project_path(project, matches[0].record_locator)
            raw = record_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != matches[0].record_sha256:
                raise ValueError("registered evaluation record has drifted")
            bundle = ProjectEvaluationBundle.model_validate_json(raw)
            _require_evaluation_entry_matches_bundle(matches[0], bundle)
            _verify_evaluation_bundle(record_path.parent, bundle)
            current_alias = project / "evaluations" / "current"
            _require_replaceable_symlink(current_alias)
            _replace_symlink(current_alias, evaluation_id)
            manifest = self._replace_manifest(
                project,
                expected_revision=expected_revision,
                changes={"current_evaluation": evaluation_id},
            )
        return self._snapshot(project, manifest)

    def _project_path(self, project_id: str) -> Path:
        validate_project_id(project_id)
        return self.projects_root / project_id

    @staticmethod
    def _load_manifest(project: Path) -> ProjectManifest:
        path = project / "PROJECT.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        manifest = ProjectManifest.model_validate_json(path.read_text(encoding="utf-8"))
        if manifest.project_id != project.name:
            raise ValueError("PROJECT.json project_id does not match its directory")
        return manifest

    @staticmethod
    def _load_paper(path: Path) -> PaperManifest:
        if not path.is_file():
            raise FileNotFoundError(path)
        return PaperManifest.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _require_revision(manifest: ProjectManifest, expected_revision: int) -> None:
        if manifest.revision != expected_revision:
            raise ProjectRevisionConflictError(
                f"stale project revision {expected_revision}; current is {manifest.revision}"
            )

    def _replace_manifest(
        self,
        project: Path,
        *,
        expected_revision: int,
        changes: dict[str, Any],
    ) -> ProjectManifest:
        current = self._load_manifest(project)
        self._require_revision(current, expected_revision)
        payload = current.model_dump(mode="json")
        payload.update(changes)
        payload["revision"] = current.revision + 1
        updated = ProjectManifest.model_validate(payload)
        _atomic_json(project / "PROJECT.json", updated.model_dump(mode="json"))
        return updated

    def _snapshot(self, project: Path, manifest: ProjectManifest) -> ProjectSnapshot:
        warnings: list[str] = []
        run_locators: dict[str, str] = {}
        for run in manifest.runs:
            canonical = f"projects/{manifest.project_id}/runs/{run.run_id}"
            run_path = self.outputs_root / canonical
            if _lexists(run_path):
                locator = canonical
            elif run.artifact is not None and (project / run.artifact).exists():
                locator = f"projects/{manifest.project_id}/{run.artifact}"
            else:
                locator = canonical
                warnings.append(f"registered run is missing: {run.run_id}")
            run_locators[run.run_id] = locator

        review_locators: dict[str, str] = {}
        for review in manifest.reviews:
            canonical = f"projects/{manifest.project_id}/{review.round_locator}"
            try:
                round_path = _contained_project_path(project, review.round_locator)
                observed = hashlib.sha256(round_path.read_bytes()).hexdigest()
                if observed != review.round_sha256:
                    warnings.append(f"registered review hash mismatch: {review.review_id}")
                review_locators[review.review_id] = canonical
            except (OSError, ValueError):
                review_locators[review.review_id] = canonical
                warnings.append(f"registered review is missing or invalid: {review.review_id}")

        evaluation_locators: dict[str, str] = {}
        for evaluation in manifest.evaluations:
            canonical = f"projects/{manifest.project_id}/{evaluation.record_locator}"
            evaluation_locators[evaluation.evaluation_id] = canonical
            try:
                record_path = _contained_project_path(project, evaluation.record_locator)
                raw = record_path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != evaluation.record_sha256:
                    raise ValueError("record hash mismatch")
                bundle = ProjectEvaluationBundle.model_validate_json(raw)
                if bundle.project_id != manifest.project_id:
                    raise ValueError("record project identity mismatch")
                _require_evaluation_entry_matches_bundle(evaluation, bundle)
                _verify_evaluation_bundle(record_path.parent, bundle)
            except (OSError, ValueError):
                warnings.append(
                    f"registered evaluation is missing or invalid: {evaluation.evaluation_id}"
                )

        papers: list[ProjectPaperEntry] = []
        papers_root = project / "papers"
        if papers_root.is_dir():
            for path in sorted(papers_root.glob("*/MANIFEST.json")):
                if path.parent.is_symlink():
                    continue
                try:
                    paper = self._load_paper(path)
                    if paper.project_id != manifest.project_id:
                        raise ValueError("paper manifest belongs to another project")
                    raw = path.read_bytes()
                    papers.append(
                        ProjectPaperEntry(
                            directory_name=path.parent.name,
                            manifest_sha256=hashlib.sha256(raw).hexdigest(),
                            manifest=paper,
                        )
                    )
                except (OSError, ValueError) as exc:
                    warnings.append(f"invalid paper manifest {path.parent.name}: {exc}")

        current_run_locator = (
            run_locators.get(manifest.current_run) if manifest.current_run is not None else None
        )
        current_stage_locator = None
        if manifest.current_run is not None:
            stage_link = project / "stages" / "current"
            if _lexists(stage_link):
                current_stage_locator = f"projects/{manifest.project_id}/stages/current"
            else:
                warnings.append("current_run has no stages/current alias")
        current_paper_locator = None
        if manifest.current_paper is not None:
            paper_link = project / "papers" / "current"
            paper_dir = project / manifest.current_paper
            if not paper_dir.is_dir():
                warnings.append(f"current paper is missing: {manifest.current_paper}")
            elif not _lexists(paper_link):
                warnings.append("current_paper has no papers/current alias")
            else:
                current_paper_locator = f"projects/{manifest.project_id}/{manifest.current_paper}"
        current_review_locator = None
        if manifest.current_review is not None:
            review_link = project / "reviews" / "current"
            review = next(
                item for item in manifest.reviews if item.review_id == manifest.current_review
            )
            try:
                _contained_project_path(project, review.round_locator)
            except (OSError, ValueError):
                warnings.append(f"current review is missing: {manifest.current_review}")
            else:
                if not _lexists(review_link):
                    warnings.append("current_review has no reviews/current alias")
                else:
                    current_review_locator = (
                        f"projects/{manifest.project_id}/reviews/{manifest.current_review}"
                    )
        current_evaluation_locator = None
        if manifest.current_evaluation is not None:
            evaluation_link = project / "evaluations" / "current"
            if manifest.current_evaluation not in evaluation_locators:
                warnings.append(f"current evaluation is missing: {manifest.current_evaluation}")
            elif not _lexists(evaluation_link):
                warnings.append("current_evaluation has no evaluations/current alias")
            else:
                current_evaluation_locator = (
                    f"projects/{manifest.project_id}/evaluations/{manifest.current_evaluation}"
                )

        manifest_path = project / "PROJECT.json"
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        snapshot_payload = {
            "manifest": manifest.model_dump(mode="json"),
            "manifest_sha256": manifest_sha,
            "run_locators": run_locators,
            "review_locators": review_locators,
            "evaluation_locators": evaluation_locators,
            "papers": [item.model_dump(mode="json") for item in papers],
            "current_run_locator": current_run_locator,
            "current_stage_locator": current_stage_locator,
            "current_paper_locator": current_paper_locator,
            "current_review_locator": current_review_locator,
            "current_evaluation_locator": current_evaluation_locator,
            "warnings": warnings,
        }
        return ProjectSnapshot(
            project_id=manifest.project_id,
            revision=manifest.revision,
            snapshot_sha256=content_sha256(snapshot_payload),
            manifest_sha256=manifest_sha,
            project_locator=f"projects/{manifest.project_id}",
            manifest=manifest,
            run_locators=run_locators,
            review_locators=review_locators,
            evaluation_locators=evaluation_locators,
            papers=papers,
            current_run_locator=current_run_locator,
            current_stage_locator=current_stage_locator,
            current_paper_locator=current_paper_locator,
            current_review_locator=current_review_locator,
            current_evaluation_locator=current_evaluation_locator,
            warnings=warnings,
        )


def _contained_path(root: Path, locator: str) -> Path:
    validate_relative_locator(locator, field_name="artifact locator")
    candidate = root / PurePosixPath(locator)
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("artifact locator resolves outside its paper bundle") from exc
    return candidate


def _contained_project_path(project: Path, locator: str) -> Path:
    validate_relative_locator(locator, field_name="project artifact locator")
    root = project.resolve(strict=True)
    candidate = project / PurePosixPath(locator)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("project artifact locator resolves outside its project") from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise ValueError("project artifact locator must be a regular non-symlink file")
    return resolved


def _verify_evaluation_bundle(
    directory: Path,
    bundle: ProjectEvaluationBundle,
) -> None:
    for label, binding in bundle.files.items():
        candidate = directory / PurePosixPath(binding.locator)
        parent = directory
        for part in PurePosixPath(binding.locator).parts:
            parent /= part
            if parent.is_symlink():
                raise ValueError(f"evaluation artifact {label!r} cannot traverse a symbolic link")
        artifact = _contained_path(directory, binding.locator)
        if candidate.is_symlink() or not artifact.is_file():
            raise ValueError(f"evaluation artifact {label!r} must be a regular file")
        raw = artifact.read_bytes()
        if len(raw) != binding.size_bytes:
            raise ValueError(f"evaluation artifact {label!r} size mismatch")
        if hashlib.sha256(raw).hexdigest() != binding.sha256:
            raise ValueError(f"evaluation artifact {label!r} hash mismatch")


def _require_evaluation_entry_matches_bundle(
    entry: ProjectEvaluation,
    bundle: ProjectEvaluationBundle,
) -> None:
    blocker_count = len(
        set(
            (
                *bundle.readiness_blocker_codes,
                *bundle.authorization_blocker_codes,
                *bundle.critic_blocking_codes,
                *bundle.cell_plan_blockers,
            )
        )
    )
    if (
        bundle.evaluation_id != entry.evaluation_id
        or bundle.manifest_id != entry.manifest_id
        or bundle.protocol_id != entry.protocol_id
        or bundle.study_scope != entry.study_scope
        or bundle.status != entry.status
        or bundle.proposal_sha256 != entry.proposal_sha256
        or bundle.planned_cells != entry.planned_cells
        or bundle.api_resources != entry.api_resources
        or bundle.gpu_resources != entry.gpu_resources
        or bundle.ready_for_author_review != entry.ready_for_author_review
        or bundle.execution_authorized != entry.execution_authorized
        or blocker_count != entry.blocker_count
        or bundle.no_execution_performed != entry.no_execution_performed
    ):
        raise ValueError("registered evaluation summary does not match its bundle")


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _require_replaceable_symlink(path: Path) -> None:
    if _lexists(path) and not path.is_symlink():
        raise FileExistsError(f"refusing to replace non-symlink path: {path}")


def _replace_symlink(path: Path, target: str) -> None:
    _require_replaceable_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, payload: Any) -> None:
    _atomic_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _atomic_bytes(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        _fsync_directory(path.parent)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _atomic_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        _fsync_directory(path.parent)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _default_readme(manifest: ProjectManifest) -> str:
    return (
        f"# {manifest.title}\n\n"
        f"Project ID: `{manifest.project_id}`\n\n"
        f"{manifest.research_direction}\n"
    )


def _default_stages_document(manifest: ProjectManifest) -> str:
    return (
        "# Stage semantics\n\n"
        f"This project uses `{manifest.stage_semantics}`.\n\n"
        "`stages/current` is a navigation alias selected by ProjectRuntime; "
        "historical run directories remain immutable.\n"
    )

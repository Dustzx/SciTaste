"""Strict research-landscape artifacts for visual experiment-design sensemaking."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.generative_ui.safety import SafeIdentifier, SafeLocator, SafeText, Sha256
from scitaste.project.models import ProjectRun, ProjectSnapshot

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_PROJECTION_KIND = "autoresearch-evaluation-landscape-v2"
_PROJECTION_KINDS = frozenset({"autoresearch-evaluation-landscape-v1", _PROJECTION_KIND})
_MAX_ARTIFACT_BYTES = 256 * 1024


class ResearchStage(BaseModel):
    model_config = _CONFIG

    stage_id: SafeIdentifier
    label_en: SafeText
    label_zh: SafeText


class EvaluationLens(BaseModel):
    model_config = _CONFIG

    lens_id: SafeIdentifier
    symbol: SafeText
    label_en: SafeText
    label_zh: SafeText
    question_en: SafeText
    question_zh: SafeText


class ResearchWork(BaseModel):
    model_config = _CONFIG

    work_id: SafeIdentifier
    name: SafeText
    venue: SafeText
    evaluation_unit: SafeText
    scale: SafeText
    comparison_anchor: SafeText
    contribution_type: Literal["method", "benchmark", "hybrid", "unclassified"] = "unclassified"
    experiment_role: Literal["system-comparator", "task-source", "design-precedent"] = (
        "design-precedent"
    )
    bundled_artifacts: tuple[Literal["system", "benchmark", "judge", "dataset"], ...] = Field(
        default=(), max_length=4
    )
    stage_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=8)
    lens_ids: tuple[SafeIdentifier, ...] = Field(min_length=1, max_length=6)
    execution_signal: Literal["executed", "mixed", "artifact", "simulated"]
    resource_tier: Literal["desktop", "moderate", "high", "frontier", "unreported"]
    role: Literal["primary", "anchor", "context"]


class ComparisonCandidate(BaseModel):
    model_config = _CONFIG

    candidate_id: SafeIdentifier
    name: SafeText
    candidate_kind: Literal["benchmark", "system", "judge"]
    role: Literal["primary", "secondary", "stretch"]
    readiness: Literal["reference", "adaptation", "formal"]
    barrier_code: SafeIdentifier


class PlanningGate(BaseModel):
    model_config = _CONFIG

    gate_id: SafeIdentifier
    label_en: SafeText
    label_zh: SafeText
    state: Literal["ready", "candidate", "blocked"]
    reason_code: SafeIdentifier


class ResearchQuestion(BaseModel):
    model_config = _CONFIG

    question_id: SafeIdentifier
    label_en: SafeText
    label_zh: SafeText


class ResearchLandscapeArtifact(BaseModel):
    """Projectable synthesis; it describes literature, never experiment results."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.1"
    artifact_kind: Literal[
        "autoresearch-evaluation-landscape-v1",
        "autoresearch-evaluation-landscape-v2",
    ] = _PROJECTION_KIND
    title: SafeText
    source_document: SafeLocator
    source_document_sha256: Sha256
    synthesis_scope: Literal["literature-and-protocol-design-only"]
    corpus_scope: Literal["targeted-evaluation-precedents"] = "targeted-evaluation-precedents"
    scope_note_en: SafeText = (
        "Selected evaluation precedents; counts do not estimate publication prevalence."
    )
    scope_note_zh: SafeText = "评测先例定向样本的数量不代表领域论文分布。"
    freeze_decision: Literal["hold", "candidate", "ready"]
    decision_reason_code: SafeIdentifier
    stages: tuple[ResearchStage, ...] = Field(min_length=4, max_length=8)
    lenses: tuple[EvaluationLens, ...] = Field(min_length=3, max_length=6)
    works: tuple[ResearchWork, ...] = Field(min_length=3, max_length=16)
    comparison_candidates: tuple[ComparisonCandidate, ...] = Field(min_length=2, max_length=12)
    planning_gates: tuple[PlanningGate, ...] = Field(min_length=4, max_length=8)
    open_questions: tuple[ResearchQuestion, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def references_are_closed_and_ordered(self) -> ResearchLandscapeArtifact:
        expected_pair = {
            "1.0": "autoresearch-evaluation-landscape-v1",
            "1.1": "autoresearch-evaluation-landscape-v2",
        }
        if self.artifact_kind != expected_pair[self.schema_version]:
            raise ValueError("research landscape schema and artifact kind must match")
        stage_ids = [item.stage_id for item in self.stages]
        lens_ids = [item.lens_id for item in self.lenses]
        work_ids = [item.work_id for item in self.works]
        candidate_ids = [item.candidate_id for item in self.comparison_candidates]
        gate_ids = [item.gate_id for item in self.planning_gates]
        question_ids = [item.question_id for item in self.open_questions]
        for label, values in (
            ("stage", stage_ids),
            ("lens", lens_ids),
            ("work", work_ids),
            ("candidate", candidate_ids),
            ("gate", gate_ids),
            ("question", question_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"research landscape {label} IDs must be unique")
        known_stages = set(stage_ids)
        known_lenses = set(lens_ids)
        for work in self.works:
            if set(work.stage_ids) - known_stages:
                raise ValueError("research work references an unknown lifecycle stage")
            if set(work.lens_ids) - known_lenses:
                raise ValueError("research work references an unknown evaluation lens")
            if len(work.stage_ids) != len(set(work.stage_ids)):
                raise ValueError("research work lifecycle stages must be unique")
            if len(work.lens_ids) != len(set(work.lens_ids)):
                raise ValueError("research work evaluation lenses must be unique")
        if not any(item.role == "primary" for item in self.works):
            raise ValueError("research landscape requires a primary comparison work")
        contribution_types = {item.contribution_type for item in self.works}
        if self.schema_version == "1.1":
            if "unclassified" in contribution_types:
                raise ValueError("v2 research works require an explicit contribution type")
            if not {"method", "benchmark", "hybrid"}.issubset(contribution_types):
                raise ValueError("v2 landscape must separate method, benchmark, and hybrid work")
            for work in self.works:
                if len(work.bundled_artifacts) != len(set(work.bundled_artifacts)):
                    raise ValueError("research work bundled artifacts must be unique")
        if self.freeze_decision == "ready" and any(
            item.state != "ready" for item in self.planning_gates
        ):
            raise ValueError("a ready freeze decision requires every planning gate")
        return self


class ResearchLandscapeData(ResearchLandscapeArtifact):
    """Receiver data bound to the project manifest and one content-addressed run."""

    project_ref_id: SafeIdentifier
    run_ref_id: SafeIdentifier
    support_ref_ids: tuple[SafeIdentifier, ...] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def evidence_binding_is_closed(self) -> ResearchLandscapeData:
        if set(self.support_ref_ids) != {self.project_ref_id, self.run_ref_id}:
            raise ValueError("research landscape must cite exactly its project and run evidence")
        return self


def load_research_landscape_source(path: str | Path) -> ResearchLandscapeArtifact:
    """Load one tracked YAML/JSON synthesis through the closed artifact schema."""

    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("research landscape source must be an object")
    return ResearchLandscapeArtifact.model_validate(payload)


def materialize_research_landscape(
    source: str | Path,
    output: str | Path,
    *,
    evidence_root: str | Path = ".",
) -> ResearchLandscapeArtifact:
    """Validate a synthesis and atomically emit canonical project artifact JSON."""

    source_path = Path(source)
    artifact = load_research_landscape_source(source_path)
    evidence_path = Path(evidence_root) / artifact.source_document
    expected = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    if artifact.source_document_sha256 != expected:
        raise ValueError("research landscape source_document_sha256 does not match its source")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return artifact


def find_research_landscape_run(snapshot: ProjectSnapshot) -> ProjectRun | None:
    """Select only the latest registered run explicitly declaring this projection."""

    matches = [
        run
        for run in snapshot.manifest.runs
        if getattr(run, "generative_ui_projection", None) in _PROJECTION_KINDS
    ]
    return matches[-1] if matches else None


def load_project_research_landscape(
    project_root: Path,
    snapshot: ProjectSnapshot,
    run: ProjectRun,
) -> ResearchLandscapeArtifact:
    """Read a bounded artifact contained by its registered run directory."""

    declared_projection = getattr(run, "generative_ui_projection", None)
    if declared_projection not in _PROJECTION_KINDS:
        raise ValueError("run does not declare the research-landscape projection")
    if run.artifact is None:
        raise ValueError("research-landscape run does not declare an artifact")
    root = project_root.resolve(strict=True)
    run_root = (project_root / "runs" / run.run_id).resolve(strict=True)
    artifact_path = (project_root / run.artifact).resolve(strict=True)
    for candidate, owner, message in (
        (run_root, root, "research-landscape run escaped its project"),
        (artifact_path, run_root, "research-landscape artifact escaped its run"),
    ):
        try:
            candidate.relative_to(owner)
        except ValueError as exc:
            raise ValueError(message) from exc
    if artifact_path.is_symlink() or not artifact_path.is_file():
        raise ValueError("research-landscape artifact must be a regular file")
    payload = artifact_path.read_bytes()
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise ValueError("research-landscape artifact exceeds its byte limit")
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    artifact = ResearchLandscapeArtifact.model_validate(value)
    if artifact.artifact_kind != declared_projection:
        raise ValueError("research-landscape artifact kind differs from its declaring run")
    return artifact


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key in research landscape: {key}")
        value[key] = item
    return value

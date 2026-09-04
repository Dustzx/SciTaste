"""Project-owned offline composition of the Phase 4--7 workflows."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from scitaste.benchmark.manuscript import materialize_manuscript
from scitaste.discovery.loop import DiscoveryLoop, DiscoveryScenario, load_discovery_scenario
from scitaste.evidence.workflow import (
    EvidenceWorkflow,
    EvidenceWorkflowScenario,
    load_evidence_scenario,
)
from scitaste.generative_ui import ProjectSnapshotAdapter
from scitaste.project import (
    PaperManifest,
    ProjectManifest,
    ProjectRun,
    ProjectRuntime,
    ProjectSnapshot,
)
from scitaste.project.models import validate_entry_id, validate_project_id
from scitaste.visual.workflow import FigureScenario, FigureWorkflow, load_figure_scenario
from scitaste.writing.workflow import (
    CommunicationScenario,
    CommunicationWorkflow,
    load_communication_scenario,
)


class FullWorkflowConfig(BaseModel):
    """Paths and publication identity for one deterministic full-workflow case."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    title: str = Field(min_length=1)
    research_direction: str = Field(min_length=1)
    target_domain: str = Field(min_length=1)
    target_venue: str | None = None
    condition: str = "full_scitaste"
    provider: Literal["mock"] = "mock"
    model: str = "deterministic-controller"
    evidence_scope: str = "offline-integration-only"
    discovery_scenario: Path
    evidence_scenario: Path
    communication_scenario: Path
    figure_scenario: Path
    paper_id: str
    paper_directory: str
    paper_title: str = Field(min_length=1)
    paper_date: date

    @field_validator("project_id")
    @classmethod
    def canonical_project_id(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("paper_id", "paper_directory")
    @classmethod
    def safe_entry_id(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "entry")
        return validate_entry_id(value, field_name=field_name)


class FullWorkflow:
    """Run Discovery through Figure generation inside one managed project run."""

    def __init__(self, *, seed: int = 0) -> None:
        self.seed = seed

    def run(
        self,
        config: FullWorkflowConfig,
        *,
        outputs_root: str | Path,
        run_id: str,
    ) -> dict[str, object]:
        validate_entry_id(run_id, field_name="run_id")
        runtime = ProjectRuntime(outputs_root)
        snapshot = self._open_or_create_project(runtime, config)
        snapshot = runtime.begin_run(
            config.project_id,
            ProjectRun(
                run_id=run_id,
                provider=config.provider,
                model=config.model,
                condition=config.condition,
                seed=self.seed,
                status="running",
                evidence_scope=config.evidence_scope,
                stage_path="stages",
            ),
            expected_revision=snapshot.revision,
        )
        snapshot = runtime.select_run(
            config.project_id,
            run_id,
            expected_revision=snapshot.revision,
        )
        run_root = runtime.outputs_root / "projects" / config.project_id / "runs" / run_id

        try:
            summaries, final_state = self._run_stages(config, run_root)
            paper_files = self._materialize_paper(config, runtime, run_root)
            snapshot = runtime.update_run(
                config.project_id,
                run_id,
                expected_revision=runtime.open(config.project_id).revision,
                status="complete",
                artifact=f"runs/{run_id}/full_run_summary.json",
                final_state=f"runs/{run_id}/{_owned_locator(run_root, final_state)}",
                stage_records={
                    name: f"runs/{run_id}/stages/{name}/STAGE.json" for name in summaries
                },
            )
            paper = PaperManifest(
                paper_id=config.paper_id,
                project_id=config.project_id,
                title=config.paper_title,
                date=config.paper_date,
                provider=config.provider,
                model=config.model,
                condition=config.condition,
                task="conflict-aware-research-control",
                seed=self.seed,
                stage=18,
                status="reviewed-draft",
                evidence_scope=config.evidence_scope,
                publication_ready=False,
                source_run=run_id,
                files=paper_files,
                stage_semantics="offline-phase-4-to-7-integration",
            )
            snapshot = runtime.register_paper(
                config.project_id,
                paper,
                directory_name=config.paper_directory,
                expected_revision=snapshot.revision,
            )
            snapshot = runtime.select_paper(
                config.project_id,
                config.paper_directory,
                expected_revision=snapshot.revision,
            )
            snapshot = runtime.update(
                config.project_id,
                expected_revision=snapshot.revision,
                status="reviewed-draft",
            )
        except BaseException as exc:
            self._mark_failed(runtime, config.project_id, run_id, exc)
            raise

        summary: dict[str, object] = {
            "schema_version": "1.0",
            "project_id": config.project_id,
            "run_id": run_id,
            "status": "complete",
            "scope": config.evidence_scope,
            "effectiveness_claim": False,
            "project_revision": snapshot.revision,
            "current_paper": snapshot.current_paper_locator,
            "stages": summaries,
            "final_state": f"runs/{run_id}/{_owned_locator(run_root, final_state)}",
            "paper_files": paper_files,
        }
        summary_path = run_root / "full_run_summary.json"
        _write_json(summary_path, summary)
        binding = ProjectSnapshotAdapter(runtime).build_binding(config.project_id)
        binding_path = (
            runtime.outputs_root
            / "projects"
            / config.project_id
            / "surfaces"
            / f"{run_id}-snapshot-binding.json"
        )
        _write_json(binding_path, binding.model_dump(mode="json"))
        return {
            **summary,
            "summary": str(summary_path),
            "snapshot_binding": str(binding_path),
            "snapshot_binding_sha256": binding.snapshot_sha256,
        }

    @staticmethod
    def _open_or_create_project(
        runtime: ProjectRuntime, config: FullWorkflowConfig
    ) -> ProjectSnapshot:
        try:
            snapshot = runtime.open(config.project_id)
        except FileNotFoundError:
            return runtime.create(
                ProjectManifest(
                    project_id=config.project_id,
                    title=config.title,
                    research_direction=config.research_direction,
                    target_domain=config.target_domain,
                    target_venue=config.target_venue,
                    status="active",
                    stage_semantics="scitaste-workflow-phases",
                )
            )
        manifest = snapshot.manifest
        identity = (
            manifest.research_direction,
            manifest.target_domain,
            manifest.target_venue,
        )
        expected = (config.research_direction, config.target_domain, config.target_venue)
        if identity != expected:
            raise ValueError("existing project research identity does not match full config")
        return snapshot

    def _run_stages(
        self, config: FullWorkflowConfig, run_root: Path
    ) -> tuple[dict[str, object], Path]:
        stages = run_root / "stages"
        discovery_scenario = _discovery_for_project(config)
        discovery_root = stages / "discovery"
        discovery_raw = DiscoveryLoop(seed=self.seed).run(
            discovery_scenario,
            output_dir=discovery_root,
        )
        discovery_state = Path(str(discovery_raw["latest_state"]))
        discovery = _portable_summary(discovery_raw, run_root)
        _stage_record(discovery_root, "discovery", discovery)

        evidence_scenario = _evidence_for_project(config)
        evidence_root = stages / "evidence"
        evidence_raw = EvidenceWorkflow(seed=self.seed).run(
            evidence_scenario,
            output_dir=evidence_root,
            state_path=discovery_state,
        )
        evidence_state = Path(str(evidence_raw["latest_state"]))
        evidence = _portable_summary(evidence_raw, run_root)
        _stage_record(evidence_root, "evidence", evidence)

        communication_scenario = _communication_for_project(config)
        communication_root = stages / "communication"
        communication_raw = CommunicationWorkflow(seed=self.seed).run(
            communication_scenario,
            output_dir=communication_root,
            state_path=evidence_state,
        )
        communication_state = Path(str(communication_raw["latest_state"]))
        communication = _portable_summary(communication_raw, run_root)
        _stage_record(communication_root, "communication", communication)

        figure_scenario = _figure_for_project(config)
        figure_root = stages / "figure"
        figure_raw = FigureWorkflow(seed=self.seed).run(
            figure_scenario,
            output_dir=figure_root,
            state_path=communication_state,
        )
        figure = _portable_summary(figure_raw, run_root)
        _stage_record(figure_root, "figure", figure)
        summaries = {
            "discovery": discovery,
            "evidence": evidence,
            "communication": communication,
            "figure": figure,
        }
        return summaries, figure_root / "research_state.json"

    @staticmethod
    def _materialize_paper(
        config: FullWorkflowConfig,
        runtime: ProjectRuntime,
        run_root: Path,
    ) -> dict[str, str]:
        communication_paper = run_root / "stages" / "communication" / "paper.md"
        source = run_root / "stages" / "communication" / "paper_with_title.md"
        source.write_text(
            f"## Title\n{config.paper_title}\n\n" + communication_paper.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        paper_root = (
            runtime.outputs_root
            / "projects"
            / config.project_id
            / "papers"
            / config.paper_directory
        )
        paths = materialize_manuscript(markdown_path=source, target_dir=paper_root)
        figures = paper_root / "figures"
        figures.mkdir(parents=True, exist_ok=True)
        for name in ("figure.svg", "figure.drawio"):
            source_figure = run_root / "stages" / "figure" / name
            shutil.copy2(source_figure, figures / name)
            paths.append(figures / name)
        return {
            _paper_file_label(path, paper_root): path.relative_to(paper_root).as_posix()
            for path in sorted(paths)
        }

    @staticmethod
    def _mark_failed(
        runtime: ProjectRuntime,
        project_id: str,
        run_id: str,
        error: BaseException,
    ) -> None:
        try:
            snapshot = runtime.open(project_id)
            runtime.update_run(
                project_id,
                run_id,
                expected_revision=snapshot.revision,
                status="failed",
                failure_type=type(error).__name__,
                failure_message=str(error)[:1000],
            )
        except (FileNotFoundError, ValueError):
            return


def load_full_workflow_config(path: str | Path) -> FullWorkflowConfig:
    config_path = Path(path).resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for field in (
        "discovery_scenario",
        "evidence_scenario",
        "communication_scenario",
        "figure_scenario",
    ):
        scenario = Path(payload[field])
        if not scenario.is_absolute():
            payload[field] = (config_path.parent / scenario).resolve()
    return FullWorkflowConfig.model_validate(payload)


def _discovery_for_project(config: FullWorkflowConfig) -> DiscoveryScenario:
    scenario = load_discovery_scenario(config.discovery_scenario)
    return DiscoveryScenario.model_validate(_identity_payload(scenario, config))


def _evidence_for_project(config: FullWorkflowConfig) -> EvidenceWorkflowScenario:
    scenario = load_evidence_scenario(config.evidence_scenario)
    return EvidenceWorkflowScenario.model_validate(_identity_payload(scenario, config))


def _communication_for_project(config: FullWorkflowConfig) -> CommunicationScenario:
    scenario = load_communication_scenario(config.communication_scenario)
    payload = _identity_payload(scenario, config)
    if payload["review_resolution"] is not None:
        payload["review_resolution"].update(
            {
                "project_id": config.project_id,
                "research_direction": config.research_direction,
                "target_domain": config.target_domain,
                "target_venue": config.target_venue,
            }
        )
    return CommunicationScenario.model_validate(payload)


def _figure_for_project(config: FullWorkflowConfig) -> FigureScenario:
    scenario = load_figure_scenario(config.figure_scenario)
    return FigureScenario.model_validate(_identity_payload(scenario, config))


def _identity_payload(scenario: BaseModel, config: FullWorkflowConfig) -> dict[str, object]:
    payload = scenario.model_dump(mode="json")
    payload.update(
        {
            "project_id": config.project_id,
            "research_direction": config.research_direction,
            "target_domain": config.target_domain,
            "target_venue": config.target_venue,
        }
    )
    return payload


def _stage_record(root: Path, name: str, summary: dict[str, object]) -> None:
    _write_json(
        root / "STAGE.json",
        {
            "schema_version": "1.0",
            "stage": name,
            "status": "complete",
            "purpose": {
                "discovery": "Form and probe hypotheses, then select a bounded idea.",
                "evidence": "Test a registered claim and route the interpreted result.",
                "communication": "Draft, review, resolve an obligation, and revise the paper.",
                "figure": "Build, critique, patch, and export an editable claim-linked figure.",
            }[name],
            "summary": summary,
        },
    )


def _paper_file_label(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return {
        "main.md": "Markdown manuscript",
        "main.tex": "LaTeX manuscript",
        "main.pdf": "PDF manuscript",
        "build.json": "Build record",
        "README.md": "Bundle README",
        "figures/figure.svg": "Editable SVG figure",
        "figures/figure.drawio": "Draw.io figure source",
    }.get(relative, f"Artifact {relative}")


def _owned_locator(run_root: Path, path: Path) -> str:
    return path.relative_to(run_root).as_posix()


def _portable_summary(value: object, run_root: Path) -> object:
    if isinstance(value, dict):
        return {key: _portable_summary(item, run_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_summary(item, run_root) for item in value]
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute():
            try:
                return path.relative_to(run_root).as_posix()
            except ValueError:
                return value
    return value


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

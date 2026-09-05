from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.benchmark.study import MatchedStudyPlanner, load_study_protocol
from scitaste.benchmark.study_execution import (
    CommandLauncherConfig,
    LauncherResult,
    LauncherUsage,
    ProcessResult,
    StudyLaunchConfig,
)
from scitaste.benchmark.study_models import (
    CellStatus,
    EvidenceClass,
    StudyOutcome,
    SystemCondition,
)
from scitaste.benchmark.study_project import (
    ProjectMatchedStudyRunner,
    ProjectStudyConfig,
)
from scitaste.project import (
    ProjectManifest,
    ProjectRevisionConflictError,
    ProjectRuntime,
)

PILOT_PROTOCOL = "configs/experiments/matched_budget_local_pilot_v1.yaml"


def _project(runtime: ProjectRuntime, project_id: str = "managed-study") -> None:
    runtime.create(
        ProjectManifest(
            project_id=project_id,
            title="Managed study",
            research_direction="Keep matched-study evidence under one project.",
            status="active",
            stage_semantics="matched-budget-study-cells",
        )
    )


def _config() -> ProjectStudyConfig:
    return ProjectStudyConfig(
        project_id="managed-study",
        run_id="2026-09-05__scripted__phase9__seed-07",
        provider="scripted",
        model="deterministic-adapter",
        seed=7,
    )


def _launch_config(command: str = "adapter") -> StudyLaunchConfig:
    return StudyLaunchConfig(
        launchers={
            SystemCondition.AUTORESEARCHCLAW: CommandLauncherConfig(
                command=[command, "{cell_request}"],
                timeout_seconds=100,
            )
        }
    )


def _outcome() -> StudyOutcome:
    return StudyOutcome(
        useful_results=1,
        proposed_ideas=1,
        valid_ideas=1,
        pilots=1,
        discarded_ideas=0,
        unproductive_experiments=0,
        total_experiments=1,
        gpu_hours_before_useful_signal=0,
        pivots=0,
        correct_pivots=0,
        evidence_sufficiency=0.8,
        reviewer_concerns_opened=0,
        reviewer_concerns_closed=0,
        total_claims=1,
        unsupported_claims=0,
    )


class SuccessfulProcess:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, command, *, cwd, environment, **kwargs) -> ProcessResult:
        self.calls += 1
        (cwd / "paper.md").write_text("project-owned artifact", encoding="utf-8")
        result = LauncherResult(
            status=CellStatus.SUCCEEDED,
            evidence_class=EvidenceClass.SYNTHETIC,
            usage=LauncherUsage(
                experiments=1,
                api_cost_usd=0,
                search_queries=0,
                llm_tokens=100,
            ),
            outcome=_outcome(),
            artifact_paths=["paper.md"],
        )
        Path(environment["SCITASTE_STUDY_CELL_RESULT"]).write_text(
            result.model_dump_json(), encoding="utf-8"
        )
        return ProcessResult(returncode=0)


class FailThenSucceedProcess(SuccessfulProcess):
    def run(self, command, **kwargs) -> ProcessResult:
        if self.calls == 0:
            self.calls += 1
            return ProcessResult(returncode=2)
        return super().run(command, **kwargs)


class ConcurrentMutationProcess(SuccessfulProcess):
    def __init__(self, runtime: ProjectRuntime) -> None:
        super().__init__()
        self.runtime = runtime

    def run(self, command, **kwargs) -> ProcessResult:
        snapshot = self.runtime.open("managed-study")
        self.runtime.update(
            "managed-study",
            expected_revision=snapshot.revision,
            status="changed-by-concurrent-writer",
        )
        return super().run(command, **kwargs)


def _clock(*values: float):
    readings = iter(values)
    return lambda: next(readings)


def _runner(
    runtime: ProjectRuntime,
    process,
    *,
    launch_config: StudyLaunchConfig | None = None,
    clock=None,
) -> ProjectMatchedStudyRunner:
    return ProjectMatchedStudyRunner(
        runtime,
        load_study_protocol(PILOT_PROTOCOL),
        launch_config or _launch_config(),
        process_runner=process,
        clock=clock or _clock(0, 1),
    )


def test_project_study_dry_run_is_mutation_free(tmp_path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    _project(runtime)
    process = SuccessfulProcess()

    summary = _runner(runtime, process).run(
        _config(),
        conditions=[SystemCondition.AUTORESEARCHCLAW],
        max_cells=1,
        dry_run=True,
    )

    assert summary.run_status == "planned"
    assert summary.project_revision == 0
    assert summary.study.selected_cells == 1
    assert process.calls == 0
    assert runtime.open("managed-study").manifest.runs == []
    assert not (runtime.projects_root / "managed-study/runs" / _config().run_id).exists()


def test_project_study_registers_and_selects_partial_run(tmp_path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    _project(runtime)
    process = SuccessfulProcess()

    summary = _runner(runtime, process).run(
        _config(),
        conditions=[SystemCondition.AUTORESEARCHCLAW],
        max_cells=1,
    )

    assert summary.run_status == "partial"
    assert summary.project_revision == 3
    assert summary.study.succeeded_cells == 1
    assert summary.study.results_sha256
    snapshot = runtime.open("managed-study")
    run = snapshot.manifest.runs[0]
    assert snapshot.manifest.current_run == _config().run_id
    assert run.status == "partial"
    assert run.stage_path == "study"
    assert run.model_extra["recorded_cells"] == 1
    assert run.model_extra["planned_cells"] == 16
    assert (runtime.projects_root / summary.project_run_locator.removeprefix("projects/")).is_dir()
    assert (runtime.projects_root / "managed-study/stages/current").resolve().name == "study"


def test_failed_project_study_resumes_and_archives_attempt(tmp_path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    _project(runtime)
    process = FailThenSucceedProcess()
    runner = _runner(runtime, process, clock=_clock(0, 10, 20, 30))

    first = runner.run(
        _config(),
        conditions=[SystemCondition.AUTORESEARCHCLAW],
        max_cells=1,
    )
    second = runner.run(
        _config(),
        conditions=[SystemCondition.AUTORESEARCHCLAW],
        max_cells=1,
        resume=True,
    )

    assert first.run_status == "failed"
    assert second.run_status == "partial"
    assert second.study.archived_attempts
    snapshot = runtime.open("managed-study")
    run = snapshot.manifest.runs[0]
    assert run.status == "partial"
    assert run.model_extra["resume_attempt"] == 1
    archive = (
        runtime.projects_root
        / "managed-study/runs"
        / _config().run_id
        / "study"
        / second.study.archived_attempts[0]
    )
    assert json.loads((archive / "execution_record.json").read_text())["status"] == "failed"


def test_project_resume_identity_drift_fails_before_revision_change(tmp_path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    _project(runtime)
    first = _runner(runtime, FailThenSucceedProcess(), clock=_clock(0, 1)).run(
        _config(),
        conditions=[SystemCondition.AUTORESEARCHCLAW],
        max_cells=1,
    )
    assert first.run_status == "failed"
    revision = runtime.open("managed-study").revision

    with pytest.raises(ValueError, match="execution identity"):
        _runner(
            runtime,
            SuccessfulProcess(),
            launch_config=_launch_config("changed-adapter"),
        ).run(
            _config(),
            conditions=[SystemCondition.AUTORESEARCHCLAW],
            max_cells=1,
            resume=True,
        )

    assert runtime.open("managed-study").revision == revision


def test_concurrent_project_mutation_conflicts_instead_of_adopting_latest(tmp_path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    _project(runtime)
    process = ConcurrentMutationProcess(runtime)

    with pytest.raises(ProjectRevisionConflictError, match="stale project revision"):
        _runner(runtime, process).run(
            _config(),
            conditions=[SystemCondition.AUTORESEARCHCLAW],
            max_cells=1,
        )

    snapshot = runtime.open("managed-study")
    assert snapshot.manifest.status == "changed-by-concurrent-writer"
    assert snapshot.manifest.runs[0].status == "running"


def test_complete_project_study_cannot_be_resumed(tmp_path) -> None:
    runtime = ProjectRuntime(tmp_path / "outputs")
    _project(runtime)
    protocol = load_study_protocol(PILOT_PROTOCOL)
    plan = MatchedStudyPlanner().plan(protocol)
    assert len(plan.cells) == 16
    launchers = {
        condition: CommandLauncherConfig(command=["adapter", "{cell_request}"])
        for condition in {cell.condition for cell in plan.cells}
    }
    process = SuccessfulProcess()
    values = []
    for index in range(len(plan.cells)):
        values.extend([float(index * 2), float(index * 2 + 1)])
    runner = ProjectMatchedStudyRunner(
        runtime,
        protocol,
        StudyLaunchConfig(launchers=launchers),
        process_runner=process,
        clock=_clock(*values),
    )

    summary = runner.run(_config())

    assert summary.run_status == "complete"
    with pytest.raises(ValueError, match="completed matched-study"):
        runner.run(_config(), resume=True, dry_run=True)

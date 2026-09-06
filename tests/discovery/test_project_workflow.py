from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.discovery import (
    DiscoveryCommand,
    ProjectDiscoveryManifest,
    ProjectDiscoveryWorkflow,
    load_discovery_scenario,
)
from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.mock import MockExecutor
from scitaste.project import ProjectManifest, ProjectRuntime
from scitaste.schema.actions import MetaAction

SCENARIO_PATH = Path("configs/experiments/discovery_weak.yaml")
RUN_ID = "managed-discovery-01"


def _project(outputs: Path) -> ProjectRuntime:
    scenario = load_discovery_scenario(SCENARIO_PATH)
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id=scenario.project_id,
            title="Managed discovery",
            research_direction=scenario.research_direction,
            target_domain=scenario.target_domain,
            target_venue=scenario.target_venue,
            status="active",
            stage_semantics="scitaste-workflow-phases",
        )
    )
    return runtime


def _advance(
    workflow: ProjectDiscoveryWorkflow,
    revision: int,
    command: DiscoveryCommand,
    *,
    resume: bool = False,
):
    return workflow.advance(
        load_discovery_scenario(SCENARIO_PATH),
        project_id="discovery-weak-intuition",
        run_id=RUN_ID,
        command=command,
        expected_revision=revision,
        resume=resume,
    )


def test_project_discovery_composes_one_verified_project_owned_run(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    runtime = _project(outputs)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)
    scenario = load_discovery_scenario(SCENARIO_PATH)

    preview = workflow.preview(
        scenario,
        project_id=scenario.project_id,
        run_id=RUN_ID,
        command=DiscoveryCommand.HYPOTHESIZE,
        expected_revision=0,
    )
    assert preview.creates_run is True
    assert preview.expected_final_revision == 3
    assert preview.destination == f"runs/{RUN_ID}/discovery/steps/001-hypothesize"
    assert runtime.open(scenario.project_id).revision == 0

    revision = 0
    reports = []
    for command in (
        DiscoveryCommand.HYPOTHESIZE,
        DiscoveryCommand.PROBE,
        DiscoveryCommand.REFORMULATE,
        DiscoveryCommand.PROBE,
        DiscoveryCommand.IDEATE,
        DiscoveryCommand.PORTFOLIO_SELECT,
    ):
        report = _advance(workflow, revision, command)
        reports.append(report)
        revision = report.project_revision

    assert [item.project_revision for item in reports] == [3, 5, 7, 9, 11, 13]
    assert reports[-1].status == "complete"
    assert reports[-1].command_report.final_stage.value == "PILOT"
    assert reports[-1].verification.command_count == 6
    assert reports[-1].verification.project_revision == 13
    assert reports[-1].verification.latest_state_id == (reports[-1].command_report.output_state_id)

    snapshot = runtime.open(scenario.project_id)
    registered = snapshot.manifest.runs[0]
    assert snapshot.manifest.current_run == RUN_ID
    assert registered.status == "complete"
    assert registered.artifact == f"runs/{RUN_ID}/discovery/DISCOVERY.json"
    assert registered.model_extra["effectiveness_claim"] is False
    assert registered.model_extra["command_count"] == 6
    assert all(
        registered.model_extra[name] is None
        for name in (
            "pending_command",
            "pending_ordinal",
            "pending_input_state_id",
            "pending_operation_token",
            "pending_project_revision_reserved",
            "pending_resumed",
        )
    )

    manifest_path = outputs / "projects" / scenario.project_id / str(registered.artifact)
    manifest = ProjectDiscoveryManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    assert manifest.status == "complete"
    assert [step.command for step in manifest.steps] == [item.command for item in reports]
    assert all(
        step.input_state_id == previous.output_state_id
        for step, previous in zip(manifest.steps[1:], manifest.steps, strict=False)
    )
    persisted_receipt = json.loads(
        (manifest_path.parent / manifest.steps[0].locator / "discovery_command.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted_receipt["state"] == "research_state.json"
    assert persisted_receipt["decision_log"] == "decisions.jsonl"
    assert persisted_receipt["report"] == "discovery_command.json"


def test_invalid_command_and_stale_revision_have_no_project_side_effect(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    runtime = _project(outputs)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)
    first = _advance(workflow, 0, DiscoveryCommand.HYPOTHESIZE)
    project_root = outputs / "projects/discovery-weak-intuition"

    with pytest.raises(ValueError, match="reproducible observation"):
        _advance(workflow, first.project_revision, DiscoveryCommand.IDEATE)
    assert runtime.open("discovery-weak-intuition").revision == first.project_revision
    assert not (project_root / f"runs/{RUN_ID}/discovery/steps/002-ideate").exists()

    with pytest.raises(ValueError, match="stale project revision"):
        _advance(workflow, first.project_revision - 1, DiscoveryCommand.PROBE)
    assert runtime.open("discovery-weak-intuition").revision == first.project_revision
    assert not (project_root / f"runs/{RUN_ID}/discovery/steps/002-probe").exists()


def test_failed_executor_is_registered_and_can_resume_without_state_advance(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    runtime = _project(outputs)

    def fail_search(state, action):
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.FAILED,
            executor="registered-failure",
            error="expected test failure",
        )

    failed_executor = MockExecutor(seed=7, handlers={MetaAction.SEARCH: fail_search})
    failed = ProjectDiscoveryWorkflow(outputs, seed=7, executor=failed_executor)
    with pytest.raises(RuntimeError, match="expected test failure"):
        _advance(failed, 0, DiscoveryCommand.HYPOTHESIZE)

    snapshot = runtime.open("discovery-weak-intuition")
    assert snapshot.revision == 3
    assert snapshot.manifest.runs[0].status == "failed"
    assert snapshot.manifest.runs[0].model_extra["pending_command"] == "hypothesize"
    assert not (
        outputs / f"projects/discovery-weak-intuition/runs/{RUN_ID}/discovery/steps/001-hypothesize"
    ).exists()

    recovered = _advance(
        ProjectDiscoveryWorkflow(outputs, seed=7),
        snapshot.revision,
        DiscoveryCommand.HYPOTHESIZE,
        resume=True,
    )
    assert recovered.status == "active"
    assert recovered.recovered_without_execution is False
    assert recovered.project_revision == 5
    assert recovered.verification.command_count == 1
    assert (
        runtime.open("discovery-weak-intuition").manifest.runs[0].model_extra["resume_attempt"] == 1
    )


def test_completed_pending_step_recovers_without_reexecuting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    runtime = _project(outputs)
    executor = MockExecutor(seed=7)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7, executor=executor)
    original_finalize = workflow._finalize

    def interrupt_finalize(*args, **kwargs):
        raise RuntimeError("interrupt after durable step")

    monkeypatch.setattr(workflow, "_finalize", interrupt_finalize)
    with pytest.raises(RuntimeError, match="interrupt after durable step"):
        _advance(workflow, 0, DiscoveryCommand.HYPOTHESIZE)
    calls_after_interruption = list(executor.calls)
    assert len(calls_after_interruption) == 3
    failed_snapshot = runtime.open("discovery-weak-intuition")
    assert failed_snapshot.manifest.runs[0].status == "failed"

    monkeypatch.setattr(workflow, "_finalize", original_finalize)
    recovered = _advance(
        workflow,
        failed_snapshot.revision,
        DiscoveryCommand.HYPOTHESIZE,
        resume=True,
    )
    assert recovered.recovered_without_execution is True
    assert executor.calls == calls_after_interruption
    assert recovered.verification.command_count == 1


def test_step_without_published_head_is_reconstructed_without_reexecution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    runtime = _project(outputs)
    executor = MockExecutor(seed=7)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7, executor=executor)
    original_write = workflow._write_manifest

    def interrupt_write(*args, **kwargs):
        raise RuntimeError("interrupt before head publish")

    monkeypatch.setattr(workflow, "_write_manifest", interrupt_write)
    with pytest.raises(RuntimeError, match="interrupt before head publish"):
        _advance(workflow, 0, DiscoveryCommand.HYPOTHESIZE)
    calls_after_interruption = list(executor.calls)
    failed_snapshot = runtime.open("discovery-weak-intuition")
    assert failed_snapshot.manifest.runs[0].status == "failed"
    assert not (
        outputs / f"projects/discovery-weak-intuition/runs/{RUN_ID}/discovery/DISCOVERY.json"
    ).exists()

    monkeypatch.setattr(workflow, "_write_manifest", original_write)
    preview = workflow.preview(
        load_discovery_scenario(SCENARIO_PATH),
        project_id="discovery-weak-intuition",
        run_id=RUN_ID,
        command=DiscoveryCommand.HYPOTHESIZE,
        expected_revision=failed_snapshot.revision,
        resume=True,
    )
    assert preview.recovers_completed_step is True
    recovered = _advance(
        workflow,
        failed_snapshot.revision,
        DiscoveryCommand.HYPOTHESIZE,
        resume=True,
    )
    assert recovered.recovered_without_execution is True
    assert executor.calls == calls_after_interruption
    assert recovered.verification.command_count == 1


def test_verifier_rejects_tampered_project_step(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    _project(outputs)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)
    report = _advance(workflow, 0, DiscoveryCommand.HYPOTHESIZE)
    decisions = (
        outputs
        / "projects/discovery-weak-intuition/runs"
        / RUN_ID
        / "discovery/steps/001-hypothesize/decisions.jsonl"
    )
    decisions.write_text(decisions.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="decision log hash mismatch"):
        workflow.verify("discovery-weak-intuition", RUN_ID)
    assert report.project_revision == runtime_revision(outputs)


def runtime_revision(outputs: Path) -> int:
    return ProjectRuntime(outputs).open("discovery-weak-intuition").revision

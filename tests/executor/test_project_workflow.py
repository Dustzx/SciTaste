from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import scitaste.executor.project_workflow as project_workflow_module
from scitaste.cli import main
from scitaste.executor.base import ExecutionResult
from scitaste.executor.call_protocol import ExternalCallPhase, ExternalCallProtocol
from scitaste.executor.project_bootstrap import ProjectSubstrateBootstrapWorkflow
from scitaste.executor.project_workflow import (
    ProjectSubstrateActionWorkflow,
    ProjectSubstrateWorkflowConfig,
    load_project_substrate_config,
)
from scitaste.project import ProjectRuntime
from scitaste.project.models import content_sha256
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.state.research_state import ResearchState
from scitaste.state.resources import record_resource_usage
from scitaste.state.transitions import apply_transition


def _source_run(root: Path) -> Path:
    source = root / "source-arc-run"
    stage = source / "stage-02"
    stage.mkdir(parents=True)
    (stage / "problem_tree.md").write_text("# Registered problems\n", encoding="utf-8")
    (source / "checkpoint.json").write_text(
        json.dumps({"last_completed_stage": 2, "run_id": "source-run"}),
        encoding="utf-8",
    )
    (source / "cost_log.jsonl").write_text(
        json.dumps({"cost_usd": 0.5}) + "\n",
        encoding="utf-8",
    )
    return source


def _executor_config(root: Path) -> Path:
    path = root / "autoresearchclaw.yaml"
    path.write_text("llm:\n  api_key: ${ZAI_API_KEY}\n", encoding="utf-8")
    return path


def _config(root: Path, *, live_enabled: bool = True) -> ProjectSubstrateWorkflowConfig:
    return ProjectSubstrateWorkflowConfig(
        config_id="project-substrate-test-v1",
        project_id="project-substrate-test",
        title="Project substrate test",
        research_direction="Audit one project-owned research action",
        target_domain="autonomous-research",
        target_venue="test-only",
        action_type="SEARCH",
        model="fixture-model",
        live_enabled=live_enabled,
        autoresearchclaw_config=_executor_config(root),
        max_output_tokens=2048,
    )


def _downgrade_selected_run(
    outputs: Path,
    run_id: str,
    *,
    schema_version: str = "1.1",
) -> Path:
    run_root = outputs / "projects/project-substrate-test/runs" / run_id
    manifest_path = run_root / "substrate_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = schema_version
    manifest.pop("external_call_protocol_version")
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = content_sha256(
        {key: value for key, value in manifest.items() if value is not None}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    invocation_path = run_root / "substrate_action/invocation.json"
    invocation = json.loads(invocation_path.read_text(encoding="utf-8"))
    invocation["binding_sha256"] = manifest["manifest_sha256"]
    invocation.pop("invocation_sha256")
    invocation["invocation_sha256"] = content_sha256(invocation)
    invocation_path.write_text(json.dumps(invocation), encoding="utf-8")

    result_path = run_root / "substrate_action/executor_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["data"].pop("call_started_sha256")
    result["data"]["invocation_sha256"] = invocation["invocation_sha256"]
    result_path.write_text(json.dumps(result), encoding="utf-8")

    decisions_path = run_root / "substrate_action/decisions.jsonl"
    if decisions_path.is_file():
        decisions = [
            json.loads(line) for line in decisions_path.read_text(encoding="utf-8").splitlines()
        ]
        for decision in decisions:
            if decision.get("actual_outcome") is not None:
                decision["actual_outcome"] = result
        decisions_path.write_text(
            "".join(json.dumps(decision) + "\n" for decision in decisions),
            encoding="utf-8",
        )
        invocation_record = ResearchDecision.model_validate(decisions[0])
        executor_result = ExecutionResult.model_validate(result)
        store = StateStore(run_root / "substrate_action")
        predecessor = store.load(invocation["state_snapshot_id"])
        recovered = apply_transition(predecessor, invocation_record)
        recovered = record_resource_usage(recovered, executor_result.cost)
        session = executor_result.data.get("session")
        if isinstance(session, dict):
            recovered.executor_context["autoresearchclaw_session_id"] = session.get("session_id")
            recovered.executor_context["autoresearchclaw_upstream_run_id"] = session.get(
                "current_upstream_run_id"
            )
        store.save(recovered)

    summary_path = run_root / "substrate_action/substrate_summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary.pop("call_phase")
        summary.pop("call_receipt_sha256")
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
    shutil.rmtree(run_root / "substrate_action/call_protocol")

    project_path = outputs / "projects/project-substrate-test/PROJECT.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    registered = next(item for item in project["runs"] if item["run_id"] == run_id)
    registered["manifest_sha256"] = manifest["manifest_sha256"]
    registered["invocation_sha256"] = invocation["invocation_sha256"]
    for key in (
        "external_call_protocol_version",
        "external_call_attempt",
        "external_call_phase",
        "external_call_phase_sha256",
        "external_call_request_sha256",
    ):
        registered.pop(key, None)
    project_path.write_text(json.dumps(project), encoding="utf-8")
    return run_root


def _successful_runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
    work = Path(command[command.index("--output") + 1])
    stage = work / "stage-03"
    stage.mkdir(parents=True)
    (stage / "search_plan.yaml").write_text("queries: []\n", encoding="utf-8")
    (stage / "sources.json").write_text("[]\n", encoding="utf-8")
    (stage / "queries.json").write_text("[]\n", encoding="utf-8")
    with (work / "cost_log.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"cost_usd": 0.02}) + "\n")
    (work / "checkpoint.json").write_text(
        json.dumps(
            {
                "last_completed_stage": 3,
                "last_completed_name": "SEARCH_STRATEGY",
                "run_id": "selected-action-run",
            }
        ),
        encoding="utf-8",
    )
    (work / "pipeline_summary.json").write_text(
        json.dumps({"final_status": "done", "final_stage": 3}),
        encoding="utf-8",
    )
    return subprocess.CompletedProcess(command, 0, stdout="stage complete", stderr="")


def _bootstrap_runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
    work = Path(command[command.index("--output") + 1])
    stage_one = work / "stage-01"
    stage_two = work / "stage-02"
    stage_one.mkdir(parents=True)
    stage_two.mkdir(parents=True)
    (stage_one / "goal.md").write_text("# Goal\n", encoding="utf-8")
    (stage_one / "hardware_profile.json").write_text("{}\n", encoding="utf-8")
    (stage_two / "problem_tree.md").write_text("# Problems\n", encoding="utf-8")
    (work / "checkpoint.json").write_text(
        json.dumps(
            {
                "last_completed_stage": 2,
                "last_completed_name": "PROBLEM_DECOMPOSE",
                "run_id": "project-bootstrap",
            }
        ),
        encoding="utf-8",
    )
    (work / "pipeline_summary.json").write_text(
        json.dumps({"final_status": "done", "final_stage": 2}),
        encoding="utf-8",
    )
    (work / "cost_log.jsonl").write_text(
        json.dumps({"cost_usd": 0.03}) + "\n",
        encoding="utf-8",
    )
    return subprocess.CompletedProcess(command, 0, stdout="prefix complete", stderr="")


def test_project_owned_substrate_action_is_verified_and_charges_only_delta(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=_successful_runner)

    result = workflow.run(
        config,
        outputs_root=outputs,
        run_id="selected-search-01",
        source_run_dir=source,
        allow_live=True,
    )

    assert result["status"] == "complete"
    assert result["execution_status"] == "SUCCEEDED"
    assert result["external_call_phase"] == "result_published"
    assert isinstance(result["external_call_phase_sha256"], str)
    assert result["transition_applied"] is True
    run = outputs / "projects/project-substrate-test/runs/selected-search-01"
    state = StateStore(run / "substrate_action").load()
    assert state.resource_usage.api_cost_usd == pytest.approx(0.02)
    assert (run / "inputs/autoresearchclaw/stage-02/problem_tree.md").is_file()
    assert (run / "work/autoresearchclaw/stage-03/search_plan.yaml").is_file()
    snapshot = ProjectRuntime(outputs).open(config.project_id)
    assert snapshot.manifest.current_run == "selected-search-01"
    assert snapshot.manifest.runs[0].status == "complete"

    status = workflow.status(
        outputs_root=outputs,
        project_id=config.project_id,
        run_id="selected-search-01",
    )
    assert status["status"] == "verified"
    assert status["execution_status"] == "SUCCEEDED"

    artifact = run / "work/autoresearchclaw/stage-03/sources.json"
    artifact.write_text('["tampered"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="working tree hash drift"):
        workflow.status(
            outputs_root=outputs,
            project_id=config.project_id,
            run_id="selected-search-01",
        )


def test_project_substrate_action_consumes_a_verified_project_bootstrap(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    config = _config(tmp_path)
    bootstrap = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=_bootstrap_runner)
    bootstrap.run(
        config,
        outputs_root=outputs,
        run_id="owned-bootstrap-01",
        allow_live=True,
    )

    result = ProjectSubstrateActionWorkflow(seed=7, command_runner=_successful_runner).run(
        config,
        outputs_root=outputs,
        run_id="selected-search-owned-source-01",
        source_project_run_id="owned-bootstrap-01",
        allow_live=True,
    )

    assert result["status"] == "complete"
    assert result["source_project_run_id"] == "owned-bootstrap-01"
    assert isinstance(result["source_receipt_sha256"], str)
    run = outputs / "projects/project-substrate-test/runs/selected-search-owned-source-01"
    assert (run / "inputs/autoresearchclaw/stage-01/goal.md").is_file()
    assert (run / "work/autoresearchclaw/stage-03/search_plan.yaml").is_file()
    status = ProjectSubstrateActionWorkflow().status(
        outputs_root=outputs,
        project_id=config.project_id,
        run_id="selected-search-owned-source-01",
    )
    assert status["source_project_run_id"] == "owned-bootstrap-01"
    assert status["source_receipt_sha256"] == result["source_receipt_sha256"]


def test_project_substrate_resumes_prepared_attempt_without_replacing_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0
    fail_once = True
    original_update = ProjectRuntime.update_run

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    def interrupted_update(
        self: ProjectRuntime,
        project_id: str,
        registered_run_id: str,
        *,
        expected_revision: int,
        **changes: object,
    ):
        nonlocal fail_once
        if fail_once and "invocation_sha256" in changes:
            fail_once = False
            raise OSError("controlled interruption after prepared")
        return original_update(
            self,
            project_id,
            registered_run_id,
            expected_revision=expected_revision,
            **changes,
        )

    monkeypatch.setattr(ProjectRuntime, "update_run", interrupted_update)
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="after prepared"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="prepared-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    assert calls == 0
    action_root = (
        outputs / "projects/project-substrate-test/runs/prepared-search-01/substrate_action"
    )
    invocation_before = (action_root / "invocation.json").read_bytes()
    chain = ExternalCallProtocol(action_root / "call_protocol").load(required=True)
    assert [entry.phase for entry in chain] == [ExternalCallPhase.PREPARED]

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="prepared-search-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["status"] == "complete"
    assert (action_root / "invocation.json").read_bytes() == invocation_before
    run = ProjectRuntime(outputs).open(config.project_id).manifest.runs[0]
    assert (run.model_extra or {})["external_call_attempt"] == 1


def test_project_substrate_recovers_result_published_before_final_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0
    fail_once = True
    original_publish = ExternalCallProtocol.publish_result

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    def interrupted_publish(self: ExternalCallProtocol, **kwargs: object):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("controlled interruption before result phase")
        return original_publish(self, **kwargs)

    monkeypatch.setattr(ExternalCallProtocol, "publish_result", interrupted_publish)
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="before result phase"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="unjournaled-result-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    assert calls == 1

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="unjournaled-result-search-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["recovered_without_provider"] is True
    action_root = (
        outputs
        / "projects/project-substrate-test/runs/unjournaled-result-search-01/substrate_action"
    )
    assert (
        ExternalCallProtocol(action_root / "call_protocol").load(required=True)[-1].phase
        is ExternalCallPhase.RESULT_PUBLISHED
    )


def test_project_substrate_failure_resumes_from_immutable_input(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def fail_once(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            work = Path(command[command.index("--output") + 1])
            (work / "partial-provider-response.txt").write_text("failed", encoding="utf-8")
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")
        return _successful_runner(command, **kwargs)

    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=fail_once)
    failed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="resumable-search-01",
        source_run_dir=source,
        allow_live=True,
    )
    assert failed["status"] == "failed"
    assert failed["execution_status"] == "FAILED"

    with pytest.raises(ValueError, match="seed"):
        ProjectSubstrateActionWorkflow(seed=8, command_runner=_successful_runner).run(
            config,
            outputs_root=outputs,
            run_id="resumable-search-01",
            resume=True,
            allow_live=True,
        )

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="resumable-search-01",
        resume=True,
        allow_live=True,
    )

    assert resumed["status"] == "complete"
    assert resumed["resume_attempt"] == 1
    assert resumed["archived_attempt"] == "failed_attempts/attempt-001"
    run = outputs / "projects/project-substrate-test/runs/resumable-search-01"
    assert (
        run / "failed_attempts/attempt-001/work/autoresearchclaw/partial-provider-response.txt"
    ).is_file()
    assert (run / "inputs/autoresearchclaw/checkpoint.json").is_file()
    assert not (run / "inputs/autoresearchclaw/partial-provider-response.txt").exists()


def test_project_substrate_running_failed_result_starts_exactly_one_new_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def fail_once(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            work = Path(command[command.index("--output") + 1])
            (work / "partial-provider-response.txt").write_text("failed", encoding="utf-8")
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")
        return _successful_runner(command, **kwargs)

    original_build = project_workflow_module._build_verification
    interrupt_once = True

    def interrupted_build(*args: object, **kwargs: object):
        nonlocal interrupt_once
        if interrupt_once:
            interrupt_once = False
            raise OSError("simulated death after failed result")
        return original_build(*args, **kwargs)

    monkeypatch.setattr(project_workflow_module, "_build_verification", interrupted_build)
    monkeypatch.setattr(
        ProjectSubstrateActionWorkflow,
        "_mark_failed",
        staticmethod(lambda *_args: None),
    )
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=fail_once)
    with pytest.raises(OSError, match="death after failed result"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="running-failed-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    assert calls == 1
    assert ProjectRuntime(outputs).open(config.project_id).manifest.runs[0].status == "running"

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="running-failed-search-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 2
    assert resumed["status"] == "complete"
    run = ProjectRuntime(outputs).open(config.project_id).manifest.runs[0]
    assert (run.model_extra or {})["external_call_attempt"] == 2
    assert (run.model_extra or {})["resume_attempt"] == 1


def test_schema_11_selected_success_recovers_without_second_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0
    fail_once = True
    original_append = DecisionLogger.append

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    def interrupted_append(self: DecisionLogger, decision: ResearchDecision) -> None:
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("controlled legacy selected interruption")
        original_append(self, decision)

    monkeypatch.setattr(DecisionLogger, "append", interrupted_append)
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="legacy selected interruption"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="legacy-success-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    _downgrade_selected_run(outputs, "legacy-success-search-01")

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="legacy-success-search-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["status"] == "complete"
    assert resumed["recovered_without_provider"] is True
    assert resumed["external_call_phase"] == "legacy_unjournaled"
    assert resumed["external_call_phase_sha256"] is None


def test_schema_11_selected_success_accepts_legacy_summary_after_late_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0
    fail_once = True
    original_build = project_workflow_module._build_verification

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    def interrupted_build(*args: object, **kwargs: object):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("controlled legacy post-summary interruption")
        return original_build(*args, **kwargs)

    monkeypatch.setattr(project_workflow_module, "_build_verification", interrupted_build)
    monkeypatch.setattr(
        ProjectSubstrateActionWorkflow,
        "_mark_failed",
        staticmethod(lambda *_args: None),
    )
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="post-summary interruption"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="legacy-late-success-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    run_root = _downgrade_selected_run(outputs, "legacy-late-success-search-01")
    legacy_summary = json.loads(
        (run_root / "substrate_action/substrate_summary.json").read_text(encoding="utf-8")
    )
    assert "call_phase" not in legacy_summary

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="legacy-late-success-search-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["status"] == "complete"
    assert resumed["recovered_without_provider"] is True
    assert (
        json.loads(
            (run_root / "substrate_action/substrate_summary.json").read_text(encoding="utf-8")
        )
        == legacy_summary
    )


def test_schema_11_selected_failure_retries_as_phase_aware_attempt_two(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def fail_once(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")
        return _successful_runner(command, **kwargs)

    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=fail_once)
    failed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="legacy-failed-search-01",
        source_run_dir=source,
        allow_live=True,
    )
    assert failed["status"] == "failed"
    run_root = _downgrade_selected_run(outputs, "legacy-failed-search-01")

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="legacy-failed-search-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 2
    assert resumed["status"] == "complete"
    registered = ProjectRuntime(outputs).open(config.project_id).manifest.runs[0]
    assert (registered.model_extra or {})["external_call_attempt"] == 2
    chain = ExternalCallProtocol(run_root / "substrate_action/call_protocol").load(required=True)
    assert chain[-1].phase is ExternalCallPhase.RESULT_PUBLISHED
    assert chain[-1].external_call_attempt == 2


def test_schema_10_selected_run_remains_read_only(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def failed_runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=failed_runner)
    workflow.run(
        config,
        outputs_root=outputs,
        run_id="legacy-read-only-search-01",
        source_run_dir=source,
        allow_live=True,
    )
    _downgrade_selected_run(
        outputs,
        "legacy-read-only-search-01",
        schema_version="1.0",
    )

    with pytest.raises(ValueError, match="read-only"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="legacy-read-only-search-01",
            resume=True,
            allow_live=True,
        )
    assert calls == 1


def test_project_substrate_resume_recovers_recorded_success_without_second_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=counted_runner)
    original_append = DecisionLogger.append
    fail_once = True

    def interrupted_append(self: DecisionLogger, decision: ResearchDecision) -> None:
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("controlled post-result interruption")
        original_append(self, decision)

    monkeypatch.setattr(DecisionLogger, "append", interrupted_append)
    with pytest.raises(OSError, match="post-result interruption"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="recoverable-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    assert calls == 1

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="recoverable-search-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["status"] == "complete"
    assert resumed["recovered_without_provider"] is True
    assert resumed["archived_attempt"] is None
    run = outputs / "projects/project-substrate-test/runs/recoverable-search-01"
    assert not (run / "failed_attempts").exists()
    assert (run / "substrate_action/verification.json").is_file()
    assert (
        workflow.status(
            outputs_root=outputs,
            project_id=config.project_id,
            run_id="recoverable-search-01",
        )["status"]
        == "verified"
    )
    registered = ProjectRuntime(outputs).open(config.project_id).manifest.runs[0]
    assert registered.model_extra["recovered_without_provider"] is True


def test_project_substrate_recovers_running_hard_crash_without_second_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0
    original_append = DecisionLogger.append
    fail_once = True

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    def interrupted_append(self: DecisionLogger, decision: ResearchDecision) -> None:
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("simulated process death after result publication")
        original_append(self, decision)

    monkeypatch.setattr(DecisionLogger, "append", interrupted_append)
    monkeypatch.setattr(
        ProjectSubstrateActionWorkflow,
        "_mark_failed",
        staticmethod(lambda *_args: None),
    )
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="simulated process death"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="hard-crash-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    assert ProjectRuntime(outputs).open(config.project_id).manifest.runs[0].status == "running"
    plan = workflow.plan(
        config,
        outputs_root=outputs,
        run_id="hard-crash-search-01",
        resume=True,
        allow_live=True,
    )
    assert plan["would_contact_provider"] is False
    assert plan["recovery_without_provider_available"] is True

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="hard-crash-search-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["status"] == "complete"
    assert resumed["recovered_without_provider"] is True


def test_project_substrate_retry_rejects_success_status_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    monkeypatch.setattr(
        DecisionLogger,
        "append",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("post-result stop")),
    )
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="post-result stop"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="status-tamper-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    result_path = (
        outputs
        / "projects/project-substrate-test/runs/status-tamper-search-01"
        / "substrate_action/executor_result.json"
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["status"] = "FAILED"
    payload["error"] = "AutoResearchClaw command failed"
    payload["data"]["returncode"] = 1
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"contradicts successful terminal evidence|published external result identity drift",
    ):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="status-tamper-search-01",
            resume=True,
            allow_live=True,
        )
    assert calls == 1


@pytest.mark.parametrize(
    ("relative_path", "contents"),
    [
        ("stage-02/problem_tree.md", "# changed inherited input\n"),
        ("unexpected-provider-file.txt", "unbound addition\n"),
    ],
)
def test_project_substrate_recovery_binds_the_complete_work_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    contents: str,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    monkeypatch.setattr(
        DecisionLogger,
        "append",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("post-result stop")),
    )
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="post-result stop"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="whole-tree-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    work = (
        outputs / "projects/project-substrate-test/runs/whole-tree-search-01/work/autoresearchclaw"
    )
    (work / relative_path).write_text(contents, encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"normalized working_tree drift|published external result identity drift",
    ):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="whole-tree-search-01",
            resume=True,
            allow_live=True,
        )
    assert calls == 1


def test_project_substrate_recovery_rejects_content_addressed_state_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    monkeypatch.setattr(
        DecisionLogger,
        "append",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("post-result stop")),
    )
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="post-result stop"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="state-tamper-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    action = (
        outputs / "projects/project-substrate-test/runs/state-tamper-search-01/substrate_action"
    )
    invocation = json.loads((action / "invocation.json").read_text(encoding="utf-8"))
    snapshot_path = action / "state_snapshots" / f"{invocation['state_snapshot_id']}.json"
    state = json.loads(snapshot_path.read_text(encoding="utf-8"))
    state["research_direction"] = "tampered predecessor"
    snapshot_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(ValueError, match="content-addressed name"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="state-tamper-search-01",
            resume=True,
            allow_live=True,
        )
    assert calls == 1


def test_project_substrate_resume_rejects_an_active_run_lock(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def failed_runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=failed_runner)
    workflow.run(
        config,
        outputs_root=outputs,
        run_id="locked-search-01",
        source_run_dir=source,
        allow_live=True,
    )
    run_root = outputs / "projects/project-substrate-test/runs/locked-search-01"
    descriptor = project_workflow_module._acquire_run_lock(run_root)
    try:
        with pytest.raises(ValueError, match="already active"):
            workflow.run(
                config,
                outputs_root=outputs,
                run_id="locked-search-01",
                resume=True,
                allow_live=True,
            )
    finally:
        project_workflow_module._release_run_lock(descriptor)
    assert calls == 1


def test_project_substrate_resume_blocks_ambiguous_unrecorded_external_work(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def interrupted_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        work = Path(command[command.index("--output") + 1])
        (work / "provider-request-started.txt").write_text("unknown outcome\n", encoding="utf-8")
        raise OSError("provider connection interrupted")

    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=interrupted_runner)
    with pytest.raises(OSError, match="provider connection interrupted"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="ambiguous-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    assert calls == 1

    with pytest.raises(ValueError, match="publication is ambiguous"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="ambiguous-search-01",
            resume=True,
            allow_live=True,
        )

    assert calls == 1


def test_project_substrate_running_without_result_remains_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def interrupted_runner(
        _command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        raise OSError("unknown provider outcome")

    monkeypatch.setattr(
        ProjectSubstrateActionWorkflow,
        "_mark_failed",
        staticmethod(lambda *_args: None),
    )
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=interrupted_runner)
    with pytest.raises(OSError, match="unknown provider outcome"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="running-ambiguous-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    assert ProjectRuntime(outputs).open(config.project_id).manifest.runs[0].status == "running"

    with pytest.raises(ValueError, match="running substrate result publication is ambiguous"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="running-ambiguous-search-01",
            resume=True,
            allow_live=True,
        )
    assert calls == 1


def test_project_substrate_resume_replays_existing_decision_without_second_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    original_save = StateStore.save
    fail_once = True

    def interrupted_save(self: StateStore, state: ResearchState) -> str:
        nonlocal fail_once
        if fail_once and getattr(state, "revision", None) == 1:
            fail_once = False
            raise OSError("controlled post-decision interruption")
        return original_save(self, state)

    monkeypatch.setattr(StateStore, "save", interrupted_save)
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="post-decision interruption"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="decision-recovery-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    assert calls == 1

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="decision-recovery-search-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["status"] == "complete"
    assert resumed["recovered_without_provider"] is True
    run = outputs / "projects/project-substrate-test/runs/decision-recovery-search-01"
    assert len(DecisionLogger(run / "substrate_action/decisions.jsonl").read_all()) == 1


def test_project_substrate_recovery_rejects_changed_stage_evidence_without_second_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    calls = 0

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    def interrupted_append(*_args: object, **_kwargs: object) -> None:
        raise OSError("controlled post-result interruption")

    monkeypatch.setattr(DecisionLogger, "append", interrupted_append)
    workflow = ProjectSubstrateActionWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="post-result interruption"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="tampered-recovery-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    run = outputs / "projects/project-substrate-test/runs/tampered-recovery-search-01"
    (run / "work/autoresearchclaw/stage-03/sources.json").write_text(
        '["changed"]\n', encoding="utf-8"
    )

    with pytest.raises(
        ValueError,
        match=r"artifact_manifest drift|published external result identity drift",
    ):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="tampered-recovery-search-01",
            resume=True,
            allow_live=True,
        )

    assert calls == 1


def test_project_substrate_plan_is_mutation_free_and_live_is_double_gated(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    disabled = _config(tmp_path, live_enabled=False)
    workflow = ProjectSubstrateActionWorkflow(seed=7)

    plan = workflow.plan(
        disabled,
        outputs_root=outputs,
        run_id="planned-search-01",
        source_run_dir=source,
    )
    assert plan["status"] == "planned"
    assert plan["would_contact_provider"] is False
    assert not outputs.exists()

    with pytest.raises(ValueError, match="disabled by configuration"):
        workflow.run(
            disabled,
            outputs_root=outputs,
            run_id="planned-search-01",
            source_run_dir=source,
            allow_live=True,
        )
    with pytest.raises(ValueError, match="caller live opt-in"):
        workflow.run(
            _config(tmp_path),
            outputs_root=outputs,
            run_id="planned-search-02",
            source_run_dir=source,
        )
    assert not outputs.exists()


def test_project_substrate_loader_resolves_relative_executor_config(tmp_path: Path) -> None:
    executor = _executor_config(tmp_path)
    config_path = tmp_path / "project-substrate.yaml"
    config_path.write_text(
        "\n".join(
            [
                'schema_version: "1.0"',
                "config_id: project-substrate-loader-v1",
                "project_id: loader-project",
                "title: Loader project",
                "research_direction: Verify loader boundaries",
                "target_domain: autonomous-research",
                "target_venue: test-only",
                "action_type: SEARCH",
                "provider: autoresearchclaw",
                "model: fixture-model",
                "condition: project_substrate_action",
                "evidence_scope: online-engineering-only",
                "live_enabled: false",
                f"autoresearchclaw_config: {executor.name}",
                "timeout_seconds: 120",
                "max_output_tokens: 2048",
                "max_snapshot_bytes: 1048576",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = load_project_substrate_config(config_path)

    assert loaded.autoresearchclaw_config == executor.resolve()
    assert loaded.action_type.value == "SEARCH"


def test_committed_zhipu_project_substrate_template_is_inert_and_bounded() -> None:
    loaded = load_project_substrate_config(
        "configs/workflows/project_substrate_search_zhipu_glm53_flash.example.yaml"
    )

    assert loaded.project_id == "scitaste-self-development"
    assert loaded.model == "glm-5.3-flash"
    assert loaded.target_domain is None
    assert loaded.execution_target_domain == "autonomous-research"
    assert loaded.live_enabled is False
    assert loaded.max_output_tokens == 4096
    assert loaded.max_total_tokens == 100_000
    assert loaded.autoresearchclaw_config.name == (
        "autoresearchclaw.zhipu-glm53-flash.example.yaml"
    )


def test_source_snapshot_rejects_symlinks(tmp_path: Path) -> None:
    source = _source_run(tmp_path)
    (source / "unsafe-link").symlink_to(source / "checkpoint.json")

    with pytest.raises(ValueError, match="cannot contain symlinks"):
        ProjectSubstrateActionWorkflow(seed=7).plan(
            _config(tmp_path),
            outputs_root=tmp_path / "outputs",
            run_id="unsafe-source-01",
            source_run_dir=source,
        )


def test_owned_copy_rejects_a_nested_parent_symlink(tmp_path: Path) -> None:
    source = _source_run(tmp_path)
    run_root = tmp_path / "owned-run"
    outside = tmp_path / "outside"
    run_root.mkdir()
    outside.mkdir()
    (run_root / "inputs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="parent cannot be a symbolic link"):
        project_workflow_module._copy_tree_exclusive(
            source,
            run_root / "inputs/autoresearchclaw",
        )

    assert not (outside / "autoresearchclaw").exists()


def test_run_lock_rejects_a_fifo(tmp_path: Path) -> None:
    run_root = tmp_path / "owned-run"
    run_root.mkdir()
    os.mkfifo(run_root / ".substrate-action.lock")

    with pytest.raises(ValueError, match="must be a regular file"):
        project_workflow_module._acquire_run_lock(run_root)


def test_project_substrate_cli_plan_is_read_only(tmp_path: Path, capsys) -> None:
    source = _source_run(tmp_path)
    executor = _executor_config(tmp_path)
    workflow_config = tmp_path / "project-substrate.yaml"
    workflow_config.write_text(
        "\n".join(
            [
                'schema_version: "1.0"',
                "config_id: project-substrate-cli-v1",
                "project_id: cli-substrate-project",
                "title: CLI substrate project",
                "research_direction: Verify project substrate CLI",
                "target_domain: autonomous-research",
                "action_type: SEARCH",
                "model: fixture-model",
                "live_enabled: false",
                f"autoresearchclaw_config: {executor.name}",
                "max_output_tokens: 4096",
                "max_total_tokens: 100000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    outputs = tmp_path / "outputs"

    exit_code = main(
        [
            "substrate",
            "project",
            "plan",
            "--config",
            str(workflow_config),
            "--run-id",
            "cli-plan-01",
            "--source-run",
            str(source),
            "--outputs-root",
            str(outputs),
            "--seed",
            "11",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "planned"
    assert payload["seed"] == 11
    assert payload["would_contact_provider"] is False
    assert not outputs.exists()


def test_project_substrate_rejects_owned_config_drift_before_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    source = _source_run(tmp_path)
    config = _config(tmp_path)
    provider_calls = 0
    original_copy = project_workflow_module._copy_file_exclusive

    def tampering_copy(source_path: Path, destination: Path) -> None:
        original_copy(source_path, destination)
        destination.write_text("changed: true\n", encoding="utf-8")

    def counted_runner(*_args: object, **_kwargs: object):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider must not be contacted")

    monkeypatch.setattr(project_workflow_module, "_copy_file_exclusive", tampering_copy)

    with pytest.raises(ValueError, match="changed before substrate execution"):
        ProjectSubstrateActionWorkflow(command_runner=counted_runner).run(
            config,
            outputs_root=outputs,
            run_id="config-drift-selected-01",
            source_run_dir=source,
            allow_live=True,
        )

    assert provider_calls == 0

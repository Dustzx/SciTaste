from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import scitaste.executor.project_bootstrap as bootstrap_module
from scitaste.cli import main
from scitaste.executor.autoresearchclaw import PINNED_COMMIT
from scitaste.executor.call_protocol import ExternalCallPhase, ExternalCallProtocol
from scitaste.executor.project_bootstrap import (
    ProjectSubstrateBootstrapManifest,
    ProjectSubstrateBootstrapWorkflow,
)
from scitaste.executor.project_workflow import ProjectSubstrateWorkflowConfig
from scitaste.project import ProjectRuntime
from scitaste.project.models import content_sha256


def _executor_config(root: Path) -> Path:
    path = root / "autoresearchclaw.yaml"
    path.write_text("llm:\n  api_key_env: ZAI_API_KEY\n", encoding="utf-8")
    return path


def _config(root: Path, *, live_enabled: bool = True) -> ProjectSubstrateWorkflowConfig:
    return ProjectSubstrateWorkflowConfig(
        config_id="project-substrate-bootstrap-test-v1",
        project_id="bootstrap-test-project",
        title="Bootstrap test project",
        research_direction="Create an owned prerequisite source",
        target_domain="autonomous-research",
        action_type="SEARCH",
        model="fixture-model",
        live_enabled=live_enabled,
        autoresearchclaw_config=_executor_config(root),
        max_output_tokens=4096,
        max_total_tokens=100_000,
    )


def _downgrade_bootstrap_run(
    outputs: Path,
    run_id: str,
    *,
    schema_version: str = "1.1",
) -> Path:
    run_root = outputs / "projects/bootstrap-test-project/runs" / run_id
    manifest_path = run_root / "bootstrap_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = schema_version
    manifest.pop("external_call_protocol_version")
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = content_sha256(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result_path = run_root / "substrate_bootstrap/executor_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["data"]["bootstrap_manifest_sha256"] = manifest["manifest_sha256"]
    result["data"].pop("call_started_sha256")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    shutil.rmtree(run_root / "substrate_bootstrap/call_protocol")
    (run_root / "substrate_bootstrap/source_receipt.json").unlink(missing_ok=True)

    project_path = outputs / "projects/bootstrap-test-project/PROJECT.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    registered = next(item for item in project["runs"] if item["run_id"] == run_id)
    registered["bootstrap_manifest_sha256"] = manifest["manifest_sha256"]
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
                "run_id": "owned-bootstrap-upstream",
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
    (work / "scitaste_llm_telemetry.jsonl").write_text(
        json.dumps(
            {
                "model": "fixture-model",
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "total_tokens": 300,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return subprocess.CompletedProcess(command, 0, stdout="complete", stderr="")


def test_schema_11_bootstrap_manifest_canonicalizes_an_explicit_null_protocol() -> None:
    manifest = ProjectSubstrateBootstrapManifest.create(
        schema_version="1.1",
        project_id="bootstrap-test-project",
        run_id="legacy-manifest-01",
        workflow_config_sha256="a" * 64,
        executor_config_sha256="b" * 64,
        expected_substrate_commit=PINNED_COMMIT,
        actual_substrate_commit=PINNED_COMMIT,
        seed=7,
        external_call_protocol_version=None,
    )

    assert manifest.external_call_protocol_version is None
    assert (
        ProjectSubstrateBootstrapManifest.model_validate_json(manifest.model_dump_json())
        == manifest
    )


def test_project_bootstrap_publishes_and_revalidates_owned_source(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    config = _config(tmp_path)
    workflow = ProjectSubstrateBootstrapWorkflow(
        seed=7,
        command_runner=_successful_runner,
    )

    result = workflow.run(
        config,
        outputs_root=outputs,
        run_id="bootstrap-source-01",
        allow_live=True,
    )

    assert result["status"] == "complete"
    assert result["execution_status"] == "SUCCEEDED"
    assert result["telemetry_total_tokens"] == 300
    assert result["api_cost_measured"] is True
    source, receipt = workflow.source_path(
        outputs_root=outputs,
        project_id=config.project_id,
        run_id="bootstrap-source-01",
    )
    assert (source / "stage-01/goal.md").is_file()
    assert (source / "stage-02/problem_tree.md").is_file()
    assert receipt.source_snapshot_sha256 == result["source_snapshot_sha256"]
    snapshot = ProjectRuntime(outputs).open(config.project_id)
    assert snapshot.manifest.runs[0].status == "complete"

    (source / "stage-02/problem_tree.md").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source snapshot hash drift"):
        workflow.status(
            outputs_root=outputs,
            project_id=config.project_id,
            run_id="bootstrap-source-01",
        )


def test_project_bootstrap_plan_is_read_only_and_live_is_double_gated(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    workflow = ProjectSubstrateBootstrapWorkflow(seed=7)
    disabled = _config(tmp_path, live_enabled=False)

    plan = workflow.plan(
        disabled,
        outputs_root=outputs,
        run_id="planned-bootstrap-01",
    )

    assert plan["status"] == "planned"
    assert plan["would_contact_provider"] is False
    assert not outputs.exists()
    with pytest.raises(ValueError, match="disabled by configuration"):
        workflow.run(
            disabled,
            outputs_root=outputs,
            run_id="planned-bootstrap-01",
            allow_live=True,
        )
    with pytest.raises(ValueError, match="caller live opt-in"):
        workflow.run(
            _config(tmp_path),
            outputs_root=outputs,
            run_id="planned-bootstrap-02",
        )
    assert not outputs.exists()


def test_project_bootstrap_resumes_prepared_attempt_before_any_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
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
        if fail_once and changes.get("external_call_phase") == "prepared":
            fail_once = False
            raise OSError("controlled bootstrap interruption after prepared")
        return original_update(
            self,
            project_id,
            registered_run_id,
            expected_revision=expected_revision,
            **changes,
        )

    monkeypatch.setattr(ProjectRuntime, "update_run", interrupted_update)
    workflow = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="after prepared"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="prepared-bootstrap-01",
            allow_live=True,
        )
    assert calls == 0
    action_root = (
        outputs / "projects/bootstrap-test-project/runs/prepared-bootstrap-01/substrate_bootstrap"
    )
    assert [
        entry.phase
        for entry in ExternalCallProtocol(action_root / "call_protocol").load(required=True)
    ] == [ExternalCallPhase.PREPARED]

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="prepared-bootstrap-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["status"] == "complete"
    run = ProjectRuntime(outputs).open(config.project_id).manifest.runs[0]
    assert (run.model_extra or {})["external_call_attempt"] == 1


def test_project_bootstrap_recovers_result_before_final_phase_without_recalling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
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
            raise OSError("controlled bootstrap interruption before result phase")
        return original_publish(self, **kwargs)

    monkeypatch.setattr(ExternalCallProtocol, "publish_result", interrupted_publish)
    workflow = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=counted_runner)
    with pytest.raises(OSError, match="before result phase"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="unjournaled-bootstrap-01",
            allow_live=True,
        )
    assert calls == 1

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="unjournaled-bootstrap-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["recovered_without_provider"] is True
    action_root = (
        outputs
        / "projects/bootstrap-test-project/runs/unjournaled-bootstrap-01/substrate_bootstrap"
    )
    assert (
        ExternalCallProtocol(action_root / "call_protocol").load(required=True)[-1].phase
        is ExternalCallPhase.RESULT_PUBLISHED
    )


def test_project_bootstrap_call_started_without_result_remains_ambiguous(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    config = _config(tmp_path)
    calls = 0

    def interrupted_runner(
        _command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        raise OSError("unknown bootstrap provider outcome")

    workflow = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=interrupted_runner)
    with pytest.raises(OSError, match="unknown bootstrap provider outcome"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="ambiguous-bootstrap-01",
            allow_live=True,
        )
    assert calls == 1
    with pytest.raises(ValueError, match="publication is ambiguous"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="ambiguous-bootstrap-01",
            resume=True,
            allow_live=True,
        )
    assert calls == 1


def test_project_bootstrap_recovers_a_persisted_paid_success_without_recalling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    config = _config(tmp_path)
    calls = 0

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    workflow = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=counted_runner)
    original = workflow._build_receipt
    fail_once = True

    def interrupted(*args: object, **kwargs: object):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("controlled post-result interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow, "_build_receipt", interrupted)
    with pytest.raises(OSError, match="post-result interruption"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="recoverable-bootstrap-01",
            allow_live=True,
        )
    assert calls == 1

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="recoverable-bootstrap-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["status"] == "complete"
    assert resumed["recovered_without_provider"] is True


def test_project_bootstrap_running_failed_result_starts_one_new_external_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
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

    workflow = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=fail_once)
    original = workflow._build_receipt
    interrupt_once = True

    def interrupted(*args: object, **kwargs: object):
        nonlocal interrupt_once
        if interrupt_once:
            interrupt_once = False
            raise OSError("simulated death after failed bootstrap result")
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow, "_build_receipt", interrupted)
    monkeypatch.setattr(
        bootstrap_module.ProjectSubstrateActionWorkflow,
        "_mark_failed",
        staticmethod(lambda *_args: None),
    )
    with pytest.raises(OSError, match="failed bootstrap result"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="running-failed-bootstrap-01",
            allow_live=True,
        )
    assert calls == 1
    assert ProjectRuntime(outputs).open(config.project_id).manifest.runs[0].status == "running"

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="running-failed-bootstrap-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 2
    assert resumed["status"] == "complete"
    run = ProjectRuntime(outputs).open(config.project_id).manifest.runs[0]
    assert (run.model_extra or {})["external_call_attempt"] == 2
    assert (run.model_extra or {})["resume_attempt"] == 1
    assert resumed["resume_attempt"] == 1


def test_schema_11_bootstrap_success_recovers_without_second_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    config = _config(tmp_path)
    calls = 0
    fail_once = True

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    workflow = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=counted_runner)
    original = workflow._build_receipt

    def interrupted(*args: object, **kwargs: object):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("controlled legacy bootstrap interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow, "_build_receipt", interrupted)
    with pytest.raises(OSError, match="legacy bootstrap interruption"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="legacy-success-bootstrap-01",
            allow_live=True,
        )
    _downgrade_bootstrap_run(outputs, "legacy-success-bootstrap-01")

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="legacy-success-bootstrap-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["status"] == "complete"
    assert resumed["recovered_without_provider"] is True
    assert resumed["external_call_phase"] == "legacy_unjournaled"


def test_schema_11_bootstrap_failure_retries_as_phase_aware_attempt_two(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    config = _config(tmp_path)
    calls = 0

    def fail_once(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")
        return _successful_runner(command, **kwargs)

    workflow = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=fail_once)
    failed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="legacy-failed-bootstrap-01",
        allow_live=True,
    )
    assert failed["status"] == "failed"
    run_root = _downgrade_bootstrap_run(outputs, "legacy-failed-bootstrap-01")

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="legacy-failed-bootstrap-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 2
    assert resumed["status"] == "complete"
    registered = ProjectRuntime(outputs).open(config.project_id).manifest.runs[0]
    assert (registered.model_extra or {})["external_call_attempt"] == 2
    chain = ExternalCallProtocol(run_root / "substrate_bootstrap/call_protocol").load(required=True)
    assert chain[-1].phase is ExternalCallPhase.RESULT_PUBLISHED
    assert chain[-1].external_call_attempt == 2


def test_schema_10_bootstrap_run_remains_read_only(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    config = _config(tmp_path)
    calls = 0

    def failed_runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

    workflow = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=failed_runner)
    workflow.run(
        config,
        outputs_root=outputs,
        run_id="legacy-read-only-bootstrap-01",
        allow_live=True,
    )
    _downgrade_bootstrap_run(
        outputs,
        "legacy-read-only-bootstrap-01",
        schema_version="1.0",
    )

    with pytest.raises(ValueError, match="read-only"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="legacy-read-only-bootstrap-01",
            resume=True,
            allow_live=True,
        )
    assert calls == 1


def test_project_bootstrap_recovers_running_hard_crash_without_recalling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    config = _config(tmp_path)
    calls = 0

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    workflow = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=counted_runner)
    original = workflow._build_receipt
    fail_once = True

    def interrupted(*args: object, **kwargs: object):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise OSError("simulated bootstrap process death")
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow, "_build_receipt", interrupted)
    monkeypatch.setattr(
        bootstrap_module.ProjectSubstrateActionWorkflow,
        "_mark_failed",
        staticmethod(lambda *_args: None),
    )
    with pytest.raises(OSError, match="simulated bootstrap process death"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="hard-crash-bootstrap-01",
            allow_live=True,
        )
    assert ProjectRuntime(outputs).open(config.project_id).manifest.runs[0].status == "running"
    plan = workflow.plan(
        config,
        outputs_root=outputs,
        run_id="hard-crash-bootstrap-01",
        resume=True,
        allow_live=True,
    )
    assert plan["would_contact_provider"] is False

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="hard-crash-bootstrap-01",
        resume=True,
        allow_live=True,
    )

    assert calls == 1
    assert resumed["status"] == "complete"
    assert resumed["recovered_without_provider"] is True


def test_project_bootstrap_retry_rejects_success_status_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    config = _config(tmp_path)
    calls = 0

    def counted_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return _successful_runner(command, **kwargs)

    workflow = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=counted_runner)
    monkeypatch.setattr(
        workflow,
        "_build_receipt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("post-result stop")),
    )
    with pytest.raises(OSError, match="post-result stop"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="status-tamper-bootstrap-01",
            allow_live=True,
        )
    result_path = (
        outputs
        / "projects/bootstrap-test-project/runs/status-tamper-bootstrap-01"
        / "substrate_bootstrap/executor_result.json"
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["status"] = "FAILED"
    payload["error"] = f"AutoResearchClaw command timed out after {config.timeout_seconds:g}s"
    payload["data"].pop("returncode")
    payload["data"]["partial_after_timeout"] = True
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"contradicts successful terminal evidence|published external result identity drift",
    ):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="status-tamper-bootstrap-01",
            resume=True,
            allow_live=True,
        )
    assert calls == 1


def test_project_bootstrap_archives_failed_attempt_before_explicit_retry(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    config = _config(tmp_path)
    calls = 0

    def fail_once(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            work = Path(command[command.index("--output") + 1])
            (work / "partial.txt").write_text("failed\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")
        return _successful_runner(command, **kwargs)

    workflow = ProjectSubstrateBootstrapWorkflow(seed=7, command_runner=fail_once)
    failed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="retried-bootstrap-01",
        allow_live=True,
    )
    assert failed["status"] == "failed"

    resumed = workflow.run(
        config,
        outputs_root=outputs,
        run_id="retried-bootstrap-01",
        resume=True,
        allow_live=True,
    )

    assert resumed["status"] == "complete"
    assert resumed["archived_attempt"] == "failed_attempts/attempt-001"
    run = outputs / "projects/bootstrap-test-project/runs/retried-bootstrap-01"
    assert (run / "failed_attempts/attempt-001/work/autoresearchclaw/partial.txt").is_file()
    assert (run / "source/autoresearchclaw/stage-02/problem_tree.md").is_file()


def test_project_bootstrap_cli_plan_is_read_only(tmp_path: Path, capsys) -> None:
    executor = _executor_config(tmp_path)
    workflow_config = tmp_path / "project-substrate.yaml"
    workflow_config.write_text(
        "\n".join(
            [
                'schema_version: "1.0"',
                "config_id: project-bootstrap-cli-v1",
                "project_id: bootstrap-cli-project",
                "title: Bootstrap CLI project",
                "research_direction: Verify bootstrap CLI boundaries",
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
            "bootstrap",
            "plan",
            "--config",
            str(workflow_config),
            "--run-id",
            "bootstrap-cli-plan-01",
            "--outputs-root",
            str(outputs),
            "--seed",
            "17",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "planned"
    assert payload["target_stage"] == "PROBLEM_DECOMPOSE"
    assert payload["seed"] == 17
    assert payload["would_contact_provider"] is False
    assert not outputs.exists()


def test_project_bootstrap_rejects_owned_config_drift_before_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = tmp_path / "outputs"
    config = _config(tmp_path)
    provider_calls = 0
    original_copy = bootstrap_module._copy_file_exclusive

    def tampering_copy(source: Path, destination: Path) -> None:
        original_copy(source, destination)
        destination.write_text("changed: true\n", encoding="utf-8")

    def counted_runner(*_args: object, **_kwargs: object):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider must not be contacted")

    monkeypatch.setattr(bootstrap_module, "_copy_file_exclusive", tampering_copy)

    with pytest.raises(ValueError, match="changed before bootstrap execution"):
        ProjectSubstrateBootstrapWorkflow(command_runner=counted_runner).run(
            config,
            outputs_root=outputs,
            run_id="config-drift-bootstrap-01",
            allow_live=True,
        )

    assert provider_calls == 0

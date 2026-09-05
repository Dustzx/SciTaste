from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import scitaste.executor.project_workflow as project_workflow_module
from scitaste.cli import main
from scitaste.executor.project_bootstrap import ProjectSubstrateBootstrapWorkflow
from scitaste.executor.project_workflow import (
    ProjectSubstrateActionWorkflow,
    ProjectSubstrateWorkflowConfig,
    load_project_substrate_config,
)
from scitaste.project import ProjectRuntime
from scitaste.state.persistence import StateStore


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

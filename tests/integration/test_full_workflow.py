from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

import scitaste.benchmark.manuscript as manuscript
import scitaste.full_workflow as full_workflow
from scitaste.cli import main
from scitaste.executor import ExecutionResult, ExecutionStatus, SciTasteNativeExecutor
from scitaste.full_workflow import FullStageRecord, FullWorkflow, load_full_workflow_config
from scitaste.project import ProjectRuntime
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.persistence import StateStore
from scitaste.state.research_state import ResearchState
from scitaste.writing.evidence_projection import WritingEvidenceProjection


def test_full_cli_preserves_one_state_and_registers_a_project_paper(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    outputs = tmp_path / "outputs"

    exit_code = main(
        [
            "run",
            "full",
            "--config",
            "configs/workflows/full_offline_v1.yaml",
            "--project-id",
            "full-integration-test",
            "--run-id",
            "offline-seed-07",
            "--seed",
            "7",
            "--output",
            str(outputs),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "complete"
    assert payload["effectiveness_claim"] is False
    assert payload["execution_backend"] == "scitaste-native"
    project = outputs / "projects/full-integration-test"
    run = project / "runs/offline-seed-07"
    final_state = StateStore(run / "stages/figure").load()
    assert final_state.project_id == "full-integration-test"
    assert final_state.working_hypotheses
    assert final_state.experiment_history
    assert final_state.writing_state is not None
    assert final_state.figure_state is not None
    assert len(final_state.decision_history) >= 15
    assert {
        decision.actual_outcome["executor"]
        for decision in final_state.decision_history
        if decision.actual_outcome is not None
    } == {"scitaste-native"}
    assert payload["native_execution"]["record_count"] == len(final_state.decision_history)
    assert payload["native_execution"]["head_record_sha256"]
    assert payload["native_execution"]["experiment"]["experiment_id"] == "experiment-support"
    assert payload["native_execution"]["experiment"]["availability"]["available"] is True
    assert payload["native_execution"]["code_admission"]["decision"] == "accepted"
    assert payload["native_execution"]["code_admission"]["runtime_isolation_required"] is True
    measured_experiment = next(
        item
        for item in final_state.experiment_history
        if item.experiment_id == "experiment-support"
    )
    assert measured_experiment.result_ref.startswith("res-")
    assert measured_experiment.result_ref != "result-support"
    assert measured_experiment.cost["experiments"] == 1.0
    search_decision = next(
        decision
        for decision in final_state.decision_history
        if decision.selected_action.type == MetaAction.SEARCH
    )
    assert search_decision.actual_outcome is not None
    assert search_decision.actual_outcome["data"]["result_basis"] == ("knowledge-library-retrieval")
    assert search_decision.actual_outcome["data"]["retrieved_document_ids"]
    evidence_summary = payload["stages"]["evidence"]
    assert evidence_summary["result_basis"] == "sandbox-measured-replicates"
    assert evidence_summary["measured_metrics"]["correct_pivot_delta"] == pytest.approx(0.1)
    communication_summary = payload["stages"]["communication"]
    assert communication_summary["measured_primary_metric"] == "correct_pivot_delta"
    assert communication_summary["measured_primary_value"] == pytest.approx(0.1)
    projection_path = run / "stages/communication/evidence_projection.json"
    projection = WritingEvidenceProjection.model_validate_json(
        projection_path.read_text(encoding="utf-8")
    )
    assert projection.result_id == measured_experiment.result_ref
    assert projection.primary_values == pytest.approx([0.1, 0.1, 0.1])
    assert projection.primary_dispersion == pytest.approx(0.0)
    communication_paper = (run / "stages/communication/paper.md").read_text(encoding="utf-8")
    assert "mean correct pivot delta of 0.100000" in communication_paper
    assert "replicate values: 0.100000, 0.100000, 0.100000" in communication_paper
    assert "result-support" not in communication_paper
    assert "result-matched-baseline" not in communication_paper
    assert "0.110000" not in communication_paper
    assert "0.080000 across" not in communication_paper
    publication_paper = (run / "stages/communication/paper.publication.md").read_text(
        encoding="utf-8"
    )
    assert "mean correct pivot delta of 0.100000" in publication_paper
    assert "[claim:" not in publication_paper
    assert "[evidence:" not in publication_paper
    assert "obligation-review" not in publication_paper
    retrieval_locator = search_decision.actual_outcome["artifacts"][0]
    assert (run / retrieval_locator).is_file()
    context = json.loads((run / "native_execution/context/CONTEXT.json").read_text())
    library_manifest = run / context["library_manifest_locator"]
    manifest = json.loads(library_manifest.read_text(encoding="utf-8"))
    assert manifest["knowledge_path"] == "knowledge/records.jsonl"
    assert not Path(manifest["knowledge_path"]).is_absolute()
    code_context = run / "native_execution/context/code"
    code_receipt = json.loads((code_context / "CODE.json").read_text(encoding="utf-8"))
    assert code_receipt["decision"] == "accepted"
    assert (code_context / "proposed.py").read_bytes() == (
        code_context / "admitted/experiment.py"
    ).read_bytes()
    native_records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((run / "native_execution/records").glob("*.json"))
    ]
    experiment_record = next(
        item
        for item in native_records
        if item["result"]["data"].get("result_basis") == "sandbox-measured-replicates"
    )
    assert list(experiment_record["input_sha256"]) == [
        "native_execution/context/code/admitted/experiment.py"
    ]
    assert payload["resumed"] is False
    assert payload["reused_stages"] == []
    for stage in payload["stages"]:
        record_path = run / "stages" / stage / "STAGE.json"
        assert record_path.is_file()
        record = FullStageRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
        assert record.stage == stage

    paper = project / "papers/offline-full-integration-fixture"
    assert (paper / "main.md").is_file()
    assert (paper / "main.tex").is_file()
    assert (paper / "build.json").is_file()
    assert (paper / "figures/figure.svg").is_file()
    assert (paper / "figures/figure.drawio").is_file()
    assert (paper / "MANIFEST.json").is_file()
    assert (paper / "ASSESSMENT.json").is_file()
    published_markdown = (paper / "main.md").read_text(encoding="utf-8")
    assert "mean correct pivot delta of 0.100000" in published_markdown
    assert "[claim:" not in published_markdown
    assert "[evidence:" not in published_markdown
    assert (project / "papers/current").resolve() == paper.resolve()
    paper_manifest = json.loads((paper / "MANIFEST.json").read_text(encoding="utf-8"))
    assessment = json.loads((paper / "ASSESSMENT.json").read_text(encoding="utf-8"))
    assert paper_manifest["status"] == "integration-fixture"
    assert paper_manifest["manuscript_role"] == "integration-fixture"
    assert set(paper_manifest["artifact_sha256"]) == set(paper_manifest["files"].values())
    assert len(paper_manifest["finalization_plan_sha256"]) == 64
    assert (run / "finalization/PLAN.json").is_file()
    assert payload["finalization"]["recovered_after_all_stages"] is False
    assert (
        assessment["manuscript_sha256"]
        == hashlib.sha256((paper / "main.md").read_bytes()).hexdigest()
    )
    assert assessment["substantive_research_draft"] is False
    assert assessment["paper_status"] == "integration-fixture"
    assert payload["manuscript_assessment"] == assessment
    assert Path(payload["snapshot_binding"]).is_file()

    decision_log = run / "stages/discovery/decisions.jsonl"
    decisions = [json.loads(line) for line in decision_log.read_text().splitlines()]
    decisions[0]["actual_outcome"]["observations"].append("tampered observation")
    tampered_log = run / "tampered-decisions.jsonl"
    tampered_log.write_text(
        "\n".join(json.dumps(item) for item in decisions) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="result does not match its decision"):
        full_workflow._verify_native_execution_bindings(tampered_log, run_root=run)


def test_full_workflow_executes_a_materialized_dataset_profile(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    config = load_full_workflow_config("configs/workflows/full_offline_dataset_v1.yaml")
    outputs = tmp_path / "outputs"

    payload = FullWorkflow(seed=7).run(
        config,
        outputs_root=outputs,
        run_id="dataset-seed-07",
    )

    run_root = outputs / "projects" / config.project_id / "runs/dataset-seed-07"
    experiment = payload["native_execution"]["experiment"]
    assert experiment["execution_profile_id"] == "conflict-pivot-dataset-cpu"
    assert experiment["dataset_mounts"] == ["/datasets/conflict-pivot-cases"]
    assert experiment["gpu_authorized"] is False
    assert experiment["availability"]["resources"]["available"] is True
    profile_record = run_root / "native_execution/context/resources/PROFILE.json"
    copied_dataset = run_root / "native_execution/context/resources/datasets/conflict-pivot-cases"
    assert profile_record.is_file()
    assert (
        copied_dataset.read_bytes()
        == Path("examples/native_experiments/data/conflict_pivot_cases_v1.json").read_bytes()
    )
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((run_root / "native_execution/records").glob("*.json"))
    ]
    execution = next(
        record
        for record in records
        if record["result"]["data"].get("result_basis") == "sandbox-measured-replicates"
    )
    assert any(locator.endswith("PROFILE.json") for locator in execution["input_sha256"])
    assert any(
        locator.endswith("datasets/conflict-pivot-cases") for locator in execution["input_sha256"]
    )
    assert execution["result"]["cost"]["gpu_hours"] == 0.0


def test_full_cli_dry_run_is_mutation_free(tmp_path: Path, capsys) -> None:
    outputs = tmp_path / "outputs"

    exit_code = main(
        [
            "run",
            "full",
            "--config",
            "configs/workflows/full_offline_v1.yaml",
            "--project-id",
            "dry-full-project",
            "--output",
            str(outputs),
            "--resume",
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "planned"
    assert payload["execution_backend"] == "scitaste-native"
    assert payload["native_execution"]["project_owned_records"] is True
    assert payload["native_execution"]["knowledge_configured"] is True
    assert payload["native_execution"]["resource_profile"] == {
        "profile_id": "default-deny",
        "datasets": [],
        "gpu_authorized": False,
    }
    assert payload["native_execution"]["experiment_configured"] is True
    assert payload["native_execution"]["experiment_id"] == "experiment-support"
    assert payload["native_execution"]["isolation_required"] is True
    assert payload["native_execution"]["isolation"]["available"] is True
    assert payload["native_execution"]["code_admission"]["decision"] == "accepted"
    assert payload["native_execution"]["code_admission"]["proposal_only"] is True
    assert payload["native_execution"]["code_admission"]["would_materialize_on_run"] is True
    assert payload["resume"] is True
    assert payload["stages"] == ["discovery", "evidence", "communication", "figure"]
    assert payload["paper"]["role"] == "integration-fixture"
    assert payload["paper"]["publication_ready"] is False
    assert not outputs.exists()


def test_full_cli_dry_run_preflights_dataset_profile_without_materializing(
    tmp_path: Path, capsys
) -> None:
    outputs = tmp_path / "outputs"

    exit_code = main(
        [
            "run",
            "full",
            "--config",
            "configs/workflows/full_offline_dataset_v1.yaml",
            "--output",
            str(outputs),
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    profile = payload["native_execution"]["resource_profile"]
    assert exit_code == 0
    assert profile["profile_id"] == "conflict-pivot-dataset-cpu"
    assert len(profile["fingerprint"]) == 64
    assert profile["datasets"][0]["mount_path"] == "/datasets/conflict-pivot-cases"
    assert profile["preflight"]["available"] is True
    assert profile["would_materialize_datasets_on_run"] is True
    assert payload["native_execution"]["isolation"]["resource_mount_probe"] == (
        "deferred-until-project-materialization"
    )
    assert not outputs.exists()


def test_full_workflow_refuses_to_label_short_fixture_as_research_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    base = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    config = type(base).model_validate(
        {
            **base.model_dump(mode="python"),
            "project_id": "short-research-manuscript",
            "paper_id": "short-research-manuscript-paper",
            "paper_directory": "short-research-manuscript-draft",
            "paper_role": "research-working-draft",
        }
    )

    with pytest.raises(ValueError, match="research manuscript completeness gate failed"):
        FullWorkflow(seed=7).run(
            config,
            outputs_root=tmp_path / "outputs",
            run_id="short-research-manuscript-run",
        )

    project = ProjectRuntime(tmp_path / "outputs").open(config.project_id)
    run = next(
        item for item in project.manifest.runs if item.run_id == "short-research-manuscript-run"
    )
    assert run.status == "failed"
    assert not any((tmp_path / "outputs/projects/short-research-manuscript/papers").iterdir())


def test_full_workflow_retains_rejected_code_proposal_without_executing_it(
    tmp_path: Path,
    capsys,
) -> None:
    candidate = tmp_path / "unsafe.py"
    candidate.write_text(
        "import json\n"
        "import socket\n"
        "payload={'schema_version':'1.0','measurements':["
        "{'replicate_id':'one','metrics':{'correct_pivot_delta':0.1}}]}\n"
        "print('SCITASTE_MEASUREMENTS_JSON='+json.dumps(payload))\n",
        encoding="utf-8",
    )
    proposal = tmp_path / "unsafe-proposal.yaml"
    proposal.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "proposal_id": "unsafe-network-proposal",
                "source_path": str(candidate),
                "rationale": "Deliberately exercise deterministic rejection.",
                "expected_metrics": ["correct_pivot_delta"],
                "producer": {
                    "schema_version": "1.0",
                    "mode": "registered",
                    "producer_id": "integration-fixture",
                },
                "experiment": {
                    "experiment_id": "experiment-support",
                    "primary_metric": "correct_pivot_delta",
                    "metric_direction": "maximize",
                    "support_threshold": 0.0,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    base = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    config = type(base).model_validate(
        {
            **base.model_dump(mode="python"),
            "project_id": "rejected-code-project",
            "paper_directory": "rejected-code-paper",
            "native_code_proposal_config": proposal,
        }
    )
    dry_config_path = tmp_path / "full-rejected.yaml"
    dry_config_path.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    dry_outputs = tmp_path / "dry-outputs"

    assert (
        main(
            [
                "run",
                "full",
                "--config",
                str(dry_config_path),
                "--run-id",
                "rejected-code-dry-run",
                "--output",
                str(dry_outputs),
                "--dry-run",
            ]
        )
        == 0
    )
    preview = json.loads(capsys.readouterr().out)
    assert preview["native_execution"]["code_admission"]["decision"] == "rejected"
    assert preview["native_execution"]["code_admission"]["violation_count"] == 1
    assert preview["native_execution"]["isolation_required"] is False
    assert preview["native_execution"]["isolation"] is None
    assert not dry_outputs.exists()

    outputs = tmp_path / "outputs"

    with pytest.raises(ValueError, match="import-not-allowed"):
        FullWorkflow(seed=7).run(
            config,
            outputs_root=outputs,
            run_id="rejected-code-run",
        )

    run_root = outputs / "projects/rejected-code-project/runs/rejected-code-run"
    receipt = json.loads(
        (run_root / "native_execution/context/code/CODE.json").read_text(encoding="utf-8")
    )
    admission = json.loads(
        (run_root / "native_execution/context/code/ADMISSION.json").read_text(encoding="utf-8")
    )
    registered = ProjectRuntime(outputs).open("rejected-code-project").manifest.runs[0]
    assert receipt["decision"] == "rejected"
    assert {item["code"] for item in admission["violations"]} == {"import-not-allowed"}
    assert not (run_root / "native_execution/context/code/admitted").exists()
    assert not any((run_root / "stages").iterdir())
    assert registered.status == "failed"
    assert (registered.model_extra or {})["failure_type"] == "NativeCodeAdmissionError"


def test_full_cli_can_explicitly_select_mock_compatibility_backend(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "run",
            "full",
            "--config",
            "configs/workflows/full_offline_v1.yaml",
            "--project-id",
            "mock-compatibility-project",
            "--backend",
            "mock",
            "--output",
            str(tmp_path / "outputs"),
            "--dry-run",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["execution_backend"] == "mock"


def test_full_config_rejects_ambiguous_registered_and_proposed_source() -> None:
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")

    with pytest.raises(ValueError, match="mutually exclusive"):
        type(config).model_validate(
            {
                **config.model_dump(mode="python"),
                "native_experiment_config": Path(
                    "configs/experiments/native_evidence_support_v1.yaml"
                ).resolve(),
            }
        )


def test_full_workflow_preserves_legacy_registered_experiment_context(tmp_path: Path) -> None:
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    legacy = type(config).model_validate(
        {
            **config.model_dump(mode="python"),
            "native_code_proposal_config": None,
            "native_experiment_config": Path(
                "configs/experiments/native_evidence_support_v1.yaml"
            ).resolve(),
        }
    )
    run_root = tmp_path / "legacy-run"
    run_root.mkdir()

    definition = full_workflow._prepare_native_experiment(legacy, run_root=run_root)

    assert definition is not None
    assert definition.experiment_id == "experiment-support"
    assert definition.source_path == run_root / "native_execution/context/experiment/experiment.py"
    assert (run_root / "native_execution/context/experiment/EXPERIMENT.json").is_file()


def test_full_workflow_retains_a_failed_run_for_audit(tmp_path: Path, monkeypatch) -> None:
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    payload = config.model_dump(mode="python")
    payload["project_id"] = "failed-full-project"
    config = type(config).model_validate(payload)

    def fail_figure(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("controlled figure failure")

    monkeypatch.setattr(full_workflow.FigureWorkflow, "run", fail_figure)
    outputs = tmp_path / "outputs"
    with pytest.raises(RuntimeError, match="controlled figure failure"):
        FullWorkflow(seed=7).run(config, outputs_root=outputs, run_id="failed-seed-07")

    snapshot = ProjectRuntime(outputs).open("failed-full-project")
    run = snapshot.manifest.runs[0]
    assert run.status == "failed"
    assert run.model_extra is not None
    assert run.model_extra["failure_type"] == "RuntimeError"
    assert run.model_extra["failure_message"] == "controlled figure failure"
    assert len(run.model_extra["workflow_config_sha256"]) == 64
    assert (outputs / "projects/failed-full-project/runs/failed-seed-07/stages").is_dir()


def test_failed_native_execution_is_logged_without_advancing_state(tmp_path: Path) -> None:
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    config = type(config).model_validate(
        {**config.model_dump(mode="python"), "project_id": "failed-native-execution"}
    )

    def fail(_state: ResearchState, action: ResearchAction) -> ExecutionResult:
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.FAILED,
            executor="scitaste-native",
            error="controlled native failure",
        )

    executor = SciTasteNativeExecutor(handlers={MetaAction.SEARCH: fail})
    outputs = tmp_path / "outputs"
    with pytest.raises(RuntimeError, match="controlled native failure"):
        FullWorkflow(seed=7, executor=executor).run(
            config,
            outputs_root=outputs,
            run_id="failed-native-seed-07",
        )

    run_root = outputs / "projects/failed-native-execution/runs/failed-native-seed-07"
    state = StateStore(run_root / "stages/discovery").load()
    decision = json.loads(
        (run_root / "stages/discovery/decisions.jsonl").read_text(encoding="utf-8")
    )
    registered = ProjectRuntime(outputs).open("failed-native-execution").manifest.runs[0]
    assert state.revision == 0
    assert state.decision_history == []
    assert decision["actual_outcome"]["status"] == "FAILED"
    assert registered.status == "failed"


def test_full_workflow_recovers_registered_paper_after_summary_interruption(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    payload = config.model_dump(mode="python")
    payload.update(
        {
            "project_id": "summary-failure-project",
            "paper_directory": "summary-failure-reviewed-draft",
        }
    )
    config = type(config).model_validate(payload)
    original_write_json = full_workflow._write_json

    def fail_summary(path: Path, value: object) -> None:
        if path.name == "full_run_summary.json":
            raise OSError("controlled summary failure")
        original_write_json(path, value)

    monkeypatch.setattr(full_workflow, "_write_json", fail_summary)
    outputs = tmp_path / "outputs"

    with pytest.raises(OSError, match="controlled summary failure"):
        FullWorkflow(seed=7).run(
            config,
            outputs_root=outputs,
            run_id="summary-failure-seed-07",
        )

    snapshot = ProjectRuntime(outputs).open("summary-failure-project")
    registered_run = snapshot.manifest.runs[0]
    assert registered_run.status == "failed"
    assert (registered_run.model_extra or {}).get("artifact") is None
    assert not (
        outputs / "projects/summary-failure-project/runs/summary-failure-seed-07/"
        "full_run_summary.json"
    ).exists()
    paper_root = outputs / "projects/summary-failure-project/papers/summary-failure-reviewed-draft"
    original_manifest = (paper_root / "MANIFEST.json").read_bytes()

    monkeypatch.setattr(full_workflow, "_write_json", original_write_json)
    result = FullWorkflow(seed=7).run(
        config,
        outputs_root=outputs,
        run_id="summary-failure-seed-07",
        resume=True,
    )

    assert result["status"] == "complete"
    assert result["reused_stages"] == ["discovery", "evidence", "communication", "figure"]
    assert result["finalization"]["recovered_after_all_stages"] is True
    assert result["finalization"]["reused_registered_paper"] is True
    assert (paper_root / "MANIFEST.json").read_bytes() == original_manifest
    completed = ProjectRuntime(outputs).open("summary-failure-project").manifest.runs[0]
    assert completed.status == "complete"


def test_full_workflow_archives_partial_paper_before_finalization_retry(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    config = type(config).model_validate(
        {
            **config.model_dump(mode="python"),
            "project_id": "partial-paper-project",
            "paper_directory": "partial-paper-draft",
        }
    )
    original_materialize = full_workflow.materialize_manuscript

    def interrupt_materialization(*, markdown_path: Path, target_dir: Path) -> list[Path]:
        target_dir.mkdir(parents=True)
        (target_dir / "partial.txt").write_text("interrupted", encoding="utf-8")
        raise OSError("controlled paper interruption")

    monkeypatch.setattr(full_workflow, "materialize_manuscript", interrupt_materialization)
    outputs = tmp_path / "outputs"
    workflow = FullWorkflow(seed=7)
    with pytest.raises(OSError, match="controlled paper interruption"):
        workflow.run(config, outputs_root=outputs, run_id="partial-paper-seed-07")

    monkeypatch.setattr(full_workflow, "materialize_manuscript", original_materialize)
    result = workflow.run(
        config,
        outputs_root=outputs,
        run_id="partial-paper-seed-07",
        resume=True,
    )

    archived = (
        outputs / "projects/partial-paper-project/runs/partial-paper-seed-07/"
        "failed_attempts/finalization/paper/attempt-001/partial-paper-draft/partial.txt"
    )
    assert archived.read_text(encoding="utf-8") == "interrupted"
    assert result["archived_attempts"] == [
        "failed_attempts/finalization/paper/attempt-001/partial-paper-draft"
    ]
    assert result["finalization"]["recovered_after_all_stages"] is True


def test_full_workflow_rejects_tampered_registered_paper_on_retry(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    config = type(config).model_validate(
        {
            **config.model_dump(mode="python"),
            "project_id": "tampered-finalization-project",
            "paper_directory": "tampered-finalization-draft",
        }
    )
    original_write_json = full_workflow._write_json

    def fail_summary(path: Path, value: object) -> None:
        if path.name == "full_run_summary.json":
            raise OSError("controlled summary failure")
        original_write_json(path, value)

    monkeypatch.setattr(full_workflow, "_write_json", fail_summary)
    outputs = tmp_path / "outputs"
    with pytest.raises(OSError, match="controlled summary failure"):
        FullWorkflow(seed=7).run(
            config,
            outputs_root=outputs,
            run_id="tampered-finalization-seed-07",
        )
    paper = outputs / "projects/tampered-finalization-project/papers/tampered-finalization-draft"
    (paper / "main.md").write_text("tampered\n", encoding="utf-8")

    monkeypatch.setattr(full_workflow, "_write_json", original_write_json)
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        FullWorkflow(seed=7).run(
            config,
            outputs_root=outputs,
            run_id="tampered-finalization-seed-07",
            resume=True,
        )


def test_completed_run_repairs_missing_snapshot_binding_without_stage_execution(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    config = type(config).model_validate(
        {
            **config.model_dump(mode="python"),
            "project_id": "surface-repair-project",
            "paper_directory": "surface-repair-draft",
        }
    )
    original_write_json = full_workflow._write_json

    def fail_surface(path: Path, value: object) -> None:
        if path.name == "surface-repair-seed-07-snapshot-binding.json":
            raise OSError("controlled surface interruption")
        original_write_json(path, value)

    monkeypatch.setattr(full_workflow, "_write_json", fail_surface)
    outputs = tmp_path / "outputs"
    workflow = FullWorkflow(seed=7)
    with pytest.raises(OSError, match="controlled surface interruption"):
        workflow.run(config, outputs_root=outputs, run_id="surface-repair-seed-07")
    before = ProjectRuntime(outputs).open(config.project_id)
    assert before.manifest.runs[0].status == "complete"
    native_records = list(
        (
            outputs / "projects/surface-repair-project/runs/surface-repair-seed-07/"
            "native_execution/records"
        ).glob("*.json")
    )

    monkeypatch.setattr(full_workflow, "_write_json", original_write_json)
    result = workflow.run(
        config,
        outputs_root=outputs,
        run_id="surface-repair-seed-07",
        resume=True,
    )

    assert result["completion_repaired"] is True
    assert Path(result["snapshot_binding"]).is_file()
    assert len(
        list(
            (
                outputs / "projects/surface-repair-project/runs/surface-repair-seed-07/"
                "native_execution/records"
            ).glob("*.json")
        )
    ) == len(native_records)


def test_full_workflow_archives_stale_summary_after_completion_update_failure(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    config = type(config).model_validate(
        {
            **config.model_dump(mode="python"),
            "project_id": "summary-update-retry-project",
            "paper_directory": "summary-update-retry-draft",
        }
    )
    original_update_run = full_workflow.ProjectRuntime.update_run
    interrupted = False

    def fail_completion_once(
        runtime: ProjectRuntime,
        project_id: str,
        registered_run_id: str,
        *,
        expected_revision: int,
        **changes: object,
    ) -> object:
        nonlocal interrupted
        if changes.get("status") == "complete" and not interrupted:
            interrupted = True
            raise OSError("controlled completion update failure")
        return original_update_run(
            runtime,
            project_id,
            registered_run_id,
            expected_revision=expected_revision,
            **changes,
        )

    monkeypatch.setattr(full_workflow.ProjectRuntime, "update_run", fail_completion_once)
    outputs = tmp_path / "outputs"
    workflow = FullWorkflow(seed=7)
    with pytest.raises(OSError, match="controlled completion update failure"):
        workflow.run(config, outputs_root=outputs, run_id="summary-update-retry-seed-07")

    monkeypatch.setattr(full_workflow.ProjectRuntime, "update_run", original_update_run)
    result = workflow.run(
        config,
        outputs_root=outputs,
        run_id="summary-update-retry-seed-07",
        resume=True,
    )

    assert result["status"] == "complete"
    assert result["archived_attempts"] == [
        "failed_attempts/finalization/summary/attempt-001/full_run_summary.json"
    ]
    archived_summary = (
        outputs / "projects/summary-update-retry-project/runs/summary-update-retry-seed-07/"
        "failed_attempts/finalization/summary/attempt-001/full_run_summary.json"
    )
    assert archived_summary.is_file()


def test_full_workflow_resumes_a_valid_prefix_and_archives_partial_stage(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(manuscript.shutil, "which", lambda _name: None)
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    payload = config.model_dump(mode="python")
    payload.update(
        {
            "project_id": "resumed-full-project",
            "paper_directory": "resumed-reviewed-draft",
        }
    )
    config = type(config).model_validate(payload)
    original_run = full_workflow.FigureWorkflow.run
    attempt = 0

    def fail_once(
        workflow: object,
        scenario: object,
        *,
        output_dir: str | Path,
        state_path: str | Path | None = None,
    ) -> dict[str, object]:
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            partial = Path(output_dir)
            partial.mkdir(parents=True, exist_ok=True)
            (partial / "partial.txt").write_text("interrupted", encoding="utf-8")
            raise RuntimeError("controlled one-shot failure")
        return original_run(
            workflow,
            scenario,
            output_dir=output_dir,
            state_path=state_path,
        )

    monkeypatch.setattr(full_workflow.FigureWorkflow, "run", fail_once)
    outputs = tmp_path / "outputs"
    workflow = FullWorkflow(seed=7)
    with pytest.raises(RuntimeError, match="controlled one-shot failure"):
        workflow.run(config, outputs_root=outputs, run_id="resumable-seed-07")

    run_root = outputs / "projects/resumed-full-project/runs/resumable-seed-07"
    prefix = ("discovery", "evidence", "communication")
    original_records = {
        stage: (run_root / "stages" / stage / "STAGE.json").read_bytes() for stage in prefix
    }
    original_native_record_count = len(list((run_root / "native_execution/records").glob("*.json")))

    result = workflow.run(
        config,
        outputs_root=outputs,
        run_id="resumable-seed-07",
        resume=True,
    )

    assert result["status"] == "complete"
    assert result["resume_attempt"] == 1
    assert result["reused_stages"] == list(prefix)
    assert result["archived_attempts"] == ["failed_attempts/stages/figure/attempt-001"]
    assert result["native_execution"]["record_count"] == original_native_record_count + 1
    assert (run_root / "failed_attempts/stages/figure/attempt-001/partial.txt").is_file()
    assert all(
        (run_root / "stages" / stage / "STAGE.json").read_bytes() == original_records[stage]
        for stage in prefix
    )
    snapshot = ProjectRuntime(outputs).open("resumed-full-project")
    registered_run = snapshot.manifest.runs[0]
    assert registered_run.status == "complete"
    assert registered_run.model_extra is not None
    assert registered_run.model_extra["resume_attempt"] == 1


def test_full_workflow_rejects_tampered_completed_stage_on_resume(
    tmp_path: Path, monkeypatch
) -> None:
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    payload = config.model_dump(mode="python")
    payload.update(
        {
            "project_id": "tampered-full-project",
            "paper_directory": "tampered-reviewed-draft",
        }
    )
    config = type(config).model_validate(payload)

    def fail_figure(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("stop before final stage")

    monkeypatch.setattr(full_workflow.FigureWorkflow, "run", fail_figure)
    outputs = tmp_path / "outputs"
    workflow = FullWorkflow(seed=7)
    with pytest.raises(RuntimeError, match="stop before final stage"):
        workflow.run(config, outputs_root=outputs, run_id="tampered-seed-07")

    run_root = outputs / "projects/tampered-full-project/runs/tampered-seed-07"
    changed_payload = config.model_dump(mode="python")
    changed_payload["paper_title"] = "A changed resume target"
    changed_config = type(config).model_validate(changed_payload)
    with pytest.raises(ValueError, match="workflow configuration does not match"):
        workflow.run(
            changed_config,
            outputs_root=outputs,
            run_id="tampered-seed-07",
            resume=True,
        )

    projection = run_root / "stages/communication/evidence_projection.json"
    projection.write_text(projection.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")

    with pytest.raises(ValueError, match="stage artifact hash mismatch"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="tampered-seed-07",
            resume=True,
        )

    snapshot = ProjectRuntime(outputs).open("tampered-full-project")
    assert snapshot.manifest.runs[0].status == "failed"
    assert not (run_root / "failed_attempts").exists()


def test_full_workflow_rejects_native_knowledge_drift_on_resume(
    tmp_path: Path, monkeypatch
) -> None:
    config = load_full_workflow_config("configs/workflows/full_offline_v1.yaml")
    config = type(config).model_validate(
        {
            **config.model_dump(mode="python"),
            "project_id": "native-context-drift-project",
            "paper_directory": "native-context-drift-draft",
        }
    )

    def fail_figure(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("stop after native retrieval")

    monkeypatch.setattr(full_workflow.FigureWorkflow, "run", fail_figure)
    outputs = tmp_path / "outputs"
    workflow = FullWorkflow(seed=7)
    with pytest.raises(RuntimeError, match="stop after native retrieval"):
        workflow.run(config, outputs_root=outputs, run_id="native-context-drift-seed-07")

    knowledge = (
        outputs / "projects/native-context-drift-project/runs/native-context-drift-seed-07/"
        "native_execution/context/libraries/knowledge/records.jsonl"
    )
    knowledge.write_text(knowledge.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        workflow.run(
            config,
            outputs_root=outputs,
            run_id="native-context-drift-seed-07",
            resume=True,
        )
    snapshot = ProjectRuntime(outputs).open("native-context-drift-project")
    assert snapshot.manifest.runs[0].status == "failed"

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scitaste.executor.native_code import NativeCodeAdmissionError, prepare_native_code_experiment
from scitaste.executor.native_code_generation import (
    NativeCodeGenerationError,
    generate_native_code_proposal,
    load_native_code_generation_config,
    load_native_code_repair_config,
    repair_native_code_proposal,
    validate_native_code_repair_binding,
    verify_native_code_generation_ledger,
)
from scitaste.model_nodes.backends import ScriptedStructuredBackend
from scitaste.model_nodes.runtime import RuntimeOutcome
from scitaste.model_nodes.runtime_config import ScriptedRuntimeBackend
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime

CONFIG = Path("configs/experiments/native_code_generation_scripted_support_v1.yaml")
REPAIR_CONFIG = Path("configs/experiments/native_code_repair_scripted_support_v1.yaml")
PROJECT_ID = "native-code-generation-project"
RUN_ID = "generated-source-run"
WORKFLOW_SHA256 = "a" * 64


def _rejected_generation_config():
    loaded = load_native_code_generation_config(CONFIG)
    assert isinstance(loaded.config.backend, ScriptedRuntimeBackend)
    reply = loaded.config.backend.reply
    output = dict(reply.output_payload)
    output["source_code"] = (
        "import os\n"
        'print("SCITASTE_MEASUREMENTS_JSON={\\"baseline_correct_pivot_rate\\":0}")\n'
        'baseline_correct_pivot_rate = "baseline_correct_pivot_rate"\n'
        'conflict_aware_correct_pivot_rate = "conflict_aware_correct_pivot_rate"\n'
        'correct_pivot_delta = "correct_pivot_delta"\n'
    )
    backend = loaded.config.backend.model_copy(
        update={"reply": reply.model_copy(update={"output_payload": output})}
    )
    return replace(loaded, config=loaded.config.model_copy(update={"backend": backend}))


def _project(tmp_path: Path) -> tuple[ProjectRuntime, int, Path]:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id=PROJECT_ID,
            title="Native code generation project",
            research_direction="Exercise proposal-only model source generation.",
            status="active",
        )
    )
    snapshot = runtime.begin_run(
        PROJECT_ID,
        ProjectRun(
            run_id=RUN_ID,
            provider="workflow",
            model="deterministic-controller",
            condition="native-code-generation",
            seed=7,
            status="running",
            evidence_scope="engineering-acceptance",
        ),
        expected_revision=0,
    )
    run_root = runtime.outputs_root / "projects" / PROJECT_ID / "runs" / RUN_ID
    return runtime, snapshot.revision, run_root


def test_generation_records_exact_model_provenance_before_admission(tmp_path: Path) -> None:
    runtime, revision, run_root = _project(tmp_path)
    loaded = load_native_code_generation_config(CONFIG)

    generated = generate_native_code_proposal(
        loaded,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )

    assert generated.record.receipt.outcome is RuntimeOutcome.ACCEPTED
    assert generated.record.receipt.telemetry.total_tokens == 2150
    assert generated.record.receipt.telemetry.cost_usd == 0
    assert generated.record.admission_decision == "accepted"
    assert generated.inspection.config.producer.mode == "model"
    assert generated.inspection.config.producer.request_sha256 == (generated.record.request_sha256)
    assert generated.inspection.config.producer.response_sha256 == (
        generated.record.response_sha256
    )
    assert generated.proposal_config_path.parent == (
        run_root / "native_execution/context/code_generation/result"
    )
    assert not (run_root / "native_execution/context/code/admitted/experiment.py").exists()
    assert runtime.open(PROJECT_ID).revision == revision


def test_generation_resume_reuses_completed_ledger_without_backend_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, revision, run_root = _project(tmp_path)
    loaded = load_native_code_generation_config(CONFIG)
    calls = 0
    original_build = ScriptedRuntimeBackend.build

    def counted_build(self: ScriptedRuntimeBackend, request_id: str):
        backend = original_build(self, request_id)
        original_complete = backend.complete

        def counted_complete(request):
            nonlocal calls
            calls += 1
            return original_complete(request)

        monkeypatch.setattr(backend, "complete", counted_complete)
        return backend

    monkeypatch.setattr(ScriptedRuntimeBackend, "build", counted_build)
    first = generate_native_code_proposal(
        loaded,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )
    second = generate_native_code_proposal(
        loaded,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
        resume=True,
    )

    assert calls == 1
    assert first.record.record_sha256 == second.record.record_sha256
    assert runtime.open(PROJECT_ID).revision == revision


def test_generation_recovers_after_ledger_commit_without_second_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scitaste.executor.native_code_generation as generation

    runtime, revision, run_root = _project(tmp_path)
    loaded = load_native_code_generation_config(CONFIG)
    calls = 0
    original_complete = ScriptedStructuredBackend.complete
    original_record_builder = generation._build_generation_record
    failed = False

    def counted_complete(self, request):
        nonlocal calls
        calls += 1
        return original_complete(self, request)

    def fail_after_ledger(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise SystemExit("controlled crash after model ledger commit")
        return original_record_builder(*args, **kwargs)

    monkeypatch.setattr(ScriptedStructuredBackend, "complete", counted_complete)
    monkeypatch.setattr(generation, "_build_generation_record", fail_after_ledger)
    with pytest.raises(SystemExit, match="ledger commit"):
        generate_native_code_proposal(
            loaded,
            project_runtime=runtime,
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            run_root=run_root,
            expected_project_revision=revision,
            workflow_config_sha256=WORKFLOW_SHA256,
            seed=7,
        )

    recovered = generate_native_code_proposal(
        loaded,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
        resume=True,
    )

    assert calls == 1
    assert recovered.record.admission_decision == "accepted"
    assert recovered.record.receipt.recovered_without_provider is False


def test_generation_fails_closed_on_result_tamper(tmp_path: Path) -> None:
    runtime, revision, run_root = _project(tmp_path)
    loaded = load_native_code_generation_config(CONFIG)
    generated = generate_native_code_proposal(
        loaded,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )
    generated.proposal_config_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(NativeCodeGenerationError, match="artifact hash drift"):
        generate_native_code_proposal(
            loaded,
            project_runtime=runtime,
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            run_root=run_root,
            expected_project_revision=revision,
            workflow_config_sha256=WORKFLOW_SHA256,
            seed=7,
            resume=True,
        )


def test_generated_source_rejection_is_recorded_before_execution(tmp_path: Path) -> None:
    runtime, revision, run_root = _project(tmp_path)
    configured = _rejected_generation_config()
    generated = generate_native_code_proposal(
        configured,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )

    assert generated.record.receipt.outcome is RuntimeOutcome.ACCEPTED
    assert generated.record.admission_decision == "rejected"
    assert {item.code for item in generated.inspection.admission.violations} == {
        "import-not-allowed"
    }
    with pytest.raises(NativeCodeAdmissionError, match="import-not-allowed"):
        prepare_native_code_experiment(
            generated.proposal_config_path,
            run_root=run_root,
            inspection=generated.inspection,
        )
    assert (run_root / "native_execution/context/code/ADMISSION.json").is_file()
    assert not (run_root / "native_execution/context/code/admitted/experiment.py").exists()


def test_rejected_generation_receives_one_readmitted_repair(tmp_path: Path) -> None:
    runtime, revision, run_root = _project(tmp_path)
    generated = generate_native_code_proposal(
        _rejected_generation_config(),
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )
    repair = load_native_code_repair_config(REPAIR_CONFIG)
    validate_native_code_repair_binding(repair, generated.loaded)

    repaired = repair_native_code_proposal(
        repair,
        generated=generated,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )

    assert generated.inspection.admission.decision == "rejected"
    assert repaired.inspection.admission.decision == "accepted"
    assert repaired.record.attempt_number == repaired.record.max_attempts == 1
    assert repaired.record.original_generation_record_sha256 == generated.record.record_sha256
    assert (generated.proposal_config_path.parent / "generated.py").read_text(
        encoding="utf-8"
    ).find("import os") >= 0
    assert (repaired.proposal_config_path.parent / "repaired.py").read_text(encoding="utf-8").find(
        "import os"
    ) == -1
    definition = prepare_native_code_experiment(
        repaired.proposal_config_path,
        run_root=run_root,
        inspection=repaired.inspection,
    )
    assert (
        definition.source_path.read_bytes()
        == (
            run_root / "native_execution/context/code_generation/repair/result/repaired.py"
        ).read_bytes()
    )
    verification = verify_native_code_generation_ledger(
        runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
    )
    assert verification.totals.entry_count == 2
    assert verification.totals.total_tokens == 3900
    assert verification.totals.cost_usd == 0


def test_repair_resume_never_calls_provider_twice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, revision, run_root = _project(tmp_path)
    generated = generate_native_code_proposal(
        _rejected_generation_config(),
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )
    repair = load_native_code_repair_config(REPAIR_CONFIG)
    calls = 0
    original_complete = ScriptedStructuredBackend.complete

    def counted_complete(self, request):
        nonlocal calls
        if self.model == "bounded-python-repair-v1":
            calls += 1
        return original_complete(self, request)

    monkeypatch.setattr(ScriptedStructuredBackend, "complete", counted_complete)
    first = repair_native_code_proposal(
        repair,
        generated=generated,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )
    second = repair_native_code_proposal(
        repair,
        generated=generated,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
        resume=True,
    )

    assert calls == 1
    assert first.record.record_sha256 == second.record.record_sha256


def test_repair_that_still_violates_policy_is_durably_rejected(tmp_path: Path) -> None:
    runtime, revision, run_root = _project(tmp_path)
    generated = generate_native_code_proposal(
        _rejected_generation_config(),
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )
    repair = load_native_code_repair_config(REPAIR_CONFIG)
    assert isinstance(repair.config.backend, ScriptedRuntimeBackend)
    reply = repair.config.backend.reply
    output = dict(reply.output_payload)
    output["source_code"] = "import os\n" + str(output["source_code"])
    unsafe = replace(
        repair,
        config=repair.config.model_copy(
            update={
                "backend": repair.config.backend.model_copy(
                    update={"reply": reply.model_copy(update={"output_payload": output})}
                )
            }
        ),
    )

    repaired = repair_native_code_proposal(
        unsafe,
        generated=generated,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )

    assert repaired.record.admission_decision == "rejected"
    assert {item.code for item in repaired.inspection.admission.violations} == {
        "import-not-allowed"
    }
    with pytest.raises(NativeCodeAdmissionError, match="import-not-allowed"):
        prepare_native_code_experiment(
            repaired.proposal_config_path,
            run_root=run_root,
            inspection=repaired.inspection,
        )


def test_repair_resume_fails_closed_on_source_tamper(tmp_path: Path) -> None:
    runtime, revision, run_root = _project(tmp_path)
    generated = generate_native_code_proposal(
        _rejected_generation_config(),
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )
    repair = load_native_code_repair_config(REPAIR_CONFIG)
    repaired = repair_native_code_proposal(
        repair,
        generated=generated,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )
    (repaired.proposal_config_path.parent / "repaired.py").write_text(
        "print('tampered')\n",
        encoding="utf-8",
    )

    with pytest.raises(NativeCodeGenerationError, match="artifact hash drift"):
        repair_native_code_proposal(
            repair,
            generated=generated,
            project_runtime=runtime,
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            run_root=run_root,
            expected_project_revision=revision,
            workflow_config_sha256=WORKFLOW_SHA256,
            seed=7,
            resume=True,
        )


def test_generation_config_rejects_embedded_credentials(tmp_path: Path) -> None:
    payload = CONFIG.read_text(encoding="utf-8") + "\napi_key: forbidden\n"
    path = tmp_path / "secret-bearing.yaml"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match="invalid native code generation configuration"):
        load_native_code_generation_config(path)


def test_generation_evidence_is_json_and_contains_no_secret(tmp_path: Path) -> None:
    runtime, revision, run_root = _project(tmp_path)
    loaded = load_native_code_generation_config(CONFIG)
    generated = generate_native_code_proposal(
        loaded,
        project_runtime=runtime,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        run_root=run_root,
        expected_project_revision=revision,
        workflow_config_sha256=WORKFLOW_SHA256,
        seed=7,
    )
    payload = json.loads(generated.proposal_config_path.read_text(encoding="utf-8"))

    assert "api_key" not in json.dumps(payload).casefold()
    assert payload["producer"]["provider"] == "scitaste-scripted"
    assert payload["producer"]["model"] == "bounded-python-generator-v1"

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.evaluation.task_execution import parse_benchmark_objective
from scitaste.evaluation.task_patch import (
    BenchmarkPatchEdit,
    BenchmarkPatchPolicy,
    BenchmarkPatchProducer,
    BenchmarkPatchProposal,
    apply_benchmark_patch,
    inspect_benchmark_patch,
    snapshot_benchmark_editable_files,
)
from scitaste.evaluation.task_patch_generation import (
    BenchmarkPatchGenerationInput,
    BenchmarkPatchGenerationNode,
    materialize_benchmark_patch_proposal,
)
from scitaste.evaluation.task_runtime import (
    BenchmarkTaskRuntimeSpec,
    RuntimeEvidenceBinding,
    hash_benchmark_tree,
    inspect_benchmark_task_runtime,
    prepare_benchmark_workspace,
)
from scitaste.model_nodes import (
    NodeContext,
    NodePolicy,
    NodeResultStatus,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
)
from scitaste.model_nodes.registry import first_party_node_types


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, BenchmarkTaskRuntimeSpec]:
    root = tmp_path / "root"
    checkout = root / "source"
    visible = checkout / "task" / "env"
    _write(visible / "main.py", "print('controller')\n")
    _write(visible / "methods" / "MyMethod.py", "VALUE = 1\n")
    _write(checkout / "task" / "research_problem.txt", "Improve the held-out metric.\n")
    _write(checkout / "task" / "read_only_files.txt", "main.py\n")
    _write(checkout / "task" / "environment.yml", "name: task-runtime\n")
    _write(root / "evidence" / "receipt.json", '{"receipt_sha256":"' + "a" * 64 + '"}\n')
    _write(root / "evidence" / "archive.json", '{"report_sha256":"' + "b" * 64 + '"}\n')
    _write(root / "evidence" / "license.json", '{"report_sha256":"' + "c" * 64 + '"}\n')
    _write(root / "evidence" / "objective.py", "print('objective')\n")

    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=SciTaste Test",
            "-c",
            "user.email=test@scitaste.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=checkout,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    visible_sha256, _, _ = hash_benchmark_tree(visible)

    def binding(path: Path, locator: str) -> RuntimeEvidenceBinding:
        return RuntimeEvidenceBinding(locator=locator, file_sha256=_sha256(path))

    spec = BenchmarkTaskRuntimeSpec(
        spec_id="mlrc-fixture-v1",
        project_id="task-runtime-project",
        benchmark_id="mlrc-bench",
        task_id="fixture-task",
        source_checkout="source",
        repository_commit=commit,
        task_root="task",
        visible_root="task/env",
        visible_tree_sha256=visible_sha256,
        maximum_visible_files=10,
        maximum_visible_bytes=10_000,
        research_problem=binding(
            checkout / "task" / "research_problem.txt",
            "task/research_problem.txt",
        ),
        read_only_manifest=binding(
            checkout / "task" / "read_only_files.txt",
            "task/read_only_files.txt",
        ),
        environment_manifest=binding(
            checkout / "task" / "environment.yml",
            "task/environment.yml",
        ),
        objective_entrypoint=binding(
            root / "evidence" / "objective.py",
            "evidence/objective.py",
        ),
        editable_globs=("methods/MyMethod.py",),
        dataset_directories=("data",),
        writable_output_directories=("outputs",),
        development_command=("python", "main.py", "-p", "dev"),
        heldout_command=("python", "main.py", "-p", "test"),
        heldout_materialization_paths=("data/test_labels.json",),
        primary_metric="normalized_score",
        metric_direction="higher",
        baseline_development_score=0.1,
        baseline_heldout_score=0.05,
        asset_receipt=binding(root / "evidence" / "receipt.json", "evidence/receipt.json"),
        archive_qualification=binding(
            root / "evidence" / "archive.json", "evidence/archive.json"
        ),
        license_evidence=binding(
            root / "evidence" / "license.json", "evidence/license.json"
        ),
        source_status=ReadinessStatus.VERIFIED,
        archive_status=ReadinessStatus.VERIFIED,
        license_status=ReadinessStatus.VERIFIED,
        ingestion_status=ReadinessStatus.VERIFIED,
        environment_status=ReadinessStatus.VERIFIED,
        scorer_status=ReadinessStatus.VERIFIED,
    )
    return root, spec


def test_task_runtime_materializes_only_the_visible_edit_surface(tmp_path: Path) -> None:
    root, spec = _fixture(tmp_path)
    inspection = inspect_benchmark_task_runtime(
        spec,
        workspace_root=root,
        spec_sha256="d" * 64,
    )

    assert inspection.ready_for_workspace_materialization
    assert inspection.ready_for_development_execution
    assert inspection.blocker_codes == ()
    with pytest.raises(ValueError, match="explicit authorization"):
        prepare_benchmark_workspace(
            spec,
            inspection,
            workspace_root=root,
            destination=root / "cells" / "cell-1",
        )

    receipt = prepare_benchmark_workspace(
        spec,
        inspection,
        workspace_root=root,
        destination=root / "cells" / "cell-1",
        allow_materialization=True,
    )

    workspace = root / "cells" / "cell-1"
    assert receipt.workspace_locator == "cell-1"
    assert receipt.editable_files == ("methods/MyMethod.py",)
    assert "main.py" in receipt.read_only_files
    assert (workspace / "outputs").is_dir()
    assert not (workspace / "data" / "test_labels.json").exists()
    assert (workspace / "methods" / "MyMethod.py").stat().st_mode & stat.S_IWUSR
    assert not (workspace / "main.py").stat().st_mode & stat.S_IWUSR
    retained = json.loads((root / "cells" / "cell-1.receipt.json").read_text())
    assert retained["receipt_sha256"] == receipt.receipt_sha256
    assert str(root) not in json.dumps(retained)


def test_task_runtime_refuses_source_drift_and_size_excess(tmp_path: Path) -> None:
    root, spec = _fixture(tmp_path)
    editable = root / "source" / "task" / "env" / "methods" / "MyMethod.py"
    editable.write_text("VALUE = 2\n", encoding="utf-8")

    inspection = inspect_benchmark_task_runtime(
        spec.model_copy(update={"maximum_visible_bytes": 1}),
        workspace_root=root,
        spec_sha256="e" * 64,
    )

    assert not inspection.ready_for_workspace_materialization
    assert "source-checkout-dirty" in inspection.blocker_codes
    assert "visible-tree-drift" in inspection.blocker_codes
    assert "visible-tree-byte-limit-exceeded" in inspection.blocker_codes


def test_benchmark_patch_replaces_exact_context_without_running_task(tmp_path: Path) -> None:
    root, spec = _fixture(tmp_path)
    inspection = inspect_benchmark_task_runtime(
        spec,
        workspace_root=root,
        spec_sha256="d" * 64,
    )
    prepared = prepare_benchmark_workspace(
        spec,
        inspection,
        workspace_root=root,
        destination=root / "cells" / "cell-1",
        allow_materialization=True,
    )
    workspace = root / "cells" / "cell-1"
    context = snapshot_benchmark_editable_files(
        spec,
        prepared,
        workspace,
        selected_paths=("methods/MyMethod.py",),
    )
    replacement = "VALUE = 2\n"
    edit = BenchmarkPatchEdit(
        path=context.files[0].path,
        expected_sha256=context.files[0].sha256,
        replacement=replacement,
        replacement_sha256=hashlib.sha256(replacement.encode()).hexdigest(),
    )
    policy = BenchmarkPatchPolicy()
    proposal = BenchmarkPatchProposal(
        proposal_id="fixture-patch-1",
        spec_id=spec.spec_id,
        spec_fingerprint=spec.fingerprint,
        policy_fingerprint=policy.fingerprint,
        context_sha256=context.context_sha256,
        iteration=1,
        base_editable_surface_sha256=context.editable_surface_sha256,
        hypothesis="Changing the registered method value should alter the controlled fixture.",
        expected_effect="The development fixture should observe value two.",
        edits=(edit,),
        producer=BenchmarkPatchProducer(mode="registered", producer_id="fixture"),
    )

    admission = inspect_benchmark_patch(
        proposal,
        context,
        spec,
        prepared,
        policy,
        workspace=workspace,
    )
    assert admission.decision == "accepted"
    with pytest.raises(ValueError, match="explicit authorization"):
        apply_benchmark_patch(
            proposal,
            admission,
            spec,
            policy,
            workspace=workspace,
            receipt_path=root / "cells" / "patch-1.json",
        )

    receipt = apply_benchmark_patch(
        proposal,
        admission,
        spec,
        policy,
        workspace=workspace,
        receipt_path=root / "cells" / "patch-1.json",
        allow_mutation=True,
    )

    assert (workspace / "methods" / "MyMethod.py").read_text() == replacement
    assert receipt.model_invocation_performed_by_application is False
    assert receipt.benchmark_execution_performed is False
    assert receipt.edits[0].before_sha256 == context.files[0].sha256
    assert json.loads((root / "cells" / "patch-1.json").read_text())["receipt_sha256"] == (
        receipt.receipt_sha256
    )


def test_benchmark_patch_rejects_invalid_or_stale_source(tmp_path: Path) -> None:
    root, spec = _fixture(tmp_path)
    inspection = inspect_benchmark_task_runtime(
        spec,
        workspace_root=root,
        spec_sha256="d" * 64,
    )
    prepared = prepare_benchmark_workspace(
        spec,
        inspection,
        workspace_root=root,
        destination=root / "cells" / "cell-1",
        allow_materialization=True,
    )
    workspace = root / "cells" / "cell-1"
    context = snapshot_benchmark_editable_files(
        spec,
        prepared,
        workspace,
        selected_paths=("methods/MyMethod.py",),
    )
    replacement = "not valid python !\n"
    policy = BenchmarkPatchPolicy()
    proposal = BenchmarkPatchProposal(
        proposal_id="fixture-patch-invalid",
        spec_id=spec.spec_id,
        spec_fingerprint=spec.fingerprint,
        policy_fingerprint=policy.fingerprint,
        context_sha256=context.context_sha256,
        iteration=1,
        base_editable_surface_sha256=context.editable_surface_sha256,
        hypothesis="Exercise deterministic rejection.",
        expected_effect="No mutation should occur.",
        edits=(
            BenchmarkPatchEdit(
                path=context.files[0].path,
                expected_sha256=context.files[0].sha256,
                replacement=replacement,
                replacement_sha256=hashlib.sha256(replacement.encode()).hexdigest(),
            ),
        ),
        producer=BenchmarkPatchProducer(mode="registered", producer_id="fixture"),
    )

    admission = inspect_benchmark_patch(
        proposal,
        context,
        spec,
        prepared,
        policy,
        workspace=workspace,
    )

    assert admission.decision == "rejected"
    assert [item.code for item in admission.violations] == ["replacement-syntax"]
    with pytest.raises(ValueError, match="rejected benchmark patch"):
        apply_benchmark_patch(
            proposal,
            admission,
            spec,
            policy,
            workspace=workspace,
            receipt_path=root / "cells" / "patch-invalid.json",
            allow_mutation=True,
        )
    assert (workspace / "methods" / "MyMethod.py").read_text() == "VALUE = 1\n"
    protected = workspace / "main.py"
    protected.chmod(protected.stat().st_mode | stat.S_IWUSR)
    protected.write_text("print('tampered')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="protected benchmark source changed"):
        snapshot_benchmark_editable_files(
            spec,
            prepared,
            workspace,
            selected_paths=("methods/MyMethod.py",),
        )


def test_benchmark_patch_model_node_can_propose_or_stop_without_authority(tmp_path: Path) -> None:
    root, spec = _fixture(tmp_path)
    inspection = inspect_benchmark_task_runtime(
        spec,
        workspace_root=root,
        spec_sha256="d" * 64,
    )
    prepared = prepare_benchmark_workspace(
        spec,
        inspection,
        workspace_root=root,
        destination=root / "cells" / "cell-1",
        allow_materialization=True,
    )
    workspace = root / "cells" / "cell-1"
    context = snapshot_benchmark_editable_files(
        spec,
        prepared,
        workspace,
        selected_paths=("methods/MyMethod.py",),
    )
    policy = BenchmarkPatchPolicy()
    input_data = BenchmarkPatchGenerationInput(
        task_id=spec.task_id,
        research_problem="Improve the development score without using held-out data.",
        primary_metric=spec.primary_metric,
        metric_direction=spec.metric_direction,
        baseline_development_score=spec.baseline_development_score,
        current_development_score=0.1,
        best_development_score=0.1,
        iteration=1,
        remaining_experiment_runs=2,
        patch_context=context,
        patch_policy=policy,
        taste_guidance=("Prefer a falsifiable structural change over parameter churn.",),
        constraints=("Only replace source included in the exact context.",),
    )
    output = {
        "schema_version": "1.0",
        "decision": "propose",
        "hypothesis": "A different controlled value should improve the fixture score.",
        "expected_effect": "Development score should increase above 0.1.",
        "edits": [{"path": "methods/MyMethod.py", "replacement": "VALUE = 2\n"}],
        "stop_reason": None,
    }
    backend = ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "patch-node-1": ScriptedStructuredReply(
                output_payload=output,
                usage=Usage(input_tokens=10, output_tokens=10, cost_usd=0.0),
            )
        },
    )
    node_policy = NodePolicy(
        policy_id="fixture-patch-node",
        enabled=True,
        allowed_node_names=["benchmark-research-patch"],
        expected_backend="scripted",
        expected_model="scripted-v1",
        max_request_bytes=100_000,
        max_input_tokens=100,
        max_output_tokens=100,
        max_total_tokens=200,
        max_api_cost_usd=0.1,
        max_latency_ms=1_000,
    )
    result = BenchmarkPatchGenerationNode().run(
        input_data,
        context=NodeContext(
            project_id=spec.project_id,
            stage="EXPERIMENTATION",
            state_snapshot_id=context.context_sha256,
            cumulative_api_cost_usd=0,
        ),
        backend=backend,
        policy=node_policy,
        request_id="patch-node-1",
    )

    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    proposal = materialize_benchmark_patch_proposal(
        result.proposal,
        input_data,
        proposal_id="fixture-model-patch-1",
        producer=BenchmarkPatchProducer(
            mode="model",
            producer_id="fixture-node",
            provider="scripted",
            model="scripted-v1",
            request_sha256=result.request.fingerprint,
            response_sha256=result.response.raw_response_sha256,
        ),
    )
    admission = inspect_benchmark_patch(
        proposal,
        context,
        spec,
        prepared,
        policy,
        workspace=workspace,
    )
    assert admission.decision == "accepted"
    assert "benchmark-research-patch" in first_party_node_types()
    assert (workspace / "methods" / "MyMethod.py").read_text() == "VALUE = 1\n"


def test_benchmark_objective_parser_requires_one_development_measurement() -> None:
    marker = b"SCITASTE_BENCHMARK_OBJECTIVE_JSON="
    payload = json.dumps(
        {
            "schema_version": "1.0",
            "task_id": "fixture-task",
            "phase": "dev",
            "method": "my_method",
            "score": 0.25,
            "elapsed_seconds": 1.5,
            "secondary_llm_judge_invoked": False,
        },
        separators=(",", ":"),
    ).encode()

    objective = parse_benchmark_objective(
        b"training\n" + marker + payload + b"\n",
        task_id="fixture-task",
    )

    assert objective.score == 0.25
    assert objective.secondary_llm_judge_invoked is False
    with pytest.raises(ValueError, match="exactly one"):
        parse_benchmark_objective(
            marker + payload + b"\n" + marker + payload,
            task_id="fixture-task",
        )

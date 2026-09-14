from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from pathlib import Path

import pytest

from scitaste.evaluation.prelaunch import ReadinessStatus
from scitaste.evaluation.task_runtime import (
    BenchmarkTaskRuntimeSpec,
    RuntimeEvidenceBinding,
    hash_benchmark_tree,
    inspect_benchmark_task_runtime,
    prepare_benchmark_workspace,
)


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
        editable_globs=("methods/MyMethod.py",),
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

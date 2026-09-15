from __future__ import annotations

import csv
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation.acquisition import (
    AcquiredItemReceipt,
    DatasetAcquisitionReceipt,
    DatasetAcquisitionRequest,
    load_dataset_acquisition_request,
    save_dataset_acquisition_request,
)
from scitaste.evaluation.lifecycle_benchmark_bridge import (
    BenchmarkBridgeKind,
    ConjunctiveResultInput,
    LifecycleStage,
    OutputPackage,
    OutputStatus,
    StageOutput,
    StageStatus,
    inspect_lifecycle_benchmark_bridge,
    materialize_lifecycle_task_package,
    plan_lifecycle_benchmark_bridge,
)
from scitaste.evaluation.lifecycle_benchmark_bridge_cli import main as bridge_main

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = ROOT / (
    "configs/evaluation/programs/iclr2027_scitaste_complete_autoresearch_program_v3.yaml"
)
MLR_REQUEST = ROOT / "configs/evaluation/acquisition/mlr_bench_official_ten_briefs_v1.yaml"
EXP_REQUEST = ROOT / "configs/evaluation/acquisition/expbench_task_metadata_v1.yaml"
MLR_SELECTION = ROOT / "docs/research/data/mlr_bench_official_ten_candidate_v2.yaml"


def _program(tmp_path: Path) -> Path:
    target = tmp_path / "program.yaml"
    shutil.copyfile(PROGRAM, target)
    return target


def _materialize_acquisition(
    tmp_path: Path,
    source_request: Path,
    payloads: dict[str, bytes],
) -> tuple[Path, Path, DatasetAcquisitionRequest]:
    request = load_dataset_acquisition_request(source_request).request
    destination = f"acquisitions/{request.request_id}/raw"
    request = request.model_copy(update={"destination_root": destination})
    request_path = tmp_path / "request.yaml"
    save_dataset_acquisition_request(request, request_path)
    acquisition_root = tmp_path / "acquisitions" / request.request_id
    raw_root = acquisition_root / "raw"
    raw_root.mkdir(parents=True)
    items: list[AcquiredItemReceipt] = []
    for item in request.items:
        payload = payloads[item.item_id]
        target = raw_root / item.destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        items.append(
            AcquiredItemReceipt(
                item_id=item.item_id,
                source_url=item.source_url,
                source_revision=item.source_revision,
                destination=item.destination,
                size_bytes=len(payload),
                sha256=_sha(payload),
                expected_sha256=item.expected_sha256,
            )
        )
    receipt = DatasetAcquisitionReceipt.create(
        request_id=request.request_id,
        request_sha256=request.request_sha256,
        approved_by="test-owner",
        approved_at=datetime(2026, 9, 15, 0, 0, tzinfo=UTC),
        acquired_at=datetime(2026, 9, 15, 0, 1, tzinfo=UTC),
        approval_scope="download-only-no-ingestion",
        destination_root=destination,
        items=tuple(items),
        item_count=len(items),
        total_bytes=sum(item.size_bytes for item in items),
        maximum_total_bytes=request.maximum_total_bytes,
        source_hosts=tuple(
            sorted(
                {
                    "raw.githubusercontent.com"
                    if "github" in item.source_url
                    else "huggingface.co"
                    for item in request.items
                }
            )
        ),
    )
    (acquisition_root / "RECEIPT.json").write_text(
        receipt.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return request_path, acquisition_root, request


def _sha(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _mlr_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    selection = tmp_path / "docs/research/data/mlr_bench_official_ten_candidate_v2.yaml"
    selection.parent.mkdir(parents=True)
    shutil.copyfile(MLR_SELECTION, selection)
    request = load_dataset_acquisition_request(MLR_REQUEST).request
    payloads = {
        item.item_id: f"# Brief for {item.item_id}\n\nFrozen input.\n".encode()
        for item in request.items
    }
    request_path, acquisition_root, _ = _materialize_acquisition(
        tmp_path,
        MLR_REQUEST,
        payloads,
    )
    return request_path, acquisition_root, _program(tmp_path)


def _exp_csv() -> bytes:
    from io import StringIO

    output = StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=(
            "conference",
            "paper_id",
            "paper_title",
            "task_index",
            "task_type",
            "subtask_count",
            "question",
            "agent_instructions",
            "impl_requirements",
            "expected_outcome",
            "source_files",
        ),
    )
    writer.writeheader()
    for index in range(2):
        writer.writerow(
            {
                "conference": "iclr2024",
                "paper_id": "12345",
                "paper_title": "A frozen paper",
                "task_index": str(index),
                "task_type": "1",
                "subtask_count": "2",
                "question": f"Question {index}?",
                "agent_instructions": "Run a bounded experiment.",
                "impl_requirements": "Produce code and logs.",
                "expected_outcome": f"SCORER_ONLY_SECRET_{index}",
                "source_files": "['train.py']",
            }
        )
    return output.getvalue().encode()


def test_mlr_bridge_is_brief_only_and_materializes_exact_existing_bytes(tmp_path: Path) -> None:
    request, acquisition, program = _mlr_fixture(tmp_path)
    plan = plan_lifecycle_benchmark_bridge(
        BenchmarkBridgeKind.MLR_BENCH,
        request_path=request,
        acquisition_root=acquisition,
        program_path=program,
        workspace_root=tmp_path,
    )

    assert plan.ready_to_materialize is True
    assert plan.task_package is not None
    assert plan.task_package.task_count == 10
    assert plan.task_package.source_group_count == 10
    assert plan.task_package.scientific_use == "brief-only-stagewise-prepilot"
    assert plan.task_package.complete_e3_claim_allowed is False
    assert plan.ready_for_controller_acquisition_binding is True
    assert plan.ready_for_controller_admission_binding is False
    assert {finding.code for finding in plan.findings} >= {
        "heldout-source-group-audit-pending",
        "runtime-assets-absent",
        "benchmark-rubric-unmaterialized",
    }

    output = tmp_path / "materialized-mlr"
    receipt = materialize_lifecycle_task_package(
        plan,
        workspace_root=tmp_path,
        output_root=output,
    )
    status = inspect_lifecycle_benchmark_bridge(
        plan,
        workspace_root=tmp_path,
        package_root=output,
    )

    assert receipt.projected_file_count == 10
    assert status.materialized_package_valid is True
    assert status.brief_only_stagewise_prepilot_ready is True
    assert status.runtime_ready is False
    assert status.scorer_ready is False
    assert status.formal_task_ready is False


def test_exp_bridge_groups_by_paper_and_keeps_expected_outcome_scorer_only(
    tmp_path: Path,
) -> None:
    csv_bytes = _exp_csv()
    request, acquisition, _ = _materialize_acquisition(
        tmp_path,
        EXP_REQUEST,
        {"exp_bench_dataset": csv_bytes},
    )
    plan = plan_lifecycle_benchmark_bridge(
        BenchmarkBridgeKind.EXP_BENCH,
        request_path=request,
        acquisition_root=acquisition,
        program_path=_program(tmp_path),
        workspace_root=tmp_path,
    )

    assert plan.task_package is not None
    assert plan.task_package.task_count == 2
    assert plan.task_package.source_group_count == 1
    assert plan.task_package.scientific_use == "metadata-only-experiment-chain-planning"
    assert plan.task_package.complete_e4_claim_allowed is False
    boundary = plan.task_package.scoring_boundary
    assert "expected_outcome" in boundary.scorer_only_input_fields
    assert "expected_outcome" not in boundary.agent_visible_input_fields
    assert boundary.hidden_label_materialized_in_task_package is False
    assert boundary.scorer_implemented_by_bridge is False

    output = tmp_path / "materialized-exp"
    materialize_lifecycle_task_package(
        plan,
        workspace_root=tmp_path,
        output_root=output,
    )
    visible = json.loads((output / plan.input_projections[0].output_ref).read_text())
    assert "expected_outcome" not in visible
    assert b"SCORER_ONLY_SECRET" not in b"".join(
        path.read_bytes() for path in output.rglob("*") if path.is_file()
    )
    status = inspect_lifecycle_benchmark_bridge(
        plan,
        workspace_root=tmp_path,
        package_root=output,
    )
    assert status.metadata_ready is True
    assert status.runtime_ready is False
    assert status.scorer_ready is False
    assert status.ready_for_controller_admission_binding is False


def test_missing_receipt_is_a_materialization_and_admission_blocker(tmp_path: Path) -> None:
    request = load_dataset_acquisition_request(EXP_REQUEST).request.model_copy(
        update={"destination_root": "acquisitions/expbench-task-metadata-v1/raw"}
    )
    request_path = tmp_path / "request.yaml"
    save_dataset_acquisition_request(request, request_path)

    plan = plan_lifecycle_benchmark_bridge(
        BenchmarkBridgeKind.EXP_BENCH,
        request_path=request_path,
        acquisition_root=tmp_path / "acquisitions/expbench-task-metadata-v1",
        program_path=_program(tmp_path),
        workspace_root=tmp_path,
    )

    assert plan.task_package is None
    assert plan.ready_to_materialize is False
    finding = next(item for item in plan.findings if item.code == "acquisition-receipt-missing")
    assert finding.blocks_materialization is True
    assert finding.blocks_admission is True


def test_output_contract_cannot_claim_completion_before_candidate_freeze() -> None:
    result_input = ConjunctiveResultInput(
        candidate_manifest_sha256="1" * 64,
        stage_outputs=(
            StageOutput(stage=LifecycleStage.HYPOTHESIS, status=StageStatus.SUCCEEDED),
        ),
    )

    with pytest.raises(ValidationError, match="frozen candidate"):
        OutputPackage(
            output_package_id="output-v1",
            task_package_sha256="2" * 64,
            benchmark_id=BenchmarkBridgeKind.EXP_BENCH,
            task_id="exp-task-1",
            system_id="scitaste-native",
            status=OutputStatus.COMPLETE,
            candidate_frozen=False,
            result_input=result_input,
            scoring_boundary_id="exp-bench-isolated-scorer-v1",
        )


def test_standalone_cli_exposes_plan_materialize_and_blocked_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request, acquisition, program = _mlr_fixture(tmp_path)
    plan_path = tmp_path / "bridge-plan.json"
    output = tmp_path / "bridge-package"

    assert (
        bridge_main(
            [
                "plan",
                "--benchmark",
                "mlr-bench",
                "--request",
                str(request),
                "--acquisition-root",
                str(acquisition),
                "--program",
                str(program),
                "--workspace-root",
                str(tmp_path),
                "--output",
                str(plan_path),
            ]
        )
        == 0
    )
    assert (
        bridge_main(
            [
                "materialize",
                "--plan",
                str(plan_path),
                "--workspace-root",
                str(tmp_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert (
        bridge_main(
            [
                "status",
                "--plan",
                str(plan_path),
                "--workspace-root",
                str(tmp_path),
                "--package-root",
                str(output),
                "--require-admission-ready",
            ]
        )
        == 1
    )
    assert '"formal_task_ready": false' in capsys.readouterr().out

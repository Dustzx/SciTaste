from __future__ import annotations

import json
from pathlib import Path

from scitaste.benchmark.study import load_study_protocol
from scitaste.benchmark.study_execution import (
    CommandLauncherConfig,
    LauncherResult,
    LauncherUsage,
    MatchedStudyRunner,
    ProcessResult,
    StudyLaunchConfig,
)
from scitaste.benchmark.study_models import (
    CellStatus,
    EvidenceClass,
    StudyOutcome,
    StudyResults,
    SystemCondition,
)
from scitaste.benchmark.study_status import (
    discover_study_result_paths,
    inspect_study_matrix,
    save_study_matrix_status,
)

PROTOCOL_PATH = "configs/experiments/matched_budget_local_pilot_v1.yaml"


def _outcome(*, evidence_sufficiency: float = 0.8) -> StudyOutcome:
    return StudyOutcome(
        useful_results=1,
        proposed_ideas=2,
        valid_ideas=1,
        pilots=1,
        discarded_ideas=1,
        unproductive_experiments=0,
        total_experiments=1,
        gpu_hours_before_useful_signal=0.05,
        pivots=1,
        correct_pivots=1,
        evidence_sufficiency=evidence_sufficiency,
        reviewer_concerns_opened=1,
        reviewer_concerns_closed=1,
        total_claims=2,
        unsupported_claims=0,
    )


class _SuccessfulProcess:
    def __init__(self, *, evidence_sufficiency: float = 0.8) -> None:
        self.evidence_sufficiency = evidence_sufficiency

    def run(self, command, *, cwd, environment, **kwargs):
        del command, kwargs
        artifact = Path(cwd) / "paper.md"
        artifact.write_text("integrity-bound paper", encoding="utf-8")
        result = LauncherResult(
            status=CellStatus.SUCCEEDED,
            evidence_class=EvidenceClass.REAL,
            usage=LauncherUsage(
                experiments=1,
                api_cost_usd=0,
                search_queries=0,
                llm_tokens=1200,
            ),
            outcome=_outcome(evidence_sufficiency=self.evidence_sufficiency),
            artifact_paths=["paper.md"],
        )
        Path(environment["SCITASTE_STUDY_CELL_RESULT"]).write_text(
            result.model_dump_json(), encoding="utf-8"
        )
        return ProcessResult(returncode=0)


def _run_one_cell(root: Path, *, evidence_sufficiency: float = 0.8):
    protocol = load_study_protocol(PROTOCOL_PATH)
    times = iter([10.0, 70.0])
    runner = MatchedStudyRunner(
        protocol,
        StudyLaunchConfig(
            launchers={SystemCondition.AUTORESEARCHCLAW: CommandLauncherConfig(command=["adapter"])}
        ),
        output_dir=root,
        process_runner=_SuccessfulProcess(evidence_sufficiency=evidence_sufficiency),
        clock=lambda: next(times),
    )
    runner.run(
        task_ids=["diagnosis-friendly-v1"],
        conditions=[SystemCondition.AUTORESEARCHCLAW],
        max_cells=1,
    )
    return protocol, runner.plan.cells[0]


def test_status_counts_only_exact_integrity_verified_results(tmp_path) -> None:
    run_root = tmp_path / "projects/example/runs/one/study"
    protocol, completed_cell = _run_one_cell(run_root)
    foreign = tmp_path / "projects/foreign/runs/one/study/study_results.json"
    foreign.parent.mkdir(parents=True)
    foreign.write_text(
        StudyResults(
            protocol_sha256="a" * 64,
            records=[],
            expert_reviews=[],
        ).model_dump_json(),
        encoding="utf-8",
    )

    paths = discover_study_result_paths(tmp_path)
    status = inspect_study_matrix(protocol, paths)

    assert status.planned_cells == 16
    assert status.integrity_verified_records == status.succeeded_cells == 1
    assert status.failed_cells == 0
    assert status.missing_cells == 15
    assert status.compatible_sources == status.foreign_sources == 1
    assert status.invalid_sources == 0
    assert completed_cell.cell_id not in status.next_execution_batch
    assert len(status.next_execution_batch) == 3
    next_cells = {cell.cell_id: cell for cell in status.cells}
    assert {next_cells[cell_id].condition for cell_id in status.next_execution_batch} == {
        "knowledge_rag",
        "taste_library",
        "full_scitaste",
    }


def test_status_excludes_a_source_after_evidence_tampering(tmp_path) -> None:
    run_root = tmp_path / "run"
    protocol, completed_cell = _run_one_cell(run_root)
    (run_root / "cells" / completed_cell.cell_id / "paper.md").write_text(
        "tampered paper", encoding="utf-8"
    )

    status = inspect_study_matrix(protocol, [run_root / "study_results.json"])

    assert status.integrity_verified_records == 0
    assert status.missing_cells == 16
    assert status.sources[0].integrity == "failed"
    assert "evidence hash mismatch" in status.sources[0].violations[0]
    assert "1 compatible result sources failed integrity verification" in status.blockers


def test_status_excludes_conflicting_verified_records(tmp_path) -> None:
    protocol, completed_cell = _run_one_cell(tmp_path / "first", evidence_sufficiency=0.8)
    _run_one_cell(tmp_path / "second", evidence_sufficiency=0.9)

    status = inspect_study_matrix(
        protocol,
        [
            tmp_path / "first/study_results.json",
            tmp_path / "second/study_results.json",
        ],
    )

    assert status.integrity_verified_records == 0
    assert status.missing_cells == 16
    assert any(completed_cell.cell_id in blocker for blocker in status.blockers)


def test_status_report_is_self_hashed_and_cli_safe_to_serialize(tmp_path) -> None:
    protocol = load_study_protocol(PROTOCOL_PATH)
    status = inspect_study_matrix(protocol, [])

    path = save_study_matrix_status(status, tmp_path / "status/status.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["status_sha256"] == status.sha256
    assert payload["planned_cells"] == 16
    assert payload["next_execution_batch"]

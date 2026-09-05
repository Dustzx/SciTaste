from __future__ import annotations

import fcntl
import hashlib
import json
import subprocess

import pytest

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
    SystemCondition,
)

PILOT_PROTOCOL = "configs/experiments/matched_budget_local_pilot_v1.yaml"


def outcome() -> StudyOutcome:
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
        evidence_sufficiency=0.8,
        reviewer_concerns_opened=1,
        reviewer_concerns_closed=1,
        total_claims=2,
        unsupported_claims=0,
    )


def launch_config(*, pass_environment=None) -> StudyLaunchConfig:
    return StudyLaunchConfig(
        launchers={
            SystemCondition.AUTORESEARCHCLAW: CommandLauncherConfig(
                command=["adapter", "--request", "{cell_request}", "--seed", "{seed}"],
                gpu_count=1,
                timeout_seconds=9999,
                pass_environment=pass_environment or [],
            )
        }
    )


class SuccessfulRunner:
    def __init__(self, *, artifact_path="paper.md") -> None:
        self.artifact_path = artifact_path
        self.calls = []

    def run(
        self,
        command,
        *,
        cwd,
        environment,
        stdout_path,
        stderr_path,
        timeout_seconds,
    ) -> ProcessResult:
        self.calls.append(
            {
                "command": command,
                "cwd": cwd,
                "environment": environment,
                "timeout_seconds": timeout_seconds,
            }
        )
        request = json.loads(open(environment["SCITASTE_STUDY_CELL_REQUEST"]).read())
        assert request["base_model"] == "Qwen/Qwen3-VL-4B-Instruct"
        if self.artifact_path == "paper.md":
            (cwd / self.artifact_path).write_text("real artifact", encoding="utf-8")
        result = LauncherResult(
            status=CellStatus.SUCCEEDED,
            evidence_class=EvidenceClass.REAL,
            usage=LauncherUsage(
                experiments=1,
                api_cost_usd=0,
                search_queries=0,
                llm_tokens=1200,
            ),
            outcome=outcome(),
            artifact_paths=[self.artifact_path],
        )
        open(environment["SCITASTE_STUDY_CELL_RESULT"], "w").write(result.model_dump_json())
        return ProcessResult(returncode=0)


class TimeoutRunner:
    def run(self, command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout_seconds"])


class NeverRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, command, **kwargs):
        self.calls += 1
        return ProcessResult(returncode=0)


class FailThenSucceedRunner(SuccessfulRunner):
    def run(self, command, **kwargs):
        if not self.calls:
            self.calls.append({"command": command})
            return ProcessResult(returncode=2)
        return super().run(command, **kwargs)


def clock(*values):
    readings = iter(values)
    return lambda: next(readings)


def test_runner_hashes_outputs_measures_time_and_resumes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DO_NOT_PASS_TO_CELL", "secret")
    protocol = load_study_protocol(PILOT_PROTOCOL)
    process = SuccessfulRunner()
    runner = MatchedStudyRunner(
        protocol,
        launch_config(),
        output_dir=tmp_path,
        process_runner=process,
        clock=clock(10, 370),
    )

    first = runner.run(
        task_ids=["diagnosis-friendly-v1"],
        conditions=[SystemCondition.AUTORESEARCHCLAW],
    )
    second = runner.run(
        task_ids=["diagnosis-friendly-v1"],
        conditions=[SystemCondition.AUTORESEARCHCLAW],
    )

    assert first.executed_cells == first.succeeded_cells == 1
    assert second.executed_cells == 0
    assert second.resumed_cells == 1
    assert len(process.calls) == 1
    assert process.calls[0]["timeout_seconds"] == 1800
    assert "DO_NOT_PASS_TO_CELL" not in process.calls[0]["environment"]
    results = json.loads((tmp_path / "study_results.json").read_text())
    record = results["records"][0]
    assert record["usage"]["wall_time_hours"] == 0.1
    assert record["usage"]["gpu_hours"] == 0.1
    assert record["usage"]["llm_tokens"] == 1200
    assert record["artifacts"][0]["sha256"] == hashlib.sha256(b"real artifact").hexdigest()


def test_dry_run_does_not_create_output(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)
    runner = MatchedStudyRunner(protocol, launch_config(), output_dir=tmp_path)

    summary = runner.run(
        task_ids=["diagnosis-friendly-v1"],
        conditions=[SystemCondition.AUTORESEARCHCLAW],
        dry_run=True,
    )

    assert summary.selected_cells == 1
    assert summary.launches[0].command[-1] == "7"
    assert list(tmp_path.iterdir()) == []


def test_formal_protocol_is_execution_ready_after_assets_are_frozen(tmp_path) -> None:
    protocol = load_study_protocol("configs/experiments/matched_budget_study_v1.yaml")
    config = StudyLaunchConfig(
        launchers={
            condition: CommandLauncherConfig(command=["adapter", "{cell_request}"])
            for condition in (
                SystemCondition.AUTORESEARCHCLAW,
                SystemCondition.KNOWLEDGE_RAG,
                SystemCondition.TASTE_LIBRARY,
                SystemCondition.FULL_SCITASTE,
            )
        }
    )

    summary = MatchedStudyRunner(protocol, config, output_dir=tmp_path).run(dry_run=True)

    assert summary.selected_cells == 48


def test_missing_launcher_is_rejected(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)

    with pytest.raises(ValueError, match="missing enabled conditions"):
        MatchedStudyRunner(protocol, launch_config(), output_dir=tmp_path).run(
            task_ids=["diagnosis-friendly-v1"],
            conditions=[SystemCondition.FULL_SCITASTE],
            dry_run=True,
        )


def test_timeout_is_an_honest_failed_record(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)
    runner = MatchedStudyRunner(
        protocol,
        launch_config(),
        output_dir=tmp_path,
        process_runner=TimeoutRunner(),
        clock=clock(5, 15),
    )

    summary = runner.run(max_cells=1)

    assert summary.failed_cells == 1
    results = json.loads((tmp_path / "study_results.json").read_text())
    assert results["records"][0]["status"] == "failed"
    assert "timed out" in results["records"][0]["error"]
    assert results["records"][0]["outcome"] is None


def test_failed_retry_accumulates_runner_owned_time(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)
    process = FailThenSucceedRunner()
    runner = MatchedStudyRunner(
        protocol,
        launch_config(),
        output_dir=tmp_path,
        process_runner=process,
        clock=clock(10, 370, 500, 680),
    )

    first = runner.run(max_cells=1)
    second = runner.run(max_cells=1)

    assert first.failed_cells == 1
    assert second.succeeded_cells == 1
    results = json.loads((tmp_path / "study_results.json").read_text())
    assert results["records"][0]["usage"]["wall_time_hours"] == pytest.approx(0.15)
    assert results["records"][0]["usage"]["gpu_hours"] == pytest.approx(0.15)
    archived = tmp_path / "cells" / results["records"][0]["cell_id"] / "failed_attempts"
    assert (archived / "attempt-001/execution_record.json").is_file()
    assert (archived / "attempt-001/cell_checkpoint.json").is_file()
    assert (
        json.loads((archived / "attempt-001/execution_record.json").read_text())["status"]
        == "failed"
    )


def test_resume_rejects_changed_artifact_bytes(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)
    process = SuccessfulRunner()
    runner = MatchedStudyRunner(
        protocol,
        launch_config(),
        output_dir=tmp_path,
        process_runner=process,
        clock=clock(0, 1),
    )
    first = runner.run(max_cells=1)
    artifact = tmp_path / "cells" / first.launches[0].cell_id / "paper.md"
    artifact.write_text("tampered artifact", encoding="utf-8")

    with pytest.raises(ValueError, match="evidence hash mismatch"):
        runner.run(max_cells=1)

    assert len(process.calls) == 1


def test_resume_rejects_coordinated_record_tampering(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)
    runner = MatchedStudyRunner(
        protocol,
        launch_config(),
        output_dir=tmp_path,
        process_runner=SuccessfulRunner(),
        clock=clock(0, 1),
    )
    first = runner.run(max_cells=1)
    cell_id = first.launches[0].cell_id
    aggregate_path = tmp_path / "study_results.json"
    record_path = tmp_path / "cells" / cell_id / "execution_record.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    aggregate["records"][0]["outcome"]["evidence_sufficiency"] = 0.99
    record["outcome"]["evidence_sufficiency"] = 0.99
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="checkpoint identity mismatch"):
        runner.run(max_cells=1)


def test_resume_rejects_changed_launcher_configuration(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)
    MatchedStudyRunner(
        protocol,
        launch_config(),
        output_dir=tmp_path,
        process_runner=SuccessfulRunner(),
        clock=clock(0, 1),
    ).run(max_cells=1)
    changed = StudyLaunchConfig(
        launchers={
            SystemCondition.AUTORESEARCHCLAW: CommandLauncherConfig(
                command=["different-adapter", "{cell_request}"],
            )
        }
    )

    with pytest.raises(ValueError, match="run identity"):
        MatchedStudyRunner(protocol, changed, output_dir=tmp_path).run(max_cells=1)


def test_concurrent_runner_for_same_output_fails_without_mutation(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)
    tmp_path.mkdir(exist_ok=True)
    lock_path = tmp_path / ".study.lock"
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="another study runner"):
            MatchedStudyRunner(protocol, launch_config(), output_dir=tmp_path).run(max_cells=1)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    assert list(tmp_path.iterdir()) == [lock_path]


def test_legacy_nonempty_output_is_not_silently_blessed(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)
    (tmp_path / "study_results.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="no integrity manifest"):
        MatchedStudyRunner(protocol, launch_config(), output_dir=tmp_path).run(max_cells=1)


def test_artifact_cannot_escape_cell_directory(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)
    process = SuccessfulRunner(artifact_path="../outside.md")
    runner = MatchedStudyRunner(
        protocol,
        launch_config(),
        output_dir=tmp_path,
        process_runner=process,
        clock=clock(0, 1),
    )

    summary = runner.run(max_cells=1)

    assert summary.failed_cells == 1
    results = json.loads((tmp_path / "study_results.json").read_text())
    assert "escapes its cell directory" in results["records"][0]["error"]


def test_missing_explicit_environment_becomes_failed_record(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)
    process = NeverRunner()
    runner = MatchedStudyRunner(
        protocol,
        launch_config(pass_environment=["DEFINITELY_MISSING_SCITASTE_KEY"]),
        output_dir=tmp_path,
        process_runner=process,
    )

    summary = runner.run(max_cells=1)

    assert summary.failed_cells == 1
    assert process.calls == 0
    results = json.loads((tmp_path / "study_results.json").read_text())
    assert "required environment variables are missing" in results["records"][0]["error"]


def test_launcher_schema_requires_complete_success_counters() -> None:
    with pytest.raises(ValueError, match="require counters"):
        LauncherResult(
            status=CellStatus.SUCCEEDED,
            evidence_class=EvidenceClass.REAL,
            usage=LauncherUsage(experiments=1),
            outcome=outcome(),
            artifact_paths=["paper.md"],
        )


def test_invalid_selection_and_command_are_rejected(tmp_path) -> None:
    protocol = load_study_protocol(PILOT_PROTOCOL)
    runner = MatchedStudyRunner(protocol, launch_config(), output_dir=tmp_path)

    with pytest.raises(ValueError, match="unknown study tasks"):
        runner.run(task_ids=["missing"], dry_run=True)
    with pytest.raises(ValueError, match="not enabled"):
        runner.run(conditions=[SystemCondition.SIBYL], dry_run=True)
    with pytest.raises(ValueError, match="max_cells"):
        runner.run(max_cells=0, dry_run=True)

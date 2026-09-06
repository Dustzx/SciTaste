from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.executor import (
    ExecutionStatus,
    MetricDirection,
    NativeExecutionRecord,
    NativeExperimentDefinition,
    NativeExperimentLimits,
    NativeExperimentRunner,
    NativeMeasurementEnvelope,
    SciTasteNativeExecutor,
    parse_measurements,
)
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState


def _state() -> ResearchState:
    return ResearchState(
        project_id="native-sandbox-test",
        research_direction="Execute a measured experiment",
        target_domain="autonomous-research",
    )


def _definition(source: Path, **limit_updates: object) -> NativeExperimentDefinition:
    limits = NativeExperimentLimits.model_validate(
        {
            **NativeExperimentLimits().model_dump(),
            **limit_updates,
        }
    )
    return NativeExperimentDefinition(
        schema_version="1.0",
        experiment_id="sandbox-test",
        source_path=source,
        primary_metric="score_delta",
        metric_direction=MetricDirection.MAXIMIZE,
        support_threshold=0.0,
        limits=limits,
    )


def _action() -> ResearchAction:
    return ResearchAction(
        action_id="run-sandbox-test",
        type=MetaAction.COLLECT_EVIDENCE,
        description="Run the registered isolated experiment",
        parameters={"experiment_id": "sandbox-test"},
    )


def test_native_sandbox_blocks_host_files_and_network_and_derives_metrics(tmp_path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    secret = tmp_path / "host-secret.txt"
    secret.write_text("must not be visible", encoding="utf-8")
    source = root / "experiment.py"
    source.write_text(
        "\n".join(
            [
                "import json, pathlib, socket",
                f"host_blocked = not pathlib.Path({str(secret)!r}).exists()",
                "write_blocked = False",
                "try:",
                "    pathlib.Path('/work/forbidden.txt').write_text('x')",
                "except OSError:",
                "    write_blocked = True",
                "network_blocked = False",
                "probe = socket.socket()",
                "probe.settimeout(0.2)",
                "try:",
                "    probe.connect(('1.1.1.1', 53))",
                "except OSError:",
                "    network_blocked = True",
                "finally:",
                "    probe.close()",
                "payload = {'schema_version': '1.0', 'measurements': [",
                "    {'replicate_id': 'seed-7', 'metrics': {'score_delta': 0.2, "
                "'host_blocked': float(host_blocked), 'write_blocked': float(write_blocked), "
                "'network_blocked': "
                "float(network_blocked)}},",
                "    {'replicate_id': 'seed-19', 'metrics': {'score_delta': 0.4, "
                "'host_blocked': float(host_blocked), 'write_blocked': float(write_blocked), "
                "'network_blocked': "
                "float(network_blocked)}}]}",
                "print('SCITASTE_MEASUREMENTS_JSON=' + json.dumps(payload))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    runner = NativeExperimentRunner(_definition(source))
    if not runner.availability().available:
        pytest.skip("bubblewrap isolation is unavailable on this host")
    executor = SciTasteNativeExecutor(
        workspace=root / "native_execution",
        artifact_root=root,
        experiment_runner=runner,
    )

    result = executor.run_experiment(_state(), _action())

    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.data["result_basis"] == "sandbox-measured-replicates"
    assert result.data["metrics"]["score_delta"] == pytest.approx(0.3)
    assert result.data["metrics"]["host_blocked"] == 1.0
    assert result.data["metrics"]["write_blocked"] == 1.0
    assert result.data["metrics"]["network_blocked"] == 1.0
    assert result.data["replicate_ids"] == ["seed-7", "seed-19"]
    assert result.data["reproducible"] is True
    assert result.data["network_access"] is False
    execution_path = next(
        root / item for item in result.artifacts if item.endswith("execution.json")
    )
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    assert execution["returncode"] == 0
    assert execution["host_filesystem"] == "not-mounted"
    assert execution["gpu_devices"] == "not-mounted"
    record_path = root / result.data["execution_record"]
    record = NativeExecutionRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
    assert list(record.input_sha256) == ["experiment.py"]
    assert set(record.artifact_sha256) == set(result.artifacts)
    assert executor.store is not None
    assert executor.store.verify().record_count == 1
    source.write_text("print('changed')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        executor.store.verify()


def test_native_sandbox_unavailability_fails_with_evidence_instead_of_falling_back(
    tmp_path,
) -> None:
    root = tmp_path / "run"
    root.mkdir()
    source = root / "experiment.py"
    source.write_text("raise AssertionError('must not execute')\n", encoding="utf-8")
    runner = NativeExperimentRunner(_definition(source), bubblewrap=root / "missing-bwrap")
    executor = SciTasteNativeExecutor(
        workspace=root / "native_execution",
        artifact_root=root,
        experiment_runner=runner,
    )

    result = executor.execute(_state(), _action())

    assert result.status == ExecutionStatus.FAILED
    assert "isolation unavailable" in (result.error or "")
    assert result.data["result_basis"] == "sandbox-failure"
    assert result.data["execution_record_sha256"]
    assert any(locator.endswith("execution.json") for locator in result.artifacts)


def test_native_sandbox_enforces_wall_time_and_output_bounds(tmp_path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    source = root / "experiment.py"
    source.write_text("while True:\n    pass\n", encoding="utf-8")
    runner = NativeExperimentRunner(_definition(source, timeout_seconds=0.1))
    if not runner.availability().available:
        pytest.skip("bubblewrap isolation is unavailable on this host")
    executor = SciTasteNativeExecutor(
        workspace=root / "native_execution",
        artifact_root=root,
        experiment_runner=runner,
    )

    result = executor.execute(_state(), _action())

    assert result.status == ExecutionStatus.FAILED
    assert "wall-time limit" in (result.error or "")
    execution_path = next(
        root / item for item in result.artifacts if item.endswith("execution.json")
    )
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    assert execution["timed_out"] is True
    assert execution["stdout_bytes"] <= runner.definition.limits.max_output_bytes
    assert execution["stderr_bytes"] <= runner.definition.limits.max_output_bytes


def test_native_sandbox_caps_stdout_before_parsing(tmp_path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    source = root / "experiment.py"
    source.write_text("print('x' * 10000)\n", encoding="utf-8")
    runner = NativeExperimentRunner(_definition(source, max_output_bytes=1024))
    if not runner.availability().available:
        pytest.skip("bubblewrap isolation is unavailable on this host")
    executor = SciTasteNativeExecutor(
        workspace=root / "native_execution",
        artifact_root=root,
        experiment_runner=runner,
    )

    result = executor.execute(_state(), _action())

    assert result.status == ExecutionStatus.FAILED
    stdout_path = next(root / item for item in result.artifacts if item.endswith("stdout.txt"))
    assert stdout_path.stat().st_size <= 1024
    assert result.data["result_basis"] == "sandbox-failure"


def test_native_sandbox_recognizes_stable_measured_contradiction(tmp_path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    source = root / "experiment.py"
    source.write_text(
        "import json\n"
        "payload={'schema_version':'1.0','measurements':["
        "{'replicate_id':'one','metrics':{'score_delta':-0.1}},"
        "{'replicate_id':'two','metrics':{'score_delta':-0.2}}]}\n"
        "print('SCITASTE_MEASUREMENTS_JSON='+json.dumps(payload))\n",
        encoding="utf-8",
    )
    runner = NativeExperimentRunner(_definition(source))
    if not runner.availability().available:
        pytest.skip("bubblewrap isolation is unavailable on this host")
    executor = SciTasteNativeExecutor(
        workspace=root / "native_execution",
        artifact_root=root,
        experiment_runner=runner,
    )

    result = executor.execute(_state(), _action())

    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.data["metric_assessment"] == "contradicts"
    assert result.data["stability"] == 1.0
    assert result.data["reproducible"] is True


def test_measurement_parser_rejects_aggregate_only_or_inconsistent_evidence() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        parse_measurements(b'{"metrics":{"score_delta":1}}\n')

    payload = {
        "schema_version": "1.0",
        "measurements": [
            {"replicate_id": "one", "metrics": {"score_delta": 0.1}},
            {"replicate_id": "two", "metrics": {"different": 0.1}},
        ],
    }
    with pytest.raises(ValueError, match="invalid SCITASTE_MEASUREMENTS_JSON"):
        parse_measurements(("SCITASTE_MEASUREMENTS_JSON=" + json.dumps(payload) + "\n").encode())

    valid = NativeMeasurementEnvelope.model_validate(
        {
            "schema_version": "1.0",
            "measurements": [
                {"replicate_id": "one", "metrics": {"score_delta": 0.1}},
            ],
        }
    )
    parsed = parse_measurements(
        (
            "human-readable line\nSCITASTE_MEASUREMENTS_JSON=" + valid.model_dump_json() + "\n"
        ).encode()
    )
    assert parsed == valid

    with pytest.raises(ValueError, match="invalid SCITASTE_MEASUREMENTS_JSON"):
        parse_measurements(
            b'SCITASTE_MEASUREMENTS_JSON={"schema_version":"1.0",'
            b'"schema_version":"1.0","measurements":[]}\n'
        )

    with pytest.raises(ValueError, match="invalid SCITASTE_MEASUREMENTS_JSON"):
        parse_measurements(
            b'SCITASTE_MEASUREMENTS_JSON={"schema_version":"1.0","measurements":'
            b'[{"replicate_id":"one","metrics":{"score_delta":true}}]}\n'
        )

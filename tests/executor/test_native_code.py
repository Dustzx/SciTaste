from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.executor.native_code import (
    NativeCodeAdmissionError,
    NativeCodeContextRecord,
    NativeCodeProducer,
    inspect_native_code_proposal,
    load_native_code_context_record,
    prepare_native_code_experiment,
)


def _safe_source(metric: str = "score_delta") -> str:
    return (
        "import json\n"
        "rows = [\n"
        f"    {{'replicate_id': 'one', 'metrics': {{{metric!r}: 0.2}}}},\n"
        f"    {{'replicate_id': 'two', 'metrics': {{{metric!r}: 0.4}}}},\n"
        "]\n"
        "payload = {'schema_version': '1.0', 'measurements': rows}\n"
        "print('SCITASTE_MEASUREMENTS_JSON=' + json.dumps(payload))\n"
    )


def _proposal(
    root: Path,
    source_text: str,
    *,
    producer: dict[str, object] | None = None,
    policy: dict[str, object] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "candidate.py"
    source.write_text(source_text, encoding="utf-8")
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "proposal_id": "candidate-v1",
        "source_path": source.name,
        "rationale": "Measure the registered score delta over two replicates.",
        "expected_metrics": ["score_delta"],
        "producer": producer
        or {
            "schema_version": "1.0",
            "mode": "registered",
            "producer_id": "fixture-author",
        },
        "experiment": {
            "experiment_id": "sandbox-test",
            "primary_metric": "score_delta",
            "metric_direction": "maximize",
            "support_threshold": 0.0,
            "limits": {
                "timeout_seconds": 5.0,
                "cpu_seconds": 3,
                "max_memory_mb": 128,
                "max_output_bytes": 8192,
                "max_open_files": 16,
                "max_processes": 4,
            },
        },
    }
    if policy is not None:
        payload["policy"] = policy
    config = root / "proposal.yaml"
    config.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return config


def test_inspection_accepts_bounded_source_without_mutating_storage(tmp_path: Path) -> None:
    config = _proposal(tmp_path / "input", _safe_source())

    inspected = inspect_native_code_proposal(config)

    assert inspected.admission.decision == "accepted"
    assert inspected.admission.violations == ()
    assert inspected.admission.imports == ("json",)
    assert inspected.admission.runtime_isolation_required is True
    assert inspected.proposal.authority == "proposal-only"
    assert inspected.proposal.source_sha256 == inspected.admission.source_sha256
    assert len(inspected.binding_sha256) == 64
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize(
    ("source", "violation"),
    [
        (_safe_source() + "import socket\n", "import-not-allowed"),
        (_safe_source() + "open('x', 'w')\n", "blocked-call"),
        (_safe_source() + "value = object().__class__\n", "dunder-access"),
        (_safe_source() + "import random\nvalue = random._os\n", "private-access"),
        (_safe_source() + "from random import _os\n", "private-import"),
        (_safe_source() + "value = eval('1 + 1')\n", "blocked-call"),
        ("def broken(:\n    pass\n", "syntax-error"),
        ("", "measurement-marker"),
        ("import json\nprint(json.dumps({}))\n", "measurement-marker"),
        (
            "import json\nprint('SCITASTE_MEASUREMENTS_JSON=' + json.dumps({}))\n",
            "expected-metric",
        ),
    ],
)
def test_static_admission_rejects_unsafe_or_unmeasurable_source(
    tmp_path: Path,
    source: str,
    violation: str,
) -> None:
    config = _proposal(tmp_path / violation, source)

    inspected = inspect_native_code_proposal(config)

    assert inspected.admission.decision == "rejected"
    assert violation in {item.code for item in inspected.admission.violations}
    assert inspected.admission.admitted_source_locator is None


def test_model_producer_requires_content_bound_call_provenance() -> None:
    with pytest.raises(ValidationError, match="request, and response hashes"):
        NativeCodeProducer(
            mode="model",
            producer_id="glm-proposer",
            provider="zhipu",
            model="glm-5.3-flash",
        )

    producer = NativeCodeProducer(
        mode="model",
        producer_id="glm-proposer",
        provider="zhipu",
        model="glm-5.3-flash",
        request_sha256="1" * 64,
        response_sha256="2" * 64,
    )

    assert producer.mode == "model"
    assert producer.request_sha256 == "1" * 64


def test_proposal_policy_can_restrict_but_not_expand_platform_imports(tmp_path: Path) -> None:
    unsafe_policy = {
        "schema_version": "1.0",
        "policy_id": "self-approved-os",
        "allowed_imports": ["json", "os"],
    }
    config = _proposal(tmp_path / "input", _safe_source(), policy=unsafe_policy)

    with pytest.raises(ValidationError, match="cannot expand the platform import ceiling"):
        inspect_native_code_proposal(config)


def test_accepted_proposal_is_atomically_materialized_and_replayed(tmp_path: Path) -> None:
    config = _proposal(tmp_path / "input", _safe_source())
    run_root = tmp_path / "outputs/projects/example/runs/run-1"
    run_root.mkdir(parents=True)

    first = prepare_native_code_experiment(config, run_root=run_root)
    second = prepare_native_code_experiment(config, run_root=run_root)

    context_root = run_root / "native_execution/context/code"
    assert first == second
    assert first.source_path == context_root / "admitted/experiment.py"
    assert first.source_path.read_text(encoding="utf-8") == _safe_source()
    assert (context_root / "proposed.py").read_bytes() == first.source_path.read_bytes()
    assert {item.name for item in context_root.iterdir()} == {
        "ADMISSION.json",
        "CODE.json",
        "POLICY.json",
        "PROPOSAL.json",
        "admitted",
        "proposed.py",
    }
    record = load_native_code_context_record(run_root)
    assert record is not None
    assert record.decision == "accepted"
    assert record.binding_sha256
    assert (
        NativeCodeContextRecord.model_validate_json(
            (context_root / "CODE.json").read_text(encoding="utf-8")
        )
        == record
    )


def test_preflight_inspection_binds_materialized_bytes_across_external_drift(
    tmp_path: Path,
) -> None:
    original = _safe_source()
    config = _proposal(tmp_path / "input", original)
    inspected = inspect_native_code_proposal(config)
    (config.parent / "candidate.py").write_text("import socket\n", encoding="utf-8")
    run_root = tmp_path / "outputs/projects/example/runs/run-preflight"
    run_root.mkdir(parents=True)

    definition = prepare_native_code_experiment(
        config,
        run_root=run_root,
        inspection=inspected,
    )

    assert definition.source_path.read_text(encoding="utf-8") == original
    assert inspect_native_code_proposal(config).binding_sha256 != inspected.binding_sha256


def test_proposal_source_read_has_a_hard_platform_byte_ceiling(tmp_path: Path) -> None:
    config = _proposal(tmp_path / "input", "#" * 262_145)

    with pytest.raises(ValueError, match="262144-byte platform ceiling"):
        inspect_native_code_proposal(config)


def test_rejected_proposal_retains_evidence_but_never_creates_admitted_source(
    tmp_path: Path,
) -> None:
    config = _proposal(tmp_path / "input", _safe_source() + "import subprocess\n")
    run_root = tmp_path / "outputs/projects/example/runs/run-rejected"
    run_root.mkdir(parents=True)

    with pytest.raises(NativeCodeAdmissionError, match="import-not-allowed"):
        prepare_native_code_experiment(config, run_root=run_root)
    with pytest.raises(NativeCodeAdmissionError, match="import-not-allowed"):
        prepare_native_code_experiment(config, run_root=run_root)

    context_root = run_root / "native_execution/context/code"
    receipt = json.loads((context_root / "CODE.json").read_text(encoding="utf-8"))
    admission = json.loads((context_root / "ADMISSION.json").read_text(encoding="utf-8"))
    assert receipt["decision"] == "rejected"
    assert admission["decision"] == "rejected"
    assert not (context_root / "admitted").exists()
    assert (context_root / "proposed.py").is_file()


def test_materialized_context_rejects_external_or_owned_source_drift(tmp_path: Path) -> None:
    config = _proposal(tmp_path / "input", _safe_source())
    run_root = tmp_path / "outputs/projects/example/runs/run-drift"
    run_root.mkdir(parents=True)
    definition = prepare_native_code_experiment(config, run_root=run_root)

    definition.source_path.write_text(_safe_source() + "# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        prepare_native_code_experiment(config, run_root=run_root)

    definition.source_path.write_text(_safe_source(), encoding="utf-8")
    (config.parent / "candidate.py").write_text(_safe_source() + "# external\n", encoding="utf-8")
    with pytest.raises(ValueError, match="proposal changed"):
        prepare_native_code_experiment(config, run_root=run_root)


def test_source_and_config_symlinks_are_not_admitted(tmp_path: Path) -> None:
    config = _proposal(tmp_path / "input", _safe_source())
    real_source = config.parent / "candidate.py"
    source_copy = config.parent / "real.py"
    real_source.rename(source_copy)
    real_source.symlink_to(source_copy)

    with pytest.raises(ValueError, match="source must be a regular non-symlink"):
        inspect_native_code_proposal(config)

    real_source.unlink()
    real_source.write_text(_safe_source(), encoding="utf-8")
    linked_config = tmp_path / "proposal-link.yaml"
    linked_config.symlink_to(config)
    with pytest.raises(ValueError, match="config must be a regular non-symlink"):
        inspect_native_code_proposal(linked_config)

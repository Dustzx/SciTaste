from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from scitaste.benchmark.study_adapter import _parse_seed_evidence

ASSET = Path("configs/experiments/tasks/assets/diagnosis_factorial_v2.py")


def load_kernel() -> ModuleType:
    spec = importlib.util.spec_from_file_location("diagnosis_factorial_v2_test", ASSET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_kernel_is_deterministic_and_executes_full_grid() -> None:
    kernel = load_kernel()

    first = kernel.execute_benchmark(kernel.EXPECTED_CONTRACT)
    second = kernel.execute_benchmark(kernel.EXPECTED_CONTRACT)

    assert first == second
    assert first["diagnostics"]["packets_per_seed"] == 648
    assert first["diagnostics"]["generated_packets"] == 1944
    assert set(first["conditions"]) == set(kernel.EXPECTED_CONTRACT["conditions"])
    assert all(
        set(record["per_seed"]) == {"7", "19", "31"} for record in first["conditions"].values()
    )
    means = [record["mean"] for record in first["conditions"].values()]
    assert first["primary_metric"]["value"] == pytest.approx(sum(means) / len(means))
    assert first["diagnostics"]["factor_effects"]["majority_vote"]["contradiction_density"] > 0


def test_frozen_kernel_rejects_contract_drift() -> None:
    kernel = load_kernel()
    changed = {**kernel.EXPECTED_CONTRACT, "examples_per_cell": 11}

    with pytest.raises(ValueError, match="does not match"):
        kernel.execute_benchmark(changed)


def test_frozen_kernel_emits_adapter_readable_evidence(monkeypatch, capsys) -> None:
    kernel = load_kernel()
    reported: dict[str, float] = {}

    class FakeHarness:
        def __init__(self, *, time_budget: int):
            assert time_budget == 1200

        def report_metric(self, name: str, value: float) -> None:
            reported[name] = value

        def finalize(self) -> None:
            return None

    harness_module = ModuleType("experiment_harness")
    harness_module.ExperimentHarness = FakeHarness
    monkeypatch.setitem(sys.modules, "experiment_harness", harness_module)

    evidence = kernel.run_and_emit(kernel.EXPECTED_CONTRACT)
    stdout = capsys.readouterr().out
    per_seed, dispersion = _parse_seed_evidence(stdout, "balanced_accuracy")

    assert set(per_seed) == {"7", "19", "31"}
    assert set(dispersion) == set(kernel.EXPECTED_CONTRACT["conditions"])
    assert reported["balanced_accuracy"] == evidence["primary_metric"]["value"]
    assert stdout.splitlines()[-1].startswith("SCITASTE_EVIDENCE_JSON=")

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.resources import (
    ComputeResourceCatalog,
    ComputeResourceRuntime,
    ObservationStatus,
    ResourceKind,
    ResourceObservation,
    inspect_compute_resource_catalog,
    load_compute_resource_catalog,
)

CATALOG = Path("configs/resources/compute_catalog_v1.yaml")
OBSERVATIONS = Path("configs/resources/observations")


def test_tracked_catalog_defines_project_superordinate_api_and_gpu_resources() -> None:
    inspection = inspect_compute_resource_catalog(CATALOG)
    loaded = load_compute_resource_catalog(CATALOG)

    assert inspection.evidence_verified is True
    assert inspection.secret_values_loaded is False
    assert inspection.external_action_performed is False
    assert inspection.api_model_ids == ("deepseek-v41-flash", "zhipu-glm53-flash")
    assert inspection.gpu_host_ids == ("gpu-host-3090-2",)
    deepseek = loaded.catalog.resource("deepseek-v41-flash")
    assert deepseek.model_id == "deepseek-flash"
    assert deepseek.model_revision == "DeepSeek-V4.1-Flash"
    assert deepseek.pricing is not None
    assert deepseek.pricing.output_per_million == 1.2


def test_catalog_rejects_duplicate_identity_and_drifted_evidence(tmp_path: Path) -> None:
    payload = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    payload["resources"].append(payload["resources"][0])
    with pytest.raises(ValidationError, match="must be unique"):
        ComputeResourceCatalog.model_validate(payload)

    payload = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    payload["resources"][2]["baseline_inventory_sha256"] = "0" * 64
    candidate = tmp_path / "catalog.yaml"
    candidate.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    inspection = inspect_compute_resource_catalog(candidate)
    assert inspection.evidence_verified is False
    assert inspection.evidence_issues == ("gpu-host-3090-2:baseline_inventory_hash_mismatch",)

    symlink = tmp_path / "linked-catalog.yaml"
    symlink.symlink_to(CATALOG.resolve())
    with pytest.raises(ValueError, match="must not be a symlink"):
        load_compute_resource_catalog(symlink)


def test_owner_observations_cannot_claim_independent_verification() -> None:
    payload = yaml.safe_load(
        (OBSERVATIONS / "gpu_host_3090_2_storage_owner_20260912_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    payload["status"] = ObservationStatus.VERIFIED

    with pytest.raises(ValidationError, match="owner reports must retain reported status"):
        ResourceObservation.model_validate(payload)


def test_runtime_owns_global_observations_outside_project_trees(tmp_path: Path) -> None:
    runtime = ComputeResourceRuntime(tmp_path / "outputs")
    snapshot = runtime.initialize(CATALOG)
    for source in sorted(OBSERVATIONS.glob("*.yaml")):
        runtime.register_observation(CATALOG, source)

    status = runtime.status(CATALOG)
    by_id = {item.resource_id: item for item in status.resources}

    assert runtime.root == (tmp_path / "outputs" / "resources").resolve()
    assert snapshot.catalog_id == "scitaste-shared-compute-v1"
    assert status.secret_values_loaded is False
    assert status.remote_probe_performed is False
    assert status.workload_executed is False
    assert by_id["deepseek-v41-flash"].observation_count == 2
    assert by_id["deepseek-v41-flash"].latest_observation is not None
    assert by_id["deepseek-v41-flash"].latest_observation.status is ObservationStatus.VERIFIED
    gpu = by_id["gpu-host-3090-2"].latest_observation
    assert gpu is not None
    assert gpu.available_storage_gb_reported == 200.0
    assert gpu.status is ObservationStatus.REPORTED
    assert not (runtime.root / "projects").exists()


def test_runtime_rejects_cross_kind_observation(tmp_path: Path) -> None:
    runtime = ComputeResourceRuntime(tmp_path / "outputs")
    runtime.initialize(CATALOG)
    payload = yaml.safe_load(
        (OBSERVATIONS / "gpu_host_3090_2_storage_owner_20260912_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    payload["resource_kind"] = ResourceKind.API_MODEL.value
    payload["available_storage_gb_reported"] = None
    payload["observed_device_count"] = None
    payload["observed_device_name"] = None
    payload["requested_model_id"] = "deepseek-flash"
    candidate = tmp_path / "wrong-kind.yaml"
    candidate.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="kind does not match"):
        runtime.register_observation(CATALOG, candidate)


def test_resource_cli_initializes_registers_and_reports_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outputs = tmp_path / "outputs"
    common = ["--catalog", str(CATALOG), "--outputs-root", str(outputs)]

    assert main(["resource", "init", *common, "--evidence-root", "."]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "resource",
                "observe",
                *common,
                "--observation",
                str(OBSERVATIONS / "gpu_host_3090_2_storage_owner_20260912_v1.yaml"),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["resource", "status", *common]) == 0

    status = json.loads(capsys.readouterr().out)
    gpu = next(item for item in status["resources"] if item["resource_id"] == "gpu-host-3090-2")
    assert gpu["latest_observation"]["available_storage_gb_reported"] == 200.0

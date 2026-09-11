from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation import load_gpu_host_inventory
from scitaste.resources import (
    ComputeResourceCatalog,
    ComputeResourceRuntime,
    ObservationStatus,
    ResourceKind,
    ResourceObservation,
    inspect_compute_resource_catalog,
    inspect_project_resource_binding,
    load_compute_resource_catalog,
    load_resource_observation,
)

CATALOG = Path("configs/resources/compute_catalog_v1.yaml")
CATALOG_V2 = Path("configs/resources/compute_catalog_v2.yaml")
OBSERVATIONS = Path("configs/resources/observations")
PROJECT_BINDING = Path("configs/resources/projects/scitaste_self_development.yaml")
LOCAL_GPU_INVENTORY = Path("docs/research/data/gpu_host_local_3090_inventory_v1.yaml")
LOCAL_CHECKPOINT_OBSERVATION = Path(
    "configs/resources/observations/v2/qwen3vl2b_local_20260912_v1.yaml"
)


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


def test_explicit_catalog_hash_binds_api_gpu_and_checkpoint_manifests() -> None:
    inspection = inspect_compute_resource_catalog(CATALOG_V2)
    loaded = load_compute_resource_catalog(CATALOG_V2)

    assert inspection.evidence_verified is True
    assert inspection.api_model_ids == (
        "deepseek-v41-flash",
        "zhipu-glm53-flash",
        "bailian-qwen38-max",
    )
    assert inspection.gpu_host_ids == ("gpu-host-local-3090", "gpu-host-3090-2")
    assert inspection.model_checkpoint_ids == ("qwen3-vl-2b-local-47f9c0e0",)
    assert len(inspection.component_file_sha256) == 6
    checkpoint = loaded.catalog.resource("qwen3-vl-2b-local-47f9c0e0")
    assert checkpoint.checkpoint_sha256 == (
        "47f9c0e0e48a54c74fb0b2b0ffa7a182fed381d5ed49a0200872038d1c286d34"
    )

    inventory = load_gpu_host_inventory(LOCAL_GPU_INVENTORY).inventory
    assert inventory.host_alias == "local-3090"
    assert len(inventory.devices) == 1
    assert inventory.devices[0].memory_free_mb == 22_947
    assert inventory.root_storage.available_bytes == 155_972_894_720
    assert inventory.checkpoint.destination_present is True
    assert inventory.checkpoint.observed_sha256 == checkpoint.checkpoint_sha256
    checkpoint_observation = load_resource_observation(LOCAL_CHECKPOINT_OBSERVATION)
    assert checkpoint_observation.resource_kind is ResourceKind.MODEL_CHECKPOINT
    assert checkpoint_observation.observed_checkpoint_sha256 == checkpoint.checkpoint_sha256


def test_self_development_binding_explicitly_selects_every_resource_class() -> None:
    inspection = inspect_project_resource_binding(CATALOG_V2, PROJECT_BINDING)

    assert inspection.valid is True
    assert inspection.issues == ()
    assert inspection.api_resource_ids == (
        "deepseek-v41-flash",
        "zhipu-glm53-flash",
        "bailian-qwen38-max",
    )
    assert inspection.gpu_resource_ids == ("gpu-host-local-3090", "gpu-host-3090-2")
    assert inspection.checkpoint_resource_ids == ("qwen3-vl-2b-local-47f9c0e0",)


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


def test_hash_index_rejects_a_modified_resource_manifest(tmp_path: Path) -> None:
    definition = tmp_path / "deepseek.yaml"
    definition.write_bytes(Path("configs/resources/api/deepseek_v41_flash.yaml").read_bytes())
    expected_sha256 = hashlib.sha256(definition.read_bytes()).hexdigest()
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.1",
                "catalog_id": "tamper-test-catalog",
                "resource_refs": [
                    {
                        "resource_id": "deepseek-v41-flash",
                        "kind": "api_model",
                        "locator": "deepseek.yaml",
                        "sha256": expected_sha256,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    definition.write_text(definition.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="definition hash mismatch"):
        load_compute_resource_catalog(catalog)


def test_owner_observations_cannot_claim_independent_verification() -> None:
    payload = yaml.safe_load(
        (OBSERVATIONS / "gpu_host_3090_2_storage_owner_20260912_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    payload["status"] = ObservationStatus.VERIFIED

    with pytest.raises(ValidationError, match="owner reports must retain reported status"):
        ResourceObservation.model_validate(payload)


def test_checkpoint_observations_reject_api_and_gpu_fields() -> None:
    payload = yaml.safe_load(LOCAL_CHECKPOINT_OBSERVATION.read_text(encoding="utf-8"))
    payload["requested_model_id"] = "deepseek-flash"
    with pytest.raises(ValidationError, match="cannot contain API model or GPU host fields"):
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


def test_runtime_updates_catalog_without_losing_observations_and_binds_project(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    runtime = ComputeResourceRuntime(outputs)
    first = runtime.initialize(CATALOG)
    runtime.register_observation(
        CATALOG,
        OBSERVATIONS / "deepseek_v41flash_official_20260912_v1.yaml",
    )
    project = outputs / "projects" / "scitaste-self-development"
    project.mkdir(parents=True)
    (project / "PROJECT.json").write_text("{}\n", encoding="utf-8")

    second = runtime.update_catalog(CATALOG_V2)
    registered = runtime.register_project_binding(CATALOG_V2, PROJECT_BINDING)
    status = runtime.status(CATALOG_V2)

    assert second.revision == first.revision + 1
    assert second.predecessor_registry_sha256 == first.registry_sha256
    assert (runtime.root / "catalog-history" / first.registry_sha256 / "REGISTRY.json").is_file()
    assert registered.binding.project_id == "scitaste-self-development"
    assert status.project_binding_ids == ("scitaste-self-development",)
    deepseek = next(item for item in status.resources if item.resource_id == "deepseek-v41-flash")
    assert deepseek.observation_count == 1
    assert {item.resource_id for item in status.resources} == {
        "deepseek-v41-flash",
        "zhipu-glm53-flash",
        "bailian-qwen38-max",
        "gpu-host-local-3090",
        "gpu-host-3090-2",
        "qwen3-vl-2b-local-47f9c0e0",
    }


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


def test_resource_cli_migrates_catalog_and_registers_explicit_project_binding(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outputs = tmp_path / "outputs"
    project = outputs / "projects" / "scitaste-self-development"
    project.mkdir(parents=True)
    (project / "PROJECT.json").write_text("{}\n", encoding="utf-8")

    assert (
        main(
            [
                "resource",
                "init",
                "--catalog",
                str(CATALOG),
                "--evidence-root",
                ".",
                "--outputs-root",
                str(outputs),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "resource",
                "update-catalog",
                "--catalog",
                str(CATALOG_V2),
                "--evidence-root",
                ".",
                "--outputs-root",
                str(outputs),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "resource",
                "bind-project",
                "--catalog",
                str(CATALOG_V2),
                "--binding",
                str(PROJECT_BINDING),
                "--outputs-root",
                str(outputs),
            ]
        )
        == 0
    )
    response = json.loads(capsys.readouterr().out)
    assert response["record"]["binding"]["project_id"] == "scitaste-self-development"

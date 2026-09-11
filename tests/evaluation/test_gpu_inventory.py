from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import (
    GpuHostInventory,
    GpuModelResource,
    ReadinessStatus,
    compare_gpu_inventory,
    load_gpu_host_inventory,
)

INVENTORY = Path("docs/research/data/gpu_host_3090_2_inventory_v1.yaml")
CHECKPOINT_SHA256 = "8e95e5f6d2ce9219e40be475c077700c51495889166d38cf99c17acd6513b7a1"


def test_tracked_inventory_matches_the_planned_qwen_resource() -> None:
    inspection = load_gpu_host_inventory(INVENTORY)

    assert len(inspection.file_sha256) == 64
    assert inspection.inventory.root_storage.available_bytes == 59_034_427_392
    assert inspection.inventory.checkpoint.destination_present is False
    assert (
        compare_gpu_inventory(
            inspection.inventory,
            host_alias="3090-2",
            device_count=8,
            device_name="NVIDIA GeForce RTX 3090",
            minimum_memory_mb_per_device=24_000,
            checkpoint_id="qwen3-vl-2b-instruct",
            checkpoint_sha256=CHECKPOINT_SHA256,
            checkpoint_bytes=4_266_653_057,
        )
        == ()
    )


def test_inventory_comparison_reports_resource_drift() -> None:
    inventory = load_gpu_host_inventory(INVENTORY).inventory

    assert set(
        compare_gpu_inventory(
            inventory,
            host_alias="another-host",
            device_count=4,
            device_name="another-device",
            minimum_memory_mb_per_device=25_000,
            checkpoint_id="another-checkpoint",
            checkpoint_sha256="0" * 64,
            checkpoint_bytes=1,
        )
    ) == {
        "host_alias_mismatch",
        "device_count_mismatch",
        "device_name_mismatch",
        "device_memory_below_minimum",
        "checkpoint_id_mismatch",
        "checkpoint_sha256_mismatch",
        "checkpoint_bytes_mismatch",
    }


def test_inventory_rejects_duplicate_devices_and_unhashed_present_checkpoint() -> None:
    inventory = load_gpu_host_inventory(INVENTORY).inventory
    payload = inventory.model_dump(mode="json")
    payload["devices"][1]["index"] = payload["devices"][0]["index"]
    with pytest.raises(ValidationError, match="indices must be unique"):
        GpuHostInventory.model_validate(payload)

    payload = inventory.model_dump(mode="json")
    payload["checkpoint"]["destination_present"] = True
    with pytest.raises(ValidationError, match="present remote checkpoints"):
        GpuHostInventory.model_validate(payload)


def test_inventory_loader_rejects_top_level_symlink(tmp_path: Path) -> None:
    linked = tmp_path / "inventory.yaml"
    linked.symlink_to(INVENTORY.resolve())

    with pytest.raises(ValueError, match="must not be a symlink"):
        load_gpu_host_inventory(linked)


def test_verified_remote_resource_requires_inventory_and_checkpoint_evidence() -> None:
    payload = {
        "host_alias": "3090-2",
        "device_count": 8,
        "device_name": "NVIDIA GeForce RTX 3090",
        "minimum_memory_mb_per_device": 24_000,
        "checkpoint_id": "qwen3-vl-2b-instruct",
        "checkpoint_source_path": "/weights/Qwen3-VL-2B-Instruct",
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "checkpoint_bytes": 4_266_653_057,
        "license_identifier": "Apache-2.0",
        "local_preflight_status": ReadinessStatus.VERIFIED,
        "remote_inventory_status": ReadinessStatus.VERIFIED,
        "remote_checkpoint_status": ReadinessStatus.VERIFIED,
        "max_gpu_hours": 1,
        "max_storage_bytes": 10_000_000_000,
        "network_access": False,
    }
    with pytest.raises(ValidationError, match="inventory requires content-bound evidence"):
        GpuModelResource.model_validate(payload)

    payload.update(
        {
            "remote_inventory_ref": "inventory/3090-2.yaml",
            "remote_inventory_sha256": "0" * 64,
        }
    )
    with pytest.raises(ValidationError, match="checkpoint requires content-bound attestation"):
        GpuModelResource.model_validate(payload)

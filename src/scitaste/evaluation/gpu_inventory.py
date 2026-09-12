"""Content-addressed, read-only GPU host inventory evidence."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_INVENTORY_BYTES = 256 * 1024


class GpuInventoryDevice(BaseModel):
    model_config = _CONFIG

    index: int = Field(ge=0, le=255)
    name: str = Field(min_length=1, max_length=200)
    uuid: str = Field(pattern=r"^GPU-[0-9a-fA-F-]{20,80}$")
    memory_total_mb: int = Field(gt=0)
    memory_free_mb: int = Field(ge=0)
    driver_version: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def free_memory_fits_device(self) -> GpuInventoryDevice:
        if self.memory_free_mb > self.memory_total_mb:
            raise ValueError("free GPU memory cannot exceed total memory")
        return self


class GpuStorageInventory(BaseModel):
    model_config = _CONFIG

    filesystem: str = Field(min_length=1, max_length=500)
    mount: str = Field(min_length=1, max_length=500)
    total_bytes: int = Field(gt=0)
    used_bytes: int = Field(ge=0)
    available_bytes: int = Field(ge=0)
    percent_used: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def storage_values_fit(self) -> GpuStorageInventory:
        if self.used_bytes > self.total_bytes or self.available_bytes > self.total_bytes:
            raise ValueError("GPU host storage values exceed total bytes")
        return self


class GpuRuntimeInventory(BaseModel):
    model_config = _CONFIG

    python_version: str = Field(min_length=1, max_length=100)
    docker_path: str | None = Field(default=None, max_length=500)
    bubblewrap_path: str | None = Field(default=None, max_length=500)


class GpuCheckpointObservation(BaseModel):
    model_config = _CONFIG

    checkpoint_id: str = Field(pattern=_ID)
    expected_sha256: str = Field(pattern=_SHA256)
    expected_bytes: int = Field(gt=0)
    destination_path: str = Field(min_length=1, max_length=2_000)
    destination_present: bool
    observed_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def presence_has_an_observed_hash(self) -> GpuCheckpointObservation:
        if self.destination_present != (self.observed_sha256 is not None):
            raise ValueError("present remote checkpoints require exactly one observed hash")
        return self


class GpuHostInventory(BaseModel):
    """One bounded observation; it carries no permission to transfer or execute."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    inventory_id: str = Field(pattern=_ID)
    host_alias: str = Field(pattern=_ID)
    hostname: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    observation_method: Literal["read-only-ssh", "read-only-local"]
    devices: tuple[GpuInventoryDevice, ...] = Field(min_length=1, max_length=64)
    root_storage: GpuStorageInventory
    runtime: GpuRuntimeInventory
    checkpoint: GpuCheckpointObservation
    remote_state_mutation_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    model_transfer_performed: Literal[False] = False
    dataset_download_performed: Literal[False] = False
    credentials_recorded: Literal[False] = False

    @model_validator(mode="after")
    def device_identities_are_unique(self) -> GpuHostInventory:
        indices = [item.index for item in self.devices]
        uuids = [item.uuid for item in self.devices]
        if len(indices) != len(set(indices)):
            raise ValueError("GPU inventory indices must be unique")
        if len(uuids) != len(set(uuids)):
            raise ValueError("GPU inventory UUIDs must be unique")
        return self


class GpuInventoryInspection(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    inventory: GpuHostInventory


def load_gpu_host_inventory(path: str | Path) -> GpuInventoryInspection:
    """Load an exact inventory without following a top-level symlink."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("GPU inventory must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_INVENTORY_BYTES:
        raise ValueError("GPU inventory must be a bounded regular file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("GPU inventory must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("GPU inventory must contain a YAML mapping")
    return GpuInventoryInspection(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        inventory=GpuHostInventory.model_validate(payload),
    )


def compare_gpu_inventory(
    inventory: GpuHostInventory,
    *,
    host_alias: str,
    device_count: int,
    device_name: str,
    minimum_memory_mb_per_device: int,
    checkpoint_id: str,
    checkpoint_sha256: str,
    checkpoint_bytes: int,
    compare_checkpoint: bool = True,
) -> tuple[str, ...]:
    """Return stable mismatch codes between evidence and one GPU lane."""

    problems: list[str] = []
    if inventory.host_alias != host_alias:
        problems.append("host_alias_mismatch")
    if len(inventory.devices) != device_count:
        problems.append("device_count_mismatch")
    if any(item.name != device_name for item in inventory.devices):
        problems.append("device_name_mismatch")
    if any(item.memory_total_mb < minimum_memory_mb_per_device for item in inventory.devices):
        problems.append("device_memory_below_minimum")
    if compare_checkpoint:
        checkpoint = inventory.checkpoint
        if checkpoint.checkpoint_id != checkpoint_id:
            problems.append("checkpoint_id_mismatch")
        if checkpoint.expected_sha256 != checkpoint_sha256:
            problems.append("checkpoint_sha256_mismatch")
        if checkpoint.expected_bytes != checkpoint_bytes:
            problems.append("checkpoint_bytes_mismatch")
    return tuple(problems)


__all__ = [
    "GpuCheckpointObservation",
    "GpuHostInventory",
    "GpuInventoryDevice",
    "GpuInventoryInspection",
    "GpuRuntimeInventory",
    "GpuStorageInventory",
    "compare_gpu_inventory",
    "load_gpu_host_inventory",
]

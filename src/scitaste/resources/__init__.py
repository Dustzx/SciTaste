"""Project-superordinate compute resource registry."""

from scitaste.resources.registry import (
    ApiModelDefinition,
    ComputeResourceCatalog,
    ComputeResourceRuntime,
    GpuHostDefinition,
    LoadedComputeResourceCatalog,
    ObservationMethod,
    ObservationStatus,
    ResourceKind,
    ResourceObservation,
    ResourceRegistryStatus,
    inspect_compute_resource_catalog,
    load_compute_resource_catalog,
    load_resource_observation,
)

__all__ = [
    "ApiModelDefinition",
    "ComputeResourceCatalog",
    "ComputeResourceRuntime",
    "GpuHostDefinition",
    "LoadedComputeResourceCatalog",
    "ObservationMethod",
    "ObservationStatus",
    "ResourceKind",
    "ResourceObservation",
    "ResourceRegistryStatus",
    "inspect_compute_resource_catalog",
    "load_compute_resource_catalog",
    "load_resource_observation",
]

"""Strict workload profiles for bounded, project-scoped model nodes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.model_nodes.models import (
    CumulativeProjectBudget,
    NodeAdmissionBudget,
    NodePolicy,
    ProviderGenerationEnvelope,
)


class ProfileConfigurationError(ValueError):
    """Raised when a profile or its binding is unsafe or internally inconsistent."""


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelNodeProfile(ProfileModel):
    """One explicit generation-capability and deterministic-admission contract."""

    schema_version: Literal["1.0"] = "1.0"
    profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    profile_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    allowed_node_names: tuple[str, ...] = Field(min_length=1)
    live_execution_permitted: bool = False
    local_execution_permitted: bool = False
    generation: ProviderGenerationEnvelope
    admission: NodeAdmissionBudget
    cumulative_project: CumulativeProjectBudget
    unrestricted_code_generation: Literal[False] = False

    @field_validator("allowed_node_names")
    @classmethod
    def node_names_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("profile node allowlist must not contain duplicates")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def ceilings_are_compatible(self) -> ModelNodeProfile:
        if self.live_execution_permitted and self.local_execution_permitted:
            raise ValueError("a profile cannot permit both remote-live and local execution")
        if self.admission.max_request_bytes > self.generation.max_request_bytes:
            raise ValueError("admission request limit exceeds the provider generation envelope")
        if self.admission.max_output_tokens > self.generation.max_output_tokens:
            raise ValueError("admission output limit exceeds the provider generation envelope")
        if self.admission.max_total_tokens > self.generation.context_window_tokens:
            raise ValueError("admission token limit exceeds the provider context window")
        if self.cumulative_project.max_total_tokens < self.admission.max_total_tokens:
            raise ValueError("project token budget cannot be below one admitted invocation")
        if self.cumulative_project.max_api_cost_usd < self.admission.max_response_cost_usd:
            raise ValueError("project cost budget cannot be below one admitted response")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        # Preserve every existing v1 profile fingerprint while making the new
        # local-execution grant explicit and content-addressed when enabled.
        if not self.local_execution_permitted:
            payload.pop("local_execution_permitted")
        return _canonical_sha256(payload)


class ModelNodeProfileReference(ProfileModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("profile paths must use POSIX separators")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or "//" in value
        ):
            raise ValueError("profile path must be normalized and relative")
        return value


class ModelNodeProfileSet(ProfileModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_set_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    profile_set_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    profiles: tuple[ModelNodeProfileReference, ...] = Field(min_length=1)
    live_enabled: bool = False

    @model_validator(mode="after")
    def references_are_unique(self) -> ModelNodeProfileSet:
        paths = [item.path for item in self.profiles]
        if len(paths) != len(set(paths)):
            raise ValueError("profile-set paths must be unique")
        return self


@dataclass(frozen=True)
class LoadedModelNodeProfiles:
    source_path: Path
    source_sha256: str
    profile_set: ModelNodeProfileSet
    profiles: dict[str, ModelNodeProfile]


def load_model_node_profile(path: str | Path) -> ModelNodeProfile:
    """Load one strict profile without accepting duplicate or unknown fields."""

    source = Path(path).expanduser().resolve(strict=True)
    return ModelNodeProfile.model_validate_json(_strict_json(_load_yaml(source)), strict=True)


def load_model_node_profile_set(path: str | Path) -> LoadedModelNodeProfiles:
    """Load a content-addressed set of profiles confined to its config directory."""

    source = Path(path).expanduser().resolve(strict=True)
    raw = source.read_bytes()
    profile_set = ModelNodeProfileSet.model_validate_json(
        _strict_json(_load_yaml(source)),
        strict=True,
    )
    root = source.parent
    profiles: dict[str, ModelNodeProfile] = {}
    for reference in profile_set.profiles:
        candidate = root / PurePosixPath(reference.path)
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, ValueError) as exc:
            raise ProfileConfigurationError(
                f"profile path is missing or escapes the profile-set directory: {reference.path}"
            ) from exc
        profile_raw = resolved.read_bytes()
        if hashlib.sha256(profile_raw).hexdigest() != reference.sha256:
            raise ProfileConfigurationError(f"profile content hash drift for {reference.path!r}")
        profile = ModelNodeProfile.model_validate_json(
            _strict_json(_load_yaml(resolved)),
            strict=True,
        )
        if profile.fingerprint != reference.profile_sha256:
            raise ProfileConfigurationError(f"profile canonical hash drift for {reference.path!r}")
        if profile.profile_id in profiles:
            raise ProfileConfigurationError(f"duplicate profile_id {profile.profile_id!r}")
        profiles[profile.profile_id] = profile
    return LoadedModelNodeProfiles(
        source_path=source,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        profile_set=profile_set,
        profiles=profiles,
    )


def validate_profile_binding(
    profile: ModelNodeProfile,
    policy: NodePolicy,
    *,
    node_name: str,
) -> None:
    """Require one policy to expose exactly the profile's effective admission limits."""

    if node_name not in profile.allowed_node_names:
        raise ProfileConfigurationError(f"profile does not permit node {node_name!r}")
    if (profile.provider, profile.model) != (policy.expected_backend, policy.expected_model):
        raise ProfileConfigurationError("profile provider/model differs from the pinned policy")
    expected = {
        "max_request_bytes": profile.admission.max_request_bytes,
        "max_input_tokens": profile.admission.max_input_tokens,
        "max_output_tokens": profile.admission.max_output_tokens,
        "max_total_tokens": profile.admission.max_total_tokens,
        "max_latency_ms": profile.admission.max_latency_ms,
        "max_api_cost_usd": profile.cumulative_project.max_api_cost_usd,
        "allowed_tool_names": list(profile.admission.allowed_tool_names),
    }
    drift = [name for name, value in expected.items() if getattr(policy, name) != value]
    if drift:
        raise ProfileConfigurationError(
            "policy/profile admission drift: " + ", ".join(sorted(drift))
        )


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ProfileConfigurationError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_yaml(path: Path) -> Any:
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ProfileConfigurationError(f"profile is not valid YAML: {path.name}") from exc
    if not isinstance(data, dict):
        raise ProfileConfigurationError(f"profile root must be a mapping: {path.name}")
    return data


def _strict_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "LoadedModelNodeProfiles",
    "ModelNodeProfile",
    "ModelNodeProfileReference",
    "ModelNodeProfileSet",
    "ProfileConfigurationError",
    "load_model_node_profile",
    "load_model_node_profile_set",
    "validate_profile_binding",
]

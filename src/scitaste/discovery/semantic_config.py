"""Non-secret application configuration for Discovery semantic generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.discovery.semantic import DiscoverySemanticBinding
from scitaste.model_nodes.models import NodePolicy
from scitaste.model_nodes.profiles import ModelNodeProfile
from scitaste.model_nodes.runtime_config import (
    RuntimeBackendBinding,
    ScriptedRuntimeBackend,
)


class DiscoverySemanticRuntimeConfig(BaseModel):
    """Backend and policy config; scientific input is always derived from the project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    request_id: str | None = Field(default=None, min_length=1)
    policy: NodePolicy
    backend: RuntimeBackendBinding

    @model_validator(mode="after")
    def backend_identity_is_pinned(self) -> DiscoverySemanticRuntimeConfig:
        identity = (
            (self.backend.provider, self.backend.model)
            if isinstance(self.backend, ScriptedRuntimeBackend)
            else (self.backend.config.provider, self.backend.config.model)
        )
        if identity != (self.policy.expected_backend, self.policy.expected_model):
            raise ValueError("semantic backend identity differs from the policy")
        return self

    def binding(
        self,
        profile: ModelNodeProfile,
        *,
        invocation_id: str,
        allow_live: bool,
    ) -> DiscoverySemanticBinding:
        return DiscoverySemanticBinding(
            backend=self.backend.build(self.request_id or invocation_id),
            profile=profile,
            policy=self.policy,
            backend_mode=self.backend.mode,
            allow_live=allow_live,
            request_id=self.request_id,
        )


@dataclass(frozen=True)
class LoadedDiscoverySemanticRuntimeConfig:
    source_path: Path
    source_sha256: str
    config: DiscoverySemanticRuntimeConfig


def load_discovery_semantic_runtime_config(
    path: str | Path,
) -> LoadedDiscoverySemanticRuntimeConfig:
    """Load strict JSON while refusing embedded credential fields."""

    source = Path(path).expanduser().resolve(strict=True)
    raw = source.read_bytes()
    try:
        value = json.loads(raw)
        _reject_secret_fields(value)
        config = DiscoverySemanticRuntimeConfig.model_validate_json(raw, strict=True)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid or secret-bearing discovery semantic config") from exc
    return LoadedDiscoverySemanticRuntimeConfig(
        source_path=source,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        config=config,
    )


def _reject_secret_fields(value: JsonValue) -> None:
    if isinstance(value, dict):
        forbidden = {"api_key", "authorization", "bearer_token", "password", "secret"}
        if any(str(key).casefold().replace("-", "_") in forbidden for key in value):
            raise ValueError("credential fields are forbidden")
        for nested in value.values():
            _reject_secret_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_fields(nested)


__all__ = [
    "DiscoverySemanticRuntimeConfig",
    "LoadedDiscoverySemanticRuntimeConfig",
    "load_discovery_semantic_runtime_config",
]

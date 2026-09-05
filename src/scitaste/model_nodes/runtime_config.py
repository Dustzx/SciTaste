"""Strict, non-secret file bindings for the model-node runtime CLI."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.model_nodes.backends import (
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    StructuredModelBackend,
)
from scitaste.model_nodes.facade import ImmutableStateProjection
from scitaste.model_nodes.models import NodePolicy
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    StructuredOpenAICompatibleConfig,
)
from scitaste.model_nodes.runtime import ModelNodeRuntimeError, ModelNodeTrigger, RuntimeBackendMode


class RuntimeConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScriptedRuntimeBackend(RuntimeConfigModel):
    kind: Literal["scripted"] = "scripted"
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reply: ScriptedStructuredReply

    @property
    def mode(self) -> RuntimeBackendMode:
        return RuntimeBackendMode.SCRIPTED

    def build(self, request_id: str) -> ScriptedStructuredBackend:
        return ScriptedStructuredBackend(
            name=self.provider,
            model=self.model,
            replies={request_id: self.reply},
        )


class LiveRuntimeBackend(RuntimeConfigModel):
    kind: Literal["openai-compatible"] = "openai-compatible"
    config: StructuredOpenAICompatibleConfig

    @property
    def mode(self) -> RuntimeBackendMode:
        return RuntimeBackendMode.LIVE

    def build(self, request_id: str) -> StructuredOpenAICompatibleBackend:
        del request_id
        return StructuredOpenAICompatibleBackend(self.config)


RuntimeBackendBinding = Annotated[
    ScriptedRuntimeBackend | LiveRuntimeBackend,
    Field(discriminator="kind"),
]


class ModelNodeRuntimeConfig(RuntimeConfigModel):
    schema_version: Literal["1.0"] = "1.0"
    node_name: Literal["review-semantic", "interpretation-threat", "ambiguous-action"]
    request_id: str | None = Field(default=None, min_length=1)
    node_input: dict[str, JsonValue]
    state_projection: ImmutableStateProjection
    trigger: ModelNodeTrigger
    policy: NodePolicy
    backend: RuntimeBackendBinding
    seed: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def backend_identity_is_pinned(self) -> ModelNodeRuntimeConfig:
        identity = (
            (self.backend.provider, self.backend.model)
            if isinstance(self.backend, ScriptedRuntimeBackend)
            else (self.backend.config.provider, self.backend.config.model)
        )
        expected = (self.policy.expected_backend, self.policy.expected_model)
        if identity != expected:
            raise ValueError("runtime backend identity differs from the policy")
        return self

    @property
    def backend_mode(self) -> RuntimeBackendMode:
        return self.backend.mode

    def build_backend(self, invocation_id: str) -> StructuredModelBackend:
        return self.backend.build(self.request_id or invocation_id)


@dataclass(frozen=True)
class LoadedModelNodeRuntimeConfig:
    source_path: Path
    source_sha256: str
    config: ModelNodeRuntimeConfig


def load_model_node_runtime_config(path: str | Path) -> LoadedModelNodeRuntimeConfig:
    """Load strict JSON while ensuring credential values cannot be embedded."""

    source = Path(path).expanduser().resolve(strict=True)
    raw = source.read_bytes()
    try:
        value = json.loads(raw)
        _reject_secret_fields(value)
        config = ModelNodeRuntimeConfig.model_validate_json(raw, strict=True)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ModelNodeRuntimeError("invalid or secret-bearing model-node runtime config") from exc
    return LoadedModelNodeRuntimeConfig(
        source_path=source,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        config=config,
    )


def _reject_secret_fields(value: JsonValue) -> None:
    if isinstance(value, dict):
        forbidden = {
            "api_key",
            "authorization",
            "bearer_token",
            "password",
            "secret",
        }
        if any(str(key).casefold().replace("-", "_") in forbidden for key in value):
            raise ValueError("credential fields are forbidden")
        for nested in value.values():
            _reject_secret_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_fields(nested)


__all__ = [
    "LiveRuntimeBackend",
    "LoadedModelNodeRuntimeConfig",
    "ModelNodeRuntimeConfig",
    "RuntimeBackendBinding",
    "ScriptedRuntimeBackend",
    "load_model_node_runtime_config",
]

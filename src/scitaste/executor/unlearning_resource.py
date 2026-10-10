"""Non-secret remote execution envelope for a prepared unlearning task."""

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.resources.registry import GpuHostDefinition


class RemoteUnlearningResource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    host: GpuHostDefinition
    host_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base: str
    code: str
    python: str
    gpu_index: int = Field(ge=0)
    seed: Literal[42] = 42  # Current registered task fixes ten replicas at seeds 42-51.

    @model_validator(mode="after")
    def bounded_remote_paths(self):
        if self.host.location != "remote" or self.gpu_index >= self.host.device_count:
            raise ValueError("Select an existing device on a remote host")
        if not self.host.connection_alias or not self.host.credential_env:
            raise ValueError("Remote task requires registered connection and credential names")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.host.connection_alias):
            raise ValueError("Remote connection alias must be a literal SSH host name")
        if not self.host.connection_host or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9.-]*", self.host.connection_host
        ):
            raise ValueError("Explicit literal remote DNS name or IPv4 address required")
        for value in (self.base, self.code, self.python):
            path = PurePosixPath(value)
            if (
                not path.is_absolute()
                or len(path.parts) < 4
                or ".." in path.parts
                or str(path) != value
                or any(c in value for c in "\n\r\x00")
            ):
                raise ValueError("Remote paths must name explicit absolute task-owned locations")
        PurePosixPath(self.code).relative_to(PurePosixPath(self.base))
        return self


def load_remote_unlearning_resource(path: Path, *, code_root: Path) -> RemoteUnlearningResource:
    payload = yaml.safe_load(path.read_text())
    host_path = (code_root / payload.pop("host_manifest")).resolve(strict=True)
    host_path.relative_to(code_root.resolve(strict=True))
    raw = host_path.read_bytes()
    return RemoteUnlearningResource.model_validate(
        {
            **payload,
            "host": yaml.safe_load(raw)["resource"],
            "host_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )

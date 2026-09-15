"""Content-addressed Hugging Face checkpoint identity manifests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_CONFIG = ConfigDict(extra="forbid", frozen=True)
_SHA256 = r"^[0-9a-f]{64}$"
_HASH_CHUNK_BYTES = 8 * 1024 * 1024


class CheckpointManifestFile(BaseModel):
    model_config = _CONFIG

    path: str
    size_bytes: int = Field(ge=0)
    identity_scope: Literal["complete-file"]
    identity_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def path_is_relative(self) -> CheckpointManifestFile:
        path = PurePosixPath(self.path)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("checkpoint manifest file path must be normalized and relative")
        return self


class LocalCheckpointIdentityManifest(BaseModel):
    """Portable checkpoint identity that binds every checkpoint byte."""

    model_config = _CONFIG

    schema_version: Literal["2.0"] = "2.0"
    algorithm: Literal["scitaste-hf-checkpoint-manifest-v2"]
    model_path: str
    files: tuple[CheckpointManifestFile, ...] = Field(min_length=1)
    checkpoint_identity_sha256: str = Field(pattern=_SHA256)
    manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def hashes_are_valid(self) -> LocalCheckpointIdentityManifest:
        paths = [item.path for item in self.files]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("checkpoint manifest files must be sorted and unique")
        identity = _canonical_sha256(
            {
                "algorithm": self.algorithm,
                "files": [item.model_dump(mode="json") for item in self.files],
            }
        )
        if identity != self.checkpoint_identity_sha256:
            raise ValueError("checkpoint identity hash mismatch")
        manifest = _canonical_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if manifest != self.manifest_sha256:
            raise ValueError("checkpoint manifest self-hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        model_path: str | Path,
        files: tuple[CheckpointManifestFile, ...],
    ) -> LocalCheckpointIdentityManifest:
        algorithm = "scitaste-hf-checkpoint-manifest-v2"
        identity = _canonical_sha256(
            {
                "algorithm": algorithm,
                "files": [item.model_dump(mode="json") for item in files],
            }
        )
        unsigned = {
            "schema_version": "2.0",
            "algorithm": algorithm,
            "model_path": str(Path(model_path).resolve(strict=True)),
            "files": [item.model_dump(mode="json") for item in files],
            "checkpoint_identity_sha256": identity,
        }
        return cls(**unsigned, manifest_sha256=_canonical_sha256(unsigned))


def build_local_checkpoint_identity_manifest(
    model_path: str | Path,
) -> LocalCheckpointIdentityManifest:
    """Stream-hash every regular checkpoint file, including tensor payloads."""

    root = _checkpoint_root(model_path)
    files: list[CheckpointManifestFile] = []
    for source in _regular_checkpoint_files(root):
        relative = source.relative_to(root).as_posix()
        size = source.stat().st_size
        scope = "complete-file"
        digest = _file_sha256(source)
        files.append(
            CheckpointManifestFile(
                path=relative,
                size_bytes=size,
                identity_scope=scope,
                identity_sha256=digest,
            )
        )
    return LocalCheckpointIdentityManifest.create(root, tuple(files))


def verify_local_checkpoint_identity_manifest(
    model_path: str | Path,
    manifest_path: str | Path,
    *,
    expected_manifest_file_sha256: str,
    expected_checkpoint_identity_sha256: str,
) -> LocalCheckpointIdentityManifest:
    """Recompute the manifest and reject drift in any checkpoint byte."""

    source = Path(manifest_path).resolve(strict=True)
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_manifest_file_sha256:
        raise RuntimeError("checkpoint identity-manifest file hash mismatch")
    try:
        manifest = LocalCheckpointIdentityManifest.model_validate_json(raw, strict=True)
    except ValueError as exc:
        raise RuntimeError("checkpoint identity manifest is invalid") from exc
    observed = build_local_checkpoint_identity_manifest(model_path)
    if observed.model_path != manifest.model_path or observed.files != manifest.files:
        raise RuntimeError("local checkpoint differs from its identity manifest")
    if manifest.checkpoint_identity_sha256 != expected_checkpoint_identity_sha256:
        raise RuntimeError("checkpoint identity differs from the runtime binding")
    return manifest


def _checkpoint_root(model_path: str | Path) -> Path:
    unresolved = Path(model_path).expanduser()
    if unresolved.is_symlink():
        raise RuntimeError("local checkpoint directory cannot be a symbolic link")
    root = unresolved.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError(f"local model directory does not exist: {root}")
    return root


def _regular_checkpoint_files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for source in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if source.is_symlink():
            raise RuntimeError("local checkpoint cannot contain symbolic links")
        if source.is_dir():
            continue
        if not source.is_file():
            raise RuntimeError("local checkpoint contains a non-regular entry")
        files.append(source)
    if not files:
        raise RuntimeError("local checkpoint directory contains no files")
    return tuple(files)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "CheckpointManifestFile",
    "LocalCheckpointIdentityManifest",
    "build_local_checkpoint_identity_manifest",
    "verify_local_checkpoint_identity_manifest",
]

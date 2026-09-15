from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scitaste.backends.checkpoint_manifest import (
    build_local_checkpoint_identity_manifest,
    verify_local_checkpoint_identity_manifest,
)


def test_checkpoint_manifest_binds_every_checkpoint_byte(
    tmp_path: Path,
) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"model_type":"bounded"}\n', encoding="utf-8")
    header = b'{"weight":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}   '
    (model / "model.safetensors").write_bytes(
        len(header).to_bytes(8, "little") + header + b"\x00\x00\x00\x00"
    )
    manifest = build_local_checkpoint_identity_manifest(model)
    manifest_path = tmp_path / "CHECKPOINT_IDENTITY.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

    verified = verify_local_checkpoint_identity_manifest(
        model,
        manifest_path,
        expected_manifest_file_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        expected_checkpoint_identity_sha256=manifest.checkpoint_identity_sha256,
    )
    assert verified == manifest

    # A tensor-payload mutation with the same safetensors header and file size
    # must invalidate exact experimental identity.
    safetensors = model / "model.safetensors"
    mutated = bytearray(safetensors.read_bytes())
    mutated[-1] = 1
    safetensors.write_bytes(mutated)
    with pytest.raises(RuntimeError, match="differs from its identity manifest"):
        verify_local_checkpoint_identity_manifest(
            model,
            manifest_path,
            expected_manifest_file_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            expected_checkpoint_identity_sha256=manifest.checkpoint_identity_sha256,
        )

    safetensors.write_bytes(
        len(header).to_bytes(8, "little") + header + b"\x00\x00\x00\x00"
    )
    (model / "config.json").write_text('{"model_type":"drifted"}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="differs from its identity manifest"):
        verify_local_checkpoint_identity_manifest(
            model,
            manifest_path,
            expected_manifest_file_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            expected_checkpoint_identity_sha256=manifest.checkpoint_identity_sha256,
        )

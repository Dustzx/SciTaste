"""Tensor-only handoff between an untrusted method and the trusted evaluator.

The launcher must sandbox its worker. This module never imports candidate Python
or deserializes pickle outputs. Seeds per replica are an explicit development
protocol amendment, not a claim of bitwise equivalence to upstream execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

MAX_SNAPSHOT_BYTES = 100_000_000


def stage_candidate_data(loaders: Mapping[str, Any], root: Path) -> None:
    """Export only allowed normalized examples, never the scoring split.

    Iterating dataset indices (not loader iterators) preserves scorer sampler
    state. Storage is about 645 MiB for CIFAR retain/forget/validation combined.
    """
    root.mkdir(parents=True, exist_ok=False)
    for split in ("retain", "forget", "validation"):
        dataset = loaders[split].dataset
        images = np.lib.format.open_memmap(
            root / f"{split}-images.npy",
            mode="w+",
            dtype=np.float32,
            shape=(len(dataset), 3, 32, 32),
        )
        labels = np.lib.format.open_memmap(
            root / f"{split}-labels.npy",
            mode="w+",
            dtype=np.int64,
            shape=(len(dataset),),
        )
        for index in range(len(dataset)):
            image, label = dataset[index]
            images[index] = image.detach().cpu().numpy()
            labels[index] = int(label)
        images.flush()
        labels.flush()


def write_tensor_snapshot(path: Path, state: Mapping[str, Any]) -> str:
    """Export an existing model, exclusively creating an uncompressed NPZ."""
    arrays = {name: tensor.detach().cpu().numpy() for name, tensor in state.items()}
    if not arrays or sum(value.nbytes for value in arrays.values()) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Model state exceeds snapshot budget")
    if any(value.dtype.hasobject for value in arrays.values()):
        raise ValueError("Object tensors are forbidden")
    with path.open("xb") as stream:
        np.savez(stream, **arrays)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_tensor_snapshot(path: Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    """Validate archive, tensor names/shapes/dtypes and finiteness before load."""
    import torch

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_SNAPSHOT_BYTES:
            raise ValueError("Snapshot must be a bounded regular file")
        with zipfile.ZipFile(stream) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(names) != len(set(names)) or set(names) != {f"{key}.npy" for key in expected}:
                raise ValueError("Snapshot tensor inventory differs from model")
            if sum(member.file_size for member in members) > MAX_SNAPSHOT_BYTES:
                raise ValueError("Expanded snapshot exceeds budget")
            # Header checks precede allocation: even a short NPY can claim a huge shape.
            for member in members:
                target = expected[member.filename[:-4]].detach().cpu().numpy()
                if member.compress_type != zipfile.ZIP_STORED:
                    raise ValueError("Only uncompressed tensor snapshots are accepted")
                with archive.open(member) as array_stream:
                    version = np.lib.format.read_magic(array_stream)
                    if version != (1, 0):
                        raise ValueError("Unexpected tensor header format")
                    shape, fortran, dtype = np.lib.format.read_array_header_1_0(array_stream)
                    if shape != target.shape or dtype != target.dtype or fortran:
                        raise ValueError("Tensor metadata differs from model")
                    if dtype.hasobject or array_stream.tell() + target.nbytes != member.file_size:
                        raise ValueError("Invalid tensor payload size or dtype")
        stream.seek(0)
        result = {}
        with np.load(stream, allow_pickle=False) as archive:
            for name in expected:
                value = archive[name]
                if not np.isfinite(value).all():
                    raise ValueError("Non-finite candidate tensor")
                result[name] = torch.from_numpy(value.copy())
        return result


class IsolatedUnlearningMethod:
    """Upstream method interface that exchanges weights, never candidate code.

    launch(replica, seed, original_snapshot, output_snapshot) must finish and
    reap the sandbox before returning. It receives no scorer model or loaders.
    Allowed retain/forget/validation data must already be staged separately.
    No testing data or retrained model may be mounted in that worker.
    """

    def __init__(
        self,
        root: Path,
        launch: Callable[[int, int, Path, Path], None],
        *,
        seed: int = 42,
    ) -> None:
        root.mkdir(parents=True, exist_ok=False)
        self.root = root
        self.launch = launch
        self.seed = seed
        self.replica = 0

    def get_name(self) -> str:
        return "isolated_candidate"

    def run(self, net: Any, retain_loader: Any, forget_loader: Any, val_loader: Any) -> None:
        if self.replica >= 10:
            raise ValueError("The fixed development protocol allows ten replicas")
        replica = self.replica
        self.replica += 1  # Failed execution consumes its slot; no silent retry.
        directory = self.root / f"replica-{replica:02d}"
        directory.mkdir()
        original = directory / "original.npz"
        output = directory / "candidate.npz"
        original_sha = write_tensor_snapshot(original, net.state_dict())
        self.launch(replica, self.seed + replica, original, output)
        state = load_tensor_snapshot(output, net.state_dict())
        net.load_state_dict(state, strict=True)
        net.eval()
        receipt = {
            "replica": replica,
            "seed": self.seed + replica,
            "original_sha256": original_sha,
            "candidate_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "candidate_python_imported_in_scorer": False,
            "formal_evidence": False,
        }
        with (directory / "RECEIPT.json").open("x") as stream:
            json.dump(receipt, stream, indent=2)

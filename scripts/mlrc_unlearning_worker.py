#!/usr/bin/env python3
"""Candidate-side worker. Invoke only inside a network/filesystem/GPU sandbox."""

from __future__ import annotations

import argparse
import importlib
import random
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset
from torchvision.models import resnet18


class ArrayDataset(Dataset):
    def __init__(self, root: Path, split: str) -> None:
        self.images = np.load(root / f"{split}-images.npy", mmap_mode="r", allow_pickle=False)
        self.labels = np.load(root / f"{split}-labels.npy", mmap_mode="r", allow_pickle=False)
        if self.images.shape != (len(self.labels), 3, 32, 32):
            raise ValueError("Invalid staged CIFAR shape")
        if self.images.dtype != np.float32 or self.labels.dtype != np.int64:
            raise ValueError("Invalid staged CIFAR dtype")

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        return torch.from_numpy(self.images[index].copy()), int(self.labels[index])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if not torch.cuda.is_available():
        raise RuntimeError("This GPU task does not silently fall back to CPU")
    net = resnet18(weights=None, num_classes=10)
    with np.load(args.original, allow_pickle=False) as archive:
        net.load_state_dict(
            {name: torch.from_numpy(archive[name]) for name in archive}, strict=True
        )
    net.cuda().eval()
    retain = DataLoader(
        ArrayDataset(args.data, "retain"),
        batch_size=128,
        shuffle=True,
        generator=torch.Generator().manual_seed(args.seed),
    )
    forget = DataLoader(ArrayDataset(args.data, "forget"), batch_size=128, shuffle=True)
    validation = DataLoader(ArrayDataset(args.data, "validation"), batch_size=128, shuffle=False)
    sys.path.insert(0, str(args.candidate))
    method_type = importlib.import_module("methods.MyMethod").MyMethod
    method_type("candidate").run(net, retain, forget, validation)
    # Untrusted output: the separate scorer enforces inventory/shape/dtype/size.
    with args.output.open("xb") as stream:
        np.savez(
            stream,
            **{name: value.detach().cpu().numpy() for name, value in net.state_dict().items()},
        )


if __name__ == "__main__":
    main()

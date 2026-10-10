"""Generate real trained research subjects, never a trained research controller.

Fixed queue/exposure, independent training blocks and untouched confirmation
images are declared before training. Checkpoint/model pairs are not task counts.
The output is local-only development material; CIFAR redistribution rights are
not inferred from download access. Run CUDA training on the declared remote host.
"""

import argparse
import hashlib
import json
import os
import pickle
import random
import tarfile
import time
import traceback
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
from torch import nn

URL = "https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz"
MD5 = "c58f30108f718f92721af3b95e74349a"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retain(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


class ResearchCNN(nn.Module):
    """Six ordinary convolutions, no batchnorm or architectural matching oracle."""

    def __init__(self):
        super().__init__()
        channels = [3, 16, 16, 32, 32, 64, 64]
        layers = []
        for i in range(6):
            layers += [nn.Conv2d(channels[i], channels[i + 1], 3, padding=1), nn.ReLU()]
            if i % 2:
                layers.append(nn.MaxPool2d(2))
        self.features = nn.Sequential(*layers)
        self.head = nn.Linear(64, 10)

    def forward(self, x):
        return self.head(self.features(x).mean((2, 3)))


def acquire(root):
    archive = root / "cifar-10-python.tar.gz"
    request = urllib.request.Request(URL, headers={"User-Agent": "SciTaste-research/1.0"})
    limit = 200_000_000
    with urllib.request.urlopen(request, timeout=90) as response, archive.open("xb") as stream:
        total = 0
        while chunk := response.read(1_048_576):
            total += len(chunk)
            if total > limit:
                raise ValueError("Predeclared dataset acquisition limit exceeded")
            stream.write(chunk)
    if hashlib.md5(archive.read_bytes(), usedforsecurity=False).hexdigest() != MD5:
        raise ValueError("Official CIFAR archive integrity mismatch")
    retain(
        root / "ACQUISITION.json",
        {
            "url": URL,
            "sha256": digest(archive),
            "official_md5": MD5,
            "bytes": archive.stat().st_size,
            "acquired_at": datetime.now(UTC).isoformat(),
            "source": "official CIFAR-10 Python distribution",
            "redistribution_authorized": False,
        },
    )
    return archive


def load_archive(archive):
    if hashlib.md5(archive.read_bytes(), usedforsecurity=False).hexdigest() != MD5:
        raise ValueError("Dataset does not match the pinned official archive")
    # Load ONLY named official pickle members after verifying the whole archive.
    arrays, labels = [], []
    with tarfile.open(archive) as bundle:
        for name in [f"data_batch_{i}" for i in range(1, 6)] + ["test_batch"]:
            member = bundle.getmember("cifar-10-batches-py/" + name)
            if not member.isfile() or member.size > 40_000_000:
                raise ValueError("Unexpected CIFAR member")
            row = pickle.load(bundle.extractfile(member), encoding="bytes")
            arrays.append(np.asarray(row[b"data"]).reshape(-1, 3, 32, 32))
            labels.append(np.asarray(row[b"labels"], dtype=np.int64))
    return np.concatenate(arrays[:5]), np.concatenate(labels[:5]), arrays[5], labels[5]


def fit(model, x, y, *, epochs, seed, lr, deadline, epoch_log, name):
    torch.manual_seed(seed)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=5e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, epochs)
    generator = torch.Generator(device="cuda").manual_seed(seed)
    completed = 0
    for epoch in range(epochs):
        if time.monotonic() >= deadline:
            break
        began = time.monotonic()
        model.train()
        total_loss, correct = 0.0, 0
        order = torch.randperm(len(x), device="cuda", generator=generator)
        for start in range(0, len(x), 512):
            if time.monotonic() >= deadline:
                break
            indices = order[start : start + 512]
            images, targets = x[indices], y[indices]
            # Same augmentation recipe for every lineage; not tuned using test labels.
            flip = torch.rand(len(images), device="cuda", generator=generator) < 0.5
            images = torch.where(flip[:, None, None, None], images.flip(3), images)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = nn.functional.cross_entropy(logits, targets)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach()) * len(indices)
            correct += int((logits.argmax(1) == targets).sum())
        else:
            completed += 1
        row = {
            "model": name,
            "epoch": epoch + 1,
            "complete": completed == epoch + 1,
            "seconds": time.monotonic() - began,
            "train_loss": total_loss / len(x),
            "train_accuracy": correct / len(x),
            "exposure_examples_per_full_epoch": len(x),
        }
        with epoch_log.open("a") as log:
            log.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)
        scheduler.step()
        if completed != epoch + 1:
            break
    return completed


def train(args):
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + args.wall_seconds
    # A physical GPU index is explicit; this process never touches local GPUs.
    torch.cuda.set_device(args.gpu_index)
    torch.set_num_threads(2)
    # CUDA/cuDNN engine benchmarking failed before the first gradient on this
    # environment. Use the ordinary supported engine for EVERY subject, not
    # outcome-dependent settings or altered exposure.
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.enabled = False
    random.seed(92027)
    np.random.seed(92027)
    archive = args.archive.resolve(strict=True) if args.archive else acquire(root)
    x, y, tx, ty = load_archive(archive)
    rng = np.random.default_rng(92027)
    order = rng.permutation(len(x))
    train_ids, dev_ids, target_ids = order[:40000], order[40000:45000], order[45000:]
    for name, ids in (
        ("train", train_ids),
        ("development-calibration", dev_ids),
        ("confirmation-calibration", target_ids),
    ):
        np.savez_compressed(root / (name + ".npz"), image_id=ids, images=x[ids], labels=y[ids])
    test_ids = rng.permutation(len(tx))
    np.savez_compressed(
        root / "development-query.npz",
        image_id=test_ids[:5000],
        images=tx[test_ids[:5000]],
        labels=ty[test_ids[:5000]],
    )
    np.savez_compressed(
        root / "confirmation-query.npz",
        image_id=test_ids[5000:],
        images=tx[test_ids[5000:]],
        labels=ty[test_ids[5000:]],
    )
    queue = [("development", 0), ("development", 1), ("confirmation", 0), ("confirmation", 1)]
    queue += [
        (role, i)
        for i in range(2, args.blocks_per_split)
        for role in ("development", "confirmation")
    ]
    contract = {
        "schema_version": "1.0",
        "task_family": "weightspace-evidence-transfer",
        "frozen_at": datetime.now(UTC).isoformat(),
        "seed": 92027,
        "archive_sha256": digest(archive),
        "source_module_sha256": digest(Path(__file__)),
        "epochs": args.epochs,
        "shared_prefix_epochs": args.epochs // 2,
        "images_per_epoch": 40000,
        "batch_size": 512,
        "gpu_index": args.gpu_index,
        "gpu_uuid": str(torch.cuda.get_device_properties(args.gpu_index).uuid),
        "process_id": os.getpid(),
        "optimizer": "AdamW",
        "parent_learning_rate": 0.001,
        "branch_learning_rates": [0.0005, 0.001, 0.0015],
        "wall_seconds": args.wall_seconds,
        "queue": queue,
        "models_per_block": 6,
        "exposure_matching": "shared prefix+branch = independent total epochs",
        "subject_scope": "small from-scratch CNNs, not foundation-model fine-tuning replication",
        "formal_evidence_eligible": False,
        "redistribution_authorized": False,
        "no_quality_based_model_filtering": True,
        "cudnn_benchmark": False,
        "cudnn_enabled": False,
        "precision": "float32",
        "engineering_recovery": (
            {
                "original_training_contract": str(args.inherit_failed.resolve()),
                "original_training_contract_sha256": digest(args.inherit_failed),
                "scope": "Reuse exact official data and retain the distinct prior attempts; "
                "use native CUDA float32 and a fixed AdamW recipe for all subjects; "
                "prior SGD source generation was stopped for non-learning shared subjects, "
                "not for downstream framework outcomes",
                "repair_and_original_attempt_reserved_seconds": 7200 - args.wall_seconds,
            }
            if args.inherit_failed
            else None
        ),
        "resource_mode": "remote CUDA subjects, research/confirmation may run on CPU",
    }
    retain(root / "TRAINING_CONTRACT.json", contract)
    xg = torch.from_numpy(x[train_ids]).to("cuda", dtype=torch.float32).div_(255)
    xg = xg.contiguous(memory_format=torch.channels_last)
    yg = torch.from_numpy(y[train_ids]).to("cuda")
    rows = []
    for role, block in queue:
        if time.monotonic() >= deadline:
            break
        seed = 1000 + block * 100 + (10000 if role == "confirmation" else 0)
        torch.manual_seed(seed)
        parent = ResearchCNN().cuda().to(memory_format=torch.channels_last)
        prefix = fit(
            parent,
            xg,
            yg,
            epochs=args.epochs // 2,
            seed=seed,
            lr=0.001,
            deadline=deadline,
            epoch_log=root / "epochs.jsonl",
            name=f"{role}-{block}-parent",
        )
        parent_state = {k: v.detach().cpu().clone() for k, v in parent.state_dict().items()}
        for kind in ("shared", "independent"):
            for branch, lr in enumerate((0.0005, 0.001, 0.0015)):
                name = f"{role}-{block}-{kind}-{branch}"
                torch.manual_seed(seed + branch + (1000 if kind == "independent" else 1))
                model = ResearchCNN().cuda().to(memory_format=torch.channels_last)
                if kind == "shared":
                    model.load_state_dict(parent_state)
                epochs = args.epochs - prefix if kind == "shared" else args.epochs
                complete = fit(
                    model,
                    xg,
                    yg,
                    epochs=epochs,
                    seed=seed + 20 + branch,
                    lr=lr,
                    deadline=deadline,
                    epoch_log=root / "epochs.jsonl",
                    name=name,
                )
                path = root / "checkpoints" / (name + ".pt")
                path.parent.mkdir(exist_ok=True)
                torch.save(
                    {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}, path
                )
                rows.append(
                    {
                        "name": name,
                        "split": role,
                        "block": block,
                        "kind": kind,
                        "branch": branch,
                        "learning_rate": lr,
                        "sha256": digest(path),
                        "epochs_completed": complete + (prefix if kind == "shared" else 0),
                        "complete": complete == epochs
                        and (kind != "shared" or prefix == args.epochs // 2),
                        "path": str(path.relative_to(root)),
                    }
                )
                retain(root / "receipts" / (name + ".json"), rows[-1])
                del model
                if time.monotonic() >= deadline:
                    break
            if time.monotonic() >= deadline:
                break
        del parent
    retain(
        root / "RESULT.json",
        {
            "status": "completed"
            if len(rows) == len(queue) * 6 and all(r["complete"] for r in rows)
            else "budget-stopped-partial",
            "elapsed_seconds": time.monotonic() - started,
            "models": rows,
            "training_contract_sha256": digest(root / "TRAINING_CONTRACT.json"),
            "actual_gpu_hours": None,
            "allocated_single_gpu_wall_hours": (time.monotonic() - started) / 3600,
            "task_families": 1,
            "framework_runs": 0,
            "scientific_effectiveness_demonstrated": False,
        },
    )
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--archive", type=Path)
    p.add_argument("--gpu-index", type=int, default=6)
    p.add_argument("--epochs", type=int, default=16)
    p.add_argument("--blocks-per-split", type=int, default=4)
    p.add_argument("--wall-seconds", type=int, default=7200)
    p.add_argument("--inherit-failed", type=Path)
    args = p.parse_args()
    if args.epochs < 4 or args.epochs % 2 or not 2 <= args.blocks_per_split <= 4:
        raise ValueError("Matched full-epoch blocks required")
    if args.gpu_index != 6 or not 1 <= args.wall_seconds <= 7200:
        raise ValueError("Only the declared idle remote card and two-hour ceiling are authorized")
    try:
        code = train(args)
    except Exception as exc:
        if args.output.is_dir() and not (args.output / "FAILED.json").exists():
            retain(
                args.output / "FAILED.json",
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                    "scientific_results_imputed": False,
                },
            )
        raise
    raise SystemExit(code)


if __name__ == "__main__":
    main()

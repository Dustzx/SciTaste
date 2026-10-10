"""Inspect three exact source members, without training or admitting a task."""

import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path

import numpy as np

from scitaste.model_nodes.session_exchange import retain_json

MOLECULES = ("ethanol", "malonaldehyde", "aspirin")


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    receipt_path = source / "RECEIPT.json"
    receipt = json.loads(receipt_path.read_text())
    archive = source / "rmd17.tar.bz2"
    if (
        receipt["status"] != "source-acquired-not-task-admitted"
        or archive.is_symlink()
        or digest(archive) != receipt["sha256"]
    ):
        raise ValueError("Source is incomplete or differs from acquisition evidence")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    selected = {f"rmd17/npz_data/rmd17_{name}.npz": name for name in MOLECULES}
    rows = []
    with tarfile.open(archive, "r|bz2") as bundle:
        for member in bundle:
            if member.name not in selected:
                continue
            if not member.isfile() or member.size > 250_000_000:
                raise ValueError("Expected bounded regular molecular source member")
            name = selected[member.name]
            with bundle.extractfile(member) as stream:
                raw = stream.read(250_000_001)
            if len(raw) != member.size:
                raise ValueError("Incomplete molecular member")
            path = output / f"rmd17_{name}.npz"
            with path.open("xb") as stream:
                stream.write(raw)
            with np.load(io.BytesIO(raw), allow_pickle=False) as arrays:
                required = {"nuclear_charges", "coords", "energies", "forces", "old_indices"}
                if not required.issubset(arrays.files):
                    raise ValueError("Unexpected molecular source schema")
                charges = arrays["nuclear_charges"]
                coords, forces = arrays["coords"], arrays["forces"]
                energy, indices = arrays["energies"], arrays["old_indices"]
                n, atoms = len(coords), len(charges)
                if (
                    n != 100_000
                    or coords.shape != (n, atoms, 3)
                    or forces.shape != coords.shape
                    or energy.shape not in {(n,), (n, 1)}
                    or charges.ndim != 1
                    or not np.issubdtype(charges.dtype, np.integer)
                    or indices.shape != (n,)
                    or not np.issubdtype(indices.dtype, np.integer)
                    or len(np.unique(indices)) != n
                    or not all(np.isfinite(arrays[key]).all() for key in required)
                ):
                    raise ValueError("Invalid molecular source geometry/chronology")
                rows.append(
                    {
                        "molecule": name,
                        "member": member.name,
                        "bytes": member.size,
                        "sha256": digest(path),
                        "frames": n,
                        "atoms": atoms,
                        "array_shapes": {key: list(arrays[key].shape) for key in arrays.files},
                        "atomic_numbers": charges.tolist(),
                        "original_index_range": [int(indices.min()), int(indices.max())],
                        "stored_order_is_chronological": bool(np.all(np.diff(indices) > 0)),
                        "chronology_field": "old_indices",
                        "source_labels_kept_author_private": True,
                    }
                )
                print(json.dumps(rows[-1]), flush=True)
    if {row["molecule"] for row in rows} != set(MOLECULES):
        raise ValueError("Source archive lacks the exact required molecular members")
    result = {
        "source_receipt_sha256": digest(receipt_path),
        "source_archive_sha256": receipt["sha256"],
        "status": "source-members-inspected-not-task-materialized",
        "members": rows,
        "independent_task_families": 0,
        "raw_observations_are_newly_collected": False,
        "task_admitted": False,
        "models_executed": False,
        "gpu_used": False,
        "remaining": (
            "Freeze scientific task, label-blind grouping and evaluator before experiments"
        ),
    }
    retain_json(output / "SOURCE_INSPECTION.json", result)
    print(json.dumps({"status": result["status"], "members": len(rows)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

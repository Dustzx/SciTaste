"""Retain verified raw FMD captures only; no averaging, task admission or models."""

import argparse
import hashlib
import io
import json
import re
import tarfile
import time
from pathlib import Path, PurePosixPath

import numpy as np
from PIL import Image

from scitaste.model_nodes.session_exchange import retain_json

from .acquire_fmd_source import ARTIFACTS


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            sha.update(chunk)
    return sha.hexdigest()


def inspect(source, output, name):
    receipt_path = source / f"{name}.RECEIPT.json"
    receipt = json.loads(receipt_path.read_text())
    archive = source / f"{name}.tar"
    if (
        receipt["status"] != "source-acquired-not-task-materialized"
        or receipt["bytes"] != ARTIFACTS[name][1]
        or receipt["md5"] != ARTIFACTS[name][2]
        or archive.is_symlink()
        or digest(archive) != receipt["sha256"]
    ):
        raise ValueError("Archive differs from official-checksum acquisition evidence")
    rows, seen = [], set()
    ignored = 0
    began = time.monotonic()
    with tarfile.open(archive, "r|") as bundle:
        for member in bundle:
            path = PurePosixPath(member.name)
            if "raw" not in path.parts or path.suffix.lower() != ".png":
                ignored += 1
                continue
            if path.is_absolute() or ".." in path.parts or not member.isfile():
                raise ValueError("Raw capture must be a contained regular TAR member")
            i = path.parts.index("raw")
            if len(path.parts) != i + 3 or not path.parts[i + 1].isdigit():
                raise ValueError("Unexpected raw-capture hierarchy")
            fov = int(path.parts[i + 1])
            match = re.search(r"(\d{4})\.png$", path.name, re.IGNORECASE)
            if not match or fov not in range(1, 21):
                raise ValueError("Unexpected source FOV or capture identity")
            capture = int(match[1])
            if capture not in range(50) or (fov, capture) in seen or member.size > 2_000_000:
                raise ValueError("Duplicate, out-of-range or oversized raw capture")
            seen.add((fov, capture))
            with bundle.extractfile(member) as stream:
                raw = stream.read(2_000_001)
            if len(raw) != member.size:
                raise ValueError("Truncated raw capture")
            with Image.open(io.BytesIO(raw)) as image:
                if image.size != (512, 512) or image.mode != "L":
                    raise ValueError("Require original 512x512 8-bit grayscale captures")
                pixels = np.asarray(image)
                if pixels.dtype != np.uint8 or pixels.shape != (512, 512):
                    raise ValueError("Unexpected raw-capture numerical representation")
                mean = float(pixels.mean())
                clipped = float(np.mean(pixels == 255))
                pixel_sha = hashlib.sha256(pixels.tobytes()).hexdigest()
            relative = f"private/raw/{name}/{fov}/{capture:04d}.png"
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(raw)
            rows.append(
                {
                    "fov": fov,
                    "capture": capture,
                    "source_member": member.name,
                    "relative_path": relative,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "pixel_sha256": pixel_sha,
                    "mean_pixel_value": mean,
                    "upper_clipped_fraction": clipped,
                }
            )
    expected = {(fov, capture) for fov in range(1, 21) for capture in range(50)}
    if seen != expected:
        raise ValueError("Source must cover every raw FOV/capture exactly once")
    result = {
        "modality_source": name,
        "acquisition_receipt_sha256": digest(receipt_path),
        "archive_sha256": receipt["sha256"],
        "raw_frames": len(rows),
        "fov_identifiers": 20,
        "captures_per_fov": 50,
        "ignored_averages_or_other_members": ignored,
        "seconds": time.monotonic() - began,
        "frames": rows,
        "frame_count_is_not_independent_task_count": True,
    }
    retain_json(output / f"private/{name}.json", result)
    print(
        json.dumps({k: result[k] for k in ("modality_source", "raw_frames", "seconds")}), flush=True
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = [path.resolve(strict=True) for path in args.sources]
    bindings = {}
    for name in ARTIFACTS:
        choices = []
        for source in sources:
            receipt = source / f"{name}.RECEIPT.json"
            if (
                receipt.exists()
                and json.loads(receipt.read_text())["status"]
                == "source-acquired-not-task-materialized"
            ):
                choices.append(source)
        if len(choices) != 1:
            raise ValueError("Require one successful original/recovery archive per modality")
        bindings[name] = choices[0]
    output = args.output.resolve()
    if any(output.is_relative_to(source) or source.is_relative_to(output) for source in sources):
        raise ValueError("Inspection must not overlap immutable acquisition directories")
    output.mkdir(parents=True, exist_ok=False)
    (output / "private").mkdir()
    metadata = [json.loads((source / "SOURCE.json").read_text()) for source in sources]
    if any(m["license"]["name"] != "CC BY-SA 4.0" for m in metadata):
        raise ValueError("Source rights mismatch")
    retain_json(
        output / "PLAN.json",
        {
            "archives": {name: str(source / f"{name}.tar") for name, source in bindings.items()},
            "raw_capture_policy": (
                "exact 20 FOVs x 50 raw captures per modality, no source averages"
            ),
            "frame_values_drive_task_split": False,
            "license": "CC BY-SA 4.0; source attribution/share-alike required",
            "models_or_gpu_allowed": False,
        },
    )
    rows = [inspect(source, output, name) for name, source in bindings.items()]
    all_pixels = [frame["pixel_sha256"] for row in rows for frame in row["frames"]]
    result = {
        "status": "raw-source-inspected-not-task-materialized",
        "modalities": len(rows),
        "raw_captures": len(all_pixels),
        "nominal_fov_identifiers": 60,
        "repeated_identical_pixel_arrays": len(all_pixels) - len(set(all_pixels)),
        "cross_modality_physical_fov_identity": (
            "unresolved; integer folder IDs do not establish physical identity"
        ),
        "independent_task_families_delivered": 0,
        "models_or_gpu_executed": False,
        "source_averages_retained": False,
        "next": (
            "freeze disjoint input/reference groups, conservative FOV splits "
            "and reliable scientific endpoints before experiments"
        ),
    }
    retain_json(output / "SOURCE_INSPECTION.json", result)
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Acquire three rights/metadata-bound microscopy archives, not a task or experiment.

Author mirrors are accepted only if the complete bytes match the institution's
size and MD5. Downloads preserve failures and never execute the author's shell code.
"""

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json

METADATA = "https://api.figshare.com/v2/articles/24744648"
SOURCE_PIN = "d83cad96b205793da0f62f6dc8094799d61929e6"
AUTHOR_SCRIPT = (
    "https://raw.githubusercontent.com/yinhaoz/denoising-fluorescence/"
    f"{SOURCE_PIN}/denoising/download_dataset.sh"
)
ARTIFACTS = {
    "Confocal_BPAE_G": (
        "1Zofz11VmI1JfRIMF7rq40RVjpzM6A9vg",
        790_200_320,
        "20b796d0c502c33ffe4154f49c6e8bed",
    ),
    "TwoPhoton_BPAE_G": (
        "125nqTfQQG1-YVUs256b2vTwt4aUNCgBt",
        873_267_200,
        "ea03cc60d3335ba17e2e14fc18481f08",
    ),
    "WideField_BPAE_G": (
        "1H67O6GqIkIlQSX-n0vfMWGPwmd4zOHQr",
        792_780_800,
        "7e2e734f83bf6609bd2fe876f4a54345",
    ),
}
HEADERS = {"User-Agent": "SciTaste-scientific-source/1.0"}


def metadata_bytes(url, maximum=2_000_000):
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=HEADERS), timeout=60
    ) as response:
        content = response.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("Metadata exceeds bounded snapshot")
    return content


def acquire(directory, name, specification):
    identifier, expected_bytes, expected_md5 = specification
    url = "https://drive.usercontent.google.com/download?" + urllib.parse.urlencode(
        {"id": identifier, "export": "download", "confirm": "t"}
    )
    started = time.monotonic()
    receipt = {
        "artifact": name,
        "source_metadata": METADATA,
        "source_pin": SOURCE_PIN,
        "mirror_url": url,
        "expected_bytes": expected_bytes,
        "expected_md5": expected_md5,
        "status": "failed",
        "task_admitted": False,
        "model_or_gpu_experiment": False,
        "started_at": datetime.now(UTC).isoformat(),
    }
    partial = directory / f"{name}.tar.partial"
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
    size, report = 0, 0
    try:
        with (
            urllib.request.urlopen(
                urllib.request.Request(url, headers=HEADERS), timeout=120
            ) as response,
            partial.open("xb") as stream,
        ):
            length = response.headers.get("Content-Length")
            if length is not None and int(length) != expected_bytes:
                raise ValueError("Mirror length differs from official metadata")
            if "text/html" in response.headers.get("Content-Type", ""):
                raise ValueError("Mirror returned an HTML confirmation page, not source data")
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > expected_bytes:
                    raise ValueError("Mirror body exceeds exact authorized source size")
                sha.update(chunk)
                md5.update(chunk)
                stream.write(chunk)
                if size - report >= 64 * 1024 * 1024:
                    elapsed = time.monotonic() - started
                    speed = size / max(elapsed, 0.001)
                    print(
                        json.dumps(
                            {
                                "artifact": name,
                                "bytes": size,
                                "bytes_per_second": speed,
                                "remaining_seconds_estimate": (expected_bytes - size) / speed,
                            }
                        ),
                        flush=True,
                    )
                    report = size
        if size != expected_bytes or md5.hexdigest() != expected_md5:
            raise ValueError("Mirror checksum/size does not match the institution's source")
        partial.rename(directory / f"{name}.tar")
        receipt.update(status="source-acquired-not-task-materialized", sha256=sha.hexdigest())
    except Exception as exc:
        receipt.update(error_type=type(exc).__name__, error=str(exc))
    receipt.update(bytes=size, md5=md5.hexdigest(), elapsed_seconds=time.monotonic() - started)
    retain_json(directory / f"{name}.RECEIPT.json", receipt)
    print(
        json.dumps({k: receipt[k] for k in ("artifact", "status", "bytes", "elapsed_seconds")}),
        flush=True,
    )
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", nargs="+", choices=tuple(ARTIFACTS), default=list(ARTIFACTS))
    parser.add_argument("--recovery-of", type=Path)
    args = parser.parse_args()
    if len(set(args.artifacts)) != len(args.artifacts):
        parser.error("Select unique source artifacts")
    recovery = None
    if args.recovery_of:
        failed_path = args.recovery_of.resolve(strict=True)
        failed = json.loads(failed_path.read_text())
        if (
            len(args.artifacts) != 1
            or failed.get("status") != "failed"
            or failed.get("artifact") != args.artifacts[0]
            or failed.get("expected_md5") != ARTIFACTS[args.artifacts[0]][2]
        ):
            raise ValueError("Recovery must bind the exact original failed artifact")
        recovery = {
            "path": str(failed_path),
            "sha256": hashlib.sha256(failed_path.read_bytes()).hexdigest(),
        }
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    raw = metadata_bytes(METADATA)
    (output / "SOURCE.json").write_bytes(raw)
    source = json.loads(raw)
    if source["license"].get("name") != "CC BY-SA 4.0" or source["doi"] != "10.7274/r0-ed2r-4052":
        raise ValueError("Official source rights/identity changed; do not silently reinterpret")
    script = metadata_bytes(AUTHOR_SCRIPT, maximum=100_000)
    (output / "AUTHOR_DOWNLOAD_SOURCE.sh").write_bytes(script)
    for name, (identifier, expected_bytes, expected_md5) in ARTIFACTS.items():
        row = next(f for f in source["files"] if f["name"] == f"{name}.tar")
        if (
            row["size"] != expected_bytes
            or row["computed_md5"] != expected_md5
            or f"{name}={identifier}" not in script.decode()
        ):
            raise ValueError("Artifact does not match frozen official metadata/author mirror")
    selected = {name: ARTIFACTS[name] for name in args.artifacts}
    total = sum(spec[1] for spec in selected.values())
    if total >= 10_000_000_000:
        raise ValueError("Source selection exceeds standing automatic acquisition scope")
    retain_json(
        output / "PLAN.json",
        {
            "source_metadata_sha256": hashlib.sha256(raw).hexdigest(),
            "author_script_sha256": hashlib.sha256(script).hexdigest(),
            "artifacts": selected,
            "total_bytes": total,
            "concurrent_downloads": 2,
            "license": (
                "CC BY-SA 4.0; derived data redistribution preserves attribution/share-alike"
            ),
            "endpoint_warning": (
                "official avg50 includes noisy inputs; "
                "do not call it an independent clean reference"
            ),
            "source_acquisition_only": True,
            "retries": 0,
            "separately_registered_recovery": recovery,
        },
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda item: acquire(output, *item), selected.items()))
    complete = all(r["status"] == "source-acquired-not-task-materialized" for r in receipts)
    result = {
        "status": "source-acquired-not-task-materialized"
        if complete
        else "source-acquisition-incomplete",
        "artifacts": [
            {k: r.get(k) for k in ("artifact", "status", "sha256", "bytes", "error")}
            for r in receipts
        ],
        "expected_bytes": total,
        "independent_task_families_delivered": 0,
        "models_or_gpu_used": False,
        "formal_task_admitted": False,
    }
    retain_json(output / "RECEIPT.json", result)
    print(json.dumps(result), flush=True)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())

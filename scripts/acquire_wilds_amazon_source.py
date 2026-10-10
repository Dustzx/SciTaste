"""Acquire a bounded official natural-user-shift source, not an experiment."""

import argparse
import hashlib
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json

PIN = "472677590de351857197a9bf24958838c39c272b"
SOURCE = f"https://raw.githubusercontent.com/p-lambda/wilds/{PIN}/wilds/datasets/amazon_dataset.py"
URL = (
    "https://worksheets.codalab.org/rest/bundles/0xe3ed909786d34ee79d430d065582aa29/contents/blob/"
)
EXPECTED_ESTIMATE = 1_989_805_589
MAXIMUM_BYTES = 2_500_000_000
HEADERS = {"User-Agent": "SciTaste-source-acquisition/1.0"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    receipt = {
        "source": SOURCE,
        "source_pin": PIN,
        "url": URL,
        "dataset_version": "2.1",
        "started_at": datetime.now(UTC).isoformat(),
        "status": "failed",
        "maximum_bytes": MAXIMUM_BYTES,
        "historical_compressed_size": EXPECTED_ESTIMATE,
        "upstream_archive_checksum_available": False,
        "license": "Research-use-only; no explicit redistribution license",
        "redistribution_authorized": False,
        "task_admitted": False,
        "model_calls": 0,
        "gpu_used": False,
    }
    partial = output / "amazon_v2.1.tar.gz.partial"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(SOURCE, headers=HEADERS), timeout=60
        ) as r:
            metadata = r.read(100_001)
        if len(metadata) > 100_000:
            raise ValueError("Source metadata exceeded its bound")
        text = metadata.decode()
        if URL not in text or "research purposes only" not in text:
            raise ValueError("Official version or use restrictions changed")
        (output / "UPSTREAM_DATASET.py.txt").write_bytes(metadata)
        receipt["source_metadata_sha256"] = hashlib.sha256(metadata).hexdigest()
        sha, total, last = hashlib.sha256(), 0, 0
        download_start = time.monotonic()
        with urllib.request.urlopen(urllib.request.Request(URL, headers=HEADERS), timeout=120) as r:
            if "text/html" in r.headers.get("Content-Type", ""):
                raise ValueError("Official source returned HTML rather than an archive")
            with partial.open("xb") as stream:
                while chunk := r.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAXIMUM_BYTES:
                        raise ValueError("Source exceeds the automatic download allowance")
                    stream.write(chunk)
                    sha.update(chunk)
                    if total - last >= 64 * 1024 * 1024:
                        elapsed = time.monotonic() - download_start
                        speed = total / max(elapsed, 0.001)
                        print(
                            json.dumps(
                                {
                                    "bytes": total,
                                    "bytes_per_second": speed,
                                    "remaining_seconds_estimate": max(0, EXPECTED_ESTIMATE - total)
                                    / speed,
                                }
                            ),
                            flush=True,
                        )
                        last = total
        if total < 1_000_000_000:
            raise ValueError("Official source is unexpectedly short")
        partial.rename(output / "amazon_v2.1.tar.gz")
        receipt.update(
            status="source-acquired-not-task-admitted",
            archive="amazon_v2.1.tar.gz",
            bytes=total,
            sha256=sha.hexdigest(),
        )
    except Exception as exc:
        receipt.update(
            error_type=type(exc).__name__,
            error=str(exc),
            retained_partial_bytes=partial.stat().st_size if partial.exists() else 0,
        )
    receipt["elapsed_seconds"] = time.monotonic() - started
    retain_json(output / "RECEIPT.json", receipt)
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"].startswith("source-acquired") else 1


if __name__ == "__main__":
    raise SystemExit(main())

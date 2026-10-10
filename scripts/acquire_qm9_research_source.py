"""Acquire official QM9 bytes and metadata; never execute or grade a researcher."""

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from scitaste.model_nodes.session_exchange import retain_json

ITEMS = (1057646, 1057644, 1057641)
LIMIT = 10_000_000_000


def acquire(item, output):
    response = requests.get(f"https://api.figshare.com/v2/articles/{item}", timeout=60)
    response.raise_for_status()
    metadata = response.json()
    retain_json(output / f"item-{item}.json", metadata)
    if metadata["license"]["url"] != "https://creativecommons.org/publicdomain/zero/1.0/":
        raise ValueError("Official dataset rights declaration needs review")
    results = []
    for spec in metadata["files"]:
        if not 0 < spec["size"] < LIMIT or Path(spec["name"]).name != spec["name"]:
            raise ValueError("Download exceeds authorization or unsafe source name")
        path = output / spec["name"]
        started = time.monotonic()
        sha, md5, count = hashlib.sha256(), hashlib.md5(), 0
        with requests.get(spec["download_url"], stream=True, timeout=(30, 90)) as download:
            download.raise_for_status()
            with path.open("xb") as stream:
                for chunk in download.iter_content(1 << 20):
                    count += len(chunk)
                    if count > spec["size"] or count > LIMIT:
                        raise ValueError("Unexpected response size")
                    stream.write(chunk)
                    sha.update(chunk)
                    md5.update(chunk)
        if count != spec["size"] or md5.hexdigest() != spec["computed_md5"]:
            raise ValueError("Official source length/checksum mismatch; retain failure bytes")
        record = {
            "item": item,
            "file_id": spec["id"],
            "name": path.name,
            "bytes": count,
            "sha256": sha.hexdigest(),
            "official_md5": md5.hexdigest(),
            "download_seconds": time.monotonic() - started,
            "license": metadata["license"],
            "url": spec["download_url"],
        }
        results.append(record)
        print(json.dumps(record), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with ThreadPoolExecutor(3) as pool:
        rows = [
            row
            for result in pool.map(lambda item: acquire(item, args.output), ITEMS)
            for row in result
        ]
    retain_json(
        args.output / "ACQUISITION.json",
        {
            "source": "QM9 official Figshare",
            "files": rows,
            "prediction_results_inspected": False,
            "gpu_use": False,
            "model_calls": 0,
        },
    )


if __name__ == "__main__":
    main()

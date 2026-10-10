"""Acquire the author-linked M4 monthly archive, not any research outcome."""

import argparse
import hashlib
import time
from pathlib import Path

import requests

from scitaste.model_nodes.session_exchange import retain_json

RECORD = 4656480
FILE = "m4_monthly_dataset.zip"
EXPECTED_SIZE = 28_235_874
EXPECTED_MD5 = "1e304a80fbd6fa93a3ce8360bd3eafa2"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    response = requests.get(f"https://zenodo.org/api/records/{RECORD}", timeout=(15, 45))
    response.raise_for_status()
    metadata = response.json()
    retain_json(args.output / "SOURCE_METADATA.json", metadata)
    specs = metadata["files"]
    if (
        metadata["metadata"]["license"]["id"] != "cc-by-4.0"
        or len(specs) != 1
        or specs[0]["key"] != FILE
        or specs[0]["size"] != EXPECTED_SIZE
        or specs[0]["checksum"] != f"md5:{EXPECTED_MD5}"
    ):
        raise ValueError("Author-linked version/size/rights/hash changed; do not guess a successor")
    spec = specs[0]
    sha, md5, count = hashlib.sha256(), hashlib.md5(), 0
    started = time.monotonic()
    with requests.get(spec["links"]["self"], stream=True, timeout=(15, 90)) as download:
        download.raise_for_status()
        with (args.output / FILE).open("xb") as stream:
            for chunk in download.iter_content(1 << 20):
                count += len(chunk)
                if count > EXPECTED_SIZE:
                    raise ValueError("Unexpected acquisition size")
                stream.write(chunk)
                sha.update(chunk)
                md5.update(chunk)
    if count != EXPECTED_SIZE or md5.hexdigest() != EXPECTED_MD5:
        raise ValueError("Official archive checksum/length mismatch; retain original failure bytes")
    receipt = {
        "source": "Author-linked Monash M4 monthly Zenodo version 3",
        "record": RECORD,
        "doi": metadata["metadata"]["doi"],
        "license": metadata["metadata"]["license"],
        "file": FILE,
        "bytes": count,
        "sha256": sha.hexdigest(),
        "official_md5": md5.hexdigest(),
        "download_seconds": time.monotonic() - started,
        "source_url": spec["links"]["self"],
        "model_calls": 0,
        "research_outcomes_inspected": False,
        "gpu_use": False,
        "scope": "Acquisition only; task admission and actual system outcomes are separate",
    }
    retain_json(args.output / "ACQUISITION.json", receipt)
    print(receipt)


if __name__ == "__main__":
    main()

"""Acquire a bounded original ACS PUMS source, not a benchmark outcome."""

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from scitaste.model_nodes.session_exchange import retain_json

FILES = ((2014, "ca"), (2014, "tx"), (2018, "ca"), (2018, "ny"))
MAX_BYTES_PER_FILE = 250_000_000
TERMS = "https://www.census.gov/data/developers/about/terms-of-service.html"


def acquire_one(output, year, state):
    url = f"https://www2.census.gov/programs-surveys/acs/data/pums/{year}/1-Year/csv_p{state}.zip"
    name = f"acs-{year}-{state}-person.zip"
    started = time.monotonic()
    sha, count = hashlib.sha256(), 0
    try:
        with requests.get(url, stream=True, timeout=(15, 90)) as response:
            response.raise_for_status()
            advertised = int(response.headers.get("Content-Length", "0"))
            if advertised > MAX_BYTES_PER_FILE:
                raise ValueError("Source exceeds the fixed per-file acquisition ceiling")
            with (output / name).open("xb") as stream:
                for chunk in response.iter_content(1 << 20):
                    count += len(chunk)
                    if count > MAX_BYTES_PER_FILE:
                        raise ValueError("Stream exceeds the fixed acquisition ceiling")
                    stream.write(chunk)
                    sha.update(chunk)
            if advertised and count != advertised:
                raise ValueError("Incomplete original source download")
            record = {
                "year": year,
                "state": state,
                "file": name,
                "url": url,
                "bytes": count,
                "sha256": sha.hexdigest(),
                "official_checksum": None,
                "official_checksum_available": False,
                "http_last_modified": response.headers.get("Last-Modified"),
                "advertised_bytes": advertised or None,
                "elapsed_seconds": time.monotonic() - started,
                "status": "acquired",
                "source_statistical_outcomes_inspected": False,
            }
            retain_json(output / (name + ".receipt.json"), record)
            return record
    except Exception as exc:
        retain_json(
            output / (name + ".failure.json"),
            {
                "error_type": type(exc).__name__,
                "detail": str(exc),
                "received_bytes": count,
                "partial_bytes_retained": True,
                "automatic_retry": False,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    retain_json(
        args.output / "CONTRACT.json",
        {
            "source": "Original Census Bureau ACS one-year person PUMS",
            "files": [{"year": year, "state": state} for year, state in FILES],
            "maximum_total_bytes": len(FILES) * MAX_BYTES_PER_FILE,
            "parallel_downloads": 2,
            "gpu_enabled": False,
            "model_calls": 0,
            "terms": TERMS,
            "research_scope": (
                "Statistical classification/calibration under population shift; "
                "no re-identification, external identity linkage or individual deployment"
            ),
            "release_scope": (
                "Local research acquisition; software MIT is not a data license. "
                "Public redistribution of raw/derived records not approved"
            ),
            "endpoint_selection_before_model_results": True,
            "counts_as_admitted_task": False,
        },
    )
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(acquire_one, args.output, year, state) for year, state in FILES]
        records = [job.result() for job in jobs]
    result = {
        "schema_version": "scitaste.acs-acquisition.v1",
        "status": "acquired-original-statistical-source",
        "records": records,
        "total_bytes": sum(row["bytes"] for row in records),
        "elapsed_seconds": time.monotonic() - started,
        "data_rights": {"terms": TERMS, "redistribution_approved": False},
        "task_admission": False,
        "system_results": False,
    }
    retain_json(args.output / "ACQUISITION.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()

"""Acquire one official CC0 research source; no task admission or model execution."""

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from scitaste.model_nodes.session_exchange import retain_json

RECORD = "https://archive.materialscloud.org/record/2020.82"
EXPECTED_BYTES = 1_066_301_513
EXPECTED_MD5 = "cb1a927628d96f2e966025da4fb63d18"
MAXIMUM_BYTES = 1_200_000_000


class ArchiveLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if "rmd17.tar.bz2" in href:
                self.links.append(urllib.parse.urljoin(RECORD, href))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    partial = directory / "rmd17.tar.bz2.partial"
    receipt = {
        "source_record": RECORD,
        "source_doi": "10.24435/materialscloud:wy-kn",
        "started_at": datetime.now(UTC).isoformat(),
        "expected_bytes": EXPECTED_BYTES,
        "expected_md5": EXPECTED_MD5,
        "maximum_bytes": MAXIMUM_BYTES,
        "status": "failed",
        "task_admitted": False,
        "research_framework_executed": False,
        "gpu_used": False,
        "api_calls": 0,
    }
    headers = {"User-Agent": "SciTaste-research-source/1.0"}
    try:
        with urllib.request.urlopen(
            urllib.request.Request(RECORD, headers=headers), timeout=60
        ) as response:
            page = response.read(2_000_001)
        if len(page) > 2_000_000:
            raise ValueError("Official metadata exceeds the bounded source snapshot")
        (directory / "SOURCE.html").write_bytes(page)
        text = page.decode("utf-8")
        if "cc0-1.0" not in text or EXPECTED_MD5 not in text:
            raise ValueError("Official source license/checksum differs; do not silently adapt")
        links = ArchiveLinks()
        links.feed(text)
        candidates = sorted(set(links.links))
        if not candidates or any(
            urllib.parse.urlparse(url).hostname != "archive.materialscloud.org"
            for url in candidates
        ):
            raise ValueError("Archive link is absent or outside the official distribution")
        url = next((link for link in candidates if "download" in link), candidates[0])
        receipt.update(download_url=url, license="CC0-1.0")
        sha = hashlib.sha256()
        md5 = hashlib.md5(usedforsecurity=False)
        total, last_report = 0, 0
        download_began = time.monotonic()
        with (
            urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=60
            ) as response,
            partial.open("xb") as stream,
        ):
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAXIMUM_BYTES:
                raise ValueError("Declared archive exceeds automatic acquisition scope")
            resolved = urllib.parse.urlparse(response.url)
            receipt["resolved_url"] = urllib.parse.urlunparse(resolved._replace(query=""))
            receipt["redirect_query_retained"] = False
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAXIMUM_BYTES:
                    raise ValueError("Archive exceeds automatic acquisition scope")
                stream.write(chunk)
                sha.update(chunk)
                md5.update(chunk)
                if total - last_report >= 64 * 1024 * 1024:
                    elapsed = time.monotonic() - download_began
                    speed = total / max(elapsed, 0.001)
                    print(
                        json.dumps(
                            {
                                "bytes": total,
                                "bytes_per_second": speed,
                                "remaining_seconds_estimate": max(0, EXPECTED_BYTES - total)
                                / speed,
                            }
                        ),
                        flush=True,
                    )
                    last_report = total
        receipt.update(bytes=total, sha256=sha.hexdigest(), md5=md5.hexdigest())
        if total != EXPECTED_BYTES or md5.hexdigest() != EXPECTED_MD5:
            raise ValueError("Archive differs from official immutable source checksum/size")
        partial.rename(directory / "rmd17.tar.bz2")
        receipt.update(status="source-acquired-not-task-admitted", archive="rmd17.tar.bz2")
    except Exception as error:
        receipt.update(error_type=type(error).__name__, error=str(error))
        if partial.exists():
            receipt["retained_partial_bytes"] = partial.stat().st_size
    receipt["elapsed_seconds"] = time.monotonic() - began
    retain_json(directory / "RECEIPT.json", receipt)
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "source-acquired-not-task-admitted" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Inspect a full-task suite or export its admitted public manifest; never execute it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scitaste.benchmark.full_task import (
    FullTaskSuite,
    audit_full_task_release,
    export_public_full_task_suite,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "export-public"))
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "export-public" and args.output is None:
        parser.error("export-public requires --output (a new manifest, not an asset directory)")
    if args.command == "audit" and args.output is not None:
        parser.error("audit prints its report; --output is only for export-public")
    suite = FullTaskSuite.model_validate_json(args.suite.read_text())
    if args.command == "audit":
        report = audit_full_task_release(suite, args.artifact_root)
        print(report.model_dump_json(indent=2))
        return 0 if report.ready else 2
    packet = export_public_full_task_suite(suite, args.artifact_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"public_manifest": str(args.output), "tasks": len(suite.tasks)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

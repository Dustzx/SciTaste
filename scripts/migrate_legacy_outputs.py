#!/usr/bin/env python3
"""Move unowned top-level outputs into a content-verified archive project."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from scitaste.project.legacy_outputs import (
    discover_legacy_directories,
    migrate_legacy_outputs,
    plan_legacy_output_migration,
    verify_legacy_output_archive,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outputs", nargs="?", type=Path, default=Path("outputs"))
    parser.add_argument(
        "--directory",
        action="append",
        default=[],
        help="exact top-level directory to migrate; repeat for multiple directories",
    )
    parser.add_argument(
        "--all-discovered",
        action="store_true",
        help="explicitly admit every discovered unowned top-level directory",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform atomic moves; otherwise only print the migration plan",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="rehash and verify an existing archive without moving anything",
    )
    args = parser.parse_args()
    if args.verify:
        if args.apply or args.directory or args.all_discovered:
            parser.error("--verify cannot be combined with migration options")
        result = verify_legacy_output_archive(args.outputs)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.directory and args.all_discovered:
        parser.error("choose explicit --directory values or --all-discovered, not both")
    if args.apply and not (args.directory or args.all_discovered):
        parser.error("--apply requires --directory or --all-discovered")
    names = (
        discover_legacy_directories(args.outputs)
        if args.all_discovered or not args.directory
        else tuple(args.directory)
    )
    plan = plan_legacy_output_migration(args.outputs, directory_names=names)
    if not args.apply:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "entry_count": len(plan),
                    "entries": [asdict(item) for item in plan],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    result = migrate_legacy_outputs(args.outputs, plan)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Reject result tables whose argumentative role is not explicit.

This is a narrow Writing Taste gate.  It does not judge whether results are
good; it prevents benchmark inventories, ecological leaderboards, matched
effects, and mechanism ablations from silently becoming interchangeable tables.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

_MARKER = re.compile(r"<!--\s*result-carrier:\s*([a-z0-9][a-z0-9-]*)\s*-->")
_TABLE_START = re.compile(r"^\|.+\|\s*$")
_TABLE_SEPARATOR = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")


def _table_markers(manuscript: str) -> tuple[str, ...]:
    lines = manuscript.splitlines()
    markers: list[str] = []
    pending: str | None = None
    for index, line in enumerate(lines):
        match = _MARKER.fullmatch(line.strip())
        if match:
            if pending is not None:
                raise ValueError(f"carrier {pending!r} has no table")
            pending = match.group(1)
            continue
        if _TABLE_START.fullmatch(line) and index + 1 < len(lines):
            if not _TABLE_SEPARATOR.fullmatch(lines[index + 1]):
                continue
            if pending is None:
                raise ValueError(f"unregistered result table at line {index + 1}")
            markers.append(pending)
            pending = None
    if pending is not None:
        raise ValueError(f"carrier {pending!r} has no table")
    if len(markers) != len(set(markers)):
        raise ValueError("a result carrier may materialize at most one table")
    return tuple(markers)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manuscript", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    carriers = contract.get("carriers")
    if contract.get("schema_version") != "1.0" or not isinstance(carriers, list):
        raise ValueError("invalid result-carrier contract")
    by_id = {item["carrier_id"]: item for item in carriers}
    if len(by_id) != len(carriers):
        raise ValueError("result carrier IDs must be unique")

    observed = set(_table_markers(args.manuscript.read_text(encoding="utf-8")))
    unknown = observed - set(by_id)
    if unknown:
        raise ValueError(f"manuscript references unknown result carriers: {sorted(unknown)}")
    expected = {
        carrier_id
        for carrier_id, item in by_id.items()
        if item.get("placement") == "main" and item.get("status") == "available"
    }
    if observed != expected:
        raise ValueError(
            "main-text result carriers differ from the available contract: "
            f"missing={sorted(expected - observed)}, unexpected={sorted(observed - expected)}"
        )
    for carrier_id in observed:
        item = by_id[carrier_id]
        scope = item.get("claim_scope")
        design = item.get("comparison_design")
        if scope == "causal" and design not in {
            "matched-same-backbone",
            "randomized-controlled",
            "shared-prefix-matched-continuations",
        }:
            raise ValueError(f"causal carrier {carrier_id!r} lacks a controlled design")
        if design == "ecological-best-native" and item.get("placement") == "main":
            raise ValueError("ecological best-native context cannot masquerade as a main result")
    print(
        f"result-carrier audit passed: {len(observed)} main tables, "
        f"{len(by_id) - len(observed)} planned/appendix carriers"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

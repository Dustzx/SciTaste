#!/usr/bin/env python3
"""Refresh the human-readable SciTaste outputs catalog."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.output_catalog import refresh_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outputs", nargs="?", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    index_path, catalog_path = refresh_catalog(args.outputs)
    print(f"index={index_path}")
    print(f"catalog={catalog_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

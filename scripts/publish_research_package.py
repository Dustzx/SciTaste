"""Synchronize an already delivered ML research package without re-execution."""

import argparse
import json
from pathlib import Path

from scitaste.project.package_progress import publish_package_progress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish_package_progress(args.project, args.package)))


if __name__ == "__main__":
    main()

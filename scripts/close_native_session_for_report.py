"""Close unanswered requests for immutable report delivery, not research replay."""

import argparse
import json
from pathlib import Path

from scitaste.executor.native_terminal_delivery import close_for_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    record = close_for_report(args.project, args.source_run, reason=args.reason)
    print(json.dumps({key: value for key, value in record.items() if key != "workspace_files"}))


if __name__ == "__main__":
    main()

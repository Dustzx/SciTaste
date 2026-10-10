"""Prepare or score real, role-isolated claim-evidence model diagnostics."""

import argparse
import json
from pathlib import Path

from scitaste.benchmark.claim_calibration import prepare, score
from scitaste.model_nodes.session_exchange import SessionResponsePending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "score"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--specification", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        if args.specification is None:
            parser.error("Preparation requires an explicit frozen specification")
        result = prepare(args.project, args.specification, args.output)
    else:
        try:
            result = score(args.project, args.output)
        except SessionResponsePending as exc:
            print(json.dumps({"status": "awaiting-session-response", "request": str(exc)}))
            return 75
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

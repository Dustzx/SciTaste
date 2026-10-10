#!/usr/bin/env python3
"""Package consumed SciTasteBench development data or score its submissions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from scitaste.evaluation.decision_dataset import build_development_dataset, evaluate_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    for name in (
        "requests",
        "keys",
        "source-qualification",
        "source-license",
        "limitations",
        "participant-output",
        "scorer-output",
    ):
        build.add_argument("--" + name, type=Path, required=True)
    build.add_argument("--native-fallback-definition", required=True)
    build.add_argument("--evidence-root", type=Path)
    evaluate = commands.add_parser("score")
    for name in ("dataset", "scorer", "submissions", "output"):
        evaluate.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        qualification = yaml.safe_load(args.source_qualification.read_text())
        origin = qualification["source"]
        limits = json.loads(args.limitations.read_text())
        if not isinstance(limits, list) or any(
            not isinstance(v, str) or not v.strip() for v in limits
        ):
            raise ValueError("limitations must be a nonempty list of text statements")
        result = build_development_dataset(
            requests_path=args.requests,
            keys_path=args.keys,
            source={
                "benchmark_id": origin["benchmark_id"],
                "title": origin["paper_title"],
                "repository": origin["official_repository"],
                "revision": origin["repository_commit"],
                "license": origin["license"],
                "license_sha256": origin["license_sha256"],
            },
            source_license=args.source_license,
            public_root=args.participant_output,
            private_root=args.scorer_output,
            limitations=tuple(limits),
            native_fallback_definition=args.native_fallback_definition,
            evidence_root=args.evidence_root,
        )
        print(
            json.dumps(
                {
                    "cases": result["cases"],
                    "source_tasks": result["independent_source_tasks"],
                    "participant_output": str(args.participant_output),
                }
            )
        )
    else:
        if args.output.exists():
            raise FileExistsError("score output must be new")
        result = evaluate_dataset(args.dataset, args.scorer, args.submissions)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"methods": len(result["methods"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()

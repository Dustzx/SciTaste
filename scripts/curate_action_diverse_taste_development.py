#!/usr/bin/env python3
"""Freeze and materialize an outcome-blind action-diverse Taste development set."""

from __future__ import annotations

import argparse
from pathlib import Path

from scitaste.evaluation.action_diverse_taste_development import (
    compile_action_diverse_curation_plan,
    load_action_diverse_curation_manifest,
    load_action_diverse_curation_plan,
    materialize_action_diverse_curation,
    save_action_diverse_artifact,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "materialize"):
        child = subparsers.add_parser(command)
        child.add_argument("--manifest", required=True, type=Path)
        child.add_argument("--workspace-root", type=Path, default=Path("."))
        child.add_argument("--outputs-root", type=Path, default=Path("outputs"))
        child.add_argument("--campaign-root", required=True, type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest = load_action_diverse_curation_manifest(args.manifest)
    plan_path = args.campaign_root / "CURATION_PLAN.json"
    if args.command == "plan":
        plan = compile_action_diverse_curation_plan(
            manifest,
            workspace_root=args.workspace_root,
            outputs_root=args.outputs_root,
        )
        save_action_diverse_artifact(plan, plan_path)
        print(
            f"curation_id={plan.curation_id} selections={len(plan.selections)} "
            f"plan_sha256={plan.plan_sha256}"
        )
        return

    plan = load_action_diverse_curation_plan(plan_path)
    receipt = materialize_action_diverse_curation(
        manifest,
        plan,
        workspace_root=args.workspace_root,
        outputs_root=args.outputs_root,
    )
    receipt_path = args.campaign_root / "CURATION_RECEIPT.json"
    save_action_diverse_artifact(receipt, receipt_path)
    print(
        f"curation_id={receipt.curation_id} candidates={len(receipt.candidates)} "
        f"receipt_sha256={receipt.receipt_sha256}"
    )


if __name__ == "__main__":
    main()

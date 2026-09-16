#!/usr/bin/env python3
"""Compile a finalized adaptive-policy activation into its E2 successor bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scitaste.evaluation.adaptive_policy_activation import (
    load_adaptive_policy_activation_finalization_result,
    load_adaptive_policy_activation_manifest,
    load_adaptive_policy_activation_state,
)
from scitaste.evaluation.adaptive_policy_e2_handoff import (
    materialize_adaptive_policy_e2_successor,
)


def execute(args: argparse.Namespace) -> dict[str, object]:
    manifest, _ = load_adaptive_policy_activation_manifest(args.manifest)
    finalization = load_adaptive_policy_activation_finalization_result(args.finalization)
    state = load_adaptive_policy_activation_state(args.state)
    successor, inspection, receipt, path = materialize_adaptive_policy_e2_successor(
        manifest,
        finalization,
        state,
        predecessor_manifest_path=args.predecessor_manifest,
        output_directory=args.output_directory,
        workspace_root=args.workspace_root,
        outputs_root=args.outputs_root,
        implementation_commit=args.implementation_commit,
        successor_manifest_id=args.successor_manifest_id,
    )
    return {
        "manifest_id": successor.manifest_id,
        "manifest_path": str(path),
        "manifest_sha256": receipt.successor_manifest_sha256,
        "ready_for_development_static_handoff": (inspection.ready_for_development_static_handoff),
        "taste_intervention_behaviorally_active": (
            inspection.taste_intervention_behaviorally_active
        ),
        "ready_for_development_execution": inspection.ready_for_development_execution,
        "blocker_codes": inspection.blocker_codes,
        "receipt_sha256": receipt.receipt_sha256,
        "external_execution_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--finalization", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--predecessor-manifest", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--successor-manifest-id", default=None)
    parser.add_argument("--implementation-commit", default=None)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    return parser


def main() -> None:
    print(json.dumps(execute(build_parser().parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

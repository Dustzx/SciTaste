#!/usr/bin/env python3
"""Prepare hidden decision requests or score submitted SciTasteBench methods.

This script makes no model calls. ``prepare`` puts policy-visible requests and
private scoring keys in separate files; never give the keys or source cases to
a competing policy. ``score`` requires every method to cover every request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.evaluation.decision_method_comparison import (
    DecisionMethodRequest,
    DecisionMethodSubmission,
    DecisionScoringKey,
    VisibleEvidenceArtifact,
    compile_decision_case,
    score_decision_methods,
    verify_visible_evidence_artifacts,
)
from scitaste.evaluation.scientific_situation_transfer import (
    FormalObjectiveForkSituationCase,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="separate public requests and private keys")
    prepare.add_argument("--cases", type=Path, required=True)
    prepare.add_argument("--native-actions", type=Path, required=True)
    prepare.add_argument("--requests-out", type=Path, required=True)
    prepare.add_argument("--private-keys-out", type=Path, required=True)
    prepare.add_argument(
        "--evidence-manifest",
        type=Path,
        help="JSON map from study_id to pre-decision evidence artifact records",
    )
    prepare.add_argument(
        "--evidence-root",
        type=Path,
        help="root used to verify evidence-manifest artifact bytes",
    )
    prepare.add_argument(
        "--allow-sealed-test",
        action="store_true",
        help="requires a separately frozen formal study; this flag is not authorization",
    )
    score = commands.add_parser("score", help="score complete method submissions")
    score.add_argument("--requests", type=Path, required=True)
    score.add_argument("--private-keys", type=Path, required=True)
    score.add_argument("--submissions", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path: Path, model: type) -> tuple:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"input must be a regular file: {path}")
    rows = tuple(
        model.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if not rows:
        raise ValueError(f"input has no rows: {path}")
    return rows


def _prepare(args: argparse.Namespace) -> None:
    if args.requests_out.resolve() == args.private_keys_out.resolve():
        raise ValueError("public requests and private keys need different files")
    if args.requests_out.parent.resolve() == args.private_keys_out.parent.resolve():
        raise ValueError("public requests and private keys need separate directories")
    if args.requests_out.exists() or args.private_keys_out.exists():
        raise FileExistsError("decision-method outputs must not overwrite prior evidence")
    cases = _read_jsonl(args.cases, FormalObjectiveForkSituationCase)
    assignments = {case.task_binding.split_assignment for case in cases}
    if len(assignments) != 1:
        raise ValueError("decision-method population mixes split assignments")
    if "test" in assignments and not args.allow_sealed_test:
        raise ValueError("opening sealed test cases requires a frozen study")
    if (args.evidence_manifest is None) != (args.evidence_root is None):
        raise ValueError("evidence manifest and root must be supplied together")
    evidence: dict[str, list[dict]] = {}
    if args.evidence_manifest is not None:
        payload = json.loads(args.evidence_manifest.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != {case.study_id for case in cases}:
            raise ValueError("evidence manifest must exactly cover the decision cases")
        if any(not isinstance(rows, list) for rows in payload.values()):
            raise ValueError("evidence manifest entries must be artifact arrays")
        evidence = payload
    native_payload = json.loads(args.native_actions.read_text(encoding="utf-8"))
    native_actions = native_payload.get("baseline_actions", native_payload)
    if not isinstance(native_actions, dict):
        raise ValueError("native actions must be a mapping")
    pairs = []
    for case in cases:
        stage = case.study_id.rsplit("-", 1)[-1]
        action = native_actions.get(case.study_id, native_actions.get(stage))
        if not isinstance(action, str):
            raise ValueError(f"no native action for {case.study_id}")
        artifacts = tuple(
            VisibleEvidenceArtifact.model_validate(item) for item in evidence.get(case.study_id, ())
        )
        request, key = compile_decision_case(
            case, native_action_id=action, evidence_artifacts=artifacts
        )
        if args.evidence_root is not None:
            verify_visible_evidence_artifacts(request, artifact_root=args.evidence_root)
        pairs.append((request, key))
    requests = tuple(item[0] for item in pairs)
    keys = tuple(item[1] for item in pairs)
    if len({item.request_sha256 for item in requests}) != len(requests):
        raise ValueError("decision population contains duplicate visible requests")
    if len({item.execution_contract_sha256 for item in keys}) != 1:
        raise ValueError("decision population mixes execution contracts")
    if len({item.scorer_contract_sha256 for item in keys}) != 1:
        raise ValueError("decision population mixes scorers")
    args.requests_out.parent.mkdir(parents=True, exist_ok=True)
    args.private_keys_out.parent.mkdir(parents=True, exist_ok=True)
    args.requests_out.write_text(
        "\n".join(item.model_dump_json() for item in requests) + "\n", encoding="utf-8"
    )
    args.private_keys_out.write_text(
        "\n".join(item.model_dump_json() for item in keys) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "cases": len(requests),
                "split": next(iter(assignments)),
                "requests_sha256": _sha256(args.requests_out),
                "private_keys_sha256": _sha256(args.private_keys_out),
                "model_calls": 0,
            },
            sort_keys=True,
        )
    )


def _score(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise FileExistsError("decision-method score must not overwrite prior evidence")
    requests = _read_jsonl(args.requests, DecisionMethodRequest)
    keys = _read_jsonl(args.private_keys, DecisionScoringKey)
    submissions = _read_jsonl(args.submissions, DecisionMethodSubmission)
    summaries = score_decision_methods(requests, keys, submissions)
    result = {
        "schema_version": "1.0",
        "requests_sha256": _sha256(args.requests),
        "private_keys_sha256": _sha256(args.private_keys),
        "submissions_sha256": _sha256(args.submissions),
        "methods": [item.model_dump(mode="json") for item in summaries],
        "paper_effect_claim_authorized": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"methods": len(summaries), "output": str(args.output)}, sort_keys=True))


def main() -> None:
    args = _parser().parse_args()
    if args.command == "prepare":
        _prepare(args)
    else:
        _score(args)


if __name__ == "__main__":
    main()

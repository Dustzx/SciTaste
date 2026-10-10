#!/usr/bin/env python3
"""Partition consumed NewtonBench development cases for prior-outcome reflection.

Task groups are allocated by a fixed identifier hash before reading outcomes.
Only one prespecified action and one paired replicate per source case enters
memory. Target outcomes remain in the private scorer file, never model input.
This is retrospective development, not a prospective learning result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from scitaste.evaluation.decision_method_comparison import (
    DecisionMethodRequest,
    DecisionMethodSubmission,
    DecisionScoringKey,
)
from scitaste.evaluation.decision_policy_baselines import DecisionReflectionEpisode
from scitaste.evaluation.scientific_situation_transfer import (
    FormalObjectiveForkSituationCase,
)
from scitaste.project.models import content_sha256

SALT = "scitastebench-reflection-development-v1"


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


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: tuple) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(row.model_dump_json() for row in rows) + "\n", encoding="utf-8")


def _case_id(case: FormalObjectiveForkSituationCase) -> str:
    return content_sha256(
        {
            "prefix_sha256": case.situation.prefix_sha256,
            "action_semantics_sha256": case.action_semantics_sha256,
        }
    )


def partition_groups(groups: frozenset[str]) -> tuple[frozenset[str], frozenset[str]]:
    if len(groups) < 4:
        raise ValueError("reflection partition requires at least four task groups")
    ordered = sorted(
        groups,
        key=lambda group: hashlib.sha256(f"{SALT}:{group}".encode()).hexdigest(),
    )
    boundary = len(ordered) // 2
    return frozenset(ordered[:boundary]), frozenset(ordered[boundary:])


def build_source_memory(
    cases: tuple[FormalObjectiveForkSituationCase, ...],
    requests: dict[str, DecisionMethodRequest],
    source_groups: frozenset[str],
) -> tuple[DecisionReflectionEpisode, ...]:
    episodes: list[DecisionReflectionEpisode] = []
    for case in cases:
        if case.task_cluster_id not in source_groups:
            continue
        request = requests[_case_id(case)]
        action = request.native_action_id
        block = case.execution_contract.seed_block_ids[0]
        observed = next(
            item
            for item in case.replicate_outcomes
            if item.seed_block_id == block and item.action_id == action
        )
        outcome = (
            f"Observed official objective={observed.raw_metric_value:.8g}; "
            f"registered utility={observed.utility:.8g}."
            if observed.objective_observed
            else f"No observed objective; failure={observed.failure_code}; "
            f"registered failure utility={observed.utility:.8g}."
        )
        episodes.append(
            DecisionReflectionEpisode(
                source_task_cluster_id=case.task_cluster_id,
                research_state=(
                    f"{request.decision_basis} " + " | ".join(request.evidence_anchors)
                ),
                action_taken=action,
                observed_outcome=outcome,
            )
        )
    return tuple(episodes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--requests", required=True, type=Path)
    parser.add_argument("--private-keys", required=True, type=Path)
    parser.add_argument("--submissions", required=True, type=Path, nargs="+")
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    if args.output_root.exists() or args.output_root.is_symlink():
        raise FileExistsError("reflection development output must be new")
    cases = _read_jsonl(args.cases, FormalObjectiveForkSituationCase)
    public = _read_jsonl(args.requests, DecisionMethodRequest)
    private = _read_jsonl(args.private_keys, DecisionScoringKey)
    if {case.task_binding.split_assignment for case in cases} != {"development"}:
        raise ValueError("reflection partition is development-only")
    case_ids = [_case_id(case) for case in cases]
    request_map = {item.case_id: item for item in public}
    request_hashes = {item.request_sha256 for item in public}
    key_map = {item.request_sha256: item for item in private}
    if (
        len(case_ids) != len(set(case_ids))
        or len(request_map) != len(public)
        or len(key_map) != len(private)
        or set(case_ids) != set(request_map)
        or request_hashes != set(key_map)
    ):
        raise ValueError("source cases, public requests, and private keys differ")
    for case in cases:
        if (
            key_map[request_map[_case_id(case)].request_sha256].task_cluster_id
            != case.task_cluster_id
        ):
            raise ValueError("source task group differs from private key")
    source_groups, target_groups = partition_groups(
        frozenset(case.task_cluster_id for case in cases)
    )
    source_memory = build_source_memory(cases, request_map, source_groups)
    target_hashes = {
        request_map[_case_id(case)].request_sha256
        for case in cases
        if case.task_cluster_id in target_groups
    }
    target_public = tuple(item for item in public if item.request_sha256 in target_hashes)
    target_private = tuple(item for item in private if item.request_sha256 in target_hashes)
    if not source_memory or not target_public or len(target_private) != len(target_public):
        raise ValueError("reflection partition yielded an incomplete target")
    filtered: dict[str, tuple[DecisionMethodSubmission, ...]] = {}
    for path in args.submissions:
        rows = _read_jsonl(path, DecisionMethodSubmission)
        method_ids = {item.method_id for item in rows}
        if len(method_ids) != 1 or len(rows) != len(public):
            raise ValueError("existing method must exactly cover the full development cohort")
        method_id = next(iter(method_ids))
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,100}", method_id):
            raise ValueError("method identifier is unsafe as a filename")
        if method_id in filtered or {item.request_sha256 for item in rows} != request_hashes:
            raise ValueError("existing method has duplicate or missing requests")
        filtered[method_id] = tuple(item for item in rows if item.request_sha256 in target_hashes)
    args.output_root.mkdir(parents=True)
    _write_jsonl(args.output_root / "public/REQUESTS.jsonl", target_public)
    _write_jsonl(args.output_root / "private/KEYS.jsonl", target_private)
    _write_jsonl(args.output_root / "source/REFLECTION_MEMORY.jsonl", source_memory)
    for method_id, rows in sorted(filtered.items()):
        _write_jsonl(args.output_root / f"comparators/{method_id}.jsonl", rows)
    manifest = {
        "schema_version": "1.0",
        "role": "consumed-retrospective-development",
        "partition_salt": SALT,
        "partition_rule": (
            "sort unique task-cluster IDs by salted SHA-256; first floor(n/2) are sources"
        ),
        "source_task_clusters": sorted(source_groups),
        "target_task_clusters": sorted(target_groups),
        "source_episodes": len(source_memory),
        "target_cases": len(target_public),
        "source_observation_rule": (
            "visible native stage heuristic action, first registered seed block only"
        ),
        "source_cases_sha256": _hash(args.cases),
        "full_requests_sha256": _hash(args.requests),
        "full_private_keys_sha256": _hash(args.private_keys),
        "target_requests_sha256": _hash(args.output_root / "public/REQUESTS.jsonl"),
        "target_private_keys_sha256": _hash(args.output_root / "private/KEYS.jsonl"),
        "source_memory_sha256": _hash(args.output_root / "source/REFLECTION_MEMORY.jsonl"),
        "comparators": {
            method_id: _hash(args.output_root / f"comparators/{method_id}.jsonl")
            for method_id in filtered
        },
        "formal_evidence_eligible": False,
    }
    (args.output_root / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "source_groups": len(source_groups),
                "target_groups": len(target_groups),
                "source_episodes": len(source_memory),
                "target_cases": len(target_public),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

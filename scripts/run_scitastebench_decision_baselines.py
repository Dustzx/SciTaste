#!/usr/bin/env python3
"""Run independent decision policies on outcome-hidden development requests.

Outputs are exclusive, local evidence. The private scoring keys are read only to
check reflection source separation; their utilities never enter model prompts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from scitaste.evaluation.decision_image_backend import ImageEvidenceDecisionBackend
from scitaste.evaluation.decision_method_comparison import (
    DecisionMethodRequest,
    DecisionScoringKey,
)
from scitaste.evaluation.decision_policy_baselines import (
    DecisionReflectionEpisode,
    run_decision_policy,
)
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    StructuredOpenAICompatibleConfig,
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.replay import RecordingStructuredBackend
from scitaste.project.models import content_sha256


class RecordedDecisionBackend(RecordingStructuredBackend):
    """Keep image capability and exact intermediate responses through recording."""

    def __init__(self, delegate, path: Path) -> None:
        super().__init__(delegate, path)
        self.supports_evidence_artifacts = getattr(delegate, "supports_evidence_artifacts", False)
        self.evidence_transport_manifest = getattr(delegate, "evidence_transport_manifest", None)


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


def _bind_credential(path: Path, name: str) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("credential file must be a regular mode-0600 file")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.isidentifier() or key in values:
            raise ValueError("credential file has an invalid binding")
        values[key] = value
    if not values.get(name):
        raise ValueError(f"credential file has no binding for {name}")
    os.environ[name] = values[name]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--kind", required=True, choices=("direct", "reflection", "planning"))
    parser.add_argument("--method-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--private-keys", type=Path)
    parser.add_argument("--reflection-memory", type=Path)
    parser.add_argument("--evidence-root", type=Path, help="Root of bound pre-decision images")
    parser.add_argument("--total-output-ceiling", type=int, default=1024)
    args = parser.parse_args()

    if args.total_output_ceiling < 2:
        raise ValueError("total output ceiling must be at least two tokens")
    requests = _read_jsonl(args.requests, DecisionMethodRequest)
    has_artifacts = any(item.evidence_artifacts for item in requests)
    if has_artifacts != (args.evidence_root is not None):
        raise ValueError("image requests require --evidence-root; text-only requests must omit it")
    config = load_structured_openai_compatible_config(args.config)
    if not config.live_enabled:
        raise ValueError("baseline backend is not enabled for live calls")
    per_call = args.total_output_ceiling // (2 if args.kind == "planning" else 1)
    config = StructuredOpenAICompatibleConfig.model_validate(
        {**config.model_dump(mode="python"), "max_output_tokens": per_call}
    )
    episodes: tuple[DecisionReflectionEpisode, ...] = ()
    target_clusters: frozenset[str] | None = None
    if args.kind == "reflection":
        if args.private_keys is None or args.reflection_memory is None:
            raise ValueError("reflection requires private keys and source-disjoint memory")
        keys = _read_jsonl(args.private_keys, DecisionScoringKey)
        if len(keys) != len(requests) or {item.request_sha256 for item in keys} != {
            item.request_sha256 for item in requests
        }:
            raise ValueError("private keys do not match the public request cohort")
        target_clusters = frozenset(item.task_cluster_id for item in keys)
        episodes = _read_jsonl(args.reflection_memory, DecisionReflectionEpisode)
    elif args.private_keys is not None or args.reflection_memory is not None:
        raise ValueError("only reflection may read private keys or prior outcomes")
    if args.credentials_file is not None:
        _bind_credential(args.credentials_file, config.api_key_env)
    if not os.getenv(config.api_key_env):
        raise ValueError(f"missing credential binding {config.api_key_env}")
    if args.output_dir.exists():
        raise FileExistsError("baseline output directory must not overwrite existing evidence")
    args.output_dir.mkdir(parents=True)
    backend = (
        ImageEvidenceDecisionBackend(config, evidence_root=args.evidence_root)
        if args.evidence_root is not None
        else StructuredOpenAICompatibleBackend(config)
    )
    backend = RecordedDecisionBackend(backend, args.output_dir / "recordings.jsonl")
    backend_hash = content_sha256(
        {
            "config": config.model_dump(mode="json"),
            "configured_output_ceiling": args.total_output_ceiling,
            "config_file_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        }
    )
    submissions = []
    consecutive_failures = 0
    for index, request in enumerate(requests):
        result = run_decision_policy(
            (request,),
            method_id=args.method_id,
            policy_kind=args.kind,
            backend=backend,
            backend_manifest_sha256=backend_hash,
            reflection_episodes=episodes,
            target_task_cluster_ids=target_clusters,
        )
        case_file = args.output_dir / f"case-{index:04d}.json"
        case_file.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        submissions.extend(result.submissions)
        consecutive_failures = (
            consecutive_failures + 1 if result.submissions[0].failure_code is not None else 0
        )
        if consecutive_failures >= 2:
            raise RuntimeError(
                "two consecutive decision failures; stopped to avoid repeated provider calls"
            )
    (args.output_dir / "submissions.jsonl").write_text(
        "\n".join(item.model_dump_json() for item in submissions) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "cases": len(submissions),
                "failures": sum(item.failure_code is not None for item in submissions),
                "method": args.method_id,
                "kind": args.kind,
                "output": str(args.output_dir),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Extend a canonical source registry with exact NewtonBench task identities."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from scitaste.evaluation.newtonbench_runtime import NewtonBenchTask
from scitaste.evaluation.source_identity import (
    CanonicalSourceIdentity,
    CanonicalSourceIdentityRegistry,
    load_canonical_source_identity_registry,
    save_canonical_source_identity_registry,
)


def execute(args: argparse.Namespace) -> CanonicalSourceIdentityRegistry:
    base = load_canonical_source_identity_registry(args.base)
    entries = {item.canonical_source_group_id: item for item in base.entries}
    source_hashes = set(base.source_artifact_sha256s)
    for task_path in args.task:
        raw = _bounded(task_path)
        task = NewtonBenchTask.model_validate_json(raw, strict=True)
        entry = CanonicalSourceIdentity.create(
            namespace="benchmark-task-v1",
            source_identifier=f"newtonbench::{task.task_id}",
        )
        entries[entry.canonical_source_group_id] = entry
        source_hashes.add(hashlib.sha256(raw).hexdigest())
    registry = CanonicalSourceIdentityRegistry.create(
        registry_id=args.registry_id,
        entries=tuple(entries.values()),
        source_artifact_sha256s=tuple(source_hashes),
    )
    save_canonical_source_identity_registry(registry, args.output)
    return registry


def _bounded(path: str | Path) -> bytes:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"NewtonBench task must be a regular file: {source}")
    if not 1 <= source.stat().st_size <= 1_048_576:
        raise ValueError(f"NewtonBench task exceeds its byte ceiling: {source}")
    return source.read_bytes()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--task", type=Path, action="append", required=True)
    parser.add_argument("--registry-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    registry = execute(build_parser().parse_args())
    print(
        f"registry_id={registry.registry_id} entries={len(registry.entries)} "
        f"registry_sha256={registry.registry_sha256}"
    )


if __name__ == "__main__":
    main()

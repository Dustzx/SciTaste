#!/usr/bin/env python3
"""Repair a truncated Python replacement by splicing only declared definitions."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
from pathlib import Path

from scitaste.evaluation.task_patch import BenchmarkPatchProposal
from scitaste.project.models import content_sha256


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _definitions(tree: ast.Module) -> dict[str, ast.AST]:
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return {item.name: item for item in tree.body if isinstance(item, kinds)}


def _node_span(node: ast.AST) -> tuple[int, int]:
    start = int(node.lineno)  # type: ignore[attr-defined]
    decorators = getattr(node, "decorator_list", ())
    if decorators:
        start = min(start, *(int(item.lineno) for item in decorators))
    return start - 1, int(node.end_lineno)  # type: ignore[attr-defined]


def _definition_preserving_repair(original: str, replacement: str) -> tuple[str, tuple[str, ...]]:
    original_tree = ast.parse(original)
    replacement_tree = ast.parse(replacement)
    original_definitions = _definitions(original_tree)
    replacement_definitions = _definitions(replacement_tree)
    removed = set(original_definitions) - set(replacement_definitions)
    if not removed:
        raise ValueError("definition-preserving repair requires a truncated replacement")
    unknown = set(replacement_definitions) - set(original_definitions)
    if unknown or len(replacement_definitions) != 1:
        raise ValueError("repair permits exactly one existing top-level definition")
    name, replacement_node = next(iter(replacement_definitions.items()))
    original_node = original_definitions[name]
    original_lines = original.splitlines(keepends=True)
    replacement_lines = replacement.splitlines(keepends=True)
    original_start, original_end = _node_span(original_node)
    replacement_start, replacement_end = _node_span(replacement_node)
    replacement_source = "".join(replacement_lines[replacement_start:replacement_end]).rstrip()
    repaired = "".join(
        [
            *original_lines[:original_start],
            replacement_source + "\n",
            *original_lines[original_end:],
        ]
    )
    repaired_tree = ast.parse(repaired)
    if set(_definitions(repaired_tree)) != set(original_definitions):
        raise ValueError("repaired module changed the public definition population")
    return repaired, tuple(sorted(removed))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    proposal_path = args.proposal.resolve(strict=True)
    proposal_bytes = proposal_path.read_bytes()
    proposal_payload = json.loads(proposal_bytes)
    serialized_fingerprint = proposal_payload.pop("fingerprint", None)
    proposal = BenchmarkPatchProposal.model_validate(proposal_payload)
    if serialized_fingerprint not in {None, proposal.fingerprint}:
        raise ValueError("serialized patch proposal fingerprint differs")
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    arm_source = output / "arm_source"
    shutil.copytree(source, arm_source)
    repairs = []
    for edit in proposal.edits:
        target = (arm_source / edit.path).resolve(strict=True)
        target.relative_to(arm_source)
        original_bytes = target.read_bytes()
        if _sha256(original_bytes) != edit.expected_sha256:
            raise ValueError(f"source changed before repair: {edit.path}")
        if not edit.path.endswith(".py"):
            raise ValueError("definition-preserving repair accepts only Python modules")
        repaired, preserved = _definition_preserving_repair(
            original_bytes.decode("utf-8"),
            edit.replacement,
        )
        repaired_bytes = repaired.encode()
        target.write_bytes(repaired_bytes)
        repairs.append(
            {
                "path": edit.path,
                "preserved_missing_definitions": list(preserved),
                "original_sha256": edit.expected_sha256,
                "model_replacement_sha256": _sha256(edit.replacement.encode()),
                "repaired_sha256": _sha256(repaired_bytes),
            }
        )
    receipt = {
        "schema_version": "1.0",
        "proposal_file_sha256": _sha256(proposal_bytes),
        "proposal_sha256": proposal.fingerprint,
        "repairs": repairs,
        "repair_kind": "definition-preserving-single-function-splice",
        "no_model_call_performed": True,
        "no_gpu_work_performed": True,
        "heldout_opened": False,
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    (output / "REPAIR_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

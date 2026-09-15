#!/usr/bin/env python3
"""Project one SciJudgeBench split into agent-visible and scorer-only files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

_MAX_INPUT_BYTES = 64 * 1024 * 1024
_MAX_ROWS = 10_000
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_output(path: Path) -> Path:
    resolved_parent = path.parent.resolve()
    resolved_parent.mkdir(parents=True, exist_ok=True)
    resolved = resolved_parent / path.name
    if resolved.exists() and resolved.is_symlink():
        raise ValueError(f"output cannot be a symlink: {resolved}")
    return resolved


def _write_atomic(path: Path, rows: list[dict[str, Any]]) -> str:
    destination = _safe_output(path)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    return _file_sha256(destination)


def _today(row: dict[str, Any]) -> str:
    messages = row.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            match = re.search(r"Today is (\d{4}-\d{2}-\d{2})", str(message.get("content", "")))
            if match:
                return match.group(1)
    raise ValueError("source row does not expose its evaluation date")


def _messages(row: dict[str, Any], *, swapped: bool) -> list[dict[str, str]]:
    first, second = ("b", "a") if swapped else ("a", "b")
    system = (
        "You are a helpful assistant. You first think about the reasoning "
        "process in your mind and then provide the user with the answer."
    )
    if "year" in row:
        user = (
            "Based on the titles and abstracts of the following two papers A and B "
            f"submitted to ICLR {row['year']}, determine which paper is more likely "
            "to be accepted.\nShow your reasoning process in <think> </think> tags. "
            "And return the final answer in <answer> </answer> tags. The final answer "
            "should contain only the letter A or B.\n\n"
            f"Paper A:\nTitle: {row[f'paper_{first}_title']}\n"
            f"Abstract: {row[f'paper_{first}_abstract']}\n\n"
            f"Paper B:\nTitle: {row[f'paper_{second}_title']}\n"
            f"Abstract: {row[f'paper_{second}_abstract']}\n"
        )
    else:
        user = (
            f"Today is {_today(row)}. Based on the titles, abstracts, and publication "
            "dates of the following two papers A and B, determine which paper has a "
            "higher citation count.\nShow your reasoning process in <reason> </reason> "
            "tags. And return the final answer in <answer> </answer> tags. The final "
            "answer should contain only the letter A or B.\n\n"
            f"Paper A (Published: {row[f'paper_{first}_date']}):\n"
            f"Title: {row[f'paper_{first}_title']}\n"
            f"Abstract: {row[f'paper_{first}_abstract']}\n\n"
            f"Paper B (Published: {row[f'paper_{second}_date']}):\n"
            f"Title: {row[f'paper_{second}_title']}\n"
            f"Abstract: {row[f'paper_{second}_abstract']}\n"
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _paper_identity(row: dict[str, Any], side: str) -> str:
    arxiv_id = row.get(f"paper_{side}_arxiv_id")
    if arxiv_id is not None:
        return str(arxiv_id)
    title = str(row[f"paper_{side}_title"])
    return f"title-sha256-{hashlib.sha256(title.encode()).hexdigest()[:16]}"


def project(args: argparse.Namespace) -> dict[str, Any]:
    source = args.input.resolve(strict=True)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_INPUT_BYTES:
        raise ValueError("input must be a bounded regular JSONL file")
    source_sha256 = _file_sha256(source)
    if source_sha256 != args.expected_input_sha256:
        raise ValueError("input SHA-256 differs from the frozen acquisition")

    visible: list[dict[str, Any]] = []
    scorer: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    with source.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if index >= _MAX_ROWS:
                raise ValueError("input exceeds the bounded row ceiling")
            row = json.loads(line)
            answer = row.get("correct_answer")
            if answer not in {"A", "B"}:
                raise ValueError(f"row {index} has no binary answer")
            paper_a_id = _paper_identity(row, "a")
            paper_b_id = _paper_identity(row, "b")
            identity = "\0".join((args.split, str(index), paper_a_id, paper_b_id))
            group_id = f"{args.split}-{hashlib.sha256(identity.encode()).hexdigest()[:16]}"
            if group_id in seen_groups:
                raise ValueError("derived group IDs are not unique")
            seen_groups.add(group_id)
            for position, swapped in (("original", False), ("swapped", True)):
                case_id = f"{group_id}-{position}"
                expected = answer if not swapped else ("B" if answer == "A" else "A")
                visible.append(
                    {
                        "schema_version": "1.0",
                        "case_id": case_id,
                        "group_id": group_id,
                        "split": args.split,
                        "position": position,
                        "messages": _messages(row, swapped=swapped),
                    }
                )
                scorer.append(
                    {
                        "schema_version": "1.0",
                        "case_id": case_id,
                        "group_id": group_id,
                        "split": args.split,
                        "position": position,
                        "expected_answer": expected,
                        "category": row.get("paper_a_category", "ICLR"),
                        "paper_a_source_id": paper_b_id if swapped else paper_a_id,
                        "paper_b_source_id": paper_a_id if swapped else paper_b_id,
                    }
                )
    if not visible:
        raise ValueError("input split is empty")

    visible_sha256 = _write_atomic(args.visible_output, visible)
    scorer_sha256 = _write_atomic(args.scorer_output, scorer)
    manifest = {
        "schema_version": "1.0",
        "projection_id": args.projection_id,
        "split": args.split,
        "source": {"path": str(source), "sha256": source_sha256, "rows": len(seen_groups)},
        "agent_visible": {
            "path": str(args.visible_output.resolve()),
            "sha256": visible_sha256,
            "rows": len(visible),
            "contains_labels_or_citations": False,
        },
        "scorer_only": {
            "path": str(args.scorer_output.resolve()),
            "sha256": scorer_sha256,
            "rows": len(scorer),
        },
        "position_swap_pairs": len(seen_groups),
        "model_or_gpu_used": False,
    }
    _write_atomic(args.manifest_output, [manifest])
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-input-sha256", required=True)
    parser.add_argument(
        "--split",
        choices=("test", "test_ood_year", "test_ood_iclr"),
        required=True,
    )
    parser.add_argument("--projection-id", required=True)
    parser.add_argument("--visible-output", type=Path, required=True)
    parser.add_argument("--scorer-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not _SHA256.fullmatch(args.expected_input_sha256):
        raise ValueError("expected input SHA-256 must contain 64 lowercase hex characters")
    print(json.dumps(project(args), indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()

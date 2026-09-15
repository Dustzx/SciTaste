#!/usr/bin/env python3
"""Inspect task-excluded B0 receipts with reasoning/final-channel separation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

_MAX_RECEIPT_BYTES = 4 * 1_048_576


def inspect(path: str | Path) -> dict[str, object]:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("B0 receipt must be a regular file")
    raw_file = source.read_bytes()
    if not 1 <= len(raw_file) <= _MAX_RECEIPT_BYTES:
        raise ValueError("B0 receipt exceeds its byte ceiling")
    payload = json.loads(raw_file)
    raw_response = payload.get("raw_response")
    if not isinstance(raw_response, str):
        raise ValueError("B0 receipt omits its raw response")
    raw_response_sha256 = hashlib.sha256(raw_response.encode()).hexdigest()
    if payload.get("raw_response_sha256") != raw_response_sha256:
        raise ValueError("B0 raw response hash mismatch")
    role = payload.get("role")
    if role == "judge":
        parsed = _parse_judge(raw_response)
        reasoning_channel_present = True
    elif role == "thinker":
        final, reasoning_channel_present = _final_channel(raw_response)
        parsed = _parse_thinker(final)
    else:
        raise ValueError("B0 receipt role is unsupported")
    output_tokens = payload.get("output_tokens")
    max_new_tokens = payload.get("max_new_tokens")
    if not isinstance(output_tokens, int) or not isinstance(max_new_tokens, int):
        raise ValueError("B0 receipt omits token telemetry")
    generation_completed = output_tokens < max_new_tokens
    result = {
        "schema_version": "1.0",
        "inspection_kind": "task-excluded-direct-taste-neighbor-b0-final-channel",
        "input_locator": source.as_posix(),
        "input_file_sha256": hashlib.sha256(raw_file).hexdigest(),
        "model_id": payload.get("model_id"),
        "model_revision": payload.get("model_revision"),
        "checkpoint_sha256": payload.get("checkpoint_sha256"),
        "role": role,
        "formal_dataset_rows_read": payload.get("formal_dataset_rows_read"),
        "reasoning_channel_present": reasoning_channel_present,
        "generation_completed_before_limit": generation_completed,
        "final_channel_schema_accepted": parsed["schema_accepted"],
        "final_channel": parsed,
        "b0_accepted": bool(
            payload.get("formal_dataset_rows_read") == 0
            and generation_completed
            and parsed["schema_accepted"]
        ),
    }
    result["inspection_sha256"] = _content_sha256(result)
    return result


def _final_channel(raw_response: str) -> tuple[str, bool]:
    if "</think>" not in raw_response:
        return raw_response.strip(), False
    return raw_response.rsplit("</think>", 1)[1].strip(), True


def _parse_judge(text: str) -> dict[str, object]:
    match = re.fullmatch(
        r"\s*<reason>.+?</reason>\s*<answer>\s*([AB])\s*</answer>\s*",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return {
        "schema_accepted": match is not None,
        "answer": match.group(1).upper() if match else None,
    }


def _parse_thinker(text: str) -> dict[str, object]:
    match = re.fullmatch(
        r"\s*Title:\s*([^\n]+)\nAbstract:\s*(\S(?:.|\n)*?)\s*",
        text,
    )
    return {
        "schema_accepted": match is not None,
        "title": match.group(1).strip() if match else None,
        "abstract": match.group(2).strip() if match else None,
    }


def _content_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.input)
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, allow_nan=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()

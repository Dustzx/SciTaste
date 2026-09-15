#!/usr/bin/env python3
"""Run one task-excluded local load/generation check for a direct Taste neighbor.

This is a development-only B0 executable.  It never opens SciJudgeBench or any
formal SciTasteBench split.  The caller supplies an already verified local
checkpoint and records the immutable checkpoint identity alongside runtime and
GPU telemetry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import time
from pathlib import Path


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _judge_messages() -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. You first think about the reasoning "
                "process in your mind and then provide the user with the answer."
            ),
        },
        {
            "role": "user",
            "content": (
                "Today is 2026-09-16. Based on the titles, abstracts, and publication "
                "dates of the following two synthetic papers A and B, determine which "
                "paper is more likely to receive more citations. Show reasoning in "
                "<reason> tags and return only A or B in <answer> tags.\n\n"
                "Paper A:\nTitle: A Decorative Header Style for Experiment Logs\n"
                "Abstract: We rename headers in one private log format without changing "
                "measurement, reliability, or scientific conclusions.\nDate: 2026-01-10\n\n"
                "Paper B:\nTitle: Hidden-Label Evaluation for Autonomous Research Agents\n"
                "Abstract: We introduce a reproducible protocol that isolates held-out "
                "scorers from research agents and detects fabricated or leaked results "
                "across multiple executable tasks.\nDate: 2026-01-10"
            ),
        },
    ]


def _thinker_messages() -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. You first think about the reasoning "
                "process in your mind and then provide the user with the answer."
            ),
        },
        {
            "role": "user",
            "content": (
                "You are a knowledgeable AI researcher. Given the following synthetic "
                "seed paper, propose one follow-up idea with high academic value. Return "
                "only `Title: ...` and `Abstract: ...`; include no numerical results.\n\n"
                "Title: Budgeted Search for Reproducible Machine Learning Experiments\n"
                "Abstract: We schedule candidate experiments by expected information gain "
                "and record immutable execution receipts, reducing duplicated work while "
                "keeping hidden evaluation isolated."
            ),
        },
    ]


def _parse(role: str, text: str) -> dict[str, object]:
    if role == "judge":
        matches = re.findall(r"<answer>\s*([AB])\s*</answer>", text, flags=re.IGNORECASE)
        return {
            "schema_accepted": len(matches) == 1,
            "answer": matches[0].upper() if len(matches) == 1 else None,
        }
    title = re.search(r"(?:^|\n)Title:\s*(.+)", text)
    abstract = re.search(r"(?:^|\n)Abstract:\s*(.+)", text, flags=re.DOTALL)
    return {
        "schema_accepted": title is not None and abstract is not None,
        "title": title.group(1).strip() if title else None,
        "abstract": abstract.group(1).strip() if abstract else None,
    }


def run(args: argparse.Namespace) -> dict[str, object]:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_path = Path(args.model_path).resolve(strict=True)
    if not model_path.is_dir():
        raise ValueError("model path must be a directory")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for direct-neighbor B0")
    if not args.device.startswith("cuda:"):
        raise ValueError("device must be an explicit CUDA device")

    messages = _judge_messages() if args.role == "judge" else _thinker_messages()
    prompt_bytes = json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()
    started = time.time()
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.cuda.reset_peak_memory_stats(args.device)

    tokenizer = AutoTokenizer.from_pretrained(
        model_path,
        local_files_only=True,
        trust_remote_code=False,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype=torch.bfloat16,
        local_files_only=True,
        trust_remote_code=False,
    ).to(args.device).eval()
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {key: value.to(args.device) for key, value in inputs.items()}
    input_tokens = int(inputs["input_ids"].shape[-1])
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            do_sample=False,
            max_new_tokens=args.max_new_tokens,
            use_cache=True,
        )
    new_tokens = generated[0, input_tokens:]
    raw_response = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    elapsed = time.time() - started
    device_index = int(args.device.split(":", 1)[1])
    device_properties = torch.cuda.get_device_properties(device_index)
    parsed = _parse(args.role, raw_response)
    return {
        "schema_version": "1.0",
        "receipt_kind": "task-excluded-direct-taste-neighbor-b0",
        "formal_evidence": False,
        "role": args.role,
        "model_id": args.model_id,
        "model_revision": args.model_revision,
        "checkpoint_sha256": args.checkpoint_sha256,
        "model_path": str(model_path),
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "formal_dataset_rows_read": 0,
        "seed": args.seed,
        "max_new_tokens": args.max_new_tokens,
        "input_tokens": input_tokens,
        "output_tokens": int(new_tokens.shape[-1]),
        "raw_response": raw_response,
        "raw_response_sha256": _sha256_text(raw_response),
        "parsed": parsed,
        "runtime": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "device": args.device,
            "device_name": device_properties.name,
            "device_total_memory_bytes": device_properties.total_memory,
            "peak_allocated_memory_bytes": torch.cuda.max_memory_allocated(args.device),
            "elapsed_seconds": elapsed,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("judge", "thinker"), required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--seed", type=int, default=260916)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", args.checkpoint_sha256):
        raise ValueError("checkpoint SHA-256 must contain 64 lowercase hex characters")
    if not 32 <= args.max_new_tokens <= 2048:
        raise ValueError("B0 max-new-tokens must be between 32 and 2048")
    receipt = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()

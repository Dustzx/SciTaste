"""Bound local Qwen3-VL-2B CUDA acceptance workload.

This is an execution-contract acceptance, not a model-quality benchmark.  It
exercises deterministic text generation, evidence-label generation, and the
vision path against one registered synthetic image.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import torch
from transformers import AutoImageProcessor, AutoTokenizer, Qwen3VLForConditionalGeneration
from transformers.models.qwen3_vl.processing_qwen3_vl import Qwen3VLProcessor
from transformers.models.qwen3_vl.video_processing_qwen3_vl import Qwen3VLVideoProcessor

MODEL_PATH = Path("/models/qwen3-vl-2b-instruct")
IMAGE_PATH = Path("/datasets/vision-probe")


class _ImageOnlyQwen3VLProcessor(Qwen3VLProcessor):
    """Avoid Transformers' optional torchvision-only auto-video placeholder."""

    def check_argument_for_proper_class(self, argument_name: str, argument: object) -> type:
        if argument_name == "video_processor":
            if not isinstance(argument, Qwen3VLVideoProcessor):
                raise TypeError("video_processor must be Qwen3VLVideoProcessor")
            return Qwen3VLVideoProcessor
        return super().check_argument_for_proper_class(argument_name, argument)


def _answer_token(text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_-]+", text.upper())
    return tokens[-1] if tokens else ""


def _messages(case: dict[str, str]) -> list[dict[str, object]]:
    if case["modality"] == "vision":
        content = [
            {"type": "image", "image": str(IMAGE_PATH)},
            {"type": "text", "text": case["prompt"]},
        ]
    else:
        content = [{"type": "text", "text": case["prompt"]}]
    return [{"role": "user", "content": content}]


def main() -> None:
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "0":
        raise RuntimeError("the acceptance requires exactly the admitted CUDA device")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable inside the admitted sandbox")
    if not MODEL_PATH.is_dir() or not IMAGE_PATH.is_file():
        raise RuntimeError("registered model or vision probe is not mounted")

    torch.manual_seed(7)
    torch.cuda.manual_seed_all(7)
    load_started = time.perf_counter()
    image_processor = AutoImageProcessor.from_pretrained(
        MODEL_PATH,
        local_files_only=True,
        use_fast=False,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_PATH,
        local_files_only=True,
        trust_remote_code=False,
    )
    video_processor = Qwen3VLVideoProcessor.from_pretrained(
        MODEL_PATH,
        local_files_only=True,
    )
    processor = _ImageOnlyQwen3VLProcessor(
        image_processor=image_processor,
        tokenizer=tokenizer,
        video_processor=video_processor,
        chat_template=tokenizer.chat_template,
    )
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        MODEL_PATH,
        dtype=torch.bfloat16,
        device_map={"": "cuda:0"},
        local_files_only=True,
        trust_remote_code=False,
        attn_implementation="eager",
    ).eval()
    model.generation_config.do_sample = False
    model.generation_config.temperature = None
    model.generation_config.top_p = None
    model.generation_config.top_k = None
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started

    cases = (
        {
            "case_id": "arithmetic-contract",
            "modality": "text",
            "prompt": "What English word is the answer to 3 + 4? Answer only SEVEN.",
            "expected": "SEVEN",
        },
        {
            "case_id": "evidence-label-contract",
            "modality": "text",
            "prompt": (
                "A registered observation is above its prespecified support threshold. "
                "Answer only SUPPORTED."
            ),
            "expected": "SUPPORTED",
        },
        {
            "case_id": "vision-contract",
            "modality": "vision",
            "prompt": "What is the single dominant color? Answer only RED.",
            "expected": "RED",
        },
    )
    measurements: list[dict[str, object]] = []
    for index, case in enumerate(cases):
        torch.manual_seed(7 + index)
        torch.cuda.manual_seed_all(7 + index)
        inputs = processor.apply_chat_template(
            _messages(case),
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        has_pixels = "pixel_values" in inputs
        modality_path_verified = has_pixels == (case["modality"] == "vision")
        inputs = inputs.to("cuda:0")
        input_tokens = int(inputs.input_ids.shape[-1])
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=16,
                use_cache=True,
            )
        torch.cuda.synchronize()
        latency_seconds = time.perf_counter() - started
        output_ids = generated[:, input_tokens:]
        response = processor.batch_decode(
            output_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0].strip()
        answer_match = _answer_token(response) == case["expected"]
        cuda_execution = next(model.parameters()).device.type == "cuda"
        response_nonempty = bool(response)
        acceptance_pass = all(
            (cuda_execution, response_nonempty, answer_match, modality_path_verified)
        )
        print(
            json.dumps(
                {
                    "case_id": case["case_id"],
                    "modality": case["modality"],
                    "expected": case["expected"],
                    "response": response,
                    "input_tokens": input_tokens,
                    "output_tokens": int(output_ids.shape[-1]),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        measurements.append(
            {
                "replicate_id": case["case_id"],
                "metrics": {
                    "acceptance_pass": float(acceptance_pass),
                    "answer_match": float(answer_match),
                    "cuda_execution": float(cuda_execution),
                    "latency_seconds": latency_seconds,
                    "load_seconds": load_seconds,
                    "modality_path_verified": float(modality_path_verified),
                    "output_tokens": float(output_ids.shape[-1]),
                    "peak_gpu_memory_gb": torch.cuda.max_memory_allocated() / 1_000_000_000,
                    "response_nonempty": float(response_nonempty),
                },
            }
        )

    payload = {"schema_version": "1.0", "measurements": measurements}
    print("SCITASTE_MEASUREMENTS_JSON=" + json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()

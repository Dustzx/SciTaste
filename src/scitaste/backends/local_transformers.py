"""Opt-in text-only preference backend for local Hugging Face checkpoints."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field

from scitaste.backends.base import PreferenceRequest, PreferenceResponse, Usage
from scitaste.backends.openai_compatible import (
    _SYSTEM_PROMPT,
    _parse_json_object,
    _preference_prompt,
)


class LocalTransformersConfig(BaseModel):
    """A pinned, local-only generation configuration.

    ``model_revision`` identifies the upstream checkpoint. Transformers receives
    only ``model_path`` and ``local_files_only=True``; this backend never downloads
    model files implicitly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = "local-transformers"
    model_path: Path
    model_id: str
    model_revision: str = Field(min_length=7)
    architecture: str = "Qwen3VLForConditionalGeneration"
    device: str = "cuda:0"
    dtype: str = "bfloat16"
    max_new_tokens: int = Field(default=256, ge=32, le=2048)
    max_retries: int = Field(default=1, ge=0, le=3)
    require_cuda: bool = True


@dataclass(frozen=True)
class LocalGeneration:
    text: str
    input_tokens: int
    output_tokens: int


class LocalGenerationRuntime(Protocol):
    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        seed: int,
        max_new_tokens: int,
    ) -> LocalGeneration: ...


class TransformersTextRuntime:
    """Lazy Transformers runtime; heavy optional imports occur on first request."""

    def __init__(self, config: LocalTransformersConfig) -> None:
        self.config = config
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._torch: Any | None = None

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        seed: int,
        max_new_tokens: int,
    ) -> LocalGeneration:
        self._load()
        torch = self._torch
        model = self._model
        tokenizer = self._tokenizer
        assert torch is not None and model is not None and tokenizer is not None

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tokenizer(prompt, return_tensors="pt")
        inputs = {key: value.to(self.config.device) for key, value in inputs.items()}
        input_tokens = int(inputs["input_ids"].shape[-1])
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=max_new_tokens,
                use_cache=True,
            )
        new_tokens = generated[0, input_tokens:]
        text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        return LocalGeneration(
            text=text,
            input_tokens=input_tokens,
            output_tokens=int(new_tokens.shape[-1]),
        )

    def _load(self) -> None:
        if self._model is not None:
            return
        model_path = self.config.model_path.expanduser().resolve()
        if not model_path.is_dir():
            raise RuntimeError(f"local model directory does not exist: {model_path}")
        try:
            import torch
            import transformers
            from transformers import AutoTokenizer
        except ImportError as exc:  # pragma: no cover - depends on optional environment
            raise RuntimeError(
                "local Transformers backend requires the 'local-gpu' optional dependencies"
            ) from exc
        if self.config.require_cuda and not torch.cuda.is_available():
            raise RuntimeError("local Transformers backend requires an available CUDA device")
        model_class = getattr(transformers, self.config.architecture, None)
        if model_class is None:
            raise RuntimeError(
                f"installed Transformers does not provide {self.config.architecture}"
            )
        dtype = getattr(torch, self.config.dtype, None)
        if dtype is None:
            raise RuntimeError(f"torch has no dtype named {self.config.dtype!r}")
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=False,
        )
        self._model = model_class.from_pretrained(
            model_path,
            dtype=dtype,
            device_map={"": self.config.device},
            local_files_only=True,
            trust_remote_code=False,
        ).eval()
        # Chat checkpoints default to sampling. Fixed-candidate evaluation uses
        # deterministic decoding and clears unused sampling flags explicitly.
        self._model.generation_config.do_sample = False
        self._model.generation_config.temperature = None
        self._model.generation_config.top_p = None
        self._model.generation_config.top_k = None
        self._torch = torch


class LocalTransformersBackend:
    """Rank fixed candidates with one explicitly selected local checkpoint."""

    def __init__(
        self,
        config: LocalTransformersConfig,
        *,
        runtime: LocalGenerationRuntime | None = None,
    ) -> None:
        self.config = config
        self.name = config.provider
        self.runtime = runtime or TransformersTextRuntime(config)

    def rank(self, request: PreferenceRequest) -> PreferenceResponse:
        prompt = _preference_prompt(request)
        started = time.perf_counter()
        attempt = 0
        while True:
            attempt += 1
            generated = self.runtime.generate(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=prompt,
                seed=request.seed,
                max_new_tokens=self.config.max_new_tokens,
            )
            try:
                parsed = _parse_json_object(generated.text)
                break
            except ValueError:
                if attempt > self.config.max_retries:
                    raise
                prompt = f"{prompt}\n\n{_FORMAT_REPAIR_REMINDER}"
        selected_action_id = str(parsed["selected_action_id"])
        candidate_ids = {action.action_id for action in request.candidate_actions}
        if selected_action_id not in candidate_ids:
            raise ValueError(f"local model selected unknown action {selected_action_id!r}")
        return PreferenceResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            selected_action_id=selected_action_id,
            rationale=str(parsed["rationale"]),
            confidence=float(parsed["confidence"]),
            backend=self.name,
            model=f"{self.config.model_id}@{self.config.model_revision}",
            raw_response=generated.text,
            raw_response_sha256=hashlib.sha256(generated.text.encode()).hexdigest(),
            latency_ms=(time.perf_counter() - started) * 1000,
            semantic_attempts=attempt,
            usage=Usage(
                input_tokens=generated.input_tokens,
                output_tokens=generated.output_tokens,
            ),
        )


def load_local_transformers_config(path: str | Path) -> LocalTransformersConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return LocalTransformersConfig.model_validate(_expand_environment(raw))


_FORMAT_REPAIR_REMINDER = (
    "Your previous response violated the required schema. Return exactly one JSON object "
    "containing selected_action_id (string), rationale (non-empty string), and confidence "
    "(number from 0 to 1). Do not add Markdown fences or commentary."
)


def _expand_environment(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    return value

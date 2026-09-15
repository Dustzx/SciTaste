"""Opt-in text-only preference backend for local Hugging Face checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.backends.base import (
    CandidateGenerationRequest,
    CandidateGenerationResponse,
    GeneratedCandidateProposal,
    PreferenceRequest,
    PreferenceResponse,
    Usage,
)
from scitaste.backends.checkpoint_manifest import (
    verify_local_checkpoint_identity_manifest,
)
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
    checkpoint_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    checkpoint_identity_manifest_path: Path | None = None
    checkpoint_identity_manifest_file_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    checkpoint_identity_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    architecture: str = "Qwen3VLForConditionalGeneration"
    device: str = "cuda:0"
    dtype: str = "bfloat16"
    max_new_tokens: int = Field(default=256, ge=32, le=8192)
    max_context_tokens: int = Field(default=16_384, ge=128, le=1_000_000)
    max_retries: int = Field(default=1, ge=0, le=3)
    require_cuda: bool = True
    execution_enabled: bool = False
    enable_thinking: bool = True

    @model_validator(mode="after")
    def generation_fits_context(self) -> LocalTransformersConfig:
        if self.max_new_tokens >= self.max_context_tokens:
            raise ValueError("max_new_tokens must be below max_context_tokens")
        manifest = (
            self.checkpoint_identity_manifest_path,
            self.checkpoint_identity_manifest_file_sha256,
            self.checkpoint_identity_sha256,
        )
        if any(manifest) != all(manifest):
            raise ValueError("checkpoint identity manifest binding must be atomic")
        if self.checkpoint_sha256 is not None and all(manifest):
            raise ValueError("select either full-tree or manifest checkpoint verification")
        return self

    @property
    def model_identity(self) -> str:
        """Return the exact identity expected by model-node policies."""

        return f"{self.model_id}@{self.model_revision}"

    @property
    def max_output_tokens(self) -> int:
        """Expose the generic structured-backend output ceiling."""

        return self.max_new_tokens


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
        self._checkpoint_verified = False

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        seed: int,
        max_new_tokens: int,
    ) -> LocalGeneration:
        return self.generate_messages(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            seed=seed,
            max_new_tokens=max_new_tokens,
            temperature=0.0,
        )

    def generate_messages(
        self,
        *,
        messages: list[dict[str, str]],
        seed: int,
        max_new_tokens: int,
        temperature: float = 0.0,
    ) -> LocalGeneration:
        """Generate from a complete chat while retaining one resident checkpoint."""

        if not messages:
            raise ValueError("local generation requires at least one chat message")
        if max_new_tokens < 1 or max_new_tokens > self.config.max_new_tokens:
            raise ValueError("requested output tokens exceed the local generation ceiling")
        if temperature < 0 or temperature > 2:
            raise ValueError("temperature must be between 0 and 2")
        self._load()
        torch = self._torch
        model = self._model
        tokenizer = self._tokenizer
        assert torch is not None and model is not None and tokenizer is not None

        template_options: dict[str, object] = {
            "tokenize": False,
            "add_generation_prompt": True,
        }
        if not self.config.enable_thinking:
            template_options["enable_thinking"] = False
        prompt = tokenizer.apply_chat_template(messages, **template_options)
        inputs = tokenizer(prompt, return_tensors="pt")
        inputs = {key: value.to(self.config.device) for key, value in inputs.items()}
        input_tokens = int(inputs["input_ids"].shape[-1])
        if input_tokens + max_new_tokens > self.config.max_context_tokens:
            raise ValueError("local generation request exceeds the configured context ceiling")
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        with torch.inference_mode():
            sampling = temperature > 0
            generation_options: dict[str, object] = {
                "do_sample": sampling,
                "max_new_tokens": max_new_tokens,
                "use_cache": True,
            }
            if sampling:
                generation_options["temperature"] = temperature
            generated = model.generate(
                **inputs,
                **generation_options,
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
        self.verify_checkpoint()
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

    def verify_checkpoint(self) -> None:
        """Verify the complete local checkpoint once before model loading."""

        if self._checkpoint_verified:
            return
        if self.config.checkpoint_identity_manifest_path is not None:
            assert self.config.checkpoint_identity_manifest_file_sha256 is not None
            assert self.config.checkpoint_identity_sha256 is not None
            verify_local_checkpoint_identity_manifest(
                self.config.model_path,
                self.config.checkpoint_identity_manifest_path,
                expected_manifest_file_sha256=(
                    self.config.checkpoint_identity_manifest_file_sha256
                ),
                expected_checkpoint_identity_sha256=self.config.checkpoint_identity_sha256,
            )
            self._checkpoint_verified = True
            return
        if self.config.checkpoint_sha256 is None:
            return
        observed = local_checkpoint_sha256(self.config.model_path)
        if observed != self.config.checkpoint_sha256:
            raise RuntimeError("local checkpoint content hash mismatch")
        self._checkpoint_verified = True

    def accept_campaign_checkpoint_verification(
        self,
        *,
        model_path: str | Path,
        checkpoint_sha256: str,
    ) -> None:
        """Reuse a controller-verified immutable checkpoint identity without rehashing it."""

        expected_path = self.config.model_path.expanduser().resolve(strict=True)
        observed_path = Path(model_path).expanduser().resolve(strict=True)
        if observed_path != expected_path:
            raise ValueError("campaign checkpoint verification belongs to another model path")
        if (
            self.config.checkpoint_sha256 is None
            or checkpoint_sha256 != self.config.checkpoint_sha256
        ):
            raise ValueError("campaign checkpoint verification has another content identity")
        self._checkpoint_verified = True


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
        input_tokens = 0
        output_tokens = 0
        while True:
            attempt += 1
            generated = self.runtime.generate(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=prompt,
                seed=request.seed,
                max_new_tokens=self.config.max_new_tokens,
            )
            input_tokens += generated.input_tokens
            output_tokens += generated.output_tokens
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
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
        )

    def generate_candidates(
        self,
        request: CandidateGenerationRequest,
    ) -> CandidateGenerationResponse:
        prompt = _candidate_generation_prompt(request)
        started = time.perf_counter()
        attempt = 0
        input_tokens = 0
        output_tokens = 0
        while True:
            attempt += 1
            generated = self.runtime.generate(
                system_prompt=_CANDIDATE_GENERATION_SYSTEM_PROMPT,
                user_prompt=prompt,
                seed=request.seed,
                max_new_tokens=self.config.max_new_tokens,
            )
            input_tokens += generated.input_tokens
            output_tokens += generated.output_tokens
            try:
                parsed = _CandidateProposalBatch.model_validate(
                    _parse_candidate_json_object(generated.text)
                )
                break
            except ValueError:
                if attempt > self.config.max_retries:
                    raise
                prompt = f"{prompt}\n\n{_CANDIDATE_FORMAT_REPAIR_REMINDER}"
        return CandidateGenerationResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            candidates=list(parsed.candidates),
            backend=self.name,
            model=f"{self.config.model_id}@{self.config.model_revision}",
            raw_response=generated.text,
            raw_response_sha256=hashlib.sha256(generated.text.encode()).hexdigest(),
            latency_ms=(time.perf_counter() - started) * 1000,
            semantic_attempts=attempt,
            usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        )


def load_local_transformers_config(path: str | Path) -> LocalTransformersConfig:
    return parse_local_transformers_config(Path(path).read_text(encoding="utf-8"))


def parse_local_transformers_config(raw: str) -> LocalTransformersConfig:
    """Parse one already-read config so callers can bind the exact source bytes."""

    raw = yaml.safe_load(raw)
    return LocalTransformersConfig.model_validate(_expand_environment(raw))


def local_checkpoint_sha256(path: str | Path) -> str:
    """Hash names, sizes, and bytes of every regular checkpoint file."""

    unresolved = Path(path).expanduser()
    if unresolved.is_symlink():
        raise RuntimeError("local checkpoint directory cannot be a symbolic link")
    root = unresolved.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError(f"local model directory does not exist: {root}")
    files: list[Path] = []
    for candidate in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if candidate.is_symlink():
            raise RuntimeError("local checkpoint cannot contain symbolic links")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise RuntimeError("local checkpoint contains a non-regular entry")
        files.append(candidate)
    if not files:
        raise RuntimeError("local checkpoint directory contains no files")

    digest = hashlib.sha256(b"SCITASTE_LOCAL_CHECKPOINT_V1\0")
    for candidate in files:
        relative = candidate.relative_to(root).as_posix().encode("utf-8")
        size = candidate.stat().st_size
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(size.to_bytes(8, "big"))
        observed_size = 0
        with candidate.open("rb") as handle:
            while block := handle.read(8 * 1024 * 1024):
                observed_size += len(block)
                digest.update(block)
        if observed_size != size:
            raise RuntimeError("local checkpoint changed while it was being hashed")
    return digest.hexdigest()


_FORMAT_REPAIR_REMINDER = (
    "Your previous response violated the required schema. Return exactly one JSON object "
    "containing selected_action_id (string), rationale (non-empty string), and confidence "
    "(number from 0 to 1). Do not add Markdown fences or commentary."
)


class _CandidateProposalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: tuple[GeneratedCandidateProposal, ...] = Field(min_length=2, max_length=12)


_CANDIDATE_GENERATION_SYSTEM_PROMPT = (
    "You concretize scientific research actions inside a deterministic execution envelope. "
    "Return JSON only. Cover every supplied template exactly once. Never invent an action ID, "
    "action type, tool, cost, or evidence. Parameter overrides must be empty except that an "
    "existing SEARCH template may override only its query string."
)

_CANDIDATE_FORMAT_REPAIR_REMINDER = (
    "Your previous response violated the required schema. Return exactly one JSON object with "
    "a candidates array. Every item must contain template_action_id, description, "
    "parameter_overrides, and rationale. Cover each template exactly once and add no fields."
)


def _candidate_generation_prompt(request: CandidateGenerationRequest) -> str:
    payload = {
        "schema_version": "1.0",
        "request_id": request.request_id,
        "task": request.task,
        "stage": request.stage,
        "decision_context": request.decision_context,
        "action_templates": [item.model_dump(mode="json") for item in request.action_templates],
        "required_output": {
            "candidates": [
                {
                    "template_action_id": "one supplied action_id",
                    "description": "bounded concrete action description",
                    "parameter_overrides": {
                        "query": "optional only for an existing SEARCH template"
                    },
                    "rationale": "why this concretization fits the supplied context",
                }
            ]
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _parse_candidate_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("candidate model did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("candidate model response JSON must be an object")
    return value


def _expand_environment(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    return value

from __future__ import annotations

import builtins
import sys
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace

import pytest

from scitaste.backends.base import PreferenceRequest
from scitaste.backends.local_transformers import (
    LocalGeneration,
    LocalTransformersBackend,
    LocalTransformersConfig,
    TransformersTextRuntime,
    _expand_environment,
    load_local_transformers_config,
    local_checkpoint_sha256,
    parse_local_transformers_config,
)
from scitaste.schema.actions import MetaAction, ResearchAction


class StubRuntime:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        seed: int,
        max_new_tokens: int,
    ) -> LocalGeneration:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "seed": seed,
                "max_new_tokens": max_new_tokens,
            }
        )
        return LocalGeneration(
            text=self.responses[len(self.calls) - 1],
            input_tokens=41,
            output_tokens=17,
        )


def _config() -> LocalTransformersConfig:
    return LocalTransformersConfig(
        model_path="/models/qwen",
        model_id="Qwen/Qwen3-VL-4B-Instruct",
        model_revision="ebb281ec70b05090aa6165b016eac8ec08e71b17",
    )


def _request() -> PreferenceRequest:
    return PreferenceRequest(
        request_id="local-case",
        task="experiment",
        stage="VALIDATION",
        decision_context="Choose the action with the highest information value.",
        candidate_actions=[
            ResearchAction(
                action_id="probe",
                type=MetaAction.PROBE,
                description="Run a bounded falsification probe",
            ),
            ResearchAction(
                action_id="write",
                type=MetaAction.WRITE,
                description="Write the conclusion immediately",
            ),
        ],
        seed=19,
    )


def test_local_backend_preserves_pinned_model_and_usage() -> None:
    runtime = StubRuntime(
        ['{"selected_action_id":"probe","rationale":"More informative","confidence":0.82}']
    )

    response = LocalTransformersBackend(_config(), runtime=runtime).rank(_request())

    assert response.selected_action_id == "probe"
    assert response.model.endswith("@ebb281ec70b05090aa6165b016eac8ec08e71b17")
    assert response.usage.input_tokens == 41
    assert response.usage.output_tokens == 17
    assert response.raw_response_sha256 is not None
    assert runtime.calls[0]["seed"] == 19


def test_local_backend_retries_schema_failure_without_changing_candidates() -> None:
    runtime = StubRuntime(
        [
            "probe",
            '{"selected_action_id":"probe","rationale":"Repaired","confidence":0.7}',
        ]
    )

    response = LocalTransformersBackend(_config(), runtime=runtime).rank(_request())

    assert response.semantic_attempts == 2
    assert "violated the required schema" in str(runtime.calls[1]["user_prompt"])
    assert '"action_id": "probe"' in str(runtime.calls[1]["user_prompt"])


def test_local_config_expands_model_path(monkeypatch, tmp_path) -> None:
    model_dir = tmp_path / "checkpoint"
    monkeypatch.setenv("SCITASTE_TEST_MODEL", str(model_dir))
    config_path = tmp_path / "local.yaml"
    config_path.write_text(
        "\n".join(
            [
                "model_path: ${SCITASTE_TEST_MODEL}",
                "model_id: Qwen/Qwen3-VL-4B-Instruct",
                "model_revision: ebb281ec70b05090aa6165b016eac8ec08e71b17",
            ]
        ),
        encoding="utf-8",
    )

    config = load_local_transformers_config(config_path)

    assert config.model_path == model_dir

    parsed = parse_local_transformers_config(config_path.read_text(encoding="utf-8"))
    assert parsed == config


def test_committed_qwen3vl2b_config_pins_the_selected_local_snapshot(
    monkeypatch,
    tmp_path,
) -> None:
    model_dir = tmp_path / "Qwen3-VL-2B-Instruct"
    monkeypatch.setenv("SCITASTE_LOCAL_MODEL_PATH", str(model_dir))

    config = load_local_transformers_config(
        "configs/backends/local_transformers_qwen3vl2b.example.yaml"
    )

    assert config.model_path == model_dir
    assert config.model_id == "Qwen/Qwen3-VL-2B-Instruct"
    assert config.checkpoint_sha256 == (
        "47f9c0e0e48a54c74fb0b2b0ffa7a182fed381d5ed49a0200872038d1c286d34"
    )


def test_scitastebench_qwen3vl2b_config_binds_the_observed_tree_and_device(
    monkeypatch,
    tmp_path,
) -> None:
    model_dir = tmp_path / "Qwen3-VL-2B-Instruct"
    monkeypatch.setenv("SCITASTE_LOCAL_MODEL_PATH", str(model_dir))
    monkeypatch.setenv("SCITASTE_LOCAL_DEVICE", "cuda:7")

    config = load_local_transformers_config(
        "configs/backends/local_transformers_qwen3vl2b_scitastebench_v1.yaml"
    )

    assert config.model_path == model_dir
    assert config.device == "cuda:7"
    assert config.model_revision == "local-tree-8e95e5f6"
    assert config.checkpoint_sha256 == (
        "8e95e5f6d2ce9219e40be475c077700c51495889166d38cf99c17acd6513b7a1"
    )


def test_local_checkpoint_hash_binds_names_sizes_and_bytes(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text("first\n", encoding="utf-8")
    nested = checkpoint / "tokenizer"
    nested.mkdir()
    (nested / "vocab.json").write_text("second\n", encoding="utf-8")

    first = local_checkpoint_sha256(checkpoint)
    assert local_checkpoint_sha256(checkpoint) == first
    (nested / "vocab.json").write_text("changed\n", encoding="utf-8")
    assert local_checkpoint_sha256(checkpoint) != first

    (nested / "vocab.json").unlink()
    (nested / "vocab.json").symlink_to(checkpoint / "config.json")
    with pytest.raises(RuntimeError, match="symbolic links"):
        local_checkpoint_sha256(checkpoint)


class FakeTensor:
    def __init__(self, shape: tuple[int, ...]) -> None:
        self.shape = shape
        self.device: str | None = None

    def to(self, device: str):
        self.device = device
        return self

    def __getitem__(self, key):
        assert key == (0, slice(self.shape[-1] - 3, None))
        return FakeTensor((3,))


class FakeTokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert messages[0]["role"] == "system"
        assert tokenize is False
        assert add_generation_prompt is True
        return "rendered prompt"

    def __call__(self, prompt, *, return_tensors):
        assert prompt == "rendered prompt"
        assert return_tensors == "pt"
        return {"input_ids": FakeTensor((1, 5)), "attention_mask": FakeTensor((1, 5))}

    def decode(self, tokens, *, skip_special_tokens):
        assert tokens.shape == (3,)
        assert skip_special_tokens is True
        return " generated text "


class FakeModel:
    def __init__(self) -> None:
        self.generation_config = SimpleNamespace(
            do_sample=True,
            temperature=0.7,
            top_p=0.8,
            top_k=20,
        )
        self.generate_kwargs = None

    def eval(self):
        return self

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return FakeTensor((1, 8))


class FakeCuda:
    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.seeds: list[int] = []

    def is_available(self) -> bool:
        return self.available

    def manual_seed_all(self, seed: int) -> None:
        self.seeds.append(seed)


class FakeTorch:
    def __init__(self, *, cuda_available: bool = True) -> None:
        self.cuda = FakeCuda(cuda_available)
        self.bfloat16 = object()
        self.seeds: list[int] = []

    def manual_seed(self, seed: int) -> None:
        self.seeds.append(seed)

    @staticmethod
    def inference_mode():
        return nullcontext()


def test_transformers_runtime_generates_from_one_resident_model() -> None:
    runtime = TransformersTextRuntime(_config())
    runtime._model = FakeModel()
    runtime._tokenizer = FakeTokenizer()
    runtime._torch = FakeTorch()

    generated = runtime.generate(
        system_prompt="system",
        user_prompt="user",
        seed=31,
        max_new_tokens=64,
    )

    assert generated == LocalGeneration(text="generated text", input_tokens=5, output_tokens=3)
    assert runtime._torch.seeds == [31]
    assert runtime._torch.cuda.seeds == [31]
    assert runtime._model.generate_kwargs["do_sample"] is False
    assert runtime._model.generate_kwargs["max_new_tokens"] == 64


def test_transformers_runtime_preserves_chat_and_bounds_context() -> None:
    runtime = TransformersTextRuntime(_config().model_copy(update={"max_context_tokens": 68}))
    runtime._model = FakeModel()
    runtime._tokenizer = FakeTokenizer()
    runtime._torch = FakeTorch()

    generated = runtime.generate_messages(
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ],
        seed=4,
        max_new_tokens=63,
        temperature=0.3,
    )

    assert generated.output_tokens == 3
    assert runtime._model.generate_kwargs["do_sample"] is True
    assert runtime._model.generate_kwargs["temperature"] == 0.3

    with pytest.raises(ValueError, match="context ceiling"):
        runtime.generate_messages(
            messages=[
                {"role": "system", "content": "system"},
                {"role": "user", "content": "oversized"},
            ],
            seed=4,
            max_new_tokens=64,
        )


def test_local_config_rejects_output_ceiling_at_or_above_context() -> None:
    with pytest.raises(ValueError, match="below max_context_tokens"):
        LocalTransformersConfig.model_validate(
            {
                **_config().model_dump(mode="python"),
                "max_new_tokens": 256,
                "max_context_tokens": 256,
            }
        )


def test_transformers_runtime_rejects_missing_checkpoint(tmp_path) -> None:
    config = _config().model_copy(update={"model_path": tmp_path / "missing"})

    with pytest.raises(RuntimeError, match="does not exist"):
        TransformersTextRuntime(config)._load()


def test_transformers_runtime_reports_missing_optional_dependencies(monkeypatch, tmp_path) -> None:
    config = _config().model_copy(update={"model_path": tmp_path})
    original_import = builtins.__import__

    def reject_torch(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("fixture")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_torch)

    with pytest.raises(RuntimeError, match="local-gpu"):
        TransformersTextRuntime(config)._load()


def _fake_modules(monkeypatch, *, cuda_available=True, model_class=True, dtype=True):
    torch = ModuleType("torch")
    fake_torch = FakeTorch(cuda_available=cuda_available)
    torch.cuda = fake_torch.cuda
    if dtype:
        torch.bfloat16 = fake_torch.bfloat16
    transformers = ModuleType("transformers")
    tokenizer = FakeTokenizer()
    tokenizer_class = SimpleNamespace(from_pretrained=lambda *args, **kwargs: tokenizer)
    transformers.AutoTokenizer = tokenizer_class
    model = FakeModel()
    if model_class:
        model_type = SimpleNamespace(from_pretrained=lambda *args, **kwargs: model)
        transformers.Qwen3VLForConditionalGeneration = model_type
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    return model, tokenizer


def test_transformers_runtime_requires_cuda(monkeypatch, tmp_path) -> None:
    _fake_modules(monkeypatch, cuda_available=False)
    config = _config().model_copy(update={"model_path": tmp_path})

    with pytest.raises(RuntimeError, match="CUDA"):
        TransformersTextRuntime(config)._load()


def test_transformers_runtime_requires_supported_architecture(monkeypatch, tmp_path) -> None:
    _fake_modules(monkeypatch, model_class=False)
    config = _config().model_copy(update={"model_path": tmp_path})

    with pytest.raises(RuntimeError, match="does not provide"):
        TransformersTextRuntime(config)._load()


def test_transformers_runtime_requires_known_dtype(monkeypatch, tmp_path) -> None:
    _fake_modules(monkeypatch, dtype=False)
    config = _config().model_copy(update={"model_path": tmp_path})

    with pytest.raises(RuntimeError, match="no dtype"):
        TransformersTextRuntime(config)._load()


def test_transformers_runtime_load_is_local_and_deterministic(monkeypatch, tmp_path) -> None:
    model, tokenizer = _fake_modules(monkeypatch)
    config = _config().model_copy(update={"model_path": tmp_path})
    runtime = TransformersTextRuntime(config)

    runtime._load()

    assert runtime._model is model
    assert runtime._tokenizer is tokenizer
    assert model.generation_config.do_sample is False
    assert model.generation_config.temperature is None
    assert model.generation_config.top_p is None
    assert model.generation_config.top_k is None


def test_local_backend_rejects_unknown_action() -> None:
    runtime = StubRuntime(['{"selected_action_id":"other","rationale":"No","confidence":0.5}'])

    with pytest.raises(ValueError, match="unknown action"):
        LocalTransformersBackend(_config(), runtime=runtime).rank(_request())


def test_local_backend_exhausts_schema_repair() -> None:
    runtime = StubRuntime(["not-json", "still-not-json"])

    with pytest.raises(ValueError, match="valid JSON"):
        LocalTransformersBackend(_config(), runtime=runtime).rank(_request())


def test_environment_expansion_handles_nested_values(monkeypatch) -> None:
    monkeypatch.setenv("SCITASTE_VALUE", "resolved")

    assert _expand_environment({"items": ["${SCITASTE_VALUE}", 3]}) == {"items": ["resolved", 3]}

#!/usr/bin/env python3
"""Run the label-hidden boundary-only negative control for SciTasteBench pairs.

The chooser receives the frozen action menu, visible budget, and the registered
fact value in two randomly ordered states.  It never receives the shared
scientific context, invariant facts, utilities, constructor rationale, or
registered labels.  Recovering both labels therefore exposes a cue-solvable
pair; failing to recover them is necessary, but never sufficient, for admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.benchmark import BoundaryCounterfactualPair, BoundaryPairPackage
from scitaste.model_nodes import (
    StructuredModelRequest,
    StructuredModelResponse,
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class BoundaryCueControlConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    control_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    pair_packages: tuple[FileBinding, ...] = Field(min_length=1)
    pair_selection_policy: Literal["first-package-wins-by-pair-id"]
    chooser_backend: FileBinding
    chooser_provider: str = Field(min_length=1)
    chooser_model: str = Field(min_length=1)
    batch_size: int = Field(ge=1, le=12)
    seed: int
    invariant_context_visible: Literal[False]
    expected_pair_labels_visible: Literal[False]
    admission_policy: Literal["reject-if-both-registered-labels-recovered"]
    formal_split_opened: Literal[False]


class BoundaryCueChoice(BaseModel):
    model_config = _CONFIG

    pair_id: str = Field(min_length=1)
    state_1_selection_id: str | None = Field(default=None, min_length=1)
    state_1_should_abstain: bool = False
    state_2_selection_id: str | None = Field(default=None, min_length=1)
    state_2_should_abstain: bool = False
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def choices_are_atomic(self) -> BoundaryCueChoice:
        for role, selection, abstains in (
            ("state_1", self.state_1_selection_id, self.state_1_should_abstain),
            ("state_2", self.state_2_selection_id, self.state_2_should_abstain),
        ):
            if abstains == (selection is not None):
                raise ValueError(f"{role} must select one action xor abstain")
        return self


class BoundaryCueChoiceBatch(BaseModel):
    model_config = _CONFIG

    choices: tuple[BoundaryCueChoice, ...] = Field(min_length=1, max_length=12)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser


def _bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bound input must be a regular file: {path}")
    return path.read_bytes()


def _bound(root: Path, binding: FileBinding) -> Path:
    path = (root / binding.locator).resolve(strict=True)
    path.relative_to(root)
    if hashlib.sha256(_bytes(path)).hexdigest() != binding.sha256:
        raise ValueError(f"bound input hash mismatch: {binding.locator}")
    return path


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
    temporary.replace(path)


def _pairs(paths: tuple[Path, ...]) -> tuple[list[BoundaryCounterfactualPair], dict[str, str]]:
    pairs: list[BoundaryCounterfactualPair] = []
    sources: dict[str, str] = {}
    seen: set[str] = set()
    for path in paths:
        package = BoundaryPairPackage.model_validate_json(_bytes(path))
        for pair in package.pairs:
            if pair.pair_id in seen:
                continue
            seen.add(pair.pair_id)
            pairs.append(pair)
            sources[pair.pair_id] = package.package_id
    return pairs, sources


def _state_order(seed: int, pair_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"cue-control:{seed}:{pair_id}".encode()).digest()
    return ("base", "twin") if digest[0] % 2 == 0 else ("twin", "base")


def _instruction() -> str:
    return """You choose between frozen scientific actions using deliberately incomplete input.
For each pair you see only a visible budget, one registered fact question, its value in two randomly
ordered states, and the identical action menu. You do not receive the research question, scientific
context, invariant facts, original source, expected labels, utilities, or observed outcome.

For each state, select exactly one listed action only when the visible fact and budget uniquely
justify it. Otherwise abstain. Do not invent missing scientific context. Return choices in input
order and one JSON object matching the supplied schema, with no prose outside it."""


def _payload(
    pair: BoundaryCounterfactualPair,
    order: tuple[str, str],
) -> dict[str, JsonValue]:
    values = {
        "base": pair.changed_fact.base_value,
        "twin": pair.changed_fact.twin_value,
    }
    return {
        "pair_id": pair.pair_id,
        "visible_budget": pair.base.visible_budget,
        "registered_fact_question": pair.changed_fact.question,
        "frozen_action_menu": [item.model_dump(mode="json") for item in pair.candidate_actions],
        "state_1_fact_value": values[order[0]],
        "state_2_fact_value": values[order[1]],
    }


def _request(
    config: BoundaryCueControlConfig,
    *,
    batch_number: int,
    pairs: list[BoundaryCounterfactualPair],
    policy_fingerprint: str,
) -> tuple[StructuredModelRequest, dict[str, tuple[str, str]]]:
    orders = {pair.pair_id: _state_order(config.seed, pair.pair_id) for pair in pairs}
    request = StructuredModelRequest(
        request_id=f"{config.control_id}-batch-{batch_number:02d}",
        node_name="scitastebench-boundary-cue-control",
        stage="EVALUATION",
        state_snapshot_id=f"{config.control_id}-context-hidden",
        expected_backend=config.chooser_provider,
        expected_model=config.chooser_model,
        policy_id=config.control_id,
        policy_fingerprint=policy_fingerprint,
        system_instruction=_instruction(),
        input_payload={
            "invariant_context_visible": False,
            "expected_pair_labels_visible": False,
            "state_names_are_randomized": True,
            "pairs": [_payload(pair, orders[pair.pair_id]) for pair in pairs],
        },
        output_schema=BoundaryCueChoiceBatch.model_json_schema(mode="serialization"),
        seed=config.seed + batch_number,
        prompt_version="scitastebench-boundary-cue-control-v1",
    )
    forbidden = (
        b'"decision_context"',
        b'"invariant_facts"',
        b'"preferred_action_id"',
        b'"action_utilities"',
        b'"utility_components"',
        b'"why_decisive"',
    )
    request_bytes = request.model_dump_json().encode()
    if any(token in request_bytes for token in forbidden):
        raise ValueError("scientific context or registered labels leaked into cue control")
    return request, orders


def _validate_choice(choice: BoundaryCueChoice, pair: BoundaryCounterfactualPair) -> None:
    action_ids = {item.action_id for item in pair.candidate_actions}
    for selection in (choice.state_1_selection_id, choice.state_2_selection_id):
        if selection is not None and selection not in action_ids:
            raise ValueError(f"cue chooser selected an action outside the menu: {selection}")


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_raw = _bytes(config_path)
    config = BoundaryCueControlConfig.model_validate(yaml.safe_load(config_raw))
    package_paths = tuple(_bound(root, item) for item in config.pair_packages)
    backend_path = _bound(root, config.chooser_backend)
    pairs, package_sources = _pairs(package_paths)
    backend_config = load_structured_openai_compatible_config(backend_path)
    if (backend_config.provider, backend_config.model) != (
        config.chooser_provider,
        config.chooser_model,
    ):
        raise ValueError("cue-control backend identity differs from frozen config")
    policy_fingerprint = content_sha256(
        {
            "config_sha256": hashlib.sha256(config_raw).hexdigest(),
            "backend_sha256": config.chooser_backend.sha256,
            "instruction": _instruction(),
        }
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    backend = StructuredOpenAICompatibleBackend(backend_config) if args.allow_api else None
    records: list[dict[str, JsonValue]] = []
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    completed = 0
    for offset in range(0, len(pairs), config.batch_size):
        batch_number = offset // config.batch_size + 1
        batch_pairs = pairs[offset : offset + config.batch_size]
        request, orders = _request(
            config,
            batch_number=batch_number,
            pairs=batch_pairs,
            policy_fingerprint=policy_fingerprint,
        )
        request_path = output / "requests" / f"{batch_number:02d}.json"
        _write(request_path, (request.model_dump_json(indent=2) + "\n").encode())
        response_path = output / "responses" / f"{batch_number:02d}.json"
        if args.resume and response_path.is_file():
            response = StructuredModelResponse.model_validate_json(_bytes(response_path))
            if response.request_fingerprint != request.fingerprint:
                raise ValueError(f"saved response request drift in batch {batch_number}")
        else:
            if backend is None:
                continue
            response = backend.complete(request)
            _write(response_path, (response.model_dump_json(indent=2) + "\n").encode())
        completed += 1
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        usage["cost_usd"] += response.usage.cost_usd or 0.0
        choices = BoundaryCueChoiceBatch.model_validate(response.output_payload).choices
        expected_ids = [pair.pair_id for pair in batch_pairs]
        if [choice.pair_id for choice in choices] != expected_ids:
            raise ValueError(f"cue chooser changed pair order in batch {batch_number}")
        for pair, choice in zip(batch_pairs, choices, strict=True):
            _validate_choice(choice, pair)
            order = orders[pair.pair_id]
            submitted = {
                order[0]: (choice.state_1_selection_id, choice.state_1_should_abstain),
                order[1]: (choice.state_2_selection_id, choice.state_2_should_abstain),
            }
            base_correct = submitted["base"] == (
                pair.base.preferred_action_id,
                pair.base.should_abstain,
            )
            twin_correct = submitted["twin"] == (
                pair.twin.preferred_action_id,
                pair.twin.should_abstain,
            )
            records.append(
                {
                    "schema_version": "1.0",
                    "control_id": config.control_id,
                    "chooser_provider": config.chooser_provider,
                    "chooser_model": config.chooser_model,
                    "pair_id": pair.pair_id,
                    "source_package_id": package_sources[pair.pair_id],
                    "state_order": {"state_1": order[0], "state_2": order[1]},
                    "choice": choice.model_dump(mode="json"),
                    "base_registered_label_recovered": base_correct,
                    "twin_registered_label_recovered": twin_correct,
                    "both_registered_labels_recovered": base_correct and twin_correct,
                    "passes_boundary_cue_control": not (base_correct and twin_correct),
                    "request_fingerprint": request.fingerprint,
                    "response_sha256": response.raw_response_sha256,
                }
            )
    batch_count = (len(pairs) + config.batch_size - 1) // config.batch_size
    plan = {
        "schema_version": "1.0",
        "control_id": config.control_id,
        "config": {
            "locator": str(config_path.relative_to(root)),
            "sha256": hashlib.sha256(config_raw).hexdigest(),
        },
        "policy_fingerprint": policy_fingerprint,
        "candidate_pair_count": len(pairs),
        "batch_count": batch_count,
        "invariant_context_visible": False,
        "expected_pair_labels_visible": False,
        "admission_policy": config.admission_policy,
        "api_execution_performed": backend is not None,
        "formal_split_opened": False,
    }
    _write(output / "PLAN.json", (json.dumps(plan, indent=2) + "\n").encode())
    if completed == 0:
        return 0
    if completed != batch_count:
        raise ValueError("cannot compile a partial boundary-cue control")
    lines = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records)
    _write(output / "CHOICES.jsonl", lines.encode())
    recovered = [item for item in records if item["both_registered_labels_recovered"]]
    summary = {
        "schema_version": "1.0",
        "control_id": config.control_id,
        "candidate_pair_count": len(records),
        "both_registered_labels_recovered_count": len(recovered),
        "passes_boundary_cue_control_count": len(records) - len(recovered),
        "pair_recovery_rate": len(recovered) / len(records),
        "choice_records_sha256": hashlib.sha256(lines.encode()).hexdigest(),
        "usage": usage,
        "invariant_context_visible": False,
        "expected_pair_labels_visible": False,
        "formal_split_opened": False,
        "effectiveness_claim_allowed": False,
    }
    _write(output / "SUMMARY.json", (json.dumps(summary, indent=2) + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

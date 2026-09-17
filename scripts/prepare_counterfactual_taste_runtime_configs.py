#!/usr/bin/env python3
"""Bind prepared counterfactual Taste inputs to the durable model-node runtime."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scitaste.model_nodes.facade import ImmutableStateProjection
from scitaste.model_nodes.models import NodePolicy
from scitaste.model_nodes.openai_compatible import (
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.model_nodes.runtime import ModelNodeTrigger
from scitaste.model_nodes.runtime_config import LiveRuntimeBackend, ModelNodeRuntimeConfig
from scitaste.taste.semantic_models import (
    GROUNDED_TASTE_ABSTRACTION_NODE,
    TasteAbstractionInput,
)


def run(args: argparse.Namespace) -> tuple[Path, ...]:
    loaded_profiles = load_model_node_profile_set(args.profile_set)
    try:
        profile = loaded_profiles.profiles[args.profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown model-node profile {args.profile_id!r}") from exc
    backend = load_structured_openai_compatible_config(args.backend_config)
    if (backend.provider, backend.model) != (profile.provider, profile.model):
        raise ValueError("backend and abstraction profile model identities differ")
    backend = backend.model_copy(
        update={"max_output_tokens": profile.generation.max_output_tokens}
    )
    policy = NodePolicy(
        policy_id="counterfactual-grounded-taste-abstraction-v1",
        enabled=True,
        allowed_node_names=[GROUNDED_TASTE_ABSTRACTION_NODE],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_tool_names=list(profile.admission.allowed_tool_names),
        allowed_action_types=[],
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
        require_cost_telemetry=True,
    )
    outputs = []
    for input_path in sorted(args.input_root.glob("*/INPUT.json")):
        abstraction_input = TasteAbstractionInput.model_validate_json(
            input_path.read_bytes(), strict=True
        )
        invocation_id = input_path.parent.name
        config = ModelNodeRuntimeConfig(
            node_name=GROUNDED_TASTE_ABSTRACTION_NODE,
            request_id=invocation_id,
            node_input=abstraction_input.model_dump(mode="json"),
            state_projection=ImmutableStateProjection(
                project_id=args.project_id,
                state_snapshot_id=abstraction_input.source_projection_sha256,
                state_revision=args.state_revision,
                stage=abstraction_input.stage,
                evidence_ids=(abstraction_input.source_id,),
            ),
            trigger=ModelNodeTrigger(
                trigger_id=f"abstract-{invocation_id}",
                reason=(
                    "Abstract an objective counterfactual development result into a "
                    "transfer-bounded Scientific Taste precedent."
                ),
            ),
            policy=policy,
            backend=LiveRuntimeBackend(config=backend),
            seed=0,
        )
        target = input_path.parent / "RUNTIME_CONFIG.json"
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        encoded = (
            json.dumps(
                config.model_dump(mode="json", exclude_computed_fields=True),
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()
        with target.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        outputs.append(target)
    if not outputs:
        raise ValueError("counterfactual abstraction input root contains no INPUT.json files")
    return tuple(outputs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--project-id", default="scitaste-self-development")
    parser.add_argument("--state-revision", type=int, required=True)
    parser.add_argument("--profile-set", type=Path, required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--backend-config", type=Path, required=True)
    return parser


def main() -> None:
    for path in run(build_parser().parse_args()):
        print(path)


if __name__ == "__main__":
    main()

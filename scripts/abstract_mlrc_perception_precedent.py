#!/usr/bin/env python3
"""Distill one source-grounded Taste precedent from the MLRC task background."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResultStatus
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.taste.semantic import GroundedTasteAbstractionNode
from scitaste.taste.semantic_models import TasteAbstractionInput

_DEFAULT_TASK = Path(
    "outputs/projects/scitaste-self-development/evaluations/acquisitions/"
    "mlrc-bench-source-v1/checkout/MLAgentBench/benchmarks_base/"
    "perception_temporal_action_loc"
)


def _exact(text: str, excerpt: str) -> str:
    if text.count(excerpt) != 1:
        raise ValueError(f"expected exactly one source excerpt: {excerpt[:80]}")
    return excerpt


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _policy(profile_path: Path) -> tuple[object, NodePolicy]:
    profile = load_model_node_profile(profile_path)
    return profile, NodePolicy(
        policy_id="mlrc-perception-grounded-taste-v1",
        enabled=True,
        allowed_node_names=["grounded-taste-abstraction"],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_tool_names=list(profile.admission.allowed_tool_names),
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", type=Path, default=_DEFAULT_TASK)
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/deepseek_v41flash.scitastebench_live_20260917.yaml"),
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(
            "configs/model_nodes/profile_deepseek_v41flash_grounded_taste_abstraction_v1.yaml"
        ),
    )
    parser.add_argument("--allow-api", action="store_true")
    args = parser.parse_args()
    if not args.allow_api:
        raise ValueError("live Taste abstraction requires --allow-api")
    repository = Path.cwd().resolve(strict=True)
    output = args.output if args.output.is_absolute() else repository / args.output
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    task = args.task if args.task.is_absolute() else repository / args.task
    task = task.resolve(strict=True)
    background = (task / "scripts" / "background.txt").read_text(encoding="utf-8")
    problem = (task / "scripts" / "research_problem.txt").read_text(encoding="utf-8")
    fields = {
        "research_goal": {
            "semantic_role": "problem_context",
            "value": _exact(
                problem,
                "Build a **temporal action localization system** and evaluate it rigorously "
                "on the train/val/test splits.",
            ),
        },
        "error_evidence": {
            "semantic_role": "evidence",
            "value": _exact(
                background,
                "the primary error of the ActionFormer baseline model is wrong label.",
            ),
        },
        "mechanism_evidence": {
            "semantic_role": "justification",
            "value": _exact(
                background,
                "We argue that this is due to the decoupling of the classification and "
                "localization branches in ActionFormer, leading to an inconsistency between "
                "classification scores and temporal localization quality.",
            ),
        },
        "selected_action": {
            "semantic_role": "scientific_action",
            "value": _exact(
                background,
                "Therefore, we propose an action quality loss, using the IoU between the "
                "temporal boundary and the ground truth as soft supervision for the "
                "classification scores, allowing the classification branch to be aware of "
                "the IoU quality.",
            ),
        },
        "available_alternatives": {
            "semantic_role": "alternative",
            "value": [
                _exact(
                    background,
                    "we transform the local self-attention in ActionFormer into global "
                    "self-attention to enhance the long-range modeling and improve overall "
                    "temporal action localization performance.",
                ),
                _exact(
                    background,
                    "we propose Action Copy Paste for data augmentation to enrich the temporal "
                    "relationships between action instances in video.",
                ),
                _exact(
                    background,
                    "we utilize ActionMamba as a complementary action detection head to "
                    "ActionFormer, aiming for subsequent model ensemble to achieve more robust "
                    "results.",
                ),
            ],
        },
        "resource_boundary": {
            "semantic_role": "limitation",
            "value": _exact(
                problem,
                "Use only the **provided pretrained video/audio features**.",
            ),
        },
    }
    projection = json.dumps(
        {
            "schema_version": "1.0",
            "outcome_information_availability": "withheld",
            "fields": fields,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    projection_sha256 = hashlib.sha256(projection.encode()).hexdigest()
    input_data = TasteAbstractionInput(
        source_id="mlrc-perception-official-background",
        candidate_id="quality-aware-classification-precedent",
        case_id="mlrc-perception-quality-aware-classification",
        stage="EXPERIMENTATION",
        decision_role="Select one falsifiable method intervention for a bounded development run.",
        source_projection=projection,
        source_projection_sha256=projection_sha256,
        domain_tags=("temporal-action-localization", "multimodal-perception"),
        outcome_information_availability="withheld",
        relation_label_hidden=True,
        held_out_task_content_excluded=True,
        source_projection_is_only_source_content=True,
    )
    profile, policy = _policy(args.profile.resolve(strict=True))
    backend_config = load_structured_openai_compatible_config(args.backend.resolve(strict=True))
    if (backend_config.provider, backend_config.model) != (profile.provider, profile.model):
        raise ValueError("abstraction backend identity differs from the model profile")
    result = GroundedTasteAbstractionNode().run(
        input_data,
        context=NodeContext(
            project_id="scitaste-self-development",
            stage=input_data.stage,
            state_snapshot_id=projection_sha256,
            cumulative_api_cost_usd=0.0,
            evidence_ids=[input_data.source_id],
        ),
        backend=StructuredOpenAICompatibleBackend(backend_config),
        policy=policy,
        profile=profile,
        request_id="mlrc-perception-grounded-taste-abstraction-v1",
    )
    output.mkdir(parents=True)
    _write_json(output / "SOURCE_PROJECTION.json", json.loads(projection))
    _write_json(output / "NODE_RESULT.json", result.model_dump(mode="json"))
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("Taste abstraction rejected: " + "; ".join(result.rejection_reasons))
    _write_json(output / "TASTE_CAPSULE.json", result.proposal.model_dump(mode="json"))
    print((output / "TASTE_CAPSULE.json").as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

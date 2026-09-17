#!/usr/bin/env python3
"""Compile outcome-grounded Taste precedents for MLRC Perception development.

The source projection combines exact method excerpts from MLRC's provided
background with objective competition outcomes from the official challenge
summary.  The abstraction model never sees the target development score or
held-out labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResultStatus
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.project.models import content_sha256
from scitaste.taste.semantic import GroundedTasteAbstractionNode
from scitaste.taste.semantic_models import TasteAbstractionInput

_DEFAULT_TASK = Path(
    "outputs/projects/scitaste-self-development/evaluations/acquisitions/"
    "mlrc-bench-source-v1/checkout/MLAgentBench/benchmarks_base/"
    "perception_temporal_action_loc"
)
_DEFAULT_SOURCES = Path(
    "outputs/projects/scitaste-self-development/evaluations/acquisitions/"
    "perception-taste-sources-v1"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _exact_normalized(source: str, excerpt: str) -> str:
    normalized_source = _normalized(source)
    normalized_excerpt = _normalized(excerpt)
    if normalized_source.count(normalized_excerpt) != 1:
        raise ValueError(f"expected one normalized source excerpt: {normalized_excerpt[:100]}")
    return normalized_excerpt


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _policy(profile_path: Path) -> tuple[Any, NodePolicy]:
    profile = load_model_node_profile(profile_path)
    return profile, NodePolicy(
        policy_id="mlrc-perception-outcome-grounded-taste-v1",
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


def _record_specs(
    *,
    problem: str,
    background: str,
    challenge_summary: str,
    task_root: Path,
    sources_root: Path,
) -> tuple[dict[str, Any], ...]:
    task = {
        "research_goal": {
            "semantic_role": "problem_context",
            "value": _exact_normalized(
                problem,
                "Build a **temporal action localization system** and evaluate it rigorously "
                "on the train/val/test splits.",
            ),
        },
        "resource_boundary": {
            "semantic_role": "limitation",
            "value": _exact_normalized(
                problem,
                "Use only the **provided pretrained video/audio features**.",
            ),
        },
    }
    aitc_outcome = _exact_normalized(
        challenge_summary,
        "Runner-up AITC (test_wbf_mamba) 0.518",
    )
    njust_outcome = _exact_normalized(
        challenge_summary,
        "Best NJUST–_KMG 0.550",  # noqa: RUF001 - exact official team name
    )
    source_metadata = {
        "semantic_role": "source_metadata",
        "value": {
            "mlrc_background": {
                "locator": (task_root / "scripts" / "background.txt").as_posix(),
                "sha256": _sha256(task_root / "scripts" / "background.txt"),
            },
            "official_challenge_summary": {
                "locator": (sources_root / "perception-test-2024-summary.pdf").as_posix(),
                "sha256": _sha256(sources_root / "perception-test-2024-summary.pdf"),
            },
        },
    }
    aitc = {
        **task,
        "error_evidence": {
            "semantic_role": "evidence",
            "value": _exact_normalized(
                background,
                "the primary error of the ActionFormer baseline model is wrong label.",
            ),
        },
        "mechanism_evidence": {
            "semantic_role": "justification",
            "value": _exact_normalized(
                background,
                "We argue that this is due to the decoupling of the classification and "
                "localization branches in ActionFormer, leading to an inconsistency between "
                "classification scores and temporal localization quality.",
            ),
        },
        "selected_action": {
            "semantic_role": "scientific_action",
            "value": _exact_normalized(
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
                _exact_normalized(
                    background,
                    "we transform the local self-attention in ActionFormer into global "
                    "self-attention to enhance the long-range modeling and improve overall "
                    "temporal action localization performance.",
                ),
                _exact_normalized(
                    background,
                    "we propose Action Copy Paste for data augmentation to enrich the temporal "
                    "relationships between action instances in video.",
                ),
            ],
        },
        "reported_outcome": {
            "semantic_role": "outcome",
            "value": aitc_outcome,
        },
        "outcome_scope": {
            "semantic_role": "limitation",
            "value": (
                "The 0.518 outcome is reported for the complete AITC submission, not an isolated "
                "causal estimate of the action-quality loss."
            ),
        },
        "source_metadata": source_metadata,
    }
    njust = {
        **task,
        "evidence_state": {
            "semantic_role": "evidence",
            "value": _exact_normalized(
                background,
                "We trained two versions of the model: Multimodal Model: This model utilizes "
                "both video and audio features to predict the start and end times of actions, "
                "as well as classify their types.",
            ),
        },
        "mechanism_evidence": {
            "semantic_role": "justification",
            "value": _exact_normalized(
                background,
                "WBF [12] is a method for merging predictions from multiple models by averaging "
                "the bounding box coordinates and confidence scores, weighted by their "
                "respective accuracies.",
            ),
        },
        "selected_action": {
            "semantic_role": "scientific_action",
            "value": _exact_normalized(
                background,
                "After training both multimodal and unimodal models, we combined their "
                "predictions using Weighted Box Fusion (WBF) [12].",
            ),
        },
        "available_alternatives": {
            "semantic_role": "alternative",
            "value": [
                _exact_normalized(
                    background,
                    "Unimodal Model: In this version, only video features are used for action "
                    "localisation.",
                ),
                _exact_normalized(
                    background,
                    "we utilize ActionMamba as a complementary action detection head to "
                    "ActionFormer, aiming for subsequent model ensemble to achieve more robust "
                    "results.",
                ),
            ],
        },
        "reported_outcome": {
            "semantic_role": "outcome",
            "value": njust_outcome,
        },
        "outcome_scope": {
            "semantic_role": "limitation",
            "value": (
                "The 0.550 outcome belongs to the complete NJUST submission. The selected action "
                "explicitly requires training both multimodal and unimodal model variants before "
                "fusion, so the record neither isolates WBF nor describes a single-model run."
            ),
        },
        "source_metadata": source_metadata,
    }
    return (
        {
            "source_id": "perception-aitc-runner-up-record",
            "candidate_id": "aitc-quality-aware-classification",
            "case_id": "perception-aitc-quality-aware-classification",
            "fields": aitc,
        },
        {
            "source_id": "perception-njust-winning-record",
            "candidate_id": "njust-multimodal-fusion",
            "case_id": "perception-njust-multimodal-fusion",
            "fields": njust,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", type=Path, default=_DEFAULT_TASK)
    parser.add_argument("--sources", type=Path, default=_DEFAULT_SOURCES)
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
        raise ValueError("outcome-grounded Taste abstraction requires --allow-api")
    repository = Path.cwd().resolve(strict=True)
    output = args.output if args.output.is_absolute() else repository / args.output
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    task_root = (args.task if args.task.is_absolute() else repository / args.task).resolve(
        strict=True
    )
    sources_root = (
        args.sources if args.sources.is_absolute() else repository / args.sources
    ).resolve(strict=True)
    problem = (task_root / "scripts" / "research_problem.txt").read_text(encoding="utf-8")
    background = (task_root / "scripts" / "background.txt").read_text(encoding="utf-8")
    challenge_summary = (sources_root / "perception-test-2024-summary.txt").read_text(
        encoding="utf-8"
    )
    records = _record_specs(
        problem=problem,
        background=background,
        challenge_summary=challenge_summary,
        task_root=task_root,
        sources_root=sources_root,
    )
    profile, policy = _policy(args.profile.resolve(strict=True))
    backend_config = load_structured_openai_compatible_config(args.backend.resolve(strict=True))
    if (backend_config.provider, backend_config.model) != (profile.provider, profile.model):
        raise ValueError("abstraction backend identity differs from the model profile")
    backend = StructuredOpenAICompatibleBackend(backend_config)
    node = GroundedTasteAbstractionNode()
    output.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "evidence_role": "consumed-development-only",
        "formal_evidence_eligible": False,
        "heldout_opened": False,
        "source_pdf_sha256": {
            "challenge_summary": _sha256(sources_root / "perception-test-2024-summary.pdf"),
            "njust_report": _sha256(sources_root / "njust-temporal-action-localisation.pdf"),
        },
        "cases": [],
    }
    for index, record in enumerate(records, 1):
        projection = json.dumps(
            {
                "schema_version": "1.0",
                "outcome_information_availability": "available",
                "fields": record["fields"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        projection_sha256 = hashlib.sha256(projection.encode()).hexdigest()
        input_data = TasteAbstractionInput(
            source_id=record["source_id"],
            candidate_id=record["candidate_id"],
            case_id=record["case_id"],
            stage="EXPERIMENTATION",
            decision_role="Select one feasible, falsifiable intervention for a bounded run.",
            source_projection=projection,
            source_projection_sha256=projection_sha256,
            domain_tags=("temporal-action-localization", "multimodal-perception"),
            outcome_information_availability="available",
            relation_label_hidden=True,
            held_out_task_content_excluded=True,
            source_projection_is_only_source_content=True,
        )
        result = node.run(
            input_data,
            context=NodeContext(
                project_id="scitaste-self-development",
                stage=input_data.stage,
                state_snapshot_id=projection_sha256,
                cumulative_api_cost_usd=0.0,
                evidence_ids=[input_data.source_id],
            ),
            backend=backend,
            policy=policy,
            profile=profile,
            request_id=f"mlrc-perception-outcome-taste-{index:02d}",
            seed=20270918 + index,
        )
        case_root = output / record["case_id"]
        _write_json(case_root / "SOURCE_PROJECTION.json", json.loads(projection))
        _write_json(case_root / "NODE_RESULT.json", result.model_dump(mode="json"))
        if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
            raise ValueError(
                f"Taste abstraction rejected for {record['case_id']}: "
                + "; ".join(result.rejection_reasons)
            )
        capsule = result.proposal.model_dump(mode="json")
        _write_json(case_root / "TASTE_CAPSULE.json", capsule)
        manifest["cases"].append(
            {
                "case_id": record["case_id"],
                "source_id": record["source_id"],
                "source_projection_sha256": projection_sha256,
                "taste_capsule_sha256": content_sha256(capsule),
                "usage": result.response.usage.model_dump(mode="json"),
            }
        )
    manifest["manifest_sha256"] = content_sha256(manifest)
    _write_json(output / "MANIFEST.json", manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

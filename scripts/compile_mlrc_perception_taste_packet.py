#!/usr/bin/env python3
"""Compile a live state-conditioned Taste packet for MLRC Perception."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResultStatus
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.project.models import content_sha256
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.taste.deliberation import (
    TasteDecisionFact,
    TasteDeliberationCandidate,
    TasteDeliberationInput,
    build_taste_control_packet,
    render_taste_control_packet,
)
from scitaste.taste.semantic import TasteDeliberationNode
from scitaste.taste.semantic_models import GroundedTasteCaseAbstraction, TasteGroundingTarget

_DEFAULT_PRECEDENTS = Path(
    "outputs/projects/scitaste-self-development/evaluations/"
    "mlrc-perception-outcome-precedents-development-v1"
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _policy(profile_path: Path) -> tuple[Any, NodePolicy]:
    profile = load_model_node_profile(profile_path)
    return profile, NodePolicy(
        policy_id="mlrc-perception-taste-deliberation-v1",
        enabled=True,
        allowed_node_names=["taste-deliberation"],
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


def _actions() -> tuple[ResearchAction, ...]:
    common = {
        "expected_cost": {"experiments": 1.0, "gpu_hours": 0.35},
        "expected_value": {"information_gain": 1.0},
        "tags": ["mlrc-perception", "one-run-feasible"],
    }
    return (
        ResearchAction(
            action_id="quality-aware-classification",
            type=MetaAction.EXPERIMENT,
            description=(
                "Implement a bounded classification-localization coupling loss using detached "
                "temporal IoU as the positive classification quality target; leave the official "
                "schedule, data, and scorer unchanged."
            ),
            **common,
        ),
        ResearchAction(
            action_id="global-attention",
            type=MetaAction.EXPERIMENT,
            description=(
                "Replace local temporal attention with a memory-feasible global-attention "
                "variant and test whether long-range modeling improves development mAP."
            ),
            **common,
        ),
        ResearchAction(
            action_id="action-copy-paste",
            type=MetaAction.EXPERIMENT,
            description=(
                "Implement within-batch action copy-paste using only provided training labels "
                "and test whether temporal-context augmentation improves development mAP."
            ),
            **common,
        ),
        ResearchAction(
            action_id="boundary-loss-refinement",
            type=MetaAction.EXPERIMENT,
            description=(
                "Refine the temporal boundary objective without changing the classification "
                "branch, to test whether localization error is the dominant bottleneck."
            ),
            **common,
        ),
    )


def _candidate(
    capsule_path: Path,
    *,
    source_id: str,
    retrieval_score: float,
) -> TasteDeliberationCandidate:
    capsule = GroundedTasteCaseAbstraction.model_validate_json(capsule_path.read_bytes())
    capsule_payload = capsule.model_dump(mode="json")
    selector_rationale = " ".join(
        item.rationale
        for item in capsule.grounding
        if item.target
        in {
            TasteGroundingTarget.CHOICE,
            TasteGroundingTarget.DECISION_PRINCIPLE,
        }
    )
    candidate = TasteDeliberationCandidate(
        case_id=capsule.case_id,
        case_sha256=content_sha256(
            {
                "source_id": source_id,
                "capsule_sha256": content_sha256(capsule_payload),
            }
        ),
        taste_grounding_sha256=content_sha256(
            [item.model_dump(mode="json") for item in capsule.grounding]
        ),
        source_identities=(f"source-group-{content_sha256(source_id)[:16]}",),
        stage="EXPERIMENTATION",
        context_summary=capsule.context_summary,
        problem_pattern=capsule.problem_pattern,
        evidence_state=capsule.evidence_state,
        candidate_actions=capsule.candidate_actions,
        preferred_action=capsule.preferred_action,
        rejected_actions=capsule.rejected_actions,
        decision_principle=capsule.decision_principle,
        why_preferred=selector_rationale,
        applies_when=capsule.transfer_boundary.applies_when,
        fails_when=capsule.transfer_boundary.fails_when,
        counterfactual_probe=capsule.transfer_boundary.counterfactual_probe,
        confidence=capsule.confidence,
        broad_retrieval_score=retrieval_score,
        broad_matched_fields=("task-family", "objective-record", "method-feasibility"),
    )
    visible = json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False)
    forbidden_outcome_cues = ("0.518", "0.550", "first place", "runner-up", "winning-record")
    if any(item.casefold() in visible.casefold() for item in forbidden_outcome_cues):
        raise ValueError("raw source outcome leaked into the Taste selector projection")
    return candidate


def _input(precedents: Path) -> TasteDeliberationInput:
    actions = _actions()
    facts = (
        TasteDecisionFact(
            fact_id="task-objective",
            kind="direction",
            text=(
                "Improve mean average precision for temporal action localization on the supplied "
                "development split with one coherent, falsifiable method change."
            ),
        ),
        TasteDecisionFact(
            fact_id="dominant-error",
            kind="observation",
            text=(
                "The supplied diagnostic record identifies wrong-label error as the primary "
                "ActionFormer baseline error."
            ),
            boundary_candidate=True,
        ),
        TasteDecisionFact(
            fact_id="branch-decoupling",
            kind="observation",
            text=(
                "The classification and localization branches are separate, while temporal "
                "ground-truth boundaries permit IoU-derived supervision during training."
            ),
            boundary_candidate=True,
        ),
        TasteDecisionFact(
            fact_id="resource-envelope",
            kind="obligation",
            text=("Only one development experiment on one 24 GiB GPU is available for this turn."),
            boundary_candidate=True,
        ),
        TasteDecisionFact(
            fact_id="data-boundary",
            kind="obligation",
            text=(
                "Only the provided training data and pretrained video/audio features may be used; "
                "additional datasets, annotations, and feature extractors are prohibited."
            ),
            boundary_candidate=True,
        ),
        TasteDecisionFact(
            fact_id="modalities-available",
            kind="observation",
            text=(
                "Both provided video and audio feature streams are available; the constraint is "
                "the single development run, not absence of a modality."
            ),
            boundary_candidate=True,
        ),
    )
    candidates = (
        _candidate(
            precedents / "perception-aitc-quality-aware-classification" / "TASTE_CAPSULE.json",
            source_id="perception-aitc-runner-up-record",
            retrieval_score=1.0,
        ),
        _candidate(
            precedents / "perception-njust-multimodal-fusion" / "TASTE_CAPSULE.json",
            source_id="perception-njust-winning-record",
            retrieval_score=0.95,
        ),
    )
    identity = {
        "task": "perception-temporal-action-loc",
        "actions": [item.model_dump(mode="json") for item in actions],
        "facts": [item.model_dump(mode="json") for item in facts],
        "candidates": [item.case_sha256 for item in candidates],
    }
    return TasteDeliberationInput(
        decision_id="mlrc-perception-method-intervention",
        state_snapshot_id=content_sha256(identity),
        stage="EXPERIMENTATION",
        current_actions=actions,
        decision_facts=facts,
        candidates=candidates,
        maximum_selected_cases=2,
    )


def _semantic_development_audit(proposal: Any) -> None:
    """Reject a known modality-vs-resource category error before packet admission."""

    for assessment in proposal.assessments:
        for support in assessment.triggered_failure_supports:
            if (
                "only one modality" in support.boundary_condition.casefold()
                and "data-boundary" in support.decision_fact_ids
            ):
                raise ValueError(
                    "Taste deliberation confused provided feature modalities with the number "
                    "of separately trainable model variants"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--precedents", type=Path, default=_DEFAULT_PRECEDENTS)
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/deepseek_v41flash.scitastebench_live_20260917.yaml"),
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("configs/model_nodes/profile_deepseek_v41flash_taste_deliberation_v1.yaml"),
    )
    parser.add_argument("--allow-api", action="store_true")
    args = parser.parse_args()
    if not args.allow_api:
        raise ValueError("live Taste packet compilation requires --allow-api")
    repository = Path.cwd().resolve(strict=True)
    output = args.output if args.output.is_absolute() else repository / args.output
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    precedents = (
        args.precedents if args.precedents.is_absolute() else repository / args.precedents
    ).resolve(strict=True)
    input_data = _input(precedents)
    profile, policy = _policy(args.profile.resolve(strict=True))
    backend_config = load_structured_openai_compatible_config(args.backend.resolve(strict=True))
    if (backend_config.provider, backend_config.model) != (profile.provider, profile.model):
        raise ValueError("deliberation backend identity differs from the model profile")
    result = TasteDeliberationNode().run(
        input_data,
        context=NodeContext(
            project_id="scitaste-self-development",
            stage=input_data.stage,
            state_snapshot_id=input_data.state_snapshot_id,
            cumulative_api_cost_usd=0.0,
            candidate_actions=list(input_data.current_actions),
        ),
        backend=StructuredOpenAICompatibleBackend(backend_config),
        policy=policy,
        profile=profile,
        request_id="mlrc-perception-taste-packet-v1",
        seed=20270921,
    )
    output.mkdir(parents=True)
    _write_json(output / "DELIBERATION_INPUT.json", input_data.model_dump(mode="json"))
    _write_json(output / "NODE_RESULT.json", result.model_dump(mode="json"))
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("Taste deliberation rejected: " + "; ".join(result.rejection_reasons))
    _semantic_development_audit(result.proposal)
    packet = build_taste_control_packet(input_data, result.proposal)
    _write_json(output / "DELIBERATION_PROPOSAL.json", result.proposal.model_dump(mode="json"))
    _write_json(output / "TASTE_CONTROL_PACKET.json", packet.model_dump(mode="json"))
    (output / "TASTE_CONTROL_PACKET.txt").write_text(
        render_taste_control_packet(packet) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "schema_version": "1.0",
        "evidence_role": "consumed-development-only",
        "formal_evidence_eligible": False,
        "heldout_opened": False,
        "input_sha256": input_data.fingerprint,
        "proposal_sha256": result.proposal.fingerprint,
        "taste_control_packet_sha256": packet.fingerprint,
        "recommended_action_id": packet.recommended_action_id,
        "abstained": packet.abstained,
        "selected_case_ids": list(result.proposal.selected_case_ids),
        "usage": result.response.usage.model_dump(mode="json"),
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    _write_json(output / "RECEIPT.json", receipt)
    print(json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

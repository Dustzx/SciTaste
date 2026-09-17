from __future__ import annotations

import pytest
from pydantic import ValidationError

from scitaste.benchmark import (
    BenchmarkDecisionContextFamily,
    BenchmarkLabelAuthority,
    BoundaryCounterfactualPair,
    BoundaryFactChange,
    BoundaryFlipKind,
    BoundaryPairJudgment,
    BoundaryPairPackage,
    BoundaryPairSplit,
    BoundaryPairState,
    BoundaryStateRole,
    inspect_boundary_pair_package,
)
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.taste.decision_families import ScientificTasteDecisionFamily


def _judgment(reviewer_id: str) -> BoundaryPairJudgment:
    return BoundaryPairJudgment(
        judgment_id=f"judgment-{reviewer_id}",
        reviewer_id=reviewer_id,
        authority=BenchmarkLabelAuthority.AI_PANEL_PROXY,
        expertise_scope="claim calibration",
        base_selection_id="narrow",
        twin_selection_id="retain",
        confidence=0.9,
        pair_order_blinded=True,
        expected_pair_labels_hidden=True,
        conflict_cleared=True,
        evidence_refs=(f"reviews/{reviewer_id}.json",),
    )


def _pair() -> BoundaryCounterfactualPair:
    actions = (
        ResearchAction(
            action_id="narrow",
            type=MetaAction.NARROW_CLAIM,
            description="State that settlement remains unobserved.",
        ),
        ResearchAction(
            action_id="retain",
            type=MetaAction.REJECT_CONCERN_WITH_EVIDENCE,
            description="Retain the settlement claim and cite direct observations.",
        ),
    )
    return BoundaryCounterfactualPair(
        pair_id="settlement-observation-boundary",
        split=BoundaryPairSplit.DEVELOPMENT,
        source_group_id="source-coral-001",
        domain="ecology",
        decision_context_family=BenchmarkDecisionContextFamily.CLAIM_CALIBRATION_AND_REVIEW_CLOSURE,
        taste_judgment_family=ScientificTasteDecisionFamily.INFERENTIAL_DISCIPLINE,
        source_locator="sources/coral-001.json",
        source_content_sha256="1" * 64,
        license_identifier="CC-BY-4.0",
        public_reconstruction_allowed=True,
        outcome_hidden_during_construction=True,
        candidate_actions=actions,
        invariant_facts=(
            "The species and heat-stress mesocosm are unchanged.",
            "Detached polyps remain viable in both states.",
        ),
        changed_fact=BoundaryFactChange(
            fact_id="direct-settlement-observation",
            question="Was resettlement directly observed?",
            base_value="No direct resettlement event was observed.",
            twin_value="Time-lapse images document three resettlement events.",
            why_decisive="The claim changes from extrapolation to an observed result.",
            base_evidence_refs=("source:review:lines-12-18",),
            twin_construction_refs=("counterfactual:protocol:direct-observation-v1",),
        ),
        flip_kind=BoundaryFlipKind.ACTION_TO_ACTION,
        base=BoundaryPairState(
            role=BoundaryStateRole.BASE,
            decision_context="Resettlement is claimed, but no event was directly observed.",
            visible_budget="No new experiment can be completed before submission.",
            preferred_action_id="narrow",
            action_utilities={"narrow": 1.0, "retain": -1.0},
            utility_rationale={
                "narrow": "Calibrates the claim to the observed evidence.",
                "retain": "Treats an inference as an observation.",
            },
        ),
        twin=BoundaryPairState(
            role=BoundaryStateRole.TWIN,
            decision_context="Resettlement is claimed and three events were directly observed.",
            visible_budget="No new experiment can be completed before submission.",
            preferred_action_id="retain",
            action_utilities={"narrow": 0.0, "retain": 1.0},
            utility_rationale={
                "narrow": "Would hide directly observed evidence.",
                "retain": "The claim is supported by the registered observation.",
            },
        ),
        judgments=(_judgment("reviewer-a"), _judgment("reviewer-b")),
        contamination_probe_refs=("probes/coral-001.json",),
        construction_manifest_sha256="2" * 64,
    )


def test_boundary_pair_package_is_ready_for_development_but_not_formal() -> None:
    package = BoundaryPairPackage(
        package_id="boundary-development-v1",
        release_tier="development",
        pairs=(_pair(),),
    )

    report = inspect_boundary_pair_package(package)

    assert report.ready_for_development
    assert not report.ready_for_formal_release
    assert report.pair_count == 1
    assert report.item_count == 2
    assert report.action_flip_count == 1
    assert report.blocker_codes == ()


def test_boundary_pair_rejects_non_flipping_action_labels() -> None:
    pair = _pair()
    twin = pair.twin.model_copy(
        update={
            "preferred_action_id": "narrow",
            "action_utilities": {"narrow": 1.0, "retain": 0.0},
        }
    )

    with pytest.raises(ValidationError, match="preferred-action flip"):
        BoundaryCounterfactualPair.model_validate({**pair.model_dump(mode="python"), "twin": twin})


def test_boundary_pair_package_rejects_source_group_reuse() -> None:
    pair = _pair()
    duplicate = pair.model_copy(
        update={
            "pair_id": "settlement-observation-boundary-copy",
            "source_content_sha256": "3" * 64,
        }
    )

    with pytest.raises(ValidationError, match="one source group"):
        BoundaryPairPackage(
            package_id="invalid-source-reuse",
            release_tier="development",
            pairs=(pair, duplicate),
        )

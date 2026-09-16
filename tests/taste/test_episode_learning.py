from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import fastjsonschema
import pytest

from scitaste.backends.base import Usage
from scitaste.evaluation.h4_policy_reproduction import (
    H4PolicyReproductionSpec,
    reproduce_h4_lifecycle_policy,
)
from scitaste.model_nodes.backends import ScriptedStructuredBackend, ScriptedStructuredReply
from scitaste.model_nodes.openai_compatible import StructuredOpenAICompatibleConfig
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.model_nodes.runtime import ModelNodeRuntime, RuntimeBackendMode, RuntimeOutcome
from scitaste.project import (
    ProjectIdeaRevisionBinding,
    ProjectManifest,
    ProjectRun,
    ProjectRuntime,
)
from scitaste.project.models import content_sha256
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.taste import (
    AITasteEpisodeAttributionReview,
    AITasteReviewArtifactBinding,
    AITasteReviewArtifactRole,
    AITasteReviewExecutionReceipt,
    AITasteReviewFirewallReport,
    AITasteReviewNormalizationReport,
    LifecycleTastePolicyConfig,
    LifecycleTastePolicyUpdateMode,
    ScientificDecisionFamilyAssignment,
    ScientificDecisionFamilyReview,
    ScientificTasteDecisionFamily,
    TasteAttributionReviewRole,
    TasteAttributionReviewVerdict,
    TasteController,
    TasteCreditAssignment,
    TasteCreditDirection,
    TasteEpisodeAttributionReview,
    TasteEpisodeDecisionContext,
    TasteEpisodeEvidence,
    TasteEpisodeEvidenceRole,
    TasteEpisodeOutcome,
    TasteEpisodePartition,
    TasteOutcomeFamily,
    TasteOutcomePolarity,
    admit_taste_episode,
    assess_lifecycle_taste_policy,
    compile_process_taste_episode_candidate,
    fit_family_conditioned_lifecycle_taste_policy,
    fit_lifecycle_taste_policy,
    inspect_taste_episode_admission,
    load_ai_taste_review_panel_contract,
)
from scitaste.taste.ai_attribution import (
    AITasteAttributionReviewProposal,
    build_ai_taste_attribution_review_material,
    build_ai_taste_attribution_runtime_config,
    materialize_ai_taste_attribution_review,
)
from scitaste.taste.family_review import (
    build_scientific_decision_family_review_material,
    build_scientific_decision_family_runtime_config,
    compile_scientific_decision_family_assignment,
    scientific_decision_family_review_from_runtime,
)
from scitaste.taste.semantic import taste_node_types


def _family_assignment(episode, ordinal: int) -> ScientificDecisionFamilyAssignment:
    family = ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION
    reviews = tuple(
        ScientificDecisionFamilyReview(
            reviewer_id=f"family-reviewer-{reviewer}-{ordinal}",
            invocation_id=f"family-invocation-{reviewer}-{ordinal}",
            model_identifier=f"isolated-family-model-{reviewer}",
            role="primary",
            decision_family=family,
            rationale="The choice allocates the next experiment from trajectory state.",
            raw_response_sha256=str(reviewer) * 64,
        )
        for reviewer in ("a", "b")
    )
    return ScientificDecisionFamilyAssignment.create(
        assignment_id=f"family-assignment-{ordinal}",
        admission_id=episode.admission_id,
        admission_sha256=episode.admission_sha256,
        decision_family=family,
        observed_outcome_families=tuple(
            item.family for item in episode.candidate.credit_assignments
        ),
        rationale="The action spends a bounded research opportunity after feedback.",
        reviews=reviews,
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _idea_binding(*, revision_id: str = "lifecycle-taste-candidate-01"):
    return ProjectIdeaRevisionBinding.create(
        project_id="episode-project",
        observed_project_revision=3,
        observed_project_snapshot_sha256="1" * 64,
        revision_id=revision_id,
        status="candidate",
        record_locator="runs/idea-run/idea_refinement/REVISION.json",
        record_sha256="2" * 64,
        artifact_sha256="3" * 64,
        selected_for_paper=False,
        paper_claim_authority=False,
    )


def _actions() -> tuple[ResearchAction, ResearchAction]:
    return (
        ResearchAction(
            action_id="probe-boundary",
            type=MetaAction.PROBE,
            description="Probe the decision-reversing uncertainty.",
            expected_value={"information_gain": 0.2},
            tags=["diagnostic"],
        ),
        ResearchAction(
            action_id="scale-now",
            type=MetaAction.ADVANCE,
            description="Scale the current method immediately.",
            expected_value={"scientific_importance": 0.5},
            tags=["scale"],
        ),
    )


def _candidate(
    tmp_path: Path,
    ordinal: int,
    *,
    polarity: TasteOutcomePolarity = TasteOutcomePolarity.SUPPORTS,
    family: TasteOutcomeFamily = TasteOutcomeFamily.DESIGN,
    source_group_id: str | None = None,
    with_decision_context: bool = False,
    decision_context: TasteEpisodeDecisionContext | None = None,
):
    actions = _actions()
    decision = ResearchDecision(
        decision_id=f"decision-{ordinal:02d}",
        stage="DISCOVERY",
        state_snapshot_id=f"state-{ordinal:02d}",
        candidate_actions=list(actions),
        selected_action=actions[0],
        rationale="The probe has higher information gain.",
        confidence=0.8,
        executor_result_id=f"result-{ordinal:02d}",
        actual_outcome={"boundary_resolved": polarity is TasteOutcomePolarity.SUPPORTS},
    )
    decision_path = tmp_path / f"decision-{ordinal:02d}.json"
    outcome_path = tmp_path / f"outcome-{ordinal:02d}.json"
    decision_path.write_text(decision.model_dump_json(indent=2) + "\n", encoding="utf-8")
    outcome_path.write_text(
        '{"boundary_resolved":true}\n'
        if polarity is TasteOutcomePolarity.SUPPORTS
        else '{"boundary_resolved":false}\n',
        encoding="utf-8",
    )
    outcome = TasteEpisodeOutcome(
        outcome_id=f"outcome-{ordinal:02d}",
        family=family,
        summary="The decision boundary was resolved.",
        horizon="next research decision",
        polarity=polarity,
        evidence_ids=(f"outcome-evidence-{ordinal:02d}",),
    )
    credit = TasteCreditAssignment(
        credit_id=f"credit-{ordinal:02d}",
        family=family,
        direction=(
            TasteCreditDirection.BENEFICIAL
            if polarity is TasteOutcomePolarity.SUPPORTS
            else TasteCreditDirection.HARMFUL
        ),
        outcome_ids=(outcome.outcome_id,),
        rationale="The selected action produced the decision-relevant observation.",
        confidence=0.9,
    )
    return compile_process_taste_episode_candidate(
        decision,
        candidate_id=f"process-episode-{ordinal:02d}",
        project_id="episode-project",
        source_project_id="episode-project",
        source_group_id=source_group_id or f"source-group-{ordinal:02d}",
        dataset_partition=TasteEpisodePartition.DEVELOPMENT,
        source_project_revision=4 + ordinal,
        source_project_snapshot_sha256=f"{ordinal % 10}" * 64,
        idea_revision=_idea_binding(),
        producer_id=f"process-taste-miner-{ordinal:02d}",
        state_summary="A decision-reversing boundary is unresolved before scaling.",
        decision_context=(
            decision_context
            or (
                TasteEpisodeDecisionContext(
                    remaining_experiments="two-to-three",
                    failure_count="zero",
                    no_improvement_streak="one",
                    score_trend="flat",
                    best_vs_baseline="equal",
                )
                if with_decision_context
                else None
            )
        ),
        decision_principle="Probe a cheap decisive uncertainty before scale-up.",
        why_preferred="The probe can change whether scale-up is justified.",
        outcomes=(outcome,),
        credit_assignments=(credit,),
        applicability_conditions=("a cheap probe can reverse the scale decision",),
        failure_conditions=("the probe cannot distinguish the explanations",),
        counterfactual_probe="Advance directly if the boundary is independently established.",
        evidence=(
            TasteEpisodeEvidence(
                evidence_id=f"decision-evidence-{ordinal:02d}",
                role=TasteEpisodeEvidenceRole.DECISION,
                locator=decision_path.name,
                sha256=_sha(decision_path),
            ),
            TasteEpisodeEvidence(
                evidence_id=f"outcome-evidence-{ordinal:02d}",
                role=TasteEpisodeEvidenceRole.OUTCOME,
                locator=outcome_path.name,
                sha256=_sha(outcome_path),
            ),
        ),
        domain_tags=("testing",),
        venue_tags=("ICLR",),
    )


def _review(
    candidate,
    *,
    reviewer_id: str,
    preferred_action_id: str = "probe-boundary",
    role: TasteAttributionReviewRole = TasteAttributionReviewRole.PRIMARY,
    verdict: TasteAttributionReviewVerdict = TasteAttributionReviewVerdict.ACCEPT,
    confidence: float = 0.9,
):
    accepted = verdict is TasteAttributionReviewVerdict.ACCEPT
    return TasteEpisodeAttributionReview(
        review_id=f"review-{candidate.candidate_id}-{reviewer_id}",
        candidate_id=candidate.candidate_id,
        candidate_sha256=candidate.candidate_sha256,
        idea_revision_binding_sha256=candidate.idea_revision.binding_sha256,
        reviewer_id=reviewer_id,
        role=role,
        verdict=verdict,
        preferred_action_id=preferred_action_id if accepted else None,
        supported_credit_ids=(candidate.credit_assignments[0].credit_id,) if accepted else (),
        decision_trace_supported=True,
        outcome_trace_supported=True,
        alternatives_supported=True,
        credit_assignment_supported=accepted,
        transfer_scope_supported=True,
        reversal_probe_supported=True,
        attribution_confidence=confidence if accepted else 0.2,
        rationale=(
            "The decision, delayed outcome, and counterfactual support this preference."
            if accepted
            else "The causal credit is not supported."
        ),
        reviewed_at=datetime(2026, 9, 14, tzinfo=UTC),
    )


def _ai_review(
    candidate,
    tmp_path: Path,
    *,
    reviewer_id: str,
    run_id: str,
    model_id: str,
    preferred_action_id: str = "probe-boundary",
):
    human_template = _review(
        candidate,
        reviewer_id=reviewer_id,
        preferred_action_id=preferred_action_id,
    )
    payload = human_template.model_dump(mode="python", exclude={"human_performed"})
    shared_content = {
        AITasteReviewArtifactRole.REVIEW_PACKET: "frozen review packet\n",
        AITasteReviewArtifactRole.INPUT_PROJECTION: "candidate-only input\n",
        AITasteReviewArtifactRole.RUBRIC: "frozen attribution rubric\n",
        AITasteReviewArtifactRole.SYSTEM_PROMPT: "review without condition identity\n",
        AITasteReviewArtifactRole.USER_PROMPT: "assess the bound candidate\n",
        AITasteReviewArtifactRole.SAMPLING_CONFIG: "temperature: 0\n",
    }
    paths: dict[AITasteReviewArtifactRole, Path] = {}
    for role, content in shared_content.items():
        path = tmp_path / f"ai-shared-{role.value}.txt"
        path.write_text(content, encoding="utf-8")
        paths[role] = path
    raw_path = tmp_path / f"{run_id}-raw-response.txt"
    raw_path.write_text(f"raw response {run_id}\n", encoding="utf-8")
    paths[AITasteReviewArtifactRole.RAW_RESPONSE] = raw_path
    prompt_sha256 = content_sha256(
        {
            role.value: _sha(paths[role])
            for role in (
                AITasteReviewArtifactRole.SYSTEM_PROMPT,
                AITasteReviewArtifactRole.USER_PROMPT,
            )
        }
    )
    normalized_response_sha256 = content_sha256(
        human_template.model_dump(mode="json", exclude={"human_performed"})
    )
    receipt = AITasteReviewExecutionReceipt.create(
        provider_id=f"{model_id}-provider",
        model_id=model_id,
        model_revision=f"{model_id}-revision",
        run_id=run_id,
        prompt_sha256=prompt_sha256,
        input_projection_sha256=_sha(paths[AITasteReviewArtifactRole.INPUT_PROJECTION]),
        raw_response_sha256=_sha(raw_path),
        input_tokens=100,
        output_tokens=20,
        cost_usd=0.001,
    )
    receipt_path = tmp_path / f"{run_id}-execution-receipt.yaml"
    receipt_path.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    paths[AITasteReviewArtifactRole.EXECUTION_RECEIPT] = receipt_path
    normalization = AITasteReviewNormalizationReport.create(
        run_id=run_id,
        candidate_sha256=candidate.candidate_sha256,
        raw_response_sha256=_sha(raw_path),
        normalized_response_sha256=normalized_response_sha256,
        schema_valid=True,
        fuzzy_repair_applied=False,
    )
    normalization_path = tmp_path / f"{run_id}-normalization-report.yaml"
    normalization_path.write_text(
        normalization.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    paths[AITasteReviewArtifactRole.NORMALIZATION_REPORT] = normalization_path
    firewall = AITasteReviewFirewallReport.create(
        review_packet_sha256=_sha(paths[AITasteReviewArtifactRole.REVIEW_PACKET]),
        input_projection_sha256=_sha(paths[AITasteReviewArtifactRole.INPUT_PROJECTION]),
        condition_identity_exposed=False,
        paper_claims_exposed=False,
        out_of_window_outcomes_exposed=False,
        other_review_exposed=False,
        producer_response_exposed=False,
    )
    firewall_path = tmp_path / f"{run_id}-firewall-report.yaml"
    firewall_path.write_text(firewall.model_dump_json(indent=2) + "\n", encoding="utf-8")
    paths[AITasteReviewArtifactRole.FIREWALL_REPORT] = firewall_path
    artifacts = tuple(
        AITasteReviewArtifactBinding(
            role=role,
            locator=paths[role].name,
            sha256=_sha(paths[role]),
        )
        for role in AITasteReviewArtifactRole
    )
    contract = load_ai_taste_review_panel_contract(
        "configs/evaluation/programs/iclr2027_scitaste_ai_review_amendment_v1.yaml"
    )
    return AITasteEpisodeAttributionReview(
        **payload,
        model_id=model_id,
        model_revision=f"{model_id}-revision",
        provider_id=f"{model_id}-provider",
        prompt_sha256=prompt_sha256,
        normalized_response_sha256=normalized_response_sha256,
        run_id=run_id,
        producer_model_id="episode-producer-model",
        producer_run_id="episode-producer-run",
        panel_contract_sha256=contract.contract_sha256,
        artifacts=artifacts,
    )


def _admitted(
    tmp_path: Path,
    ordinal: int,
    *,
    preferred: str = "probe-boundary",
    polarity: TasteOutcomePolarity = TasteOutcomePolarity.SUPPORTS,
    family: TasteOutcomeFamily = TasteOutcomeFamily.DESIGN,
    source_group_id: str | None = None,
    confidence: float = 0.9,
    with_decision_context: bool = False,
):
    candidate = _candidate(
        tmp_path,
        ordinal,
        polarity=polarity,
        family=family,
        source_group_id=source_group_id,
        with_decision_context=with_decision_context,
    )
    reviews = (
        _review(
            candidate,
            reviewer_id=f"reviewer-a-{ordinal:02d}",
            preferred_action_id=preferred,
            confidence=confidence,
        ),
        _review(
            candidate,
            reviewer_id=f"reviewer-b-{ordinal:02d}",
            preferred_action_id=preferred,
            confidence=confidence,
        ),
    )
    return admit_taste_episode(
        candidate,
        reviews,
        admission_id=f"admitted-episode-{ordinal:02d}",
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )


def _policy(tmp_path: Path, *, mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED):
    episodes = tuple(
        _admitted(
            tmp_path,
            ordinal,
            preferred=(
                "probe-boundary"
                if mode is not LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT or ordinal <= 4
                else "scale-now"
            ),
        )
        for ordinal in range(1, 9)
    )
    config = LifecycleTastePolicyConfig(
        policy_id=f"policy-{mode.value}",
        update_mode=mode,
        idea_revision=_idea_binding(),
        minimum_feature_support=3.0,
        require_stage_support=True,
        allow_cross_domain=False,
        shuffle_seed=17 if mode is LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT else 0,
    )
    return fit_lifecycle_taste_policy(episodes, config)


def test_two_independent_reviews_admit_one_training_episode(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, 1)
    reviews = (
        _review(candidate, reviewer_id="reviewer-a"),
        _review(candidate, reviewer_id="reviewer-b"),
    )

    report = inspect_taste_episode_admission(
        candidate,
        reviews,
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )
    admitted = admit_taste_episode(
        candidate,
        reviews,
        admission_id="admitted-episode-01",
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )

    assert report.ready_for_policy_training is True
    assert report.preferred_action_id == "probe-boundary"
    assert admitted.policy_training_eligible is True
    assert admitted.policy_update_authorized is False
    assert admitted.training_weight == 0.9


def test_two_ai_reviews_admit_training_but_forbid_human_validity_claim(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path, 1)
    contract = load_ai_taste_review_panel_contract(
        "configs/evaluation/programs/iclr2027_scitaste_ai_review_amendment_v1.yaml"
    )
    reviews = (
        _ai_review(
            candidate,
            tmp_path,
            reviewer_id="ai-reviewer-a",
            run_id="ai-run-a",
            model_id="review-model-a",
        ),
        _ai_review(
            candidate,
            tmp_path,
            reviewer_id="ai-reviewer-b",
            run_id="ai-run-b",
            model_id="review-model-b",
        ),
    )

    report = inspect_taste_episode_admission(
        candidate,
        reviews,
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
        ai_review_contract=contract,
        expected_ai_review_contract_sha256=contract.contract_sha256,
    )
    admitted = admit_taste_episode(
        candidate,
        reviews,
        admission_id="ai-admitted-episode-01",
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
        ai_review_contract=contract,
        expected_ai_review_contract_sha256=contract.contract_sha256,
    )

    assert report.ready_for_policy_training is True
    assert report.review_evidence_kind == "ai"
    assert report.ai_review_count == 2
    assert report.human_review_count == 0
    assert report.legacy_unverified_review_count == 0
    assert report.human_validity_claim_allowed is False
    assert report.cross_model_ai_panel is True
    assert report.ai_review_contract_sha256 == contract.contract_sha256
    assert admitted.human_validity_claim_allowed is False
    assert admitted.ai_review_contract_sha256 == contract.contract_sha256
    policy = fit_lifecycle_taste_policy(
        (admitted,),
        LifecycleTastePolicyConfig(
            policy_id="ai-reviewed-policy",
            update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
            idea_revision=_idea_binding(),
        ),
    )
    assert policy.source_review_evidence_kinds == ("ai",)
    assert policy.ai_review_contract_sha256s == (contract.contract_sha256,)
    assert policy.human_validity_claim_allowed is False
    assert policy.schema_version == "1.4"
    assert policy.source_group_keys == ("self-project:episode-project:source-group-01",)
    assert policy.source_group_count == 1
    assert policy.source_group_ids == ("source-group-01",)
    assert policy.intervention_policy_artifact_eligible is True
    assert policy.h3_policy_artifact_eligible is True
    diagnostic = fit_lifecycle_taste_policy(
        (admitted,),
        LifecycleTastePolicyConfig(
            policy_id="ai-reviewed-success-only-policy",
            update_mode=LifecycleTastePolicyUpdateMode.SUCCESS_ONLY,
            idea_revision=_idea_binding(),
        ),
    )
    assert diagnostic.intervention_policy_artifact_eligible is True
    assert diagnostic.h3_policy_artifact_eligible is False


def test_ai_attribution_schema_requires_acceptance_credit_fields() -> None:
    schema = AITasteAttributionReviewProposal.model_json_schema()

    assert "preferred_action_id" in schema["required"]
    assert "supported_credit_ids" in schema["required"]


def test_ai_attribution_schema_exposes_cross_field_verdict_contract() -> None:
    validate = fastjsonschema.compile(AITasteAttributionReviewProposal.model_json_schema())
    payload = {
        "review_packet_sha256": "a" * 64,
        "verdict": "accept",
        "preferred_action_id": "action-one",
        "supported_credit_ids": ["credit-one"],
        "decision_trace_supported": True,
        "outcome_trace_supported": True,
        "alternatives_supported": True,
        "credit_assignment_supported": True,
        "transfer_scope_supported": True,
        "reversal_probe_supported": True,
        "attribution_confidence": 0.5,
        "rationale": "Every review dimension is supported.",
    }

    validate(payload)
    with pytest.raises(fastjsonschema.JsonSchemaException):
        validate({**payload, "transfer_scope_supported": False})
    with pytest.raises(fastjsonschema.JsonSchemaException):
        validate({**payload, "verdict": "reject"})
    validate({**payload, "verdict": "reject", "transfer_scope_supported": False})


def test_runtime_bridge_materializes_cross_model_ai_review_panel(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, 1)
    outputs = tmp_path / "outputs"
    project = ProjectRuntime(outputs)
    project.create(
        ProjectManifest(
            project_id="episode-project",
            title="Episode project",
            research_direction="Exercise real model-node attribution import.",
            status="active",
        )
    )
    snapshot = project.begin_run(
        "episode-project",
        ProjectRun(
            run_id="attribution-panel-run",
            provider="scitaste-native",
            model="cross-model-panel",
            condition="ai-attribution-review",
            seed=0,
            status="running",
            evidence_scope="taste-attribution",
        ),
        expected_revision=0,
    )
    material = build_ai_taste_attribution_review_material(
        project,
        candidate,
        evidence_root=tmp_path,
        current_idea_revision=_idea_binding(),
        seed=7,
    )
    profiles = load_model_node_profile_set(
        "configs/model_nodes/runtime_profiles.taste_attribution_review_v1.yaml"
    ).profiles
    contract = load_ai_taste_review_panel_contract(
        "configs/evaluation/programs/iclr2027_scitaste_ai_review_amendment_v1.yaml"
    )
    reviews = []
    for label, profile_id in (
        ("a", "zhipu-glm53-taste-attribution-review"),
        ("b", "deepseek-v4flash-taste-attribution-review"),
    ):
        profile = profiles[profile_id]
        config = build_ai_taste_attribution_runtime_config(
            material,
            profile=profile,
            backend_config=StructuredOpenAICompatibleConfig(
                provider=profile.provider,
                base_url="https://example.test",
                model=profile.model,
                api_key_env="TEST_API_KEY",
                max_output_tokens=8192,
            ),
        )
        invocation_id = f"attribution-review-{label}"
        payload = {
            "review_packet_sha256": material.node_input.review_packet_sha256,
            "verdict": "accept",
            "preferred_action_id": candidate.selected_action_id,
            "supported_credit_ids": [candidate.credit_assignments[0].credit_id],
            "decision_trace_supported": True,
            "outcome_trace_supported": True,
            "alternatives_supported": True,
            "credit_assignment_supported": True,
            "transfer_scope_supported": True,
            "reversal_probe_supported": True,
            "attribution_confidence": 0.9,
            "rationale": f"Independent model {label} supports the bounded attribution.",
        }
        scripted = ScriptedStructuredBackend(
            name=profile.provider,
            model=profile.model,
            replies={
                invocation_id: ScriptedStructuredReply(
                    output_payload=payload,
                    usage=Usage(input_tokens=100, output_tokens=40, cost_usd=0.001),
                )
            },
        )

        class LiveFixtureBackend:
            config = SimpleNamespace(live_enabled=True, max_output_tokens=8192)

            def __init__(self, delegate):
                self.delegate = delegate
                self.name = delegate.name
                self.model = delegate.model

            def complete(self, request):
                return self.delegate.complete(request)

        receipt = ModelNodeRuntime(project, node_types=taste_node_types()).execute(
            project_id="episode-project",
            run_id="attribution-panel-run",
            invocation_id=invocation_id,
            request_id=invocation_id,
            expected_project_revision=snapshot.revision,
            state_revision=snapshot.revision,
            node_name=config.node_name,
            node_input=config.node_input,
            context=config.state_projection.to_node_context(),
            trigger=config.trigger,
            profile=profile,
            policy=config.policy,
            backend_mode=RuntimeBackendMode.LIVE,
            backend=LiveFixtureBackend(scripted),
            allow_live=True,
            seed=7,
        )
        assert receipt.outcome is RuntimeOutcome.ACCEPTED, receipt.blockers
        review, _ = materialize_ai_taste_attribution_review(
            project,
            candidate,
            project_id="episode-project",
            run_id="attribution-panel-run",
            invocation_id=invocation_id,
            review_id=f"review-{label}",
            reviewer_id=f"reviewer-{label}",
            role=TasteAttributionReviewRole.PRIMARY,
            panel_contract=contract,
            evidence_root=tmp_path,
            output_directory=f"reviews/{label}",
        )
        reviews.append(review)

    admitted = admit_taste_episode(
        candidate,
        tuple(reviews),
        admission_id="runtime-panel-admission",
        evidence_root=tmp_path,
        current_idea_revision=_idea_binding(),
        ai_review_contract=contract,
        expected_ai_review_contract_sha256=contract.contract_sha256,
    )

    assert admitted.review_evidence_kind == "ai"
    assert admitted.cross_model_ai_panel is True
    assert admitted.human_validity_claim_allowed is False
    assert len(list((tmp_path / "reviews").glob("*/REVIEW.json"))) == 2

    family_material = build_scientific_decision_family_review_material(
        project,
        admitted,
        current_idea_revision=_idea_binding(),
    )
    family_reviews = []
    for label, profile_id in (
        ("a", "zhipu-glm53-taste-attribution-review"),
        ("b", "deepseek-v4flash-taste-attribution-review"),
    ):
        profile = profiles[profile_id]
        config = build_scientific_decision_family_runtime_config(
            family_material,
            profile=profile,
            backend_config=StructuredOpenAICompatibleConfig(
                provider=profile.provider,
                base_url="https://example.test",
                model=profile.model,
                api_key_env="TEST_API_KEY",
                max_output_tokens=8192,
            ),
        )
        invocation_id = f"family-review-{label}"
        scripted = ScriptedStructuredBackend(
            name=profile.provider,
            model=profile.model,
            replies={
                invocation_id: ScriptedStructuredReply(
                    output_payload={
                        "packet_sha256": family_material.node_input.packet_sha256,
                        "decision_family": "adaptive-allocation",
                        "rationale": f"Model {label} identifies resource allocation.",
                    },
                    usage=Usage(input_tokens=80, output_tokens=20, cost_usd=0.001),
                )
            },
        )
        receipt = ModelNodeRuntime(project, node_types=taste_node_types()).execute(
            project_id="episode-project",
            run_id="attribution-panel-run",
            invocation_id=invocation_id,
            request_id=invocation_id,
            expected_project_revision=snapshot.revision,
            state_revision=snapshot.revision,
            node_name=config.node_name,
            node_input=config.node_input,
            context=config.state_projection.to_node_context(),
            trigger=config.trigger,
            profile=profile,
            policy=config.policy,
            backend_mode=RuntimeBackendMode.LIVE,
            backend=LiveFixtureBackend(scripted),
            allow_live=True,
            seed=0,
        )
        assert receipt.outcome is RuntimeOutcome.ACCEPTED, receipt.blockers
        family_reviews.append(
            scientific_decision_family_review_from_runtime(
                project,
                admitted,
                project_id="episode-project",
                run_id="attribution-panel-run",
                invocation_id=invocation_id,
                reviewer_id=f"family-reviewer-{label}",
                role="primary",
            )
        )
    assignment = compile_scientific_decision_family_assignment(
        admitted,
        tuple(family_reviews),
        assignment_id="runtime-panel-family",
    )

    assert assignment.decision_family is ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION
    assert assignment.not_human_review is True
    assert assignment.runtime_review_evidence_bound is True


def test_split_preference_requires_independent_adjudication(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, 1)
    split = (
        _review(candidate, reviewer_id="reviewer-a"),
        _review(candidate, reviewer_id="reviewer-b", preferred_action_id="scale-now"),
    )

    before = inspect_taste_episode_admission(
        candidate,
        split,
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )
    adjudicated = inspect_taste_episode_admission(
        candidate,
        (
            *split,
            _review(
                candidate,
                reviewer_id="reviewer-c",
                preferred_action_id="probe-boundary",
                role=TasteAttributionReviewRole.ADJUDICATOR,
            ),
        ),
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )

    assert before.ready_for_policy_training is False
    assert {item.code for item in before.findings} == {"adjudication-required"}
    assert adjudicated.ready_for_policy_training is True
    assert adjudicated.preferred_action_id == "probe-boundary"


def test_episode_producer_cannot_review_its_own_credit(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, 1)
    report = inspect_taste_episode_admission(
        candidate,
        (
            _review(candidate, reviewer_id=candidate.producer_id),
            _review(candidate, reviewer_id="reviewer-b"),
        ),
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )

    assert report.ready_for_policy_training is False
    assert "producer-review-conflict" in {item.code for item in report.findings}


def test_outcome_updated_policy_learns_preference_and_no_update_abstains(
    tmp_path: Path,
    research_state,
) -> None:
    learned = _policy(tmp_path)
    no_update = _policy(tmp_path, mode=LifecycleTastePolicyUpdateMode.NO_UPDATE)

    assessment = assess_lifecycle_taste_policy(
        learned,
        state=research_state,
        actions=_actions(),
        current_idea_revision=_idea_binding(),
    )
    control = assess_lifecycle_taste_policy(
        no_update,
        state=research_state,
        actions=_actions(),
        current_idea_revision=_idea_binding(),
    )

    assert learned.training_episode_count == 8
    assert learned.pairwise_comparison_count == 8
    assert assessment.abstained is False
    assert assessment.recommended_action_id == "probe-boundary"
    assert assessment.pairwise_probability is not None
    assert assessment.pairwise_probability > 0.9
    assert no_update.training_episode_count == 0
    assert control.abstained is True
    assert control.reason_codes == ("no-update-control",)


def test_outcome_updated_policy_aggregates_signed_credit_for_same_action(
    tmp_path: Path,
) -> None:
    episodes = (
        _admitted(
            tmp_path,
            1,
            preferred="probe-boundary",
            polarity=TasteOutcomePolarity.SUPPORTS,
        ),
        _admitted(
            tmp_path,
            2,
            preferred="probe-boundary",
            polarity=TasteOutcomePolarity.CHALLENGES,
        ),
    )
    policy = fit_lifecycle_taste_policy(
        episodes,
        LifecycleTastePolicyConfig(
            policy_id="signed-credit-policy",
            update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
            idea_revision=_idea_binding(),
        ),
    )
    posteriors = {item.feature: item for item in policy.feature_posteriors}

    assert policy.estimator == "signed-factorized-beta-pairwise-v2"
    assert posteriors["action::probe"].wins == pytest.approx(0.9)
    assert posteriors["action::probe"].losses == pytest.approx(0.9)
    assert posteriors["action::probe"].support == pytest.approx(1.8)
    assert posteriors["action::advance"].wins == pytest.approx(0.9)
    assert posteriors["action::advance"].losses == pytest.approx(0.9)


def test_shuffled_credit_control_preserves_action_marginal_and_records_assignment(
    tmp_path: Path,
) -> None:
    shuffled = _policy(tmp_path, mode=LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT)

    action_posteriors = {
        item.feature: item
        for item in shuffled.feature_posteriors
        if item.feature_kind == "action-type"
    }

    assert shuffled.shuffle_algorithm == "blocked-action-type-permutation-v2"
    assert shuffled.shuffle_block_count == 1
    assert shuffled.shuffled_episode_count == 8
    assert shuffled.shuffle_fixed_point_count < 8
    assert shuffled.shuffle_assignment_sha256 is not None
    assert action_posteriors["action::probe"].wins == pytest.approx(3.6)
    assert action_posteriors["action::advance"].wins == pytest.approx(3.6)


def test_shuffled_credit_rejects_nonpermutable_block(tmp_path: Path) -> None:
    episodes = tuple(_admitted(tmp_path, ordinal) for ordinal in range(1, 5))
    config = LifecycleTastePolicyConfig(
        policy_id="nonpermutable-control",
        update_mode=LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT,
        idea_revision=_idea_binding(),
        shuffle_seed=17,
    )

    with pytest.raises(ValueError, match="two preferred action types"):
        fit_lifecycle_taste_policy(episodes, config)


def test_shuffled_credit_is_order_invariant_across_weight_blocks(tmp_path: Path) -> None:
    episodes = tuple(
        _admitted(
            tmp_path,
            ordinal,
            preferred=("probe-boundary" if ordinal % 4 in {1, 2} else "scale-now"),
            confidence=(0.9 if ordinal <= 4 else 0.7),
        )
        for ordinal in range(1, 9)
    )
    config = LifecycleTastePolicyConfig(
        policy_id="weighted-shuffle-control",
        update_mode=LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT,
        idea_revision=_idea_binding(),
        shuffle_seed=23,
    )

    forward = fit_lifecycle_taste_policy(episodes, config)
    reverse = fit_lifecycle_taste_policy(tuple(reversed(episodes)), config)

    assert forward.shuffle_block_count == 2
    assert forward.shuffle_assignment_sha256 == reverse.shuffle_assignment_sha256
    assert forward.shuffle_assignments == reverse.shuffle_assignments
    assert forward.feature_posteriors == reverse.feature_posteriors
    assert forward.policy_sha256 == reverse.policy_sha256
    for block_sha256 in {item.block_sha256 for item in forward.shuffle_assignments}:
        block = [item for item in forward.shuffle_assignments if item.block_sha256 == block_sha256]
        original = sorted(
            (item.original_action_type, item.effective_episode_weight) for item in block
        )
        assigned = sorted(
            (item.assigned_action_type, item.effective_episode_weight) for item in block
        )
        assert original == assigned


def test_shuffled_credit_uses_one_independent_unit_per_source_group(
    tmp_path: Path,
) -> None:
    episodes = (
        _admitted(tmp_path, 1, source_group_id="shared-group"),
        _admitted(
            tmp_path,
            2,
            preferred="scale-now",
            source_group_id="shared-group",
        ),
    )
    config = LifecycleTastePolicyConfig(
        policy_id="cluster-invalid-control",
        update_mode=LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT,
        idea_revision=_idea_binding(),
        shuffle_seed=17,
    )

    with pytest.raises(ValueError, match="one sampled episode per source group"):
        fit_lifecycle_taste_policy(episodes, config)


def test_policy_abstains_without_current_idea_or_after_idea_revision(
    tmp_path: Path,
    research_state,
) -> None:
    policy = _policy(tmp_path)

    unverified = assess_lifecycle_taste_policy(
        policy,
        state=research_state,
        actions=_actions(),
    )
    stale = assess_lifecycle_taste_policy(
        policy,
        state=research_state,
        actions=_actions(),
        current_idea_revision=_idea_binding(revision_id="lifecycle-taste-candidate-02"),
    )

    assert unverified.abstained is True
    assert unverified.reason_codes == ("idea-revision-unverified",)
    assert all(item.adjustment == 0.0 for item in unverified.action_scores)
    assert stale.abstained is True
    assert stale.reason_codes == ("idea-revision-stale",)
    assert stale.observed_idea_revision_id == "lifecycle-taste-candidate-02"


def test_success_and_failure_controls_use_disjoint_outcome_episodes(tmp_path: Path) -> None:
    episodes = (
        _admitted(tmp_path, 1, polarity=TasteOutcomePolarity.SUPPORTS),
        _admitted(tmp_path, 2, polarity=TasteOutcomePolarity.CHALLENGES),
    )
    success = fit_lifecycle_taste_policy(
        episodes,
        LifecycleTastePolicyConfig(
            policy_id="success-only-policy",
            update_mode=LifecycleTastePolicyUpdateMode.SUCCESS_ONLY,
            idea_revision=_idea_binding(),
        ),
    )
    failure = fit_lifecycle_taste_policy(
        episodes,
        LifecycleTastePolicyConfig(
            policy_id="failure-only-policy",
            update_mode=LifecycleTastePolicyUpdateMode.FAILURE_ONLY,
            idea_revision=_idea_binding(),
        ),
    )

    assert success.training_episode_ids == ("admitted-episode-01",)
    assert failure.training_episode_ids == ("admitted-episode-02",)
    assert success.h3_policy_artifact_eligible is False
    assert failure.h3_policy_artifact_eligible is False


def test_scientific_policy_excludes_execution_only_credit_by_default(tmp_path: Path) -> None:
    episodes = (
        _admitted(tmp_path, 1, family=TasteOutcomeFamily.DESIGN),
        _admitted(tmp_path, 2, family=TasteOutcomeFamily.EXECUTION),
    )

    policy = fit_lifecycle_taste_policy(
        episodes,
        LifecycleTastePolicyConfig(
            policy_id="scientific-outcome-policy",
            update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
            idea_revision=_idea_binding(),
        ),
    )

    assert policy.source_episode_ids == (
        "admitted-episode-01",
        "admitted-episode-02",
    )
    assert policy.training_episode_ids == ("admitted-episode-01",)


def test_context_bound_episodes_fit_feedback_adaptive_policy(tmp_path: Path) -> None:
    episodes = tuple(
        _admitted(tmp_path, ordinal, with_decision_context=True) for ordinal in range(1, 5)
    )

    policy = fit_lifecycle_taste_policy(
        episodes,
        LifecycleTastePolicyConfig(
            policy_id="feedback-adaptive-policy",
            update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
            idea_revision=_idea_binding(),
        ),
    )

    assert policy.schema_version == "1.5"
    assert any(item.feature_kind == "decision-state-action" for item in policy.feature_posteriors)
    assert policy.h4_adaptive_policy_eligible is False


def test_h4_policy_reproduction_refits_ai_admissions_and_tolerates_project_revision(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    contract_source = Path(
        "configs/evaluation/programs/iclr2027_scitaste_ai_review_amendment_v1.yaml"
    )
    contract_path = tmp_path / "AI_REVIEW_CONTRACT.yaml"
    contract_path.write_bytes(contract_source.read_bytes())
    contract = load_ai_taste_review_panel_contract(contract_path)
    episodes = []
    for ordinal, preferred in ((1, "probe-boundary"), (2, "scale-now")):
        candidate = _candidate(
            evidence_root,
            ordinal,
            decision_context=TasteEpisodeDecisionContext(
                remaining_experiments="two-to-three",
                failure_count=("zero" if ordinal == 1 else "one"),
                no_improvement_streak=("zero" if ordinal == 1 else "one"),
                score_trend=("improving" if ordinal == 1 else "flat"),
                best_vs_baseline=("above" if ordinal == 1 else "equal"),
            ),
        )
        reviews = (
            _ai_review(
                candidate,
                evidence_root,
                reviewer_id=f"ai-a-{ordinal}",
                run_id=f"ai-a-run-{ordinal}",
                model_id="review-model-a",
                preferred_action_id=preferred,
            ),
            _ai_review(
                candidate,
                evidence_root,
                reviewer_id=f"ai-b-{ordinal}",
                run_id=f"ai-b-run-{ordinal}",
                model_id="review-model-b",
                preferred_action_id=preferred,
            ),
        )
        episodes.append(
            admit_taste_episode(
                candidate,
                reviews,
                admission_id=f"h4-ai-admission-{ordinal}",
                evidence_root=evidence_root,
                current_idea_revision=_idea_binding(),
                ai_review_contract=contract,
                expected_ai_review_contract_sha256=contract.contract_sha256,
            )
        )
    policy = fit_lifecycle_taste_policy(
        tuple(episodes),
        LifecycleTastePolicyConfig(
            policy_id="reproducible-h4-ai-policy",
            update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
            idea_revision=_idea_binding(),
        ),
    )
    assert policy.h4_adaptive_policy_eligible is True
    policy_path = tmp_path / "POLICY.json"
    policy_path.write_text(policy.model_dump_json(indent=2) + "\n", encoding="utf-8")
    episode_locators = []
    for episode in episodes:
        path = tmp_path / f"{episode.admission_id}.json"
        path.write_text(episode.model_dump_json(indent=2) + "\n", encoding="utf-8")
        episode_locators.append(path.name)
    spec = H4PolicyReproductionSpec.create(
        spec_id="h4-policy-reproduction-test",
        project_id="episode-project",
        evaluation_id="h4-formal-v1",
        lifecycle_policy_locator=policy_path.name,
        admitted_episode_locators=tuple(episode_locators),
        ai_review_panel_contract_locator=contract_path.name,
        episode_evidence_root_locator=evidence_root.name,
    )
    advanced_snapshot = ProjectIdeaRevisionBinding.create(
        project_id="episode-project",
        observed_project_revision=99,
        observed_project_snapshot_sha256="9" * 64,
        revision_id="lifecycle-taste-candidate-01",
        status="candidate",
        record_locator="runs/idea-run/idea_refinement/REVISION.json",
        record_sha256="2" * 64,
        artifact_sha256="3" * 64,
        selected_for_paper=False,
        paper_claim_authority=False,
    )

    report, reproduced = reproduce_h4_lifecycle_policy(
        tmp_path,
        spec,
        current_idea_revision=advanced_snapshot,
    )

    assert reproduced == policy
    assert report.refitted_policy_sha256 == policy.policy_sha256
    assert report.reviewer_kind == "ai"
    assert report.not_human_review is True


def test_repeated_decisions_from_one_trajectory_do_not_inflate_support(
    tmp_path: Path,
    research_state,
) -> None:
    episodes = tuple(
        _admitted(tmp_path, ordinal, source_group_id="shared-trajectory") for ordinal in range(1, 9)
    )
    policy = fit_lifecycle_taste_policy(
        episodes,
        LifecycleTastePolicyConfig(
            policy_id="group-weighted-policy",
            update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
            idea_revision=_idea_binding(),
            minimum_feature_support=3.0,
        ),
    )

    assessment = assess_lifecycle_taste_policy(
        policy,
        state=research_state,
        actions=_actions(),
        current_idea_revision=_idea_binding(),
    )

    assert policy.training_episode_count == 8
    assert policy.training_source_group_count == 1
    assert policy.effective_training_weight == 0.9
    assert assessment.abstained is True
    assert "insufficient-support" in assessment.reason_codes


def test_family_conditioned_policy_keeps_h4_adaptive_head_isolated(
    tmp_path: Path,
) -> None:
    episodes = tuple(_admitted(tmp_path, ordinal) for ordinal in range(1, 4))
    assignments = tuple(
        _family_assignment(episode, ordinal) for ordinal, episode in enumerate(episodes, start=1)
    )
    model = fit_family_conditioned_lifecycle_taste_policy(
        episodes,
        assignments,
        LifecycleTastePolicyConfig(
            policy_id="ignored-base-id",
            update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
            idea_revision=_idea_binding(),
            minimum_feature_support=1.0,
        ),
        policy_id="family-policy",
    )

    head = model.require_head(ScientificTasteDecisionFamily.ADAPTIVE_ALLOCATION)

    assert head.policy_id == "family-policy-adaptive-allocation"
    assert head.source_episode_ids == tuple(item.admission_id for item in episodes)
    assert ScientificTasteDecisionFamily.SCIENTIFIC_COMMUNICATION in model.empty_families
    assert model.not_human_review is True


def test_schema_11_episode_replays_but_cannot_train_without_sampling_unit(
    tmp_path: Path,
) -> None:
    current = _candidate(tmp_path, 1)
    payload = current.model_dump(mode="json", exclude={"candidate_sha256"})
    payload["schema_version"] = "1.1"
    for field in (
        "source_project_id",
        "source_group_id",
        "dataset_partition",
        "source_relationship",
    ):
        payload.pop(field)
    legacy_sha256 = content_sha256(payload)
    legacy = type(current).model_validate({**payload, "candidate_sha256": legacy_sha256})
    reviews = (
        _review(legacy, reviewer_id="reviewer-a"),
        _review(legacy, reviewer_id="reviewer-b"),
    )
    admitted = admit_taste_episode(
        legacy,
        reviews,
        admission_id="legacy-admitted-episode-01",
        evidence_root=str(tmp_path),
        current_idea_revision=_idea_binding(),
    )

    with pytest.raises(ValueError, match="frozen sampling unit"):
        fit_lifecycle_taste_policy(
            (admitted,),
            LifecycleTastePolicyConfig(
                policy_id="legacy-policy",
                update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
                idea_revision=_idea_binding(),
            ),
        )


def test_schema_10_policy_replays_under_its_original_hash(tmp_path: Path) -> None:
    current = _policy(tmp_path)
    payload = current.model_dump(mode="json", exclude={"policy_sha256"})
    payload["schema_version"] = "1.0"
    for field in (
        "training_source_group_keys",
        "training_source_group_count",
        "effective_training_weight",
        "shuffle_algorithm",
        "shuffle_block_count",
        "shuffled_episode_count",
        "shuffle_fixed_point_count",
        "shuffle_assignment_sha256",
        "shuffle_assignments",
        "source_review_evidence_kinds",
        "source_ai_reviewed_episode_count",
        "source_legacy_unverified_episode_count",
        "ai_review_contract_sha256s",
        "human_validity_claim_allowed",
        "source_group_keys",
        "source_group_count",
        "source_group_ids",
    ):
        payload.pop(field)
    legacy_sha256 = content_sha256(payload)

    legacy = type(current).model_validate({**payload, "policy_sha256": legacy_sha256})

    assert legacy.schema_version == "1.0"
    assert legacy.policy_sha256 == legacy_sha256
    assert legacy.training_source_group_keys == ()


def test_schema_11_policy_replays_with_source_group_fields(tmp_path: Path) -> None:
    current = _policy(tmp_path)
    payload = current.model_dump(mode="json", exclude={"policy_sha256"})
    payload["schema_version"] = "1.1"
    for field in (
        "shuffle_algorithm",
        "shuffle_block_count",
        "shuffled_episode_count",
        "shuffle_fixed_point_count",
        "shuffle_assignment_sha256",
        "shuffle_assignments",
        "source_review_evidence_kinds",
        "source_ai_reviewed_episode_count",
        "source_legacy_unverified_episode_count",
        "ai_review_contract_sha256s",
        "human_validity_claim_allowed",
        "source_group_keys",
        "source_group_count",
        "source_group_ids",
    ):
        payload.pop(field)
    legacy_sha256 = content_sha256(payload)

    legacy = type(current).model_validate({**payload, "policy_sha256": legacy_sha256})

    assert legacy.schema_version == "1.1"
    assert legacy.policy_sha256 == legacy_sha256
    assert legacy.training_source_group_count == 8


def test_legacy_shuffled_policy_loads_for_audit_but_is_not_h3_eligible(
    tmp_path: Path,
) -> None:
    current = _policy(tmp_path, mode=LifecycleTastePolicyUpdateMode.SHUFFLED_CREDIT)
    payload = current.model_dump(mode="json", exclude={"policy_sha256"})
    payload["schema_version"] = "1.1"
    for field in (
        "shuffle_algorithm",
        "shuffle_block_count",
        "shuffled_episode_count",
        "shuffle_fixed_point_count",
        "shuffle_assignment_sha256",
        "shuffle_assignments",
        "source_review_evidence_kinds",
        "source_ai_reviewed_episode_count",
        "source_legacy_unverified_episode_count",
        "ai_review_contract_sha256s",
        "human_validity_claim_allowed",
        "source_group_keys",
        "source_group_count",
        "source_group_ids",
    ):
        payload.pop(field)
    legacy_sha256 = content_sha256(payload)

    legacy = type(current).model_validate({**payload, "policy_sha256": legacy_sha256})

    assert legacy.schema_version == "1.1"
    assert legacy.h3_policy_artifact_eligible is False


def test_policy_update_rejects_episode_from_another_idea_revision(tmp_path: Path) -> None:
    episode = _admitted(tmp_path, 1)
    config = LifecycleTastePolicyConfig(
        policy_id="stale-policy",
        update_mode=LifecycleTastePolicyUpdateMode.OUTCOME_UPDATED,
        idea_revision=_idea_binding(revision_id="lifecycle-taste-candidate-02"),
    )

    with pytest.raises(ValueError, match="another Idea revision"):
        fit_lifecycle_taste_policy((episode,), config)


def test_controller_applies_learned_policy_and_records_exact_trace(
    tmp_path: Path,
    research_state,
) -> None:
    policy = _policy(tmp_path)
    baseline = TasteController(seed=3, critics_enabled=False).decide(
        state=research_state,
        candidate_actions=_actions(),
    )
    learned = TasteController(
        seed=3,
        critics_enabled=False,
        lifecycle_policy=policy,
        lifecycle_policy_weight=2.0,
    ).decide(
        state=research_state,
        candidate_actions=_actions(),
        current_idea_revision=_idea_binding(),
    )

    assert baseline.selected_action.action_id == "scale-now"
    assert learned.selected_action.action_id == "probe-boundary"
    assert learned.lifecycle_taste_policy is not None
    assert learned.lifecycle_taste_policy.policy_sha256 == policy.policy_sha256
    assert learned.lifecycle_taste_policy.abstained is False
    assert learned.lifecycle_taste_policy.recommended_action_id == "probe-boundary"
    assert "Learned lifecycle Taste applied" in learned.rationale

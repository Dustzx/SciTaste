from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.model_nodes import (
    BoundEvidenceRecord,
    EvidenceInspectionHandler,
    KnowledgeQueryHandler,
    RegisteredRunComparisonHandler,
)
from scitaste.model_nodes.tool_effectiveness import (
    ToolEffectivenessBlindReview,
    ToolEffectivenessBlindReviewRating,
    ToolEffectivenessCondition,
    ToolEffectivenessError,
    ToolEffectivenessFixture,
    build_tool_effectiveness_blind_packet,
    build_tool_effectiveness_trial,
    deterministic_v2_router,
    evaluate_tool_effectiveness_blind_review,
    evaluate_tool_effectiveness_study,
    execute_read_only_step,
    load_tool_effectiveness_fixture,
)
from scitaste.model_nodes.tool_intelligence import (
    ControlledToolName,
    EvidenceInspectArguments,
    EvidenceInspectStep,
    KnowledgeQueryArguments,
    KnowledgeQueryStep,
    RegisteredRunCompareArguments,
    RegisteredRunCompareStep,
)

FIXTURE_PATH = Path("configs/model_nodes/tool_intelligence_effectiveness_study_v1.json")


def _fixture() -> ToolEffectivenessFixture:
    return load_tool_effectiveness_fixture(FIXTURE_PATH)


def _handlers(fixture: ToolEffectivenessFixture):
    return (
        KnowledgeQueryHandler(fixture.knowledge_libraries),
        EvidenceInspectionHandler(
            BoundEvidenceRecord(
                evidence_id=item.evidence.evidence_id,
                payload=item.evidence.model_dump(mode="json"),
                provenance=item.provenance,
            )
            for item in fixture.evidence_records
        ),
        RegisteredRunComparisonHandler({item.run_id: item.metrics for item in fixture.run_metrics}),
    )


def _gold_step(task):
    gold = task.gold
    if gold.expected_tool_name is ControlledToolName.KNOWLEDGE_QUERY:
        return KnowledgeQueryStep(
            step_id="treatment-step",
            purpose="Retrieve the evidence specified by the semantic objective.",
            arguments=KnowledgeQueryArguments(
                query=task.objective,
                library_ids=gold.required_library_ids,
                top_k=3,
            ),
        )
    if gold.expected_tool_name is ControlledToolName.EVIDENCE_INSPECT:
        return EvidenceInspectStep(
            step_id="treatment-step",
            purpose="Inspect the semantically relevant evidence.",
            arguments=EvidenceInspectArguments(evidence_ids=gold.required_evidence_ids),
        )
    return RegisteredRunCompareStep(
        step_id="treatment-step",
        purpose="Compare the semantically relevant registered result.",
        arguments=RegisteredRunCompareArguments(
            run_ids=gold.required_run_ids,
            metric_names=gold.required_metric_names,
        ),
    )


def _complete_matrix(fixture: ToolEffectivenessFixture):
    handlers = _handlers(fixture)
    trials = []
    for task in fixture.protocol.tasks:
        for seed in fixture.protocol.seeds:
            baseline_step = deterministic_v2_router(task)
            baseline_observation = execute_read_only_step(baseline_step, handlers)
            trials.append(
                build_tool_effectiveness_trial(
                    fixture=fixture,
                    task=task,
                    seed=seed,
                    condition=ToolEffectivenessCondition.V2_FIXED_ROUTER,
                    model_admitted=False,
                    workflow_resolved=True,
                    selected_step=baseline_step,
                    observation_payload=baseline_observation,
                    model_invocations=0,
                    tool_invocations=1,
                )
            )
            treatment_step = _gold_step(task)
            treatment_observation = execute_read_only_step(treatment_step, handlers)
            trials.append(
                build_tool_effectiveness_trial(
                    fixture=fixture,
                    task=task,
                    seed=seed,
                    condition=ToolEffectivenessCondition.V3_LIVE_PROJECT_LOOP,
                    model_admitted=True,
                    workflow_resolved=True,
                    selected_step=treatment_step,
                    observation_payload=treatment_observation,
                    model_invocations=1,
                    tool_invocations=1,
                    input_tokens=100,
                    output_tokens=50,
                    known_cost_usd=0.001,
                    model_latency_ms=100,
                    tool_latency_ms=1,
                    raw_response_sha256="a" * 64,
                    evidence_locator="projects/study/runs/live/model_nodes/treatment.json",
                )
            )
    return tuple(trials)


def test_preregistered_fixture_is_closed_and_balanced() -> None:
    fixture = _fixture()

    assert len(fixture.protocol.tasks) == 12
    assert len(fixture.protocol.seeds) == 3
    assert len({task.stratum for task in fixture.protocol.tasks}) == 2
    assert fixture.protocol.minimum_paired_trials == 36
    assert fixture.protocol.minimum_independent_tasks == 12
    assert fixture.protocol.independent_domain_review_required is True
    assert fixture.protocol.external_validity == "unestablished"


def test_fixed_router_is_frozen_and_does_not_use_a_model() -> None:
    fixture = _fixture()
    handlers = _handlers(fixture)
    trials = []

    for task in fixture.protocol.tasks:
        step = deterministic_v2_router(task)
        observation = execute_read_only_step(step, handlers)
        trials.append(
            build_tool_effectiveness_trial(
                fixture=fixture,
                task=task,
                seed=7,
                condition=ToolEffectivenessCondition.V2_FIXED_ROUTER,
                model_admitted=False,
                workflow_resolved=True,
                selected_step=step,
                observation_payload=observation,
                model_invocations=0,
                tool_invocations=1,
            )
        )

    assert sum(trial.grounded_resolution_correct for trial in trials) == 6
    assert all(trial.model_invocations == 0 for trial in trials)


def test_paired_evaluator_reports_exact_mcnemar_signal_without_scientific_claim() -> None:
    fixture = _fixture()
    report = evaluate_tool_effectiveness_study(fixture, _complete_matrix(fixture))

    assert report.replicate_pair_count == 36
    assert report.independent_task_count == 12
    assert report.baseline.grounded_resolution_accuracy == 0.5
    assert report.treatment.grounded_resolution_accuracy == 1.0
    assert report.treatment.prompt_cache_input_tokens == 0
    assert report.paired_test.improved_pairs == 6
    assert report.paired_test.regressed_pairs == 0
    assert report.paired_test.exact_two_sided_mcnemar_p == pytest.approx(0.03125)
    assert report.preliminary_effectiveness_signal is True
    assert report.independent_domain_review_complete is False
    assert report.scientific_effectiveness_claim is False


def test_evaluator_refuses_missing_pair_and_foreign_fixture() -> None:
    fixture = _fixture()
    trials = _complete_matrix(fixture)

    with pytest.raises(ToolEffectivenessError, match="exact preregistered matrix"):
        evaluate_tool_effectiveness_study(fixture, trials[:-1])

    changed = trials[0].model_copy(update={"fixture_fingerprint": "0" * 64})
    with pytest.raises(ToolEffectivenessError, match="another protocol or fixture"):
        evaluate_tool_effectiveness_study(fixture, (changed, *trials[1:]))


def test_blind_packet_excludes_condition_gold_and_mapping(tmp_path: Path) -> None:
    fixture = _fixture()
    packet, key = build_tool_effectiveness_blind_packet(
        fixture,
        _complete_matrix(fixture),
        blinding_salt="independent-review-salt-v1",
    )
    packet_json = packet.model_dump_json()

    assert len(packet.items) == 72
    assert packet.fingerprint == key.packet_fingerprint
    assert "v2-fixed-router" not in packet_json
    assert "v3-live-project-loop" not in packet_json
    assert "expected_tool_name" not in packet_json
    assert {item.blind_id for item in packet.items} == {item.blind_id for item in key.entries}

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
    with pytest.raises(ToolEffectivenessError, match="invalid"):
        load_tool_effectiveness_fixture(duplicate)


def test_independent_blind_review_requires_exact_packet_and_stays_non_claiming() -> None:
    fixture = _fixture()
    trials = _complete_matrix(fixture)
    packet, key = build_tool_effectiveness_blind_packet(
        fixture,
        trials,
        blinding_salt="independent-review-salt-v1",
    )
    trial_by_fingerprint = {item.fingerprint: item for item in trials}
    review = ToolEffectivenessBlindReview(
        review_id="independent-review-v1",
        reviewer_id="reviewer-alpha",
        packet_fingerprint=packet.fingerprint,
        independence_attested=True,
        fixture_author=False,
        private_key_received_before_completion=False,
        ratings=tuple(
            ToolEffectivenessBlindReviewRating(
                blind_id=entry.blind_id,
                grounded_and_relevant=trial_by_fingerprint[
                    entry.trial_fingerprint
                ].grounded_resolution_correct,
                scope_appropriate=True,
                rationale="The selected record and action are relevant to the stated objective.",
                confidence=4,
            )
            for entry in key.entries
        ),
    )

    report = evaluate_tool_effectiveness_blind_review(fixture, packet, key, review)

    assert report.rating_count == 72
    assert report.baseline_grounded_relevance_rate == 0.5
    assert report.treatment_grounded_relevance_rate == 1.0
    assert report.improved_task_pairs == 6
    assert report.regressed_task_pairs == 0
    assert report.exact_two_sided_mcnemar_p == pytest.approx(0.03125)
    assert report.independent_domain_review_complete is True
    assert report.scientific_effectiveness_claim is False

    incomplete = review.model_copy(update={"ratings": review.ratings[:-1]})
    with pytest.raises(ToolEffectivenessError, match="exact packet"):
        evaluate_tool_effectiveness_blind_review(fixture, packet, key, incomplete)

    values = review.model_dump(mode="python", exclude={"fingerprint"})
    values["private_key_received_before_completion"] = True
    with pytest.raises(ValidationError):
        ToolEffectivenessBlindReview.model_validate(values)


def test_trial_contract_rejects_false_grounded_success() -> None:
    fixture = _fixture()
    task = fixture.protocol.tasks[0]
    step = deterministic_v2_router(task)
    values = build_tool_effectiveness_trial(
        fixture=fixture,
        task=task,
        seed=7,
        condition=ToolEffectivenessCondition.V2_FIXED_ROUTER,
        model_admitted=False,
        workflow_resolved=True,
        selected_step=step,
        observation_payload=execute_read_only_step(step, _handlers(fixture)),
        model_invocations=0,
        tool_invocations=1,
    ).model_dump(mode="python", exclude={"fingerprint"})
    values.update(workflow_resolved=False, grounded_resolution_correct=True)

    with pytest.raises(ValidationError, match="grounded correctness"):
        type(
            build_tool_effectiveness_trial(
                fixture=fixture,
                task=task,
                seed=19,
                condition=ToolEffectivenessCondition.V2_FIXED_ROUTER,
                model_admitted=False,
                workflow_resolved=True,
                selected_step=step,
                observation_payload=execute_read_only_step(step, _handlers(fixture)),
                model_invocations=0,
                tool_invocations=1,
            )
        ).model_validate(values)


def test_fixture_fingerprint_changes_when_gold_is_changed() -> None:
    fixture = _fixture()
    values = json.loads(fixture.model_dump_json(exclude_computed_fields=True))
    values["protocol"]["tasks"][0]["objective"] += " changed"
    changed = ToolEffectivenessFixture.model_validate(values)

    assert changed.fingerprint != fixture.fingerprint

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scitaste.backends.base import Usage
from scitaste.evaluation.decision_method_comparison import (
    DecisionMethodSubmission,
    VisibleEvidenceArtifact,
    compile_decision_case,
    score_decision_methods,
    verify_visible_evidence_artifacts,
)
from scitaste.evaluation.decision_policy_baselines import (
    DecisionReflectionEpisode,
    run_decision_policy,
)
from scitaste.model_nodes.models import StructuredModelResponse
from scripts.prepare_scitastebench_reflection_development import (
    build_source_memory,
    partition_groups,
)


def _value(value: str) -> SimpleNamespace:
    return SimpleNamespace(value=value)


def _case(cluster: str, prefix: str, utilities: dict[str, float]) -> SimpleNamespace:
    situation = SimpleNamespace(
        prefix_sha256=prefix * 64,
        hypothesis_structure=_value("competing-candidates"),
        evidence_relation=_value("underdetermined"),
        bottleneck=_value("functional-form-discrimination"),
        identifiability=_value("medium"),
        budget_pressure=_value("medium"),
        terminal_readiness=_value("not-ready"),
        decision_basis="Probe before committing the remaining budget.",
        anchors=(SimpleNamespace(quote="two live explanations"),),
    )
    actions = tuple(
        SimpleNamespace(
            action_id=action,
            semantic_role=f"{action}-role",
            description=f"Execute {action}.",
        )
        for action in sorted(utilities)
    )
    return SimpleNamespace(
        situation=situation,
        action_semantics_sha256="e" * 64,
        action_definitions=actions,
        execution_contract=SimpleNamespace(
            resource_limits={"max_experiments": 3.0},
            maximum_steps=3,
            timeout_seconds=120,
            contract_sha256="c" * 64,
        ),
        scorer_contract=SimpleNamespace(
            intention_to_treat_failure_utility=0.0,
            practical_equivalence_tolerance=0.001,
            contract_sha256="d" * 64,
        ),
        task_cluster_id=cluster,
        action_utility_estimates=utilities,
    )


def _submission(method: str, request_hash: str, action: str) -> DecisionMethodSubmission:
    return DecisionMethodSubmission(
        method_id=method,
        method_manifest_sha256="1" * 64,
        request_sha256=request_hash,
        selected_action_id=action,
        input_tokens=10,
        output_tokens=1,
        inference_cost_usd=0.001,
    )


def test_method_view_hides_outcomes_and_scores_task_clusters() -> None:
    cases = (
        _case("cluster-a", "a", {"A": 1.0, "B": 0.0}),
        _case("cluster-a", "b", {"A": 1.0, "B": 0.0}),
        _case("cluster-b", "f", {"A": 0.0, "B": 1.0}),
    )
    pairs = tuple(compile_decision_case(case, native_action_id="A") for case in cases)
    requests = tuple(item[0] for item in pairs)
    keys = tuple(item[1] for item in pairs)
    for request in requests:
        payload = request.model_dump(mode="json")
        assert "action_utility_estimates" not in payload
        assert "replicate_outcomes" not in payload
        assert "task_cluster_id" not in payload
        assert "scorer_contract" not in payload
    submissions = tuple(
        _submission(method, request.request_sha256, action)
        for method, action in (("direct", "A"), ("reflection", "B"))
        for request in requests
    )
    results = score_decision_methods(requests, keys, submissions)
    assert [item.method_id for item in results] == ["direct", "reflection"]
    assert results[0].mean_cluster_regret == pytest.approx(0.5)
    assert results[0].tie_aware_accuracy == pytest.approx(2 / 3)
    assert results[1].mean_cluster_regret == pytest.approx(0.5)
    assert results[1].tie_aware_accuracy == pytest.approx(1 / 3)


def test_missing_or_invalid_method_decisions_fail_closed() -> None:
    request, key = compile_decision_case(
        _case("cluster-a", "a", {"A": 0.8, "B": 0.2}), native_action_id="B"
    )
    with pytest.raises(ValueError, match="outside the menu"):
        score_decision_methods(
            (request,), (key,), (_submission("direct", request.request_sha256, "C"),)
        )
    with pytest.raises(ValueError, match="did not cover every decision"):
        second_request, second_key = compile_decision_case(
            _case("cluster-b", "b", {"A": 0.8, "B": 0.2}), native_action_id="B"
        )
        score_decision_methods(
            (request, second_request),
            (key, second_key),
            (_submission("direct", request.request_sha256, "A"),),
        )
    with pytest.raises(ValueError, match="changed its frozen manifest"):
        score_decision_methods(
            (request, second_request),
            (key, second_key),
            (
                _submission("direct", request.request_sha256, "A"),
                _submission("direct", second_request.request_sha256, "A").model_copy(
                    update={"method_manifest_sha256": "f" * 64}
                ),
            ),
        )
    failure = DecisionMethodSubmission(
        method_id="failed",
        method_manifest_sha256="2" * 64,
        request_sha256=request.request_sha256,
        failure_code="provider-error",
        input_tokens=0,
        output_tokens=0,
        inference_cost_usd=0.0,
    )
    abstain = DecisionMethodSubmission(
        method_id="abstain",
        method_manifest_sha256="3" * 64,
        request_sha256=request.request_sha256,
        abstained=True,
        input_tokens=1,
        output_tokens=1,
        inference_cost_usd=0.0,
    )
    results = score_decision_methods((request,), (key,), (failure, abstain))
    assert results[0].mean_cluster_regret == pytest.approx(0.6)
    assert results[0].abstention_rate == 1.0
    assert results[1].mean_cluster_regret == pytest.approx(0.8)
    assert results[1].failure_rate == 1.0


def test_domain_evidence_is_optional_content_bound_and_outcome_hidden(
    tmp_path: Path,
) -> None:
    root = tmp_path / "visible"
    root.mkdir()
    image = root / "error-slice.png"
    image.write_bytes(b"predecision-image-example")
    artifact = VisibleEvidenceArtifact(
        artifact_id="visual-error-1",
        relative_locator=image.name,
        media_type="image/png",
        sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
        size_bytes=image.stat().st_size,
    )
    request, _ = compile_decision_case(
        _case("cluster-a", "a", {"A": 1.0, "B": 0.0}),
        native_action_id="A",
        evidence_artifacts=(artifact,),
    )
    assert verify_visible_evidence_artifacts(request, artifact_root=root) == (image,)
    assert "action_utilities" not in request.model_dump_json()
    assert "evidence_artifacts" in request.model_dump(mode="json")
    plain, _ = compile_decision_case(
        _case("cluster-a", "a", {"A": 1.0, "B": 0.0}), native_action_id="A"
    )
    assert "evidence_artifacts" not in plain.model_dump(mode="json")
    image.write_bytes(b"changed")
    with pytest.raises(ValueError, match="size differs"):
        verify_visible_evidence_artifacts(request, artifact_root=root)
    image.unlink()
    private = tmp_path / "private-score.json"
    private.write_bytes(b"predecision-image-example")
    image.symlink_to(private)
    with pytest.raises(ValueError, match="symbolic link"):
        verify_visible_evidence_artifacts(request, artifact_root=root)
    with pytest.raises(ValueError, match="project-relative"):
        VisibleEvidenceArtifact(
            artifact_id="bad",
            relative_locator="../private/score.json",
            media_type="application/json",
            sha256="a" * 64,
            size_bytes=1,
        )


class _DecisionBackend:
    name = "fake-provider"
    model = "fake-model"

    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = outputs
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        payload = self.outputs.pop(0)
        raw = "{}"
        return StructuredModelResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            output_payload=payload,
            backend=self.name,
            model=self.model,
            raw_response=raw,
            raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            latency_ms=1,
            usage=Usage(input_tokens=10, output_tokens=2, cost_usd=None),
        )


def test_independent_policies_keep_unknown_cost_unknown_and_hide_scoring_key() -> None:
    request, key = compile_decision_case(
        _case("target", "a", {"A": 0.8, "B": 0.2}), native_action_id="B"
    )
    direct = _DecisionBackend([{"selected_action_id": "A"}])
    result = run_decision_policy(
        (request,),
        method_id="direct",
        policy_kind="direct",
        backend=direct,
        backend_manifest_sha256="e" * 64,
    )
    assert result.submissions[0].selected_action_id == "A"
    assert result.submissions[0].inference_cost_usd is None
    assert "action_utilities" not in direct.requests[0].model_dump_json()
    summary = score_decision_methods((request,), (key,), result.submissions)[0]
    assert summary.mean_inference_cost_usd is None
    assert not summary.cost_complete
    assert summary.cost_reported_cases == 0

    episodes = (
        DecisionReflectionEpisode(
            source_task_cluster_id="target",
            research_state="prior state",
            action_taken="A",
            observed_outcome="objective improved",
        ),
    )
    with pytest.raises(ValueError, match="overlaps"):
        run_decision_policy(
            (request,),
            method_id="reflection",
            policy_kind="reflection",
            backend=_DecisionBackend([]),
            backend_manifest_sha256="e" * 64,
            reflection_episodes=episodes,
            target_task_cluster_ids=frozenset({"target"}),
        )


def test_planning_elicits_all_actions_before_final_decision() -> None:
    request, _ = compile_decision_case(
        _case("target", "b", {"A": 0.8, "B": 0.2}), native_action_id="B"
    )
    backend = _DecisionBackend(
        [{"action_scores": {"A": 0.7, "B": 0.3}}, {"selected_action_id": "A"}]
    )
    result = run_decision_policy(
        (request,),
        method_id="planning",
        policy_kind="planning",
        backend=backend,
        backend_manifest_sha256="e" * 64,
    )
    assert result.submissions[0].selected_action_id == "A"
    assert result.submissions[0].input_tokens == 20
    assert [item.stage for item in result.receipts] == [
        "estimate-actions",
        "choose-action",
    ]
    assert backend.requests[1].input_payload["estimated_action_scores"] == {
        "A": 0.7,
        "B": 0.3,
    }


def test_reflection_memory_uses_only_prespecified_source_observation() -> None:
    source = _case("source-group", "a", {"A": 0.8, "B": 0.2})
    target = _case("target-group", "b", {"A": 0.1, "B": 0.9})
    source.execution_contract.seed_block_ids = ("block-0",)
    source.replicate_outcomes = (
        SimpleNamespace(
            seed_block_id="block-0",
            action_id="B",
            objective_observed=True,
            raw_metric_value=0.75,
            utility=0.2,
            failure_code=None,
        ),
    )
    source_request, _ = compile_decision_case(source, native_action_id="B")
    target_request, _ = compile_decision_case(target, native_action_id="A")
    memory = build_source_memory(
        (source, target),
        {
            source_request.case_id: source_request,
            target_request.case_id: target_request,
        },
        frozenset({"source-group"}),
    )
    assert len(memory) == 1
    assert memory[0].action_taken == "B"
    assert "0.75" in memory[0].observed_outcome
    assert "target-group" not in memory[0].model_dump_json()
    groups = frozenset({"a", "b", "c", "d", "e", "f"})
    earlier, later = partition_groups(groups)
    assert len(earlier) == len(later) == 3
    assert earlier.isdisjoint(later)
    assert earlier | later == groups

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from scitaste.backends.base import Usage
from scitaste.model_nodes import (
    ControlledToolProfile,
    EvidenceInspectPermission,
    KnowledgeQueryPermission,
    NodeContext,
    NodePolicy,
    NodePolicyViolationError,
    NodeResultStatus,
    RegisteredRunComparePermission,
    ReviewSemanticOutput,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    StructuredRepairInput,
    StructuredRepairNode,
    ToolCallProposal,
    ToolPlanInput,
    ToolPlanNode,
    ToolScopeProjection,
    canonical_json,
    output_schema_sha256,
)


def _context() -> NodeContext:
    return NodeContext(
        project_id="tool-project",
        stage="EVIDENCE",
        state_snapshot_id="snapshot-7",
        cumulative_api_cost_usd=0,
        evidence_ids=["evidence-1", "evidence-2"],
    )


def _controlled_profile(**updates: object) -> ControlledToolProfile:
    values: dict[str, object] = {
        "profile_id": "readonly-project-analysis",
        "profile_version": "1.0.0",
        "permissions": [
            KnowledgeQueryPermission(
                allowed_library_ids=("knowledge-main", "knowledge-methods"),
                max_library_ids=2,
                max_query_chars=120,
                max_top_k=5,
            ),
            EvidenceInspectPermission(
                allowed_evidence_ids=("evidence-1", "evidence-2"),
                max_evidence_items=2,
            ),
            RegisteredRunComparePermission(
                allowed_run_ids=("run-base", "run-candidate"),
                allowed_metric_names=("accuracy", "latency_ms"),
                max_runs=2,
                max_metrics=2,
            ),
        ],
        "max_plan_steps": 4,
        "max_dependency_edges": 4,
    }
    values.update(updates)
    return ControlledToolProfile.model_validate(values)


def _input(profile: ControlledToolProfile | None = None) -> ToolPlanInput:
    return ToolPlanInput(
        objective="Inspect project evidence and compare the registered runs.",
        scope=ToolScopeProjection(
            project_id="tool-project",
            state_snapshot_id="snapshot-7",
            library_ids=("knowledge-main", "knowledge-methods"),
            evidence_ids=("evidence-1", "evidence-2"),
            run_ids=("run-base", "run-candidate"),
            metric_names=("accuracy", "latency_ms"),
        ),
        tool_profile=profile or _controlled_profile(),
    )


def _policy(node_name: str, *, tools: tuple[str, ...] = ()) -> NodePolicy:
    return NodePolicy(
        policy_id=f"policy-{node_name}",
        enabled=True,
        allowed_node_names=[node_name],
        expected_backend="scripted",
        expected_model="scripted-v1",
        allowed_tool_names=list(tools),
        max_input_tokens=200,
        max_output_tokens=200,
        max_total_tokens=400,
        max_api_cost_usd=0.1,
        max_latency_ms=1_000,
    )


def _backend(
    request_id: str,
    payload: object,
    *,
    tool_calls: list[ToolCallProposal] | None = None,
    usage: Usage | None = None,
) -> ScriptedStructuredBackend:
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            request_id: ScriptedStructuredReply(
                output_payload=payload,
                usage=usage or Usage(input_tokens=20, output_tokens=15, cost_usd=0),
                latency_ms=2,
                tool_calls=tool_calls or [],
            )
        },
    )


def _plan_payload(profile: ControlledToolProfile | None = None) -> dict[str, object]:
    profile = profile or _controlled_profile()
    return {
        "tool_profile_id": profile.profile_id,
        "tool_profile_fingerprint": profile.fingerprint,
        "steps": [
            {
                "step_id": "find-methods",
                "depends_on": [],
                "purpose": "Find relevant methods in the project-owned library.",
                "tool_name": "knowledge.query",
                "arguments": {
                    "query": "methods for matched evidence comparison",
                    "library_ids": ["knowledge-methods"],
                    "top_k": 3,
                },
            },
            {
                "step_id": "inspect-evidence",
                "depends_on": ["find-methods"],
                "purpose": "Inspect the bound evidence and provenance.",
                "tool_name": "evidence.inspect",
                "arguments": {
                    "evidence_ids": ["evidence-1", "evidence-2"],
                    "include_provenance": True,
                },
            },
            {
                "step_id": "compare-runs",
                "depends_on": ["inspect-evidence"],
                "purpose": "Compare only the registered runs and metrics.",
                "tool_name": "registered-run.compare",
                "arguments": {
                    "run_ids": ["run-base", "run-candidate"],
                    "metric_names": ["accuracy"],
                },
            },
        ],
        "rationale": "Read-only inspection can reduce uncertainty before any new action.",
        "confidence": 0.82,
    }


def _review_payload() -> dict[str, object]:
    return {
        "concerns": [
            {
                "concern_id": "concern-1",
                "category": "clarity",
                "severity": "medium",
                "target_claim_ids": [],
                "target_section": None,
                "text": "Clarify the comparison protocol.",
                "requires_new_evidence": False,
                "requires_new_experiment": False,
                "required_evidence_types": [],
                "proposed_action_type": "CLARIFY_EXISTING_TEXT",
            }
        ],
        "summary": "One clarity concern.",
        "confidence": 0.8,
    }


def _repair_input(payload: object | None = None) -> StructuredRepairInput:
    invalid = payload if payload is not None else {"summary": "missing concerns"}
    return StructuredRepairInput(
        target_node_name="review-semantic",
        target_schema_sha256=output_schema_sha256(ReviewSemanticOutput),
        invalid_payload=invalid,
        invalid_payload_sha256=hashlib.sha256(canonical_json(invalid)).hexdigest(),
        validation_issues=[{"location": "concerns", "error_type": "missing"}],
    )


def test_controlled_profile_is_content_addressed_and_cannot_grant_side_effects() -> None:
    profile = _controlled_profile()

    assert profile.fingerprint == _controlled_profile().fingerprint
    assert profile.fingerprint != _controlled_profile(max_plan_steps=3).fingerprint
    assert profile.execution_authorized is False
    assert profile.authority.direct_execution is False

    values = profile.model_dump(mode="python", exclude={"fingerprint"})
    values["authority"]["network_access"] = True
    with pytest.raises(ValidationError):
        ControlledToolProfile.model_validate(values)


def test_tool_plan_node_returns_only_typed_non_executable_steps() -> None:
    node_input = _input()
    result = ToolPlanNode().run(
        node_input,
        context=_context(),
        backend=_backend("tool-plan-1", _plan_payload(node_input.tool_profile)),
        policy=_policy("tool-plan", tools=node_input.tool_profile.allowed_tool_names),
        request_id="tool-plan-1",
    )

    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert [step.tool_name for step in result.proposal.steps] == [
        "knowledge.query",
        "evidence.inspect",
        "registered-run.compare",
    ]
    assert all(step.executable is False for step in result.proposal.steps)
    assert result.executable is False


def test_tool_plan_scope_and_policy_drift_fail_before_backend_access() -> None:
    escaped = _controlled_profile(
        permissions=[
            EvidenceInspectPermission(
                allowed_evidence_ids=("evidence-1", "evidence-outside"),
                max_evidence_items=2,
            )
        ]
    )
    node_input = _input(escaped)
    candidate_backend = _backend("escaped", _plan_payload(escaped))
    with pytest.raises(NodePolicyViolationError, match="evidence scope"):
        ToolPlanNode().run(
            node_input,
            context=_context(),
            backend=candidate_backend,
            policy=_policy("tool-plan", tools=escaped.allowed_tool_names),
            request_id="escaped",
        )
    assert candidate_backend.calls == []

    valid = _input()
    candidate_backend = _backend("drift", _plan_payload(valid.tool_profile))
    with pytest.raises(NodePolicyViolationError, match="allowlists differ"):
        ToolPlanNode().run(
            valid,
            context=_context(),
            backend=candidate_backend,
            policy=_policy("tool-plan", tools=("knowledge.query",)),
            request_id="drift",
        )
    assert candidate_backend.calls == []


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda payload: payload["steps"][0]["arguments"].update(top_k=6),
            "retrieval limit",
        ),
        (
            lambda payload: payload["steps"][1].update(depends_on=["future-step"]),
            "unknown or forward dependency",
        ),
        (
            lambda payload: payload["steps"][2]["arguments"].update(
                run_ids=["run-base", "run-outside"]
            ),
            "allowed run scope",
        ),
    ],
)
def test_tool_plan_dynamic_limits_and_dependencies_reject_untrusted_proposal(
    mutate,
    reason: str,
) -> None:
    node_input = _input()
    payload = _plan_payload(node_input.tool_profile)
    mutate(payload)
    result = ToolPlanNode().run(
        node_input,
        context=_context(),
        backend=_backend("tool-plan-reject", payload),
        policy=_policy("tool-plan", tools=node_input.tool_profile.allowed_tool_names),
        request_id="tool-plan-reject",
    )

    assert result.status is NodeResultStatus.REJECTED
    assert result.proposal is None
    assert result.untrusted_proposal is not None
    assert any(reason in item for item in result.rejection_reasons)


def test_unknown_tool_and_provider_native_tool_call_fail_closed() -> None:
    node_input = _input()
    payload = _plan_payload(node_input.tool_profile)
    payload["steps"][0]["tool_name"] = "shell"
    unknown = ToolPlanNode().run(
        node_input,
        context=_context(),
        backend=_backend("unknown-tool", payload),
        policy=_policy("tool-plan", tools=node_input.tool_profile.allowed_tool_names),
        request_id="unknown-tool",
    )
    assert unknown.status is NodeResultStatus.REJECTED
    assert any("output schema violation" in item for item in unknown.rejection_reasons)

    native = ToolPlanNode().run(
        node_input,
        context=_context(),
        backend=_backend(
            "native-tool",
            _plan_payload(node_input.tool_profile),
            tool_calls=[
                ToolCallProposal(
                    name="knowledge.query",
                    arguments={"query": "bypass typed plan"},
                )
            ],
        ),
        policy=_policy("tool-plan", tools=node_input.tool_profile.allowed_tool_names),
        request_id="native-tool",
    )
    assert native.status is NodeResultStatus.REJECTED
    assert any("cannot substitute" in item for item in native.rejection_reasons)


def test_malformed_arguments_cycle_and_response_budget_fail_closed() -> None:
    node_input = _input()
    malformed = _plan_payload(node_input.tool_profile)
    malformed["steps"][0]["arguments"]["top_k"] = "3"
    malformed_result = ToolPlanNode().run(
        node_input,
        context=_context(),
        backend=_backend("malformed", malformed),
        policy=_policy("tool-plan", tools=node_input.tool_profile.allowed_tool_names),
        request_id="malformed",
    )
    assert malformed_result.status is NodeResultStatus.REJECTED
    assert any("output schema violation" in item for item in malformed_result.rejection_reasons)

    cyclic = _plan_payload(node_input.tool_profile)
    cyclic["steps"][0]["depends_on"] = ["inspect-evidence"]
    cyclic["steps"][1]["depends_on"] = ["find-methods"]
    cyclic_result = ToolPlanNode().run(
        node_input,
        context=_context(),
        backend=_backend("cyclic", cyclic),
        policy=_policy("tool-plan", tools=node_input.tool_profile.allowed_tool_names),
        request_id="cyclic",
    )
    assert cyclic_result.status is NodeResultStatus.REJECTED
    assert any("forward dependency" in item for item in cyclic_result.rejection_reasons)

    budget_result = ToolPlanNode().run(
        node_input,
        context=_context(),
        backend=_backend(
            "over-budget",
            _plan_payload(node_input.tool_profile),
            usage=Usage(input_tokens=20, output_tokens=201, cost_usd=0),
        ),
        policy=_policy("tool-plan", tools=node_input.tool_profile.allowed_tool_names),
        request_id="over-budget",
    )
    assert budget_result.status is NodeResultStatus.REJECTED
    assert "output token budget exceeded" in budget_result.rejection_reasons


def test_structured_repair_is_schema_checked_but_never_target_acceptance() -> None:
    node_input = _repair_input()
    payload = {
        "target_node_name": node_input.target_node_name,
        "target_schema_sha256": node_input.target_schema_sha256,
        "repaired_payload": _review_payload(),
        "change_summary": ["Added the required typed concern list."],
        "confidence": 0.75,
    }
    result = StructuredRepairNode().run(
        node_input,
        context=_context(),
        backend=_backend("repair-1", payload),
        policy=_policy("structured-repair"),
        request_id="repair-1",
    )

    assert result.status is NodeResultStatus.ACCEPTED
    assert result.proposal is not None
    assert result.proposal.repair_proposal_only is True
    assert result.proposal.executable is False
    assert isinstance(result.proposal.repaired_payload, dict)
    assert not isinstance(result.proposal, ReviewSemanticOutput)


def test_repair_target_hash_mismatch_blocks_call_and_invalid_repair_is_rejected() -> None:
    valid = _repair_input()
    drifted = valid.model_copy(update={"target_schema_sha256": "0" * 64})
    candidate_backend = _backend("repair-drift", {})
    with pytest.raises(NodePolicyViolationError, match="schema fingerprint"):
        StructuredRepairNode().run(
            drifted,
            context=_context(),
            backend=candidate_backend,
            policy=_policy("structured-repair"),
            request_id="repair-drift",
        )
    assert candidate_backend.calls == []

    invalid_result = StructuredRepairNode().run(
        valid,
        context=_context(),
        backend=_backend(
            "repair-invalid",
            {
                "target_node_name": valid.target_node_name,
                "target_schema_sha256": valid.target_schema_sha256,
                "repaired_payload": {"summary": "still missing concerns"},
                "change_summary": ["Changed only the summary."],
                "confidence": 0.2,
            },
        ),
        policy=_policy("structured-repair"),
        request_id="repair-invalid",
    )
    assert invalid_result.status is NodeResultStatus.REJECTED
    assert invalid_result.proposal is None
    assert any("violates target schema" in item for item in invalid_result.rejection_reasons)


def test_repair_cannot_change_target_identity_or_use_provider_tool_calls() -> None:
    node_input = _repair_input()
    payload = {
        "target_node_name": "interpretation-threat",
        "target_schema_sha256": "1" * 64,
        "repaired_payload": _review_payload(),
        "change_summary": ["Changed the target identity."],
        "confidence": 0.3,
    }
    changed_target = StructuredRepairNode().run(
        node_input,
        context=_context(),
        backend=_backend("repair-target-change", payload),
        policy=_policy("structured-repair"),
        request_id="repair-target-change",
    )
    assert changed_target.status is NodeResultStatus.REJECTED
    assert any("different target node" in item for item in changed_target.rejection_reasons)
    assert any("different target schema" in item for item in changed_target.rejection_reasons)

    payload.update(
        target_node_name=node_input.target_node_name,
        target_schema_sha256=node_input.target_schema_sha256,
    )
    native_call = StructuredRepairNode().run(
        node_input,
        context=_context(),
        backend=_backend(
            "repair-native-tool",
            payload,
            tool_calls=[ToolCallProposal(name="shell", arguments={"command": "run"})],
        ),
        policy=_policy("structured-repair"),
        request_id="repair-native-tool",
    )
    assert native_call.status is NodeResultStatus.REJECTED
    assert any("cannot contain" in item for item in native_call.rejection_reasons)


def test_repair_input_is_hash_bound_bounded_and_diagnostics_are_sanitized() -> None:
    values = _repair_input().model_dump(mode="python")
    values["invalid_payload_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="invalid_payload_sha256"):
        StructuredRepairInput.model_validate(values)

    values = _repair_input().model_dump(mode="python")
    values["validation_issues"] = [
        {"location": "payload", "error_type": "contains secret value: abc"}
    ]
    with pytest.raises(ValidationError):
        StructuredRepairInput.model_validate(values)

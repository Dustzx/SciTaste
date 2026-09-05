from __future__ import annotations

import socket
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.model_nodes import (
    ImmutableStateProjection,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
    ModelNodeProfile,
    ModelNodeRuntime,
    ModelNodeTrigger,
    NodePolicy,
    RuntimeBackendMode,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    load_model_node_profile_set,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime
from scitaste.schema.actions import MetaAction

ROOT = Path(__file__).resolve().parents[2]


def _profile() -> ModelNodeProfile:
    return load_model_node_profile_set(
        ROOT / "configs/model_nodes/runtime_profiles.example.yaml"
    ).profiles["short-structured-semantic"]


def _policy(profile: ModelNodeProfile) -> NodePolicy:
    return NodePolicy(
        policy_id="facade-review-policy",
        enabled=True,
        allowed_node_names=["review-semantic"],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_action_types=[MetaAction.ADD_BASELINE],
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )


def test_facade_returns_typed_advice_without_mutating_state_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = ProjectRuntime(tmp_path / "outputs")
    project.create(
        ProjectManifest(
            project_id="facade-project",
            title="Facade project",
            research_direction="Test immutable model-node integration.",
            status="active",
        )
    )
    snapshot = project.begin_run(
        "facade-project",
        ProjectRun(
            run_id="normal-run",
            provider="workflow",
            model="deterministic-controller",
            condition="normal-runtime",
            seed=0,
            status="running",
            evidence_scope="model-node-runtime-test",
        ),
        expected_revision=0,
    )
    profile = _profile()
    state = ImmutableStateProjection(
        project_id="facade-project",
        state_snapshot_id="immutable-state-1",
        state_revision=4,
        stage="COMMUNICATION",
        claim_ids=("claim-1",),
        section_ids=("method",),
    )
    before = state.model_dump_json()
    request = ModelNodeFacadeRequest(
        project_id="facade-project",
        run_id="normal-run",
        invocation_id="review-1",
        expected_project_revision=snapshot.revision,
        node_name="review-semantic",
        node_input={
            "review_text": "Add a matched baseline.",
            "permitted_evidence_types": ["matched baseline"],
        },
        state_projection=state,
        trigger=ModelNodeTrigger(trigger_id="review-arrived", reason="New review received."),
        profile=profile,
        policy=_policy(profile),
        backend_mode=RuntimeBackendMode.SCRIPTED,
    )
    backend = ScriptedStructuredBackend(
        name=profile.provider,
        model=profile.model,
        replies={
            "review-1": ScriptedStructuredReply(
                output_payload={
                    "concerns": [
                        {
                            "concern_id": "concern-1",
                            "category": "missing_baseline",
                            "severity": "high",
                            "target_claim_ids": ["claim-1"],
                            "target_section": "method",
                            "text": "A matched baseline is missing.",
                            "requires_new_evidence": True,
                            "requires_new_experiment": True,
                            "required_evidence_types": ["matched baseline"],
                            "proposed_action_type": "ADD_BASELINE",
                        }
                    ],
                    "summary": "One bounded concern.",
                    "confidence": 0.9,
                },
                usage=Usage(input_tokens=8, output_tokens=6, cost_usd=0.01),
            )
        },
    )

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("scripted model-node execution attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)

    result = ModelNodeFacade(ModelNodeRuntime(project)).execute(request, backend=backend)

    assert result.result is not None
    assert result.result.proposal is not None
    assert result.result.proposal.concerns[0].concern_id == "concern-1"
    assert result.advisory_only is True
    assert result.executable is False
    assert state.model_dump_json() == before
    assert project.open("facade-project").revision == snapshot.revision

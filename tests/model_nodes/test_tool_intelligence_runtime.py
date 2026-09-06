from __future__ import annotations

import hashlib
import socket
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.model_nodes import (
    ControlledToolProfile,
    CumulativeProjectBudget,
    EvidenceInspectPermission,
    ImmutableStateProjection,
    KnowledgeQueryPermission,
    ModelNodeFacade,
    ModelNodeFacadeRequest,
    ModelNodeProfile,
    ModelNodeRuntime,
    ModelNodeRuntimeError,
    ModelNodeTrigger,
    NodeAdmissionBudget,
    NodePolicy,
    ProviderGenerationEnvelope,
    RegisteredRunComparePermission,
    ReviewSemanticOutput,
    RuntimeBackendMode,
    RuntimeOutcome,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    StructuredRepairInput,
    ToolPlanInput,
    ToolScopeProjection,
    canonical_json,
    load_model_node_profile_set,
    output_schema_sha256,
)
from scitaste.project import ProjectManifest, ProjectRun, ProjectRuntime

PROJECT_ID = "tool-runtime-project"
RUN_ID = "controlled-tools-run"
CONFIG_ROOT = Path(__file__).resolve().parents[2] / "configs" / "model_nodes"


def _controlled_profile(*, max_plan_steps: int = 4) -> ControlledToolProfile:
    return ControlledToolProfile(
        profile_id="readonly-project-analysis",
        profile_version="1.0.0",
        permissions=(
            KnowledgeQueryPermission(
                allowed_library_ids=("knowledge-main",),
                max_library_ids=1,
                max_query_chars=160,
                max_top_k=5,
            ),
            EvidenceInspectPermission(
                allowed_evidence_ids=("evidence-1",),
                max_evidence_items=1,
            ),
            RegisteredRunComparePermission(
                allowed_run_ids=("run-a", "run-b"),
                allowed_metric_names=("accuracy",),
                max_runs=2,
                max_metrics=1,
            ),
        ),
        max_plan_steps=max_plan_steps,
        max_dependency_edges=3,
    )


def _model_profile(node_name: str, *, tools: tuple[str, ...] = ()) -> ModelNodeProfile:
    return ModelNodeProfile(
        profile_id=f"offline-{node_name}",
        profile_version="1.0.0",
        provider="scripted",
        model="scripted-v1",
        allowed_node_names=(node_name,),
        live_execution_permitted=False,
        generation=ProviderGenerationEnvelope(
            max_request_bytes=100_000,
            max_output_tokens=1_024,
            context_window_tokens=32_768,
            deterministic_seed_supported=True,
        ),
        admission=NodeAdmissionBudget(
            max_request_bytes=100_000,
            max_input_tokens=2_000,
            max_output_tokens=512,
            max_total_tokens=2_512,
            max_latency_ms=30_000,
            max_response_cost_usd=0.05,
            allowed_tool_names=list(tools),
            max_tool_call_proposals=0,
        ),
        cumulative_project=CumulativeProjectBudget(
            max_invocations=20,
            max_total_tokens=100_000,
            max_api_cost_usd=1,
        ),
    )


def _policy(profile: ModelNodeProfile) -> NodePolicy:
    return NodePolicy(
        policy_id=f"policy-{profile.profile_id}",
        enabled=True,
        allowed_node_names=list(profile.allowed_node_names),
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


def _state() -> ImmutableStateProjection:
    return ImmutableStateProjection(
        project_id=PROJECT_ID,
        state_snapshot_id="state-9",
        state_revision=9,
        stage="EVIDENCE",
        evidence_ids=("evidence-1",),
    )


def _tool_input(*, max_plan_steps: int = 4) -> ToolPlanInput:
    return ToolPlanInput(
        objective="Inspect project-owned evidence before selecting another action.",
        scope=ToolScopeProjection(
            project_id=PROJECT_ID,
            state_snapshot_id="state-9",
            library_ids=("knowledge-main",),
            evidence_ids=("evidence-1",),
            run_ids=("run-a", "run-b"),
            metric_names=("accuracy",),
        ),
        tool_profile=_controlled_profile(max_plan_steps=max_plan_steps),
    )


def _tool_payload(node_input: ToolPlanInput) -> dict[str, object]:
    return {
        "tool_profile_id": node_input.tool_profile.profile_id,
        "tool_profile_fingerprint": node_input.tool_profile.fingerprint,
        "steps": [
            {
                "step_id": "inspect",
                "depends_on": [],
                "purpose": "Read the registered evidence and its provenance.",
                "tool_name": "evidence.inspect",
                "arguments": {
                    "evidence_ids": ["evidence-1"],
                    "include_provenance": True,
                },
            }
        ],
        "rationale": "One bounded read-only inspection is sufficient.",
        "confidence": 0.9,
    }


def _review_payload() -> dict[str, object]:
    return {
        "concerns": [
            {
                "concern_id": "concern-1",
                "category": "clarity",
                "severity": "low",
                "target_claim_ids": [],
                "target_section": None,
                "text": "Clarify the registered comparison.",
                "requires_new_evidence": False,
                "requires_new_experiment": False,
                "required_evidence_types": [],
                "proposed_action_type": "CLARIFY_EXISTING_TEXT",
            }
        ],
        "summary": "One clarity concern.",
        "confidence": 0.7,
    }


def _repair_input() -> StructuredRepairInput:
    invalid = {"summary": "missing concerns"}
    return StructuredRepairInput(
        target_node_name="review-semantic",
        target_schema_sha256=output_schema_sha256(ReviewSemanticOutput),
        invalid_payload=invalid,
        invalid_payload_sha256=hashlib.sha256(canonical_json(invalid)).hexdigest(),
        validation_issues=({"location": "concerns", "error_type": "missing"},),
    )


def _repair_payload(node_input: StructuredRepairInput) -> dict[str, object]:
    return {
        "target_node_name": node_input.target_node_name,
        "target_schema_sha256": node_input.target_schema_sha256,
        "repaired_payload": _review_payload(),
        "change_summary": ["Added the required concern list."],
        "confidence": 0.8,
    }


def _project(tmp_path: Path) -> tuple[ProjectRuntime, int]:
    project = ProjectRuntime(tmp_path / "outputs")
    project.create(
        ProjectManifest(
            project_id=PROJECT_ID,
            title="Tool Intelligence runtime",
            research_direction="Test controlled semantic tool proposals.",
            status="active",
        )
    )
    revision = 0
    for run_id in ("run-a", "run-b", RUN_ID):
        snapshot = project.begin_run(
            PROJECT_ID,
            ProjectRun(
                run_id=run_id,
                provider="workflow",
                model="deterministic-controller",
                condition="tool-intelligence-scripted",
                seed=0,
                status="running",
                evidence_scope="controlled-semantic-tools",
            ),
            expected_revision=revision,
        )
        revision = snapshot.revision
    return project, snapshot.revision


def _request(
    *,
    node_name: str,
    node_input: ToolPlanInput | StructuredRepairInput,
    profile: ModelNodeProfile,
    invocation_id: str,
    request_id: str,
    revision: int,
) -> ModelNodeFacadeRequest:
    return ModelNodeFacadeRequest(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        invocation_id=invocation_id,
        request_id=request_id,
        expected_project_revision=revision,
        node_name=node_name,
        node_input=node_input.model_dump(mode="json"),
        state_projection=_state(),
        trigger=ModelNodeTrigger(
            trigger_id=f"trigger-{node_name}",
            reason="A deterministic controller requested bounded semantic advice.",
        ),
        profile=profile,
        policy=_policy(profile),
        backend_mode=RuntimeBackendMode.SCRIPTED,
        seed=11,
    )


def _backend(request_id: str, payload: object) -> ScriptedStructuredBackend:
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            request_id: ScriptedStructuredReply(
                output_payload=payload,
                usage=Usage(input_tokens=12, output_tokens=8, cost_usd=0),
                latency_ms=1,
            )
        },
    )


def test_committed_tool_intelligence_profiles_are_content_addressed_and_offline() -> None:
    loaded = load_model_node_profile_set(CONFIG_ROOT / "tool_intelligence_profiles.example.yaml")

    assert loaded.profile_set.live_enabled is False
    assert set(loaded.profiles) == {
        "controlled-tool-plan",
        "structured-response-repair",
    }
    assert loaded.profiles["controlled-tool-plan"].live_execution_permitted is False
    assert loaded.profiles["controlled-tool-plan"].admission.max_tool_call_proposals == 0
    assert loaded.profiles["structured-response-repair"].admission.allowed_tool_names == []


@pytest.mark.parametrize("node_name", ["tool-plan", "structured-repair"])
def test_new_nodes_plan_execute_resume_verify_and_exactly_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    node_name: str,
) -> None:
    project, revision = _project(tmp_path)
    if node_name == "tool-plan":
        node_input = _tool_input()
        tools = node_input.tool_profile.allowed_tool_names
        payload = _tool_payload(node_input)
    else:
        node_input = _repair_input()
        tools = ()
        payload = _repair_payload(node_input)
    profile = _model_profile(node_name, tools=tools)
    request = _request(
        node_name=node_name,
        node_input=node_input,
        profile=profile,
        invocation_id=f"{node_name}-source",
        request_id=f"{node_name}-stable-request",
        revision=revision,
    )
    facade = ModelNodeFacade(ModelNodeRuntime(project))
    plan = facade.plan(request)
    assert plan.receipt.outcome is RuntimeOutcome.PLANNED
    assert plan.result is None

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("scripted Tool Intelligence execution attempted network access")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    source = facade.execute(
        request,
        backend=_backend(request.request_id or request.invocation_id, payload),
    )
    assert source.receipt.outcome is RuntimeOutcome.ACCEPTED
    assert source.result is not None
    assert source.result.advisory_only is True
    assert source.result.executable is False

    restarted = ModelNodeFacade(ModelNodeRuntime(ProjectRuntime(project.outputs_root)))
    resumed = restarted.execute(request, backend=None, resume=True)
    assert resumed.receipt.entry_sha256 == source.receipt.entry_sha256

    replay_request = request.model_copy(
        update={
            "invocation_id": f"{node_name}-replay",
            "backend_mode": RuntimeBackendMode.REPLAY,
        }
    )
    replayed = restarted.replay(
        replay_request,
        source_invocation_id=request.invocation_id,
    )
    assert replayed.receipt.outcome is RuntimeOutcome.ACCEPTED
    assert replayed.result is not None
    assert replayed.result.proposal == source.result.proposal
    assert replayed.receipt.telemetry.cached is True
    assert replayed.receipt.telemetry.replayed is True
    assert replayed.receipt.totals.total_tokens == source.receipt.totals.total_tokens
    assert replayed.receipt.totals.cost_usd == source.receipt.totals.cost_usd
    verification = restarted.verify(project_id=PROJECT_ID, run_id=RUN_ID)
    assert verification.totals.entry_count == 2
    assert verification.pending_count == 0
    assert project.open(PROJECT_ID).revision == revision


def test_exact_replay_rejects_changed_controlled_profile_without_fallback(
    tmp_path: Path,
) -> None:
    project, revision = _project(tmp_path)
    original_input = _tool_input()
    tools = original_input.tool_profile.allowed_tool_names
    profile = _model_profile("tool-plan", tools=tools)
    source_request = _request(
        node_name="tool-plan",
        node_input=original_input,
        profile=profile,
        invocation_id="profile-source",
        request_id="stable-tool-request",
        revision=revision,
    )
    facade = ModelNodeFacade(ModelNodeRuntime(project))
    source = facade.execute(
        source_request,
        backend=_backend("stable-tool-request", _tool_payload(original_input)),
    )
    assert source.receipt.outcome is RuntimeOutcome.ACCEPTED

    changed = _tool_input(max_plan_steps=3)
    replay_request = _request(
        node_name="tool-plan",
        node_input=changed,
        profile=profile,
        invocation_id="profile-drift-replay",
        request_id="stable-tool-request",
        revision=revision,
    ).model_copy(update={"backend_mode": RuntimeBackendMode.REPLAY})
    missed = facade.replay(
        replay_request,
        source_invocation_id=source_request.invocation_id,
    )

    assert missed.receipt.outcome is RuntimeOutcome.FAILED
    assert missed.result is None
    assert missed.receipt.telemetry.total_tokens == 0
    assert missed.receipt.totals.total_tokens == source.receipt.totals.total_tokens
    assert missed.receipt.recording_locator is None


def test_unregistered_run_scope_fails_before_planning_or_backend_access(
    tmp_path: Path,
) -> None:
    project, revision = _project(tmp_path)
    node_input = _tool_input()
    escaped_scope = node_input.scope.model_copy(
        update={"run_ids": ("run-a", "run-b", "run-outside")}
    )
    escaped = ToolPlanInput(
        objective=node_input.objective,
        scope=escaped_scope,
        tool_profile=node_input.tool_profile,
    )
    profile = _model_profile(
        "tool-plan",
        tools=escaped.tool_profile.allowed_tool_names,
    )
    request = _request(
        node_name="tool-plan",
        node_input=escaped,
        profile=profile,
        invocation_id="unregistered-run",
        request_id="unregistered-run",
        revision=revision,
    )
    candidate_backend = _backend("unregistered-run", _tool_payload(escaped))

    with pytest.raises(ModelNodeRuntimeError, match="not registered"):
        ModelNodeFacade(ModelNodeRuntime(project)).plan(
            request,
            backend=candidate_backend,
        )

    assert candidate_backend.calls == []
    assert not (
        project.outputs_root / "projects" / PROJECT_ID / "runs" / RUN_ID / "model_nodes"
    ).exists()

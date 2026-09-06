from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.discovery import DiscoveryCommand, ProjectDiscoveryWorkflow, load_discovery_scenario
from scitaste.discovery.semantic import (
    DISCOVERY_HYPOTHESIS_NODE,
    DiscoverySemanticBinding,
    discovery_node_types,
)
from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.mock import MockExecutor
from scitaste.model_nodes import (
    NodePolicy,
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
    load_model_node_profile_set,
)
from scitaste.model_nodes.runtime import ModelNodeRuntime, RuntimeBackendMode, RuntimeOutcome
from scitaste.project import ProjectManifest, ProjectRuntime
from scitaste.schema.actions import MetaAction

SCENARIO_PATH = Path("configs/experiments/discovery_weak.yaml")
PROFILE_SET = Path("configs/model_nodes/runtime_profiles.example.yaml")
PROJECT_ID = "discovery-weak-intuition"
RUN_ID = "semantic-discovery-01"


def _scenario():
    scenario = load_discovery_scenario(SCENARIO_PATH)
    budget = scenario.resource_budget.model_copy(update={"max_api_cost_usd": 0.05})
    return scenario.model_copy(update={"resource_budget": budget})


def _project(outputs: Path) -> ProjectRuntime:
    scenario = _scenario()
    runtime = ProjectRuntime(outputs)
    runtime.create(
        ProjectManifest(
            project_id=PROJECT_ID,
            title="Semantic discovery",
            research_direction=scenario.research_direction,
            target_domain=scenario.target_domain,
            target_venue=scenario.target_venue,
            status="active",
        )
    )
    return runtime


def _proposal(*, source_id: str = "project-spec-6.1") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "intuition": {
            "statement": "Conflict structure may be more diagnostic than model scale.",
            "supporting_source_ids": [source_id],
            "confidence": 0.62,
        },
        "hypothesis": {
            "statement": "Matched evidence conflicts predict decision instability.",
            "falsifiable_predictions": [
                "Instability rises in conflict-matched cases while model scale is held fixed."
            ],
            "proposed_probe_types": ["ablation"],
            "confidence": 0.58,
        },
        "alternative_explanations": ["Prompt sensitivity explains the same concentration."],
        "uncertainty": "The registered findings do not yet establish external validity.",
    }


def _binding(backend: ScriptedStructuredBackend) -> DiscoverySemanticBinding:
    base = load_model_node_profile_set(PROFILE_SET).profiles["short-structured-semantic"]
    profile = base.model_copy(
        update={
            "profile_id": "discovery-hypothesis-test",
            "allowed_node_names": (DISCOVERY_HYPOTHESIS_NODE,),
        }
    )
    policy = NodePolicy(
        policy_id="discovery-hypothesis-test",
        enabled=True,
        allowed_node_names=[DISCOVERY_HYPOTHESIS_NODE],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_tool_names=[],
        allowed_action_types=[],
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    return DiscoverySemanticBinding(
        backend=backend,
        profile=profile,
        policy=policy,
        backend_mode=RuntimeBackendMode.SCRIPTED,
    )


def _backend(*, source_id: str = "project-spec-6.1") -> ScriptedStructuredBackend:
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "discovery-hypothesis-001": ScriptedStructuredReply(
                output_payload=_proposal(source_id=source_id),
                usage=Usage(input_tokens=31, output_tokens=23, cost_usd=0.01),
                latency_ms=3,
            )
        },
    )


def _advance(
    workflow: ProjectDiscoveryWorkflow,
    revision: int,
    binding: DiscoverySemanticBinding,
    *,
    resume: bool = False,
):
    return workflow.advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.HYPOTHESIZE,
        expected_revision=revision,
        resume=resume,
        semantic=binding,
    )


def test_semantic_hypothesis_is_project_owned_advice_not_execution_authority(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    project = _project(outputs)
    backend = _backend()
    binding = _binding(backend)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)

    preview = workflow.preview(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.HYPOTHESIZE,
        expected_revision=0,
        semantic=binding,
    )
    assert preview.semantic_generation is True
    assert project.open(PROJECT_ID).revision == 0
    assert backend.calls == []

    report = _advance(workflow, 0, binding)
    assert report.project_revision == 3
    assert report.verification.semantic_proposal_count == 1
    assert report.command_report.details["content_origin"] == "bounded-semantic-proposal"
    assert report.command_report.semantic_proposal is not None
    assert report.command_report.semantic_proposal.advisory_only is True
    assert report.command_report.semantic_proposal.executable is False
    assert len(backend.calls) == 1

    state_path = (
        outputs
        / "projects"
        / PROJECT_ID
        / "runs"
        / RUN_ID
        / "discovery"
        / "steps"
        / "001-hypothesize"
        / "research_state.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["research_intuitions"][0]["statement"].startswith("Conflict structure")
    assert state["working_hypotheses"][0]["statement"].startswith("Matched evidence")
    assert state["resource_usage"]["api_cost_usd"] == pytest.approx(0.01)
    assert [item["selected_action"]["type"] for item in state["decision_history"]] == [
        "SEARCH",
        "FORM_INTUITION",
        "FORM_WORKING_HYPOTHESIS",
    ]

    ledger = ModelNodeRuntime(
        project,
        node_types=discovery_node_types(),
    ).entry(project_id=PROJECT_ID, run_id=RUN_ID, invocation_id="discovery-hypothesis-001")
    assert ledger.outcome is RuntimeOutcome.ACCEPTED
    assert ledger.intent.policy.allowed_action_types == []
    assert ledger.intent.policy.allowed_tool_names == []

    next_report = workflow.advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.PROBE,
        expected_revision=report.project_revision,
    )
    assert next_report.verification.semantic_proposal_count == 1
    next_state = json.loads(
        (
            outputs
            / "projects"
            / PROJECT_ID
            / "runs"
            / RUN_ID
            / "discovery"
            / "steps"
            / "002-probe"
            / "research_state.json"
        ).read_text(encoding="utf-8")
    )
    assert next_state["executor_context"]["discovery_semantic"] == state[
        "executor_context"
    ]["discovery_semantic"]

    project.update_run(
        PROJECT_ID,
        RUN_ID,
        expected_revision=next_report.project_revision,
        semantic_binding_sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="differs from the runtime intent"):
        workflow.verify(PROJECT_ID, RUN_ID)


def test_unregistered_semantic_source_fails_closed_before_discovery_state(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    project = _project(outputs)
    backend = _backend(source_id="invented-source")
    binding = _binding(backend)

    with pytest.raises(ValueError, match="not accepted"):
        _advance(ProjectDiscoveryWorkflow(outputs, seed=7), 0, binding)

    snapshot = project.open(PROJECT_ID)
    assert snapshot.manifest.runs[0].status == "failed"
    assert not (
        outputs / f"projects/{PROJECT_ID}/runs/{RUN_ID}/discovery/steps/001-hypothesize"
    ).exists()
    entry = ModelNodeRuntime(project, node_types=discovery_node_types()).entry(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        invocation_id="discovery-hypothesis-001",
    )
    assert entry.outcome is RuntimeOutcome.REJECTED


def test_resume_reuses_completed_semantic_entry_without_second_model_call(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    project = _project(outputs)
    first_backend = _backend()

    def fail_search(state, action):
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.FAILED,
            executor="semantic-resume-test",
            error="fail after semantic generation",
        )

    failed_executor = MockExecutor(seed=7, handlers={MetaAction.SEARCH: fail_search})
    with pytest.raises(RuntimeError, match="fail after semantic generation"):
        _advance(
            ProjectDiscoveryWorkflow(outputs, seed=7, executor=failed_executor),
            0,
            _binding(first_backend),
        )
    assert len(first_backend.calls) == 1
    failed_revision = project.open(PROJECT_ID).revision

    recovery_backend = _backend()
    recovered = _advance(
        ProjectDiscoveryWorkflow(outputs, seed=7),
        failed_revision,
        _binding(recovery_backend),
        resume=True,
    )
    assert recovered.verification.semantic_proposal_count == 1
    assert recovery_backend.calls == []
    assert (
        ModelNodeRuntime(project, node_types=discovery_node_types())
        .status(project_id=PROJECT_ID, run_id=RUN_ID)
        .entry_count
        == 1
    )


def test_semantic_cost_ceiling_above_scenario_budget_has_no_side_effect(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    project = _project(outputs)
    scenario = _scenario().model_copy(
        update={
            "resource_budget": _scenario().resource_budget.model_copy(
                update={"max_api_cost_usd": 0.0}
            )
        }
    )
    backend = _backend()
    with pytest.raises(ValueError, match="cost ceiling"):
        ProjectDiscoveryWorkflow(outputs, seed=7).preview(
            scenario,
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            command=DiscoveryCommand.HYPOTHESIZE,
            expected_revision=0,
            semantic=_binding(backend),
        )
    assert project.open(PROJECT_ID).revision == 0
    assert backend.calls == []

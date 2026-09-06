from __future__ import annotations

import json
from pathlib import Path

import pytest

from scitaste.backends.base import Usage
from scitaste.discovery import DiscoveryCommand, ProjectDiscoveryWorkflow, load_discovery_scenario
from scitaste.discovery.semantic import (
    DISCOVERY_HYPOTHESIS_NODE,
    DISCOVERY_IDEATION_NODE,
    DISCOVERY_REFORMULATION_NODE,
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


def _binding(
    backend: ScriptedStructuredBackend,
    *,
    node_name: str = DISCOVERY_HYPOTHESIS_NODE,
) -> DiscoverySemanticBinding:
    base = load_model_node_profile_set(PROFILE_SET).profiles["short-structured-semantic"]
    profile = base.model_copy(
        update={
            "profile_id": f"{node_name}-test",
            "allowed_node_names": (node_name,),
            "admission": base.admission.model_copy(update={"max_response_cost_usd": 0.01}),
            "cumulative_project": base.cumulative_project.model_copy(
                update={"max_api_cost_usd": 0.05}
            ),
        }
    )
    policy = NodePolicy(
        policy_id=f"{node_name}-test",
        enabled=True,
        allowed_node_names=[node_name],
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


def _reformulation_proposal(
    *,
    observation_id: str = "obs-probe-01-working-hypothesis-01",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "hypothesis": {
            "statement": "Evidence-conflict structure, not scale, drives unstable decisions.",
            "falsifiable_predictions": [
                "Instability concentrates at reproducible conflict boundaries under matched scale."
            ],
            "proposed_probe_types": ["ablation"],
            "confidence": 0.67,
        },
        "supporting_observation_ids": [observation_id],
        "retained_constraints": ["Hold model scale and task difficulty fixed."],
        "alternative_explanations": ["Prompt sensitivity may induce the same pattern."],
        "uncertainty": "Only one registered contradiction is currently available.",
    }


def _reformulation_backend(
    *,
    observation_id: str = "obs-probe-01-working-hypothesis-01",
) -> ScriptedStructuredBackend:
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "discovery-reformulation-003": ScriptedStructuredReply(
                output_payload=_reformulation_proposal(observation_id=observation_id),
                usage=Usage(input_tokens=37, output_tokens=29, cost_usd=0.01),
                latency_ms=4,
            )
        },
    )


def _ideation_proposal(
    *,
    active_hypothesis_id: str = "working-hypothesis-02",
    observation_id: str = "obs-probe-02-working-hypothesis-02",
    gpu_hours: float = 0.1,
    experiments: float = 1.0,
    value_key: str = "problem_validity",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "active_hypothesis_id": active_hypothesis_id,
        "supporting_observation_ids": [observation_id],
        "problem": {
            "explanation_gap": (
                "Current aggregate utility cannot represent reproducible conflict boundaries."
            ),
            "importance": (
                "Evidence-bound decisions could reduce wasted experiments and unstable pivots."
            ),
        },
        "idea_seeds": [
            {
                "generator": "semantic-history",
                "hypothesis": (
                    "Typed semantic history improves decisions after contradictory evidence."
                ),
                "proposed_mechanism": (
                    "Bind every proposal to immutable evidence and predecessor state hashes."
                ),
                "expected_validation": [
                    "compare conflict-matched trajectories",
                    "audit semantic lineage",
                ],
                "expected_cost": {
                    "gpu_hours": gpu_hours,
                    "experiments": experiments,
                    "implementation_risk": 0.2,
                },
                "expected_value": {
                    value_key: 0.95,
                    "novelty": 0.9,
                    "feasibility": 0.9,
                },
                "main_risk": "The benefit may depend on synthetic conflict structure.",
            },
            {
                "generator": "evidence-projection",
                "hypothesis": (
                    "Signed evidence projections expose unstable aggregation decisions."
                ),
                "proposed_mechanism": (
                    "Project supporting and contradicting observations into separate features."
                ),
                "expected_validation": [
                    "ablate signed projections",
                    "measure pivot stability",
                ],
                "expected_cost": {
                    "gpu_hours": 0.2,
                    "experiments": 1.0,
                    "implementation_risk": 0.35,
                },
                "expected_value": {
                    "problem_validity": 0.9,
                    "novelty": 0.8,
                    "feasibility": 0.8,
                },
                "main_risk": "Evidence polarity labels may be noisy.",
            },
            {
                "generator": "evaluation-guard",
                "hypothesis": ("A conflict-stratified evaluation catches unsafe research pivots."),
                "proposed_mechanism": (
                    "Gate idea selection on reproducible conflict-specific diagnostics."
                ),
                "expected_validation": [
                    "measure failure predictiveness",
                    "check inter-run agreement",
                ],
                "expected_cost": {
                    "gpu_hours": 0.05,
                    "experiments": 1.0,
                    "implementation_risk": 0.15,
                },
                "expected_value": {
                    "problem_validity": 0.9,
                    "novelty": 0.7,
                    "feasibility": 0.95,
                },
                "main_risk": "A diagnostic contribution may have limited venue fit.",
            },
        ],
        "alternative_problem_formulations": [
            "Treat instability as an evidence-representation failure.",
            "Treat instability as an evaluation blind spot.",
        ],
        "uncertainty": "The registered evidence covers only two bounded probes.",
    }


def _ideation_backend(
    *,
    active_hypothesis_id: str = "working-hypothesis-02",
    observation_id: str = "obs-probe-02-working-hypothesis-02",
    gpu_hours: float = 0.1,
    experiments: float = 1.0,
    value_key: str = "problem_validity",
) -> ScriptedStructuredBackend:
    return ScriptedStructuredBackend(
        name="scripted",
        model="scripted-v1",
        replies={
            "discovery-ideation-005": ScriptedStructuredReply(
                output_payload=_ideation_proposal(
                    active_hypothesis_id=active_hypothesis_id,
                    observation_id=observation_id,
                    gpu_hours=gpu_hours,
                    experiments=experiments,
                    value_key=value_key,
                ),
                usage=Usage(input_tokens=61, output_tokens=89, cost_usd=0.01),
                latency_ms=5,
            )
        },
    )


def _prepare_ideation(workflow: ProjectDiscoveryWorkflow) -> int:
    initial = _advance(workflow, 0, _binding(_backend()))
    first_probe = workflow.advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.PROBE,
        expected_revision=initial.project_revision,
    )
    reformulated = workflow.advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.REFORMULATE,
        expected_revision=first_probe.project_revision,
    )
    second_probe = workflow.advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.PROBE,
        expected_revision=reformulated.project_revision,
    )
    return second_probe.project_revision


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
    assert (
        next_state["executor_context"]["discovery_semantic"]
        == state["executor_context"]["discovery_semantic"]
    )

    project.update_run(
        PROJECT_ID,
        RUN_ID,
        expected_revision=next_report.project_revision,
        semantic_binding_sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="bindings are inconsistent"):
        workflow.verify(PROJECT_ID, RUN_ID)


def test_semantic_reformulation_uses_registered_contradiction_and_extends_history(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    project = _project(outputs)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)
    initial = _advance(workflow, 0, _binding(_backend()))
    probed = workflow.advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.PROBE,
        expected_revision=initial.project_revision,
    )
    backend = _reformulation_backend()
    binding = _binding(backend, node_name=DISCOVERY_REFORMULATION_NODE)

    preview = workflow.preview(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.REFORMULATE,
        expected_revision=probed.project_revision,
        semantic=binding,
    )
    assert preview.semantic_generation is True
    assert backend.calls == []

    report = workflow.advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.REFORMULATE,
        expected_revision=probed.project_revision,
        semantic=binding,
    )
    assert report.verification.semantic_proposal_count == 2
    assert report.command_report.details["content_origin"] == ("bounded-semantic-reformulation")
    assert report.command_report.details["supporting_observation_ids"] == [
        "obs-probe-01-working-hypothesis-01"
    ]
    assert len(backend.calls) == 1

    state = json.loads(
        (
            outputs
            / "projects"
            / PROJECT_ID
            / "runs"
            / RUN_ID
            / "discovery/steps/003-reformulate/research_state.json"
        ).read_text(encoding="utf-8")
    )
    assert state["working_hypotheses"][-1]["statement"].startswith("Evidence-conflict structure")
    assert state["working_hypotheses"][-1]["derived_from_hypothesis_ids"] == [
        "working-hypothesis-01"
    ]
    assert state["resource_usage"]["api_cost_usd"] == pytest.approx(0.02)
    assert [item["node_name"] for item in state["executor_context"]["discovery_semantics"]] == [
        DISCOVERY_HYPOTHESIS_NODE,
        DISCOVERY_REFORMULATION_NODE,
    ]
    assert (
        ModelNodeRuntime(project, node_types=discovery_node_types())
        .status(project_id=PROJECT_ID, run_id=RUN_ID)
        .entry_count
        == 2
    )


def test_semantic_reformulation_rejects_unregistered_observation_before_state(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    project = _project(outputs)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)
    initial = _advance(workflow, 0, _binding(_backend()))
    probed = workflow.advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.PROBE,
        expected_revision=initial.project_revision,
    )
    backend = _reformulation_backend(observation_id="invented-observation")

    with pytest.raises(ValueError, match="not accepted"):
        workflow.advance(
            _scenario(),
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            command=DiscoveryCommand.REFORMULATE,
            expected_revision=probed.project_revision,
            semantic=_binding(backend, node_name=DISCOVERY_REFORMULATION_NODE),
        )

    snapshot = project.open(PROJECT_ID)
    assert snapshot.manifest.runs[0].status == "failed"
    assert not (
        outputs / f"projects/{PROJECT_ID}/runs/{RUN_ID}/discovery/steps/003-reformulate"
    ).exists()
    entry = ModelNodeRuntime(project, node_types=discovery_node_types()).entry(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        invocation_id="discovery-reformulation-003",
    )
    assert entry.outcome is RuntimeOutcome.REJECTED


def test_semantic_reformulation_resume_reuses_ledger_entry(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    project = _project(outputs)

    def fail_reformulation(state, action):
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.FAILED,
            executor="semantic-reformulation-resume-test",
            error="fail after reformulation generation",
        )

    failed_workflow = ProjectDiscoveryWorkflow(
        outputs,
        seed=7,
        executor=MockExecutor(
            seed=7,
            handlers={MetaAction.REFORMULATE_HYPOTHESIS: fail_reformulation},
        ),
    )
    initial = _advance(failed_workflow, 0, _binding(_backend()))
    probed = failed_workflow.advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.PROBE,
        expected_revision=initial.project_revision,
    )
    first_backend = _reformulation_backend()
    with pytest.raises(RuntimeError, match="fail after reformulation generation"):
        failed_workflow.advance(
            _scenario(),
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            command=DiscoveryCommand.REFORMULATE,
            expected_revision=probed.project_revision,
            semantic=_binding(first_backend, node_name=DISCOVERY_REFORMULATION_NODE),
        )
    assert len(first_backend.calls) == 1
    failed_revision = project.open(PROJECT_ID).revision

    recovery_backend = _reformulation_backend()
    recovered = ProjectDiscoveryWorkflow(outputs, seed=7).advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.REFORMULATE,
        expected_revision=failed_revision,
        resume=True,
        semantic=_binding(recovery_backend, node_name=DISCOVERY_REFORMULATION_NODE),
    )
    assert recovered.verification.semantic_proposal_count == 2
    assert recovery_backend.calls == []
    assert (
        ModelNodeRuntime(project, node_types=discovery_node_types())
        .status(project_id=PROJECT_ID, run_id=RUN_ID)
        .entry_count
        == 2
    )


def test_semantic_ideation_binds_problem_and_divergent_ideas_without_selection(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    project = _project(outputs)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)
    revision = _prepare_ideation(workflow)
    backend = _ideation_backend()
    binding = _binding(backend, node_name=DISCOVERY_IDEATION_NODE)

    preview = workflow.preview(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.IDEATE,
        expected_revision=revision,
        semantic=binding,
    )
    assert preview.semantic_generation is True
    assert backend.calls == []
    assert project.open(PROJECT_ID).revision == revision

    report = workflow.advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.IDEATE,
        expected_revision=revision,
        semantic=binding,
    )
    assert report.project_revision == revision + 2
    assert report.verification.semantic_proposal_count == 2
    assert report.command_report.details["content_origin"] == ("bounded-semantic-ideation")
    assert report.command_report.details["active_hypothesis_id"] == ("working-hypothesis-02")
    assert len(backend.calls) == 1

    state = json.loads((outputs / report.verification.latest_state).read_text(encoding="utf-8"))
    assert state["problem_candidates"][0]["explanation_gap"].startswith("Current aggregate utility")
    assert [item["generator"] for item in state["candidate_ideas"]] == [
        "semantic-history",
        "evidence-projection",
        "evaluation-guard",
    ]
    assert state["active_idea_id"] is None
    assert state["resource_usage"]["api_cost_usd"] == pytest.approx(0.02)
    assert [item["node_name"] for item in state["executor_context"]["discovery_semantics"]] == [
        DISCOVERY_HYPOTHESIS_NODE,
        DISCOVERY_IDEATION_NODE,
    ]
    assert [item["selected_action"]["type"] for item in state["decision_history"]][-2:] == [
        "FORMULATE_PROBLEM",
        "IDEATE",
    ]

    selected = workflow.advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.PORTFOLIO_SELECT,
        expected_revision=report.project_revision,
    )
    selected_state = json.loads(
        (outputs / selected.verification.latest_state).read_text(encoding="utf-8")
    )
    assert selected_state["active_idea_id"] == "idea-01-semantic-history"
    assert selected.verification.semantic_proposal_count == 2


@pytest.mark.parametrize(
    ("backend", "message"),
    [
        (_ideation_backend(observation_id="invented-observation"), "not accepted"),
        (_ideation_backend(active_hypothesis_id="working-hypothesis-99"), "not accepted"),
        (_ideation_backend(gpu_hours=3.0), "not accepted"),
        (_ideation_backend(experiments=1.5), "not accepted"),
        (_ideation_backend(value_key="invented_value"), "not accepted"),
    ],
    ids=[
        "unregistered-observation",
        "wrong-hypothesis",
        "over-budget-idea",
        "fractional-experiment-count",
        "unsupported-value-field",
    ],
)
def test_semantic_ideation_rejects_unbound_or_infeasible_content_before_state(
    tmp_path: Path,
    backend: ScriptedStructuredBackend,
    message: str,
) -> None:
    outputs = tmp_path / "outputs"
    project = _project(outputs)
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)
    revision = _prepare_ideation(workflow)

    with pytest.raises(ValueError, match=message):
        workflow.advance(
            _scenario(),
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            command=DiscoveryCommand.IDEATE,
            expected_revision=revision,
            semantic=_binding(backend, node_name=DISCOVERY_IDEATION_NODE),
        )

    assert project.open(PROJECT_ID).manifest.runs[0].status == "failed"
    assert not (
        outputs / f"projects/{PROJECT_ID}/runs/{RUN_ID}/discovery/steps/005-ideate"
    ).exists()
    entry = ModelNodeRuntime(project, node_types=discovery_node_types()).entry(
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        invocation_id="discovery-ideation-005",
    )
    assert entry.outcome is RuntimeOutcome.REJECTED


def test_semantic_ideation_resume_reuses_accepted_proposal(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    project = _project(outputs)

    def fail_problem_formation(state, action):
        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.FAILED,
            executor="semantic-ideation-resume-test",
            error="fail after ideation generation",
        )

    failed_workflow = ProjectDiscoveryWorkflow(
        outputs,
        seed=7,
        executor=MockExecutor(
            seed=7,
            handlers={MetaAction.FORMULATE_PROBLEM: fail_problem_formation},
        ),
    )
    revision = _prepare_ideation(failed_workflow)
    first_backend = _ideation_backend()
    with pytest.raises(RuntimeError, match="fail after ideation generation"):
        failed_workflow.advance(
            _scenario(),
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            command=DiscoveryCommand.IDEATE,
            expected_revision=revision,
            semantic=_binding(first_backend, node_name=DISCOVERY_IDEATION_NODE),
        )
    assert len(first_backend.calls) == 1
    failed_revision = project.open(PROJECT_ID).revision

    recovery_backend = _ideation_backend()
    recovered = ProjectDiscoveryWorkflow(outputs, seed=7).advance(
        _scenario(),
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.IDEATE,
        expected_revision=failed_revision,
        resume=True,
        semantic=_binding(recovery_backend, node_name=DISCOVERY_IDEATION_NODE),
    )
    assert recovered.verification.semantic_proposal_count == 2
    assert recovery_backend.calls == []
    assert (
        ModelNodeRuntime(project, node_types=discovery_node_types())
        .status(project_id=PROJECT_ID, run_id=RUN_ID)
        .entry_count
        == 2
    )


def test_semantic_reformulation_cumulative_ceiling_precedes_reservation(
    tmp_path: Path,
) -> None:
    outputs = tmp_path / "outputs"
    project = _project(outputs)
    budget_scenario = _scenario().model_copy(
        update={
            "resource_budget": _scenario().resource_budget.model_copy(
                update={"max_api_cost_usd": 0.015}
            )
        }
    )
    workflow = ProjectDiscoveryWorkflow(outputs, seed=7)
    initial = workflow.advance(
        budget_scenario,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.HYPOTHESIZE,
        expected_revision=0,
        semantic=_binding(_backend()),
    )
    probed = workflow.advance(
        budget_scenario,
        project_id=PROJECT_ID,
        run_id=RUN_ID,
        command=DiscoveryCommand.PROBE,
        expected_revision=initial.project_revision,
    )
    backend = _reformulation_backend()

    with pytest.raises(ValueError, match="cumulative semantic cost ceiling"):
        workflow.preview(
            budget_scenario,
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            command=DiscoveryCommand.REFORMULATE,
            expected_revision=probed.project_revision,
            semantic=_binding(backend, node_name=DISCOVERY_REFORMULATION_NODE),
        )
    assert project.open(PROJECT_ID).revision == probed.project_revision
    assert backend.calls == []


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

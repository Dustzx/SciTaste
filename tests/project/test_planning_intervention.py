"""One bounded bridge check: intent -> admission -> launch gate -> UI receipt."""

import json
from types import SimpleNamespace

import pytest

from scitaste.evaluation.program_control import ExperimentProgramControl
from scitaste.model_nodes.research_design import (
    PlanningInterventionResponse,
    ResearchDesignInput,
    ResearchDesignNode,
    ResearchDesignProposal,
)
from scitaste.project import planning_intervention as bridge


def control():
    return ExperimentProgramControl.create(
        project_id="project",
        source_publication_id="change-1",
        source_publication_sha256="a" * 64,
        source_dossier_id="program",
        source_dossier_sha256="b" * 64,
        change_kind="clarify_stage_decision",
        target_stage_id="comparison",
        summary="Compare frameworks before ablations",
        rationale="Answer the main scientific question first",
    )


def test_bound_intervention_requires_response_and_blocks_deferred_selection():
    inputs = ResearchDesignInput(
        idea_sha256="c" * 64,
        idea={},
        capabilities={},
        evidence={},
        objective="Plan",
        user_intervention=control(),
    )
    proposal = ResearchDesignProposal.model_construct(
        idea_sha256="c" * 64,
        hypotheses=(),
        comparisons=(),
        studies=(),
        next_study_id="future",
        evidence_ids=(),
    )
    node = ResearchDesignNode()

    def reject(p):
        return node._proposal_rejections(p, input_data=inputs, context=None, policy=None)

    assert "Published intervention requires an exact bound response" in reject(proposal)
    response = PlanningInterventionResponse(
        publication_sha256="a" * 64,
        disposition="deferred",
        explanation="Missing adapter",
    )
    deferred = proposal.model_copy(update={"intervention_response": response})
    assert "Published intervention requires an exact bound response" not in reject(deferred)
    selected = deferred.model_copy(
        update={
            "execution_selection": SimpleNamespace(
                template_id="absent",
                study_id="future",
                lane_id="x",
                task_ids=(),
                comparisons={},
            )
        }
    )
    assert "Deferred/conflicting intervention cannot select execution" in reject(selected)


def test_receipt_projection_and_new_run_boundary(tmp_path, monkeypatch):
    root = tmp_path / "project"
    output = root / "planning"
    output.mkdir(parents=True)
    c = control()
    monkeypatch.setattr(bridge, "current_control", lambda _: c)
    response = PlanningInterventionResponse(
        publication_sha256="a" * 64,
        disposition="addressed",
        explanation="Main comparison precedes the mechanism ablation in this plan",
    )
    design = {"intervention_response": response.model_dump()}
    result = {"status": "accepted", "proposal": design}
    for name, value in {
        "INPUT.json": {"user_intervention": c.model_dump(mode="json")},
        "DESIGN.json": design,
        "RESULT.json": result,
    }.items():
        (output / name).write_text(json.dumps(value))
    bridge.record_response(
        root,
        output,
        c,
        SimpleNamespace(
            status=SimpleNamespace(value="accepted"),
            proposal=SimpleNamespace(intervention_response=response),
        ),
    )
    plan = {
        "research_design": {
            "locator": "planning/DESIGN.json",
            "sha256": bridge.sha(output / "DESIGN.json"),
        }
    }
    bridge.execution_boundary(root, plan)
    run = SimpleNamespace(
        condition="project-research-design-proposal",
        artifact="planning/RESULT.json",
        artifact_sha256=bridge.sha(output / "RESULT.json"),
    )
    runtime = SimpleNamespace(
        projects_root=tmp_path, open=lambda _: SimpleNamespace(manifest=SimpleNamespace(runs=[run]))
    )
    publication = SimpleNamespace(project_id="project", publication_sha256="a" * 64)
    assert bridge.planning_status(runtime, publication) == ("addressed", response.explanation)
    monkeypatch.setattr(
        bridge,
        "current_control",
        lambda _: c.model_copy(update={"source_publication_sha256": "d" * 64}),
    )
    with pytest.raises(ValueError, match="superseded"):
        bridge.execution_boundary(root, plan)
    (output / "INPUT.json").write_text("{}")
    with pytest.raises(ValueError, match="sources changed"):
        bridge.planning_status(runtime, publication)


def test_no_published_change_preserves_legacy_launch(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "current_control", lambda _: None)
    bridge.execution_boundary(tmp_path, {})

import json
from types import SimpleNamespace

import pytest

from scitaste.project import ProjectManifest, ProjectRuntime
from scitaste.project import native_workspace_cycle as cycle


def test_cycle_continues_persisted_execution_after_postprocessing_failure(tmp_path, monkeypatch):
    """A process error after RESULT must neither relaunch training nor skip recovery."""
    runtime = ProjectRuntime(tmp_path)
    runtime.create(
        ProjectManifest(
            project_id="project",
            title="Boundary fixture",
            research_direction="Recover retained work without duplicate execution.",
            status="active",
        )
    )
    project = runtime.projects_root / "project"
    plan = project / "PLAN.json"
    plan.write_text(json.dumps({"executor_id": "scitaste-native-workspace"}))
    output = project / "evaluations/cycle"
    args = SimpleNamespace(
        project=project,
        plan=plan,
        output=output,
        execution_run=None,
        research_state=None,
        report_delivery=None,
        paper_prefix=None,
        brief=None,
        baseline_run=None,
        baseline_source=None,
        task_context=None,
        development_policy_refresh=None,
        development_taste_library=None,
        taste_deliberation_profile=None,
        next_planning_objective=None,
        next_workspace_resources=[],
        workflow_gaps=None,
        max_execution_continuations=1,
        allow_api=True,
        allow_execution=True,
        credentials=None,
        paper_backend=None,
        review_profile=None,
        venue_taste_profile=None,
    )
    monkeypatch.setattr(cycle, "load_native_workspace_plan", lambda *a: {})
    import scitaste.project.bounded_continuation as policy

    monkeypatch.setattr(
        policy,
        "provider_ledger_accounting",
        lambda *a: {
            "unresolved_reservations": 0,
            "liability_usd": 1,
        },
    )
    calls = []

    class ReachedReport(Exception):
        pass

    def run(command, **kwargs):
        calls.append(command)
        if "scitaste.writing.native_lifecycle" in command:
            raise ReachedReport
        destination = project / command[command.index("--output") + 1]
        (destination / "loop").mkdir(parents=True)
        continued = "--continue-from" in command
        contract = {
            "plan_sha256": cycle.sha(plan),
            "controller_owner": "scitaste-native",
            "execution_api_liability_usd": 6.5,
            "max_turns": 5,
            "plan": {"resource_envelope": {"wall_seconds": 300}},
        }
        if continued:
            parent = project / command[command.index("--continue-from") + 1]
            contract["continuation"] = {
                "parent": str(parent),
                "parent_result_sha256": cycle.sha(parent / "RESULT.json"),
            }
        (destination / "CONTRACT.json").write_text(json.dumps(contract))
        (destination / "RESULT.json").write_text(
            json.dumps(
                {
                    "controller_owner": "scitaste-native",
                    "duration_seconds": 2,
                    "status": "controller-finished"
                    if continued
                    else "native-workspace-interrupted",
                    "error_type": "JSONDecodeError",
                    "score": 0,
                }
            )
        )
        (destination / "loop/TRAJECTORY.jsonl").write_text("{}\n")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(cycle.subprocess, "run", run)
    with pytest.raises(ReachedReport):
        cycle.run_cycle(args)
    assert len(calls) == 3  # initial execution, bounded child, report; no duplicate launch
    for stage in ("execution", "continuation-01"):
        receipt = json.loads((output / f"{stage}.retained-boundary.json").read_text())
        assert receipt["returncode"] == 1
        assert receipt["execution_relaunched"] is False
        assert receipt["postprocessing_complete"] is False
    execution = project / "evaluations/cycle-execution"
    with pytest.raises(ValueError, match="another plan"):
        cycle.retained_execution_boundary(execution, plan_sha256="other", taste_binding=None)
    assert (
        cycle.retained_execution_boundary(
            project / "missing", plan_sha256=cycle.sha(plan), taste_binding=None
        )
        is None
    )

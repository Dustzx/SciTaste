import hashlib
import json

import pytest

from scitaste.executor.artifact_handoff import freeze_submission
from scitaste.executor.research_harness import SourceBoundHarnessProfile


def setup(tmp_path):
    from types import SimpleNamespace

    source = b"# source stays exactly the same\nx=1\n"
    manifest = json.dumps({"entrypoint": "predict.py", "files": ["predict.py"]}).encode()
    (tmp_path / "original.py").write_bytes(source)
    (tmp_path / "original.json").write_bytes(manifest)
    env = SimpleNamespace(
        workspace=tmp_path,
        research_harness=SimpleNamespace(
            profile=SourceBoundHarnessProfile(tool_composition="disabled")
        ),
    )
    args = {
        "manifest": {"path": "original.json", "sha256": hashlib.sha256(manifest).hexdigest()},
        "files": {
            "predict.py": {"path": "original.py", "sha256": hashlib.sha256(source).hexdigest()}
        },
        "directory": "submission",
    }
    return env, args, source, manifest


def test_stage_exact_source_before_atomic_ready_and_never_replace(tmp_path):
    env, args, source, manifest = setup(tmp_path)
    receipt = json.loads(freeze_submission(env, args))
    assert receipt["provided_source_bytes_changed"] is False
    assert (tmp_path / "submission/predict.py").read_bytes() == source
    assert (tmp_path / "submission/SUBMISSION.json").read_bytes() == manifest
    assert (tmp_path / "submission/READY").is_file()
    with pytest.raises(ValueError, match="already exists"):
        freeze_submission(env, args)


@pytest.mark.parametrize("change", ["hash", "missing", "protected", "escaping", "symlink"])
def test_invalid_dependencies_cannot_publish_partial_ready(tmp_path, change):
    env, args, _, _ = setup(tmp_path)
    if change == "hash":
        args["files"]["predict.py"]["sha256"] = "0" * 64
    elif change == "missing":
        args["files"]["predict.py"]["path"] = "missing.py"
    elif change == "protected":
        args["directory"] = "data/submission"
    elif change == "escaping":
        args["files"]["predict.py"]["path"] = "../outside.py"
    else:
        (tmp_path / "linked.py").symlink_to(tmp_path / "original.py")
        args["files"]["predict.py"]["path"] = "linked.py"
    with pytest.raises((ValueError, FileNotFoundError)):
        freeze_submission(env, args)
    assert not (tmp_path / "submission").exists()
    assert not list(tmp_path.glob(".source-handoff-*"))


def test_consumed_query_cannot_be_reopened(tmp_path):
    env, args, _, _ = setup(tmp_path)
    (tmp_path / "confirmation_feedback.json").write_text("{}")
    with pytest.raises(ValueError, match="separately allocated"):
        freeze_submission(env, args)


@pytest.mark.parametrize("failure", ["isolation", "budget", None])
def test_observed_handoff_preserves_execution_boundary_and_charges_budget(tmp_path, failure):
    from types import SimpleNamespace

    from scitaste.executor.harness_tools import HarnessToolEnvironment
    from scitaste.executor.research_tool_handler import ResearchToolActionHandler
    from scitaste.research_tool_loop import ResearchToolProposal
    from scitaste.state.research_state import ResearchState

    _, args, _, _ = setup(tmp_path)
    calls = []

    def observe(directory):
        calls.append(directory)
        return {"status": "completed"}

    env = HarnessToolEnvironment(
        workspace=tmp_path,
        log_root=tmp_path / "logs",
        research_problem="Source-bound confirmation",
        tool_map={
            "Read": SimpleNamespace(
                name="Read", description="Read fixture", parameters={"type": "object"}, call=None
            )
        },
        source_binding={},
        wall_seconds=60,
        research_harness_profile=SourceBoundHarnessProfile(tool_composition="disabled"),
        project_id="p",
        execution_authorized=True,
        isolated_code=failure != "isolation",
        handoff_observer=observe,
    )
    proposal = ResearchToolProposal(
        tool="Freeze Submission", arguments=args, rationale="Deliver unchanged scientific sources"
    )
    action = env.research_harness.bind_action(proposal.action(env, 0), proposal.model_dump())
    assert action.expected_cost == {"experiments": 1}
    state = ResearchState(project_id="p", research_direction="Research", target_domain="general")
    state.resource_budget.max_experiments = 0 if failure == "budget" else 1
    handler = ResearchToolActionHandler(project_id="p", environment=env)
    if failure:
        with pytest.raises(ValueError, match="isolated" if failure == "isolation" else "budget"):
            handler(state, action)
        assert not calls
        assert not (tmp_path / "submission").exists()
    else:
        result = handler(state, action)
        assert result.status == "SUCCEEDED"
        assert result.cost["experiments"] == 1
        assert calls == ["submission"]
        assert env.experiments_used == 1

from pathlib import Path
from types import SimpleNamespace

from scitaste.taste import research_tool_capture as capture_module


def test_prospective_capture_retries_a_mixed_project_and_idea_revision(monkeypatch, tmp_path):
    ideas = iter(
        [
            SimpleNamespace(observed_project_revision=10, observed_project_snapshot_sha256="a"),
            SimpleNamespace(observed_project_revision=11, observed_project_snapshot_sha256="b"),
        ]
    )
    snapshot = SimpleNamespace(revision=11, snapshot_sha256="b", manifest=SimpleNamespace(runs=[]))
    runtime = SimpleNamespace(open=lambda _: snapshot, projects_root=tmp_path)
    monkeypatch.setattr(
        capture_module,
        "inspect_current_idea_revision",
        lambda *_: SimpleNamespace(current_binding=next(ideas)),
    )
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(source_project_id="project", source_run_id="run")

    monkeypatch.setattr(capture_module.TasteTrajectorySamplingPlan, "create", create)
    monkeypatch.setattr(capture_module, "save_taste_trajectory_sampling_plan", lambda *_: None)
    capture_module.ResearchToolTasteCapture.prepare(
        runtime=runtime, project_id="project", run_id="run", output=Path(tmp_path / "plan.json")
    )
    assert (
        captured["idea_revision"].observed_project_revision == captured["observed_project_revision"]
    )
    assert captured["observed_project_snapshot_sha256"] == "b"

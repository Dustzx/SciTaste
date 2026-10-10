from pathlib import Path

import pytest

from scitaste.project import ProjectManifest, ProjectRuntime


def test_native_registration_preserves_selected_provider_across_updates(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    from scripts.run_mlrc_native_development_loop import register_progress

    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="provider-fixture",
            title="Provider fixture",
            research_direction="fixture",
            status="active",
            stage_semantics="scitaste-workflow-phases",
        )
    )
    project = runtime.projects_root / "provider-fixture"
    output = project / "evaluations" / "selected-provider-run"
    output.mkdir(parents=True)
    (output / "CONTRACT.json").write_text("{}")
    register_progress(project, output, "running", provider="other-provider", model="bound-model")
    register_progress(project, output, "completed", provider="other-provider", model="bound-model")
    row = runtime.open(project.name).manifest.runs[0]
    assert (row.provider, row.model, row.status) == ("other-provider", "bound-model", "completed")
    with pytest.raises(ValueError, match="cannot switch"):
        register_progress(project, output, "continued", provider="different", model="bound-model")
    assert runtime.open(project.name).manifest.runs[0] == row

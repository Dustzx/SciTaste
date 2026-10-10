"""Terminal maintenance replay keeps original source and successor bindings."""

import hashlib
import json

import pytest

from scitaste.model_nodes.session_exchange import retain_json
from scitaste.project.source_maintenance import run
from scitaste.taste.reference_quality import ReferenceQualityInput


def test_terminal_successor_replay_rejects_changed_bytes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "outputs/projects/project"
    prepared = project / "evaluations/source/prepared"
    base = project / "evaluations/base"
    output = project / "evaluations/maintenance"
    for directory in (prepared, base, output):
        directory.mkdir(parents=True)
    projection = json.dumps(
        {
            "schema_version": "1.0",
            "outcome_information_availability": "withheld",
            "fields": {"evidence": {"semantic_role": "evidence", "value": "observed contrast"}},
        }
    )
    source = ReferenceQualityInput(
        screening_id="screening-one",
        source_id="source-one",
        source_content_sha256="a" * 64,
        decision_stage="EXPERIMENT",
        decision_role="choose a discriminating probe",
        source_projection=projection,
        source_projection_sha256=hashlib.sha256(projection.encode()).hexdigest(),
        outcome_information_availability="withheld",
    )
    retain_json(prepared / "INPUT.json", source.model_dump(mode="json"))
    for path in (
        prepared / "PROFILE.json",
        prepared / "SOURCE_MANIFEST.json",
        base / "MANIFEST.json",
    ):
        retain_json(path, {})
    (base / "TASTE_LIBRARY.jsonl").write_text("retained base")
    successor = output / "successor.jsonl"
    successor.write_text("original successor")
    terminal = {
        "status": "reviewed-successor-prepared",
        "successor": {
            "locator": successor.relative_to(project).as_posix(),
            "sha256": hashlib.sha256(successor.read_bytes()).hexdigest(),
        },
    }
    retain_json(output / "RESULT.json", terminal)
    arguments = dict(
        project=project,
        prepared_source=prepared,
        base_library=base,
        output=output,
        code_root=tmp_path,
    )
    assert run(**arguments) == terminal  # no phase or model execution
    successor.write_text("changed successor")
    with pytest.raises(ValueError, match="binding changed"):
        run(**arguments)

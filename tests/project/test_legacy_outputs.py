from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scitaste.project.legacy_outputs import (
    ARCHIVE_PROJECT_ID,
    discover_legacy_directories,
    fingerprint_tree,
    migrate_legacy_outputs,
    plan_legacy_output_migration,
    verify_legacy_output_archive,
)


def _fixture_outputs(tmp_path: Path) -> Path:
    outputs = tmp_path / "outputs"
    (outputs / "papers").mkdir(parents=True)
    references = outputs / "projects" / "consumer" / "references"
    references.mkdir(parents=True)
    legacy = outputs / "legacy-run"
    (legacy / "nested").mkdir(parents=True)
    (legacy / "nested" / "evidence.json").write_text('{"passed": true}\n')
    (legacy / "notes.md").write_text("# Historical notes\n")
    os.symlink("../../../legacy-run", references / "historical")
    stages = outputs / "projects" / "consumer" / "stages"
    stages.mkdir()
    os.symlink("../references/historical/nested", stages / "indirect")
    return outputs


def test_plan_is_read_only_and_binds_tree_and_reference(tmp_path: Path) -> None:
    outputs = _fixture_outputs(tmp_path)

    plan = plan_legacy_output_migration(outputs)

    assert discover_legacy_directories(outputs) == ("legacy-run",)
    assert len(plan) == 1
    assert plan[0].fingerprint.regular_files == 2
    assert plan[0].fingerprint.symbolic_links == 0
    assert plan[0].reference_rewrites[0].old_target == "../../../legacy-run"
    assert len(plan[0].reference_rewrites) == 1
    assert (outputs / "legacy-run").is_dir()
    assert not (outputs / "projects" / ARCHIVE_PROJECT_ID).exists()


def test_migration_preserves_content_and_repairs_project_reference(tmp_path: Path) -> None:
    outputs = _fixture_outputs(tmp_path)
    plan = plan_legacy_output_migration(outputs)
    before = fingerprint_tree(outputs / "legacy-run")

    result = migrate_legacy_outputs(outputs, plan)

    payload = outputs / plan[0].destination_locator
    reference = outputs / "projects/consumer/references/historical"
    indirect = outputs / "projects/consumer/stages/indirect"
    assert result["migrated_count"] == 1
    assert not (outputs / "legacy-run").exists()
    assert fingerprint_tree(payload) == before
    assert reference.resolve() == payload.resolve()
    assert os.readlink(indirect) == "../references/historical/nested"
    assert indirect.resolve() == (payload / "nested").resolve()
    record = json.loads((payload.parent / "ARCHIVE.json").read_text())
    assert record["fingerprint"]["sha256"] == before.sha256
    manifest = json.loads(
        (outputs / "projects" / ARCHIVE_PROJECT_ID / "PROJECT.json").read_text()
    )
    assert manifest["retrieval_eligible"] is False
    assert manifest["runs"][0]["status"] == "archived"
    assert manifest["runs"][0]["stage_path"] == "payload"
    verification = verify_legacy_output_archive(outputs)
    assert verification["verified_count"] == 1
    assert verification["regular_files"] == 2


def test_source_symlink_requires_manual_review(tmp_path: Path) -> None:
    outputs = _fixture_outputs(tmp_path)
    os.symlink("notes.md", outputs / "legacy-run" / "latest")

    with pytest.raises(ValueError, match="contains symbolic links"):
        plan_legacy_output_migration(outputs)


def test_apply_rejects_tree_changed_after_plan(tmp_path: Path) -> None:
    outputs = _fixture_outputs(tmp_path)
    plan = plan_legacy_output_migration(outputs)
    (outputs / "legacy-run/notes.md").write_text("changed after planning\n")

    with pytest.raises(ValueError, match="fingerprint changed"):
        migrate_legacy_outputs(outputs, plan)

    assert (outputs / "legacy-run").is_dir()

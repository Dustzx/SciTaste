"""Release checks use generic fixtures, never real private project identities."""

import json
import runpy
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
check = runpy.run_path(str(ROOT / "scripts/check_publication_privacy.py"))["check"]


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root)


def test_staged_and_committed_content_cannot_hide_behind_working_copy(tmp_path):
    git(tmp_path, "init", "-q")
    document = tmp_path / "README.md"
    document.write_text("unpublished-study has an internal result")
    git(tmp_path, "add", "README.md")
    document.write_text("Public platform only")
    policy = {"private_terms": ["unpublished-study"]}
    assert check(tmp_path, policy)["status"] == "PASS"
    assert check(tmp_path, policy, staged=True)["status"] == "FAIL"
    git(
        tmp_path,
        "-c",
        "user.name=Example",
        "-c",
        "user.email=example@example.org",
        "commit",
        "-qm",
        "Generic fixture",
    )
    document.unlink()
    assert check(tmp_path, policy, ref="HEAD")["status"] == "FAIL"


def test_public_urls_allowed_but_research_payloads_and_unreviewed_images_blocked(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / ".env.example").write_text("EXAMPLE_KEY=replace-me")
    (tmp_path / "README.md").write_text("https://example.org/home/conference/")
    registry = tmp_path / "workspace/data/research_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"ideas": []}))
    git(tmp_path, "add", ".")
    assert check(tmp_path, {})["status"] == "PASS"
    registry.write_text(json.dumps({"ideas": [{"id": "private-proposal"}]}))
    assert check(tmp_path, {})["status"] == "FAIL"
    registry.write_text(json.dumps({"ideas": []}))
    image = tmp_path / "site/assets/platform-example.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"unreviewed media")
    git(tmp_path, "add", ".")
    assert check(tmp_path, {})["status"] == "FAIL"


def test_project_identities_come_from_local_profiles(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "workspace/scripts"))
    import local_research

    monkeypatch.setattr(local_research, "PROFILES", tmp_path)
    assert local_research.project_mapping() == {}
    profile = tmp_path / "example-project.json"
    profile.write_text(json.dumps({"project_id": "example-project", "report_id": "Example"}))
    assert local_research.project_mapping() == {"example-project": "Example"}
    profile.write_text(json.dumps({"project_id": "wrong-identity", "report_id": "Example"}))
    with pytest.raises(ValueError, match="identity mismatch"):
        local_research.project_mapping()

"""Scientific feedback routing and explicit public-input isolation, without model calls."""

import pytest

from scitaste.project.paper_feedback import review_work_items
from scitaste.project.review_research import public_assets


def concern(*, action="CLARIFY", evidence=False, experiment=False, disposition=None):
    return {
        "concern": {
            "concern_id": "paired-contrast",
            "text": "Compute the paired contrast from retained predictions.",
            "proposed_action_type": action,
            "requires_new_evidence": evidence,
            "requires_new_experiment": experiment,
        },
        "revision_response": {"disposition": disposition},
        "report_sha256": "a" * 64,
    }


@pytest.mark.parametrize(
    "row,route",
    [
        (concern(action="ADD_ANALYSIS"), "retained-evidence-analysis"),
        (concern(action="ADD_ANALYSIS", experiment=True), "new-experiment"),
        (concern(action="ADD_ANALYSIS", evidence=True), "evidence-acquisition"),
        (concern(evidence=True), "evidence-acquisition"),
        (concern(disposition="pending-evidence"), "scientific-planning-required"),
        (concern(disposition="addressed"), "claim-or-text-revision"),
    ],
)
def test_feedback_routes_without_granting_execution_or_closure(row, route):
    item = review_work_items([row])[0]
    assert item["route"] == route
    assert item["execution_authorized"] is False
    assert item["resolution_verified"] is False
    assert item["report_sha256"] == row["report_sha256"]


def test_only_selected_public_files_are_inputs(tmp_path):
    selected = tmp_path / "predictions"
    selected.mkdir()
    (selected / "a.csv").write_text("score\n1\n")
    (tmp_path / "unselected.csv").write_text("never exposed")
    assert list(public_assets(tmp_path, ["predictions", "predictions/a.csv"])) == [
        "predictions/a.csv"
    ]


@pytest.mark.parametrize("name", [".env", ".env.local", "Private/a.csv", "key.PEM"])
def test_known_private_and_credential_inputs_fail_closed(tmp_path, name):
    asset = tmp_path / name
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_text("not public")
    with pytest.raises(ValueError, match="Private/credential"):
        public_assets(tmp_path, [name])


def test_symlink_ancestor_and_escape_are_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "scores.csv").write_text("1")
    (tmp_path / "alias").symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        public_assets(tmp_path, ["alias/scores.csv"])
    with pytest.raises(ValueError, match="workspace-relative"):
        public_assets(tmp_path, ["../outside"])

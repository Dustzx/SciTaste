import json

import pytest

from scitaste.benchmark.open_research import digest
from scitaste.review.lifecycle_review import review_evidence
from scitaste.writing.confirmation_evidence import native_confirmation_evidence


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def example(root):
    source = root / "evaluations/native"
    campaign = root / "evaluations/cohort/CAMPAIGN.json"
    write(campaign, {"pack": {"not_opened": True}, "researcher_assets": {"not_opened": True}})
    write(campaign.parent / "ASSIGNMENTS.json", {"scitaste-native": {"run": "evaluations/native"}})
    write(
        source / "CONTRACT.json",
        {
            "plan": {
                "campaign": {
                    "locator": campaign.relative_to(root).as_posix(),
                    "sha256": digest(campaign),
                }
            }
        },
    )
    owned = campaign.parent / "confirmation/scitaste-native"
    write(owned / "release/frozen_submission/predict.py", "frozen source")
    write(
        owned / "release/RELEASE.json",
        {"frozen_source": {"predict.py": digest(owned / "release/frozen_submission/predict.py")}},
    )
    write(
        owned / "EXECUTION_CONTRACT.json",
        {
            "campaign_sha256": digest(campaign),
            "source_run": "evaluations/native",
            "source_contract_sha256": digest(source / "CONTRACT.json"),
        },
    )
    prediction = owned / "execution/predictions/amazon--control.npz"
    write(prediction, "retained output")
    write(
        owned / "INFERENCE_RESULT.json",
        {
            "execution_contract_sha256": digest(owned / "EXECUTION_CONTRACT.json"),
            "release_sha256": digest(owned / "release/RELEASE.json"),
            "return_code": 0,
            "before_private_scoring": True,
            "output_sha256": {prediction.name: digest(prediction)},
        },
    )
    write(
        owned / "RESULT.json",
        {
            "arm": "scitaste-native",
            "status": "completed",
            "executed_frozen_source": True,
            "execution_contract_sha256": digest(owned / "EXECUTION_CONTRACT.json"),
            "inference_result_sha256": digest(owned / "INFERENCE_RESULT.json"),
            "result": {"source_execution_verified": False, "formal_evidence_eligible": False},
        },
    )
    return source, owned


def test_public_receipts_distinguish_execution_from_formal_admission(tmp_path):
    source, owned = example(tmp_path)
    destination = tmp_path / "evaluations/paper-cycle/CONFIRMATION_EVIDENCE.json"
    paths = native_confirmation_evidence(tmp_path, source, destination)
    assert paths == (owned / "RESULT.json", owned / "INFERENCE_RESULT.json", destination)
    summary = json.loads(destination.read_text())
    assert summary["executed_frozen_source"]
    assert not summary["formal_evidence_eligible"] and not summary["scientific_approval"]
    supplemental = review_evidence(tmp_path, paths)
    assert len(supplemental) == 3
    assert all("private" not in locator for locator in supplemental)
    assert native_confirmation_evidence(tmp_path, source, destination) == paths


@pytest.mark.parametrize(
    "artifact",
    ["execution/predictions/amazon--control.npz", "release/frozen_submission/predict.py"],
)
def test_changed_prediction_or_source_cannot_enter_paper_evidence(tmp_path, artifact):
    source, owned = example(tmp_path)
    (owned / artifact).write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        native_confirmation_evidence(tmp_path, source, tmp_path / "evaluations/flow/proof.json")


def test_review_evidence_does_not_discover_credentials(tmp_path):
    path = tmp_path / "resources/access/credentials.env"
    path.parent.mkdir(parents=True)
    path.write_text("not research evidence")
    with pytest.raises(ValueError, match="research artifact"):
        review_evidence(tmp_path, [path])

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.evaluation.e2_prelaunch import E2PrelaunchManifest, load_e2_prelaunch_manifest

MANIFEST_PATH = Path("configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v1.yaml")
RELATED_WORK_MANIFEST_PATH = Path(
    "configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v2.yaml"
)


def _payload() -> dict[str, object]:
    payload = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_production_e2_manifest_closes_minimal_title_relevant_pair() -> None:
    manifest, digest = load_e2_prelaunch_manifest(MANIFEST_PATH)

    assert len(digest) == 64
    assert (
        manifest.project.program_id == "scitaste-iclr2027-capability-driven-autoresearch-program-v4"
    )
    assert manifest.workload.initial_task_weights == "none"
    assert manifest.workload.initialization_seed == 1234567891
    assert {item.system_id for item in manifest.comparison.arms} == {
        "scitaste-native",
        "native-base",
    }
    assert manifest.model_selection.b1_agent_model_id is None
    assert manifest.resources.available_gpu_devices == 8
    assert manifest.authorizes_gpu_work is False


def test_related_work_e2_manifest_does_not_require_an_available_checkpoint() -> None:
    manifest, _ = load_e2_prelaunch_manifest(RELATED_WORK_MANIFEST_PATH)

    assert (
        manifest.model_selection.candidate_universe_authority
        == "recent-related-work-and-idea-task-fit-first"
    )
    assert manifest.model_selection.scientific_agent_and_task_model_separate is True
    assert manifest.model_selection.candidate_catalog is not None
    assert all("2b" not in item.model_id.casefold() for item in manifest.model_selection.candidates)
    assert {item.model_id for item in manifest.model_selection.candidates}.issuperset(
        {"GPT-5.4-Thinking", "Gemini-3-Pro", "Qwen/Qwen3.5-9B"}
    )
    assert manifest.project.idea_revision_id == "outcome-calibrated-scientific-taste-policy-v2"
    assert manifest.project.idea_revision is not None
    assert manifest.workload.architecture == "LocPointTransformer"


def test_e2_rejects_qwen3_vl_2b_as_primary_candidate() -> None:
    payload = _payload()
    payload["model_selection"]["b0_agent_candidate_id"] = "qwen3-vl-2b-local-lower-bound"
    for candidate in payload["model_selection"]["candidates"]:
        if candidate["candidate_id"] == "qwen3-vl-2b-local-lower-bound":
            candidate["status"] = "b0-provisional-exact-candidate"

    with pytest.raises(ValidationError, match="Qwen3-VL-2B"):
        E2PrelaunchManifest.model_validate(payload)


def test_e2_rejects_hidden_score_authority_in_b0() -> None:
    payload = _payload()
    payload["resources"]["blocks"][0]["hidden_score_authority"] = True

    with pytest.raises(ValidationError, match="B0 cannot open"):
        E2PrelaunchManifest.model_validate(payload)


def test_e2_verified_model_role_gate_requires_bound_selection() -> None:
    payload = _payload()
    payload["gates"]["b0_exact_model_role_attestation"] = "verified"

    with pytest.raises(ValidationError, match="content-bound conformance selection"):
        E2PrelaunchManifest.model_validate(payload)

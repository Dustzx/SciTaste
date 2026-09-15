from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.evaluation.e2_prelaunch import E2PrelaunchManifest, load_e2_prelaunch_manifest

MANIFEST_PATH = Path("configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v1.yaml")


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

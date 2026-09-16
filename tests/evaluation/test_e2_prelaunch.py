from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scitaste.evaluation.e2_prelaunch import (
    E2FileBinding,
    E2PrelaunchManifest,
    E2TasteIntervention,
    inspect_e2_taste_intervention,
    load_e2_prelaunch_manifest,
)

MANIFEST_PATH = Path("configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v1.yaml")
RELATED_WORK_MANIFEST_PATH = Path(
    "configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v2.yaml"
)
TREATMENT_GATED_MANIFEST_PATH = Path(
    "configs/evaluation/prelaunch/mlrc_perception_native_pair_e2_v5.yaml"
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

    with pytest.raises(ValidationError, match="development cannot open"):
        E2PrelaunchManifest.model_validate(payload)


def test_e2_verified_model_role_gate_requires_bound_selection() -> None:
    payload = _payload()
    payload["gates"]["b0_exact_model_role_attestation"] = "verified"

    with pytest.raises(ValidationError, match="content-bound conformance selection"):
        E2PrelaunchManifest.model_validate(payload)


def test_e2_closed_command_identity_rejects_cross_evaluation_admission() -> None:
    payload = _payload()
    payload["resources"]["api_budget"] = {
        "provider_id": "alibaba-bailian",
        "model_id": "qwen3.8-max",
        "model_revision": "qwen3.8-max-2026-09-02",
        "maximum_invocations_per_block": 8,
        "maximum_input_tokens_per_call": 16000,
        "maximum_output_tokens_per_call": 8192,
        "maximum_total_tokens_per_block": 193536,
        "maximum_cost_usd_per_block": 1.0,
        "retry_count": 0,
    }
    payload["command_identity_closed"] = True
    for command in payload["commands"]:
        if command["command_id"] == "project-result-admit":
            index = command["argv"].index("--evaluation-id")
            command["argv"][index + 1] = "another-evaluation"

    with pytest.raises(ValidationError, match="must use the manifest ID"):
        E2PrelaunchManifest.model_validate(payload)


def test_e2_schema_11_requires_exact_taste_intervention() -> None:
    payload = _payload()
    payload["schema_version"] = "1.1"

    with pytest.raises(ValidationError, match="requires an exact learned Taste intervention"):
        E2PrelaunchManifest.model_validate(payload)


def test_current_e2_treatment_identity_is_closed_but_behavior_is_inactive() -> None:
    manifest, _ = load_e2_prelaunch_manifest(TREATMENT_GATED_MANIFEST_PATH)

    report = inspect_e2_taste_intervention(manifest, workspace_root=Path.cwd())

    policy_path = Path(manifest.taste_intervention.family_policy.locator)
    readiness_path = Path(manifest.taste_intervention.readiness.locator)
    if not policy_path.is_file() or not readiness_path.is_file():
        assert report.identity_closed is False
        assert report.behaviorally_active is False
        assert report.blocker_codes == ("taste-intervention-binding-invalid",)
        return

    assert report.identity_closed is True
    assert report.behaviorally_active is False
    assert report.blocker_codes == (
        "taste-intervention-no-training-support",
        "taste-intervention-head-not-h4-eligible",
        "taste-intervention-family-not-ready",
        "taste-intervention-policy-not-ready",
        "taste-intervention-state-probe-not-bound",
    )


def test_e2_state_probe_requires_an_acyclic_activation_basis() -> None:
    manifest, _ = load_e2_prelaunch_manifest(TREATMENT_GATED_MANIFEST_PATH)
    assert manifest.taste_intervention is not None
    payload = manifest.taste_intervention.model_dump(mode="python")
    payload.update(
        {
            "state_probe_contract": E2FileBinding(
                locator="outputs/probe-contract.json", sha256="a" * 64
            ),
            "state_probe_report": E2FileBinding(
                locator="outputs/probe-report.json", sha256="b" * 64
            ),
        }
    )

    with pytest.raises(ValidationError, match="acyclic activation basis"):
        E2TasteIntervention.model_validate(payload)

    payload["activation_basis"] = E2FileBinding(
        locator="configs/evaluation/prelaunch/base.yaml", sha256="c" * 64
    )
    intervention = E2TasteIntervention.model_validate(payload)

    assert intervention.activation_basis is not None

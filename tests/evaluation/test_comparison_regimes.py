from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import (
    ComparisonRegime,
    ExperimentPrelaunchManifest,
    ScientificLaneRole,
    compile_evaluation_cell_plan,
    load_prelaunch_manifest,
)

MANIFEST_PATH = Path("configs/evaluation/prelaunch/deepseek_v41flash_package_pilot_v6.yaml")


def _best_native_manifest() -> ExperimentPrelaunchManifest:
    base = load_prelaunch_manifest(MANIFEST_PATH).manifest
    payload = base.model_dump(mode="json")
    payload["schema_version"] = "1.2"
    lane = payload["lanes"][0]
    deepseek = lane.pop("api_model")
    zhipu = {
        **deepseek,
        "provider_id": "zhipu",
        "endpoint": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model_id": "glm-5.3-flash",
        "model_revision": "GLM-5.3-Flash",
        "identity_source_url": "https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3",
        "api_key_env": "ZAI_API_KEY",
        "pricing": {
            **deepseek["pricing"],
            "currency": "CNY",
            "source_url": "https://open.bigmodel.cn/pricing",
        },
    }
    lane.update(
        {
            "scientific_role": "best_native_system",
            "comparison_regime": "best_native",
            "model_effects_confounded": True,
            "comparison_claim_boundary": (
                "This ecological system comparison estimates package performance under each "
                "registered native model configuration; it is not a causal scaffold effect."
            ),
            "system_api_models": [
                {
                    "system_id": system_id,
                    "api_model": zhipu if system_id == "agent-laboratory" else deepseek,
                }
                for system_id in lane["system_ids"]
            ],
        }
    )
    return ExperimentPrelaunchManifest.model_validate(payload)


def test_legacy_proposal_and_cell_fingerprints_remain_stable() -> None:
    manifest = load_prelaunch_manifest(MANIFEST_PATH).manifest
    plan = compile_evaluation_cell_plan(manifest)

    assert manifest.proposal_sha256 == (
        "0820a4589b859d1f2feb2e8f14bf37cc8c0477b6c1413e32cbbe8122b6411e8e"
    )
    assert plan.plan_sha256 == "5b8b385e09db1cbc14562a2e1475260c4cfb062c9d5852ee095177c006dd1c17"
    assert plan.schema_version == "1.0"
    assert plan.lanes[0].resource is not None
    assert plan.lanes[0].system_resources is None


def test_best_native_plan_assigns_one_content_bound_model_to_each_system() -> None:
    manifest = _best_native_manifest()

    plan = compile_evaluation_cell_plan(manifest)

    assert manifest.schema_version == "1.2"
    assert manifest.lanes[0].comparison_regime is ComparisonRegime.BEST_NATIVE
    assert manifest.lanes[0].scientific_role is ScientificLaneRole.BEST_NATIVE_SYSTEM
    assert len(plan.cells) == 100
    assert plan.schema_version == "1.1"
    assert plan.lanes[0].resource is None
    assert set(plan.lanes[0].system_resources or {}) == set(plan.lanes[0].system_ids)
    assert all(cell.model_effects_confounded is True for cell in plan.cells)
    assert all(cell.scientific_role is ScientificLaneRole.BEST_NATIVE_SYSTEM for cell in plan.cells)
    providers = {
        cell.system_id: cell.resource.provider_id
        for cell in plan.cells
        if cell.task_id == "iclr2025_bi_align" and cell.seed == 7
    }
    assert providers["agent-laboratory"] == "zhipu"
    assert providers["scitaste-native"] == "deepseek"


def test_best_native_design_cannot_hide_model_confounding_or_missing_resources() -> None:
    manifest = _best_native_manifest()
    payload = manifest.model_dump(mode="json", exclude={"dossier_sha256"})
    payload["lanes"][0]["model_effects_confounded"] = False

    with pytest.raises(ValidationError, match="must declare model effects confounded"):
        ExperimentPrelaunchManifest.model_validate(payload)

    payload = manifest.model_dump(mode="json", exclude={"dossier_sha256"})
    payload["lanes"][0]["system_api_models"].pop()
    with pytest.raises(ValidationError, match="cover every lane system exactly"):
        ExperimentPrelaunchManifest.model_validate(payload)


def test_old_schema_cannot_smuggle_in_comparison_regime_semantics() -> None:
    manifest = _best_native_manifest()
    payload = manifest.model_dump(mode="json", exclude={"dossier_sha256"})
    payload["schema_version"] = "1.1"

    with pytest.raises(ValidationError, match=r"v1\.2 is required"):
        ExperimentPrelaunchManifest.model_validate(payload)

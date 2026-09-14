from __future__ import annotations

import pytest
from pydantic import ValidationError

from scitaste.evaluation.prelaunch import (
    ApiModelResource,
    ClaimAdmissionContract,
    ComparisonRegime,
    ConfirmatoryContrastRole,
    ConfirmatoryContrastSpec,
    ConfirmatoryEstimandKind,
    ContrastInferenceRole,
    ExecutionLane,
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    PrelaunchSystem,
    ProviderPricing,
    ReadinessStatus,
    ScientificLaneRole,
    SystemRole,
)


def _systems() -> dict[str, PrelaunchSystem]:
    output: dict[str, PrelaunchSystem] = {}
    for system_id in (
        "full-scitaste",
        "native-base",
        "raw-source-rag",
        "matched-abstracted-taste",
        "mismatched-taste",
    ):
        output[system_id] = PrelaunchSystem(
            system_id=system_id,
            role=(SystemRole.SCITASTE if system_id == "full-scitaste" else SystemRole.ABLATION),
            implementation_ref=f"scitaste@{'a' * 40}:{system_id}",
            availability=ReadinessStatus.VERIFIED,
            real_implementation=True,
        )
    return output


def _lane() -> ExecutionLane:
    systems = tuple(_systems())
    return ExecutionLane(
        lane_id="native-taste-mechanisms",
        kind=ExecutionLaneKind.API_ONLY,
        scientific_role=ScientificLaneRole.MATCHED_BACKBONE,
        comparison_regime=ComparisonRegime.MATCHED_BACKBONE,
        model_effects_confounded=False,
        comparison_claim_boundary="Only the three identified Scientific Taste contrasts.",
        system_ids=systems,
        task_ids=("task-a", "task-b"),
        seeds=(7,),
        repetitions=1,
        planned_cells=10,
        api_model=ApiModelResource(
            provider_id="provider",
            endpoint="https://provider.example.test/v1",
            interface="openai-chat-completions",
            model_id="model",
            model_revision="model-2026-09-14",
            rolling_alias=False,
            identity_source_url="https://provider.example.test/model",
            identity_status=ReadinessStatus.VERIFIED,
            api_key_env="PROVIDER_API_KEY",
            max_input_tokens_per_call=10_000,
            max_output_tokens_per_call=4_000,
            max_requests=10,
            max_total_tokens=100_000,
            max_cost=20,
            pricing=ProviderPricing(
                currency="USD",
                as_of="2026-09-14",
                input_cache_hit_per_million=0.1,
                input_cache_miss_per_million=1,
                output_per_million=2,
                status=ReadinessStatus.VERIFIED,
                source_url="https://provider.example.test/pricing",
            ),
        ),
    )


def _claim() -> ClaimAdmissionContract:
    return ClaimAdmissionContract(
        estimand_kind=ConfirmatoryEstimandKind.NATIVE_TASTE_MECHANISMS,
        lane_id="native-taste-mechanisms",
        candidate_system_id="full-scitaste",
        contrasts=(
            ConfirmatoryContrastSpec(
                contrast_id="full-vs-base",
                candidate_system_id="full-scitaste",
                comparator_system_id="native-base",
                role=ConfirmatoryContrastRole.NO_TASTE_CONTROL,
                inference_role=ContrastInferenceRole.CONFIRMATORY,
                favorable_direction="higher",
                minimum_effect=0,
            ),
            ConfirmatoryContrastSpec(
                contrast_id="matched-taste-vs-raw-source",
                candidate_system_id="matched-abstracted-taste",
                comparator_system_id="raw-source-rag",
                role=ConfirmatoryContrastRole.REFERENCE_REPRESENTATION_CONTROL,
                inference_role=ContrastInferenceRole.CONFIRMATORY,
                favorable_direction="higher",
                minimum_effect=0,
            ),
            ConfirmatoryContrastSpec(
                contrast_id="matched-vs-mismatched-taste",
                candidate_system_id="matched-abstracted-taste",
                comparator_system_id="mismatched-taste",
                role=ConfirmatoryContrastRole.MISMATCHED_TASTE_PLACEBO,
                inference_role=ContrastInferenceRole.CONFIRMATORY,
                favorable_direction="higher",
                minimum_effect=0,
            ),
        ),
        minimum_distinct_tasks=2,
    )


def test_native_mechanism_claim_admits_the_identified_five_arm_design() -> None:
    systems = _systems()
    lane = _lane()
    claim = _claim()

    ExperimentPrelaunchManifest._validate_claim_admission(
        claim,
        systems=systems,
        lanes={lane.lane_id: lane},
        explicit_inference=True,
    )


def test_native_mechanism_claim_rejects_full_vs_raw_as_representation_evidence() -> None:
    payload = _claim().model_dump(mode="python")
    payload["contrasts"][1]["candidate_system_id"] = "full-scitaste"
    drifted = ClaimAdmissionContract.model_validate(payload)
    lane = _lane()

    with pytest.raises(ValueError, match="exact bundle, representation"):
        ExperimentPrelaunchManifest._validate_claim_admission(
            drifted,
            systems=_systems(),
            lanes={lane.lane_id: lane},
            explicit_inference=True,
        )


def test_legacy_native_claim_still_requires_one_common_candidate() -> None:
    payload = _claim().model_dump(mode="python")
    payload["estimand_kind"] = ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL

    with pytest.raises(ValidationError, match="declared candidate"):
        ClaimAdmissionContract.model_validate(payload)

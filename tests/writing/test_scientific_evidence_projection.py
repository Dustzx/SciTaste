import json

import pytest

from scitaste.review.evidence_projection import microscopy_confirmation_view


def test_every_method_budget_mean_survives_and_omissions_are_explicit():
    scores = []
    for budget in (1, 2):
        for method in ("primary", "negative_control"):
            scores.append(
                {
                    "task_id": "microscopy-structure-restoration",
                    "method": method,
                    "input_capture_count": budget,
                    "mean_fov_psnr_db": 20.125 + budget,
                    "mean_fov_ssim": 0.6,
                    "source_execution_verified": False,
                    "fovs": [
                        {
                            "fov_id": 15,
                            "psnr_db": 20.125 + budget,
                            "ssim": 0.6,
                            "mse": 0.01,
                            "bandpass_mse": 0.001,
                            "reference_a_mse": 0.012,
                            "reference_b_mse": 0.013,
                            "half_reference_mse": 0.002,
                            "conditional_reference_noise_floor": 0.0005,
                            "bandpass_half_agreement": 0.95,
                            "reference_independence_stationarity_verified": False,
                        }
                    ],
                }
            )
    original = {
        "arm": "scitaste-native",
        "executed_frozen_source": True,
        "result": {"status": "scored-all-predeclared-procedures", "scores": scores},
    }
    result = json.loads(microscopy_confirmation_view(json.dumps(original).encode()))
    constants = result["result"]["score_constant_fields"]
    for old, projected in zip(scores, result["result"]["scores"], strict=True):
        reconstructed = {**constants, **projected}
        assert all(reconstructed[key] == value for key, value in old.items() if key != "fovs")
        assert projected["per_field_values"] == [[15, old["mean_fov_psnr_db"], 0.6, 0.001]]
    assert result["executed_frozen_source"] is True
    assert constants["source_execution_verified"] is False
    assert "reference_a_mse" in result["result"]["review_projection"]["per_field_omitted_keys"]
    assert (
        result["result"]["reference_diagnostics_by_field"]["15"][
            "reference_independence_stationarity_verified"
        ]
        is False
    )


def test_unknown_oversized_artifact_is_not_silently_summarized():
    with pytest.raises(ValueError, match="recognized microscopy"):
        microscopy_confirmation_view(b'{"result":{"scores":[]}}')

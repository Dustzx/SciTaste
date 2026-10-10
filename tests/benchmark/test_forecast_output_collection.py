import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


def load_auxiliary_admission(name="competitive_auxiliary"):
    path = Path(__file__).resolve().parents[2] / "scripts/recover_forecast_score_collection.py"
    specification = importlib.util.spec_from_file_location("forecast_output_collection", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return getattr(module, name)


def test_cached_auxiliary_projection_never_discards_unknown_target_methods(tmp_path):
    competitive_auxiliary = load_auxiliary_admission()
    frozen, predictions = tmp_path / "source", tmp_path / "output"
    frozen.mkdir()
    predictions.mkdir()
    submission = {"primary_method": "fixed", "methods": ["fixed", "control"]}
    frozen.joinpath("SUBMISSION.json").write_text(json.dumps(submission))
    predictions.joinpath("SUBMISSION.json").write_text(json.dumps(submission))
    predictions.joinpath("PUBLIC.json").write_text(json.dumps(submission))

    def admitted(name):
        return competitive_auxiliary(
            name, predictions=predictions, submission=submission, frozen=frozen
        )

    assert admitted("SUBMISSION.json")
    assert admitted("PUBLIC.json")
    assert admitted("discovery--fixed.npz")
    assert admitted("validation--control--losses.npz")
    assert admitted("cache/" + "a" * 64 + ".fit.npz")
    assert not admitted("monthly--undeclared.npz")
    assert not admitted("validation--undeclared--losses.npz")
    assert not admitted("cache/../outside.fit.npz")
    assert not admitted("arbitrary.json")
    predictions.joinpath("PUBLIC.json").write_text(
        json.dumps({**submission, "primary_method": "control"})
    )
    assert not admitted("PUBLIC.json")
    predictions.joinpath("SUBMISSION.json").write_text("{}")
    assert not admitted("SUBMISSION.json")


def test_original_native_auxiliary_requires_original_manifest(tmp_path):
    admitted = load_auxiliary_admission("original_native_auxiliary")
    public = tmp_path / "public"
    public.mkdir()
    submission = {"primary_method": "fixed", "methods": ["fixed", "control"]}
    (public / "PUBLIC_STUDY.json").write_text(json.dumps(submission))
    (tmp_path / "RUN_SUMMARY.json").write_text(json.dumps(submission))

    def allowed(name):
        return admitted(name, predictions=tmp_path, submission=submission)

    assert allowed("RUN_SUMMARY.json")
    assert allowed("public/PUBLIC_STUDY.json")
    assert allowed("public/discovery--fixed.npz")
    assert allowed("public/validation--features.npz")
    assert not allowed("monthly--undeclared.npz")
    assert not allowed("public/monthly--fixed.npz")
    assert not allowed("public/discovery--undeclared.npz")
    (tmp_path / "RUN_SUMMARY.json").write_text(
        json.dumps({**submission, "primary_method": "control"})
    )
    assert not allowed("RUN_SUMMARY.json")


def test_forecast_field_projection_preserves_arrays_and_rejects_unknown_fields(tmp_path):
    project = load_auxiliary_admission("project_prediction_fields")
    source, target = tmp_path / "original.npz", tmp_path / "scoring.npz"
    scientific = {
        "series_id": np.array([1, 2], dtype=np.int64),
        "forecast": np.arange(36, dtype=np.float64).reshape(2, 18),
        "valid": np.array([True, False]),
        "seconds": np.array([0.1, 0.2]),
    }
    np.savez_compressed(
        source,
        **scientific,
        local_fit_seconds=np.array([0.05, 0.05]),
        forecast_seconds=np.array([0.05, 0.15]),
    )
    receipt = project(source, target, timing_metadata=True)
    assert receipt["scientific_fields_array_bytes_identical"]
    assert not receipt["predictions_or_validity_repaired"]
    with np.load(target, allow_pickle=False) as values:
        assert set(values.files) == set(scientific)
        for name, expected in scientific.items():
            assert values[name].dtype == expected.dtype
            assert values[name].tobytes() == expected.tobytes()
    np.savez_compressed(source, **scientific, undeclared_forecast=np.zeros((2, 18)))
    with pytest.raises(ValueError, match="Unknown forecast fields"):
        project(source, tmp_path / "rejected.npz", timing_metadata=True)
    assert not (tmp_path / "rejected.npz").exists()

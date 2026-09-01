from __future__ import annotations

from scitaste.backends.scripted import ScriptedPreferenceBackend
from scitaste.taste.intrinsic import IntrinsicTasteCalibrator, load_calibration_suite


def test_offline_intrinsic_suite_reports_stage_metrics() -> None:
    suite = load_calibration_suite("configs/taste/intrinsic_calibration_v1.yaml")
    backend = ScriptedPreferenceBackend(
        {case.case_id: case.scripted_selection_id for case in suite.cases}
    )

    report = IntrinsicTasteCalibrator(backend, seed=7).evaluate(suite)

    assert report.overall.count == 5
    assert report.overall.accuracy == 0.8
    assert set(report.by_task) == {case.task for case in suite.cases}
    assert report.overall.brier_score >= 0
    assert report.overall.expected_calibration_error >= 0

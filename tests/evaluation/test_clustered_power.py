from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation import (
    ClusteredPowerRequest,
    HumanPreferenceAnalysisReport,
    HumanPreferenceHypothesisResult,
    HumanPreferenceSourceGroupResult,
    ObjectiveAnalysisReport,
    ObjectiveContrastAnalysis,
    ObjectiveTaskContrast,
    PilotAnalysisBinding,
    PowerAnalysisFamily,
    PowerContrastSpecification,
    PowerIndependentUnit,
    PowerResourceGeometry,
    TasteMechanismHypothesis,
    TasteStudyCondition,
    load_clustered_power_request,
    plan_clustered_power,
)
from scitaste.evaluation.prelaunch import ContrastInferenceRole

SHA = "a" * 64


def _write_report(tmp_path: Path, report: object, name: str = "pilot.json") -> tuple[Path, str]:
    path = tmp_path / name
    payload = report.model_dump(mode="json")  # type: ignore[attr-defined]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _human_pilot(tmp_path: Path) -> tuple[Path, str, HumanPreferenceAnalysisReport]:
    effects = (-0.05, 0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3)
    results = []
    for hypothesis, comparator in (
        (TasteMechanismHypothesis.H1_TASTE_ABSTRACTION, TasteStudyCondition.SAME_SOURCE_RAW_RAG),
        (
            TasteMechanismHypothesis.H2_TASTE_SPECIFICITY,
            TasteStudyCondition.SOURCE_DISJOINT_MISMATCHED_TASTE,
        ),
    ):
        groups = tuple(
            HumanPreferenceSourceGroupResult(
                source_group=f"group-{index}",
                case_count=2,
                observed_review_count=4,
                preference_probability=0.5 + effect,
                effect_over_tie=effect,
            )
            for index, effect in enumerate(effects)
        )
        results.append(
            HumanPreferenceHypothesisResult(
                hypothesis=hypothesis,
                comparator_condition=comparator,
                minimum_effect=0,
                independent_source_group_count=len(groups),
                case_count=16,
                observed_review_count=32,
                missing_review_count=0,
                source_groups=groups,
                effect_estimate=sum(effects) / len(effects),
                interval_lower=-0.01,
                interval_upper=0.26,
                raw_p_value=0.1,
                adjusted_p_value=0.2,
                conclusion="inconclusive",
            )
        )
    report = HumanPreferenceAnalysisReport.create(
        study_id="mechanism-pilot-v1",
        study_scope="pilot",
        study_sha256=SHA,
        outcome_report_sha256="b" * 64,
        analysis_contract_file_sha256="c" * 64,
        analysis_contract_semantic_sha256="d" * 64,
        power_analysis_sha256=None,
        missing_review_fraction=0,
        hypotheses=tuple(results),
        reviewer_diagnostics=(),
        both_h1_h2_supported=False,
        formal_joint_title_gate_passed=False,
    )
    path, digest = _write_report(tmp_path, report)
    return path, digest, report


def _human_request(
    pilot_file_sha256: str,
    pilot_report_sha256: str,
    *,
    blocks: int = 1,
    maximum_units: int = 500,
) -> ClusteredPowerRequest:
    return ClusteredPowerRequest.create(
        request_id=f"h1h2-power-blocks-{blocks}-max-{maximum_units}",
        formal_study_id="mechanism-formal-v1",
        family=PowerAnalysisFamily.HUMAN_H1_H2,
        independent_unit=PowerIndependentUnit.HELD_OUT_SOURCE_GROUP,
        pilot_report=PilotAnalysisBinding(
            report_kind=PowerAnalysisFamily.HUMAN_H1_H2,
            path="pilot.json",
            file_sha256=pilot_file_sha256,
            report_sha256=pilot_report_sha256,
        ),
        contrasts=(
            PowerContrastSpecification(
                contrast_id=TasteMechanismHypothesis.H1_TASTE_ABSTRACTION.value,
                minimum_effect=0,
                smallest_effect_of_interest=0.15,
                dispersion_floor=0.1,
                effect_justification=(
                    "A fifteen-point preference gain is the smallest useful effect."
                ),
                dispersion_floor_justification=(
                    "A ten-point floor prevents a constant pilot from collapsing power."
                ),
            ),
            PowerContrastSpecification(
                contrast_id=TasteMechanismHypothesis.H2_TASTE_SPECIFICITY.value,
                minimum_effect=0,
                smallest_effect_of_interest=0.15,
                dispersion_floor=0.1,
                effect_justification=(
                    "A fifteen-point specificity gain is the smallest useful effect."
                ),
                dispersion_floor_justification=(
                    "A ten-point floor prevents a constant pilot from collapsing power."
                ),
            ),
        ),
        dispersion_bootstrap_resamples=1_000,
        minimum_pilot_independent_units=6,
        minimum_formal_independent_units=8,
        maximum_formal_independent_units=maximum_units,
        resource_geometry=PowerResourceGeometry(
            generation_conditions_per_independent_unit=3,
            generation_blocks_per_condition_unit=blocks,
            human_comparisons_per_independent_unit=2,
            reviewers_per_human_comparison=2,
        ),
    )


def _objective_pilot(tmp_path: Path) -> tuple[Path, str, ObjectiveAnalysisReport]:
    effects = (-0.1, 0.0, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35)
    comparisons = []
    for contrast_id in ("full-vs-base", "matched-vs-mismatched"):
        tasks = tuple(
            ObjectiveTaskContrast(
                task_id=f"task-{index}",
                source_group_id=f"source-{index}",
                paired_block_count=3,
                candidate_normalized_mean=0.5 + effect,
                comparator_normalized_mean=0.5,
                signed_effect=effect,
            )
            for index, effect in enumerate(effects)
        )
        comparisons.append(
            ObjectiveContrastAnalysis(
                contrast_id=contrast_id,
                candidate_system_id="scitaste-full",
                comparator_system_id="native-control",
                inference_role=ContrastInferenceRole.CONFIRMATORY,
                favorable_direction="higher",
                minimum_effect=0,
                independent_task_count=len(tasks),
                observed_block_count=len(tasks) * 3,
                task_effects=tasks,
                effect_estimate=sum(effects) / len(effects),
                interval_lower=-0.02,
                interval_upper=0.31,
                raw_p_value=0.1,
                adjusted_p_value=0.2,
                conclusion="inconclusive",
                analysis_input_sha256="e" * 64,
            )
        )
    report = ObjectiveAnalysisReport.create(
        project_id="power-project",
        evaluation_id="objective-pilot",
        study_scope="pilot",
        proposal_sha256=SHA,
        plan_sha256="b" * 64,
        cell_result_population_sha256="c" * 64,
        analysis_contract_sha256="d" * 64,
        objective_outcome_contract_sha256="e" * 64,
        objective_outcome_contract_semantic_sha256="f" * 64,
        measurement_set_sha256="1" * 64,
        multiplicity_family_sha256="2" * 64,
        comparisons=tuple(comparisons),
        confirmatory_comparisons=2,
        supported_confirmatory_comparisons=0,
        formal_effectiveness_established=False,
    )
    path, digest = _write_report(tmp_path, report, "objective.json")
    return path, digest, report


def test_h1_h2_power_uses_source_groups_and_counts_review_cost(tmp_path: Path) -> None:
    _path, file_sha, pilot = _human_pilot(tmp_path)
    request = _human_request(file_sha, pilot.report_sha256)
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")

    report = plan_clustered_power(
        load_clustered_power_request(request_path), evidence_root=tmp_path
    )

    assert report.independent_unit is PowerIndependentUnit.HELD_OUT_SOURCE_GROUP
    assert report.recommended_independent_units >= 8
    assert report.generation_trajectory_count == report.recommended_independent_units * 3
    assert report.human_judgment_count == report.recommended_independent_units * 4
    assert report.ready_for_formal_sample_size_freeze is True
    assert report.repetitions_change_cost_not_power is True


def test_repeated_blocks_raise_cost_but_not_independent_power(tmp_path: Path) -> None:
    _path, file_sha, pilot = _human_pilot(tmp_path)
    one = plan_clustered_power(
        load_clustered_power_request(
            _save_request(tmp_path, _human_request(file_sha, pilot.report_sha256))
        ),
        evidence_root=tmp_path,
    )
    three_request = _human_request(file_sha, pilot.report_sha256, blocks=3)
    three = plan_clustered_power(
        load_clustered_power_request(_save_request(tmp_path, three_request, "three.json")),
        evidence_root=tmp_path,
    )

    assert one.recommended_independent_units == three.recommended_independent_units
    assert three.generation_trajectory_count == one.generation_trajectory_count * 3


def test_objective_power_uses_confirmatory_tasks_only(tmp_path: Path) -> None:
    _path, file_sha, pilot = _objective_pilot(tmp_path)
    request = ClusteredPowerRequest.create(
        request_id="h3-objective-power-v1",
        formal_study_id="objective-formal-v1",
        family=PowerAnalysisFamily.OBJECTIVE_H3,
        independent_unit=PowerIndependentUnit.HELD_OUT_TASK,
        pilot_report=PilotAnalysisBinding(
            report_kind=PowerAnalysisFamily.OBJECTIVE_H3,
            path="objective.json",
            file_sha256=file_sha,
            report_sha256=pilot.report_sha256,
        ),
        contrasts=tuple(
            PowerContrastSpecification(
                contrast_id=identity,
                minimum_effect=0,
                smallest_effect_of_interest=0.2,
                dispersion_floor=0.1,
                effect_justification=(
                    "A twenty-point normalized progress gain is practically useful."
                ),
                dispersion_floor_justification=(
                    "A ten-point task floor guards against a homogeneous pilot."
                ),
            )
            for identity in ("full-vs-base", "matched-vs-mismatched")
        ),
        dispersion_bootstrap_resamples=1_000,
        resource_geometry=PowerResourceGeometry(
            generation_conditions_per_independent_unit=3,
            generation_blocks_per_condition_unit=2,
        ),
    )
    report = plan_clustered_power(
        load_clustered_power_request(_save_request(tmp_path, request)), evidence_root=tmp_path
    )

    assert report.independent_unit is PowerIndependentUnit.HELD_OUT_TASK
    assert {item.contrast_id for item in report.contrast_results} == {
        "full-vs-base",
        "matched-vs-mismatched",
    }
    assert report.human_judgment_count == 0
    assert report.generation_trajectory_count == report.recommended_independent_units * 6


def test_ceiling_and_hash_tampering_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pilot_path, file_sha, pilot = _human_pilot(tmp_path)
    request = _human_request(file_sha, pilot.report_sha256, maximum_units=8)
    request_path = _save_request(tmp_path, request)
    output = tmp_path / "power.json"

    status = main(
        [
            "evaluation",
            "clustered-power-plan",
            "--request",
            str(request_path),
            "--evidence-root",
            str(tmp_path),
            "--output",
            str(output),
            "--require-within-ceiling",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert status == 1
    assert payload["ready_for_formal_sample_size_freeze"] is False
    assert output.is_file()

    pilot_path.write_text(pilot_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="file SHA-256"):
        plan_clustered_power(load_clustered_power_request(request_path), evidence_root=tmp_path)

    with pytest.raises(ValidationError, match="wrong independent unit"):
        ClusteredPowerRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "independent_unit": PowerIndependentUnit.HELD_OUT_TASK.value,
            }
        )


def _save_request(
    tmp_path: Path, request: ClusteredPowerRequest, name: str = "request.json"
) -> Path:
    path = tmp_path / name
    path.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path

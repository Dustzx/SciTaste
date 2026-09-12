from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from scitaste.evaluation import (
    BenchmarkMetadataAllocationPolicy,
    BenchmarkMetadataPopulation,
    BenchmarkMetadataScreeningChainInspection,
    BenchmarkMetadataScreeningReport,
    BenchmarkMetadataScreenItemReport,
    BenchmarkMetadataScreenRule,
    BenchmarkMetadataScreenRulebook,
    BenchmarkRecordScreenDisposition,
    BenchmarkScreenAssessmentAuthority,
    BenchmarkScreenEvidenceMode,
    BenchmarkScreenMissingDisposition,
    BenchmarkScreenRuleRole,
    ClusteredPowerReport,
    ClusteredPowerRequest,
    ContrastPowerResult,
    PilotAnalysisBinding,
    PowerAnalysisFamily,
    PowerContrastSpecification,
    PowerIndependentUnit,
    PowerResourceGeometry,
    ProjectedBenchmarkMetadataRecord,
    ProjectedMetadataField,
    StructuredMetadataFormat,
    allocate_benchmark_metadata_population,
    approve_benchmark_metadata_allocation,
    inspect_benchmark_metadata_allocation_chain,
    inspect_benchmark_metadata_allocation_plan_chain,
    load_benchmark_metadata_allocation_approval,
    load_benchmark_metadata_allocation_plan,
    load_benchmark_metadata_allocation_report,
    load_clustered_power_report,
    load_clustered_power_request,
    plan_benchmark_metadata_allocation,
    save_benchmark_metadata_allocation_approval,
    save_benchmark_metadata_allocation_plan,
    save_benchmark_metadata_allocation_report,
)
from scitaste.evaluation import benchmark_metadata_allocation as allocation_module

_AT = datetime(2026, 9, 13, tzinfo=UTC)
_SHA = "a" * 64


def _projected_field(name: str, value: str) -> ProjectedMetadataField:
    return ProjectedMetadataField(
        semantic_field=name,
        availability="observed-source-field",
        source_fields=(f"/{name}",),
        source_field_present=True,
        values=(value,),
    )


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path.resolve()
    records = []
    categories = ("analysis", "language", "vision")
    for index in range(9):
        records.append(
            ProjectedBenchmarkMetadataRecord(
                record_id=f"eligible-{index + 1:02d}",
                source_item_id=f"item-{index + 1:02d}",
                source_sha256=f"{index + 1:064x}",
                fields=(
                    _projected_field("benchmark-category", categories[index // 3]),
                    _projected_field("source-paper-group", f"paper-{index + 1:02d}"),
                ),
            )
        )
    records.append(
        ProjectedBenchmarkMetadataRecord(
            record_id="excluded-01",
            source_item_id="item-10",
            source_sha256=f"{10:064x}",
            fields=(
                _projected_field("benchmark-category", "analysis"),
                _projected_field("source-paper-group", "paper-10"),
            ),
        )
    )
    population = BenchmarkMetadataPopulation(
        project_id="allocation-project",
        scope_id="allocation-scope-v1",
        plan_id="projection-plan-v1",
        plan_locator="controls/projection-plan.json",
        plan_file_sha256="1" * 64,
        plan_sha256="2" * 64,
        approval_id="projection-plan-v1-approval",
        approval_locator="controls/projection-approval.json",
        approval_file_sha256="3" * 64,
        approval_sha256="4" * 64,
        audit_report_sha256="5" * 64,
        request_id="allocation-source-v1",
        receipt_sha256="6" * 64,
        projected_at=_AT.replace(hour=1),
        media_type=StructuredMetadataFormat.YAML,
        record_unit="one-record-per-acquired-item",
        record_count=10,
        required_screen_fields=("benchmark-category", "source-paper-group"),
        records=tuple(records),
        missing_source_field_observation_count=0,
    )
    rulebook = BenchmarkMetadataScreenRulebook(
        rulebook_id="allocation-rulebook-v1",
        project_id="allocation-project",
        scope_id="allocation-scope-v1",
        scope_file_sha256="7" * 64,
        frozen_at=_AT,
        rules=(
            BenchmarkMetadataScreenRule(
                exclusion_code="license-blocked",
                role=BenchmarkScreenRuleRole.ELIGIBILITY,
                evidence_fields=("benchmark-category",),
                evidence_mode=BenchmarkScreenEvidenceMode.PROJECTED_METADATA,
                assessment_authority=BenchmarkScreenAssessmentAuthority.DETERMINISTIC_METADATA,
                missing_evidence_disposition=BenchmarkScreenMissingDisposition.EXCLUDE,
                decision_standard="Exclude an item when its projected category is absent.",
            ),
        ),
        allocation_policy=BenchmarkMetadataAllocationPolicy(
            strata_fields=("benchmark-category", "source-paper-group"),
        ),
    )
    items = tuple(
        BenchmarkMetadataScreenItemReport(
            record_id=record.record_id,
            disposition=(
                BenchmarkRecordScreenDisposition.EXCLUDED
                if record.record_id == "excluded-01"
                else BenchmarkRecordScreenDisposition.ELIGIBLE
            ),
            exclusion_codes=("license-blocked",) if record.record_id == "excluded-01" else (),
            unresolved_codes=(),
        )
        for record in sorted(records, key=lambda item: item.record_id)
    )
    report = BenchmarkMetadataScreeningReport(
        project_id="allocation-project",
        scope_id="allocation-scope-v1",
        population_locator="outputs/population.json",
        population_file_sha256="8" * 64,
        population_sha256=population.population_sha256,
        rulebook_locator="controls/rulebook.json",
        rulebook_file_sha256="9" * 64,
        rulebook_sha256=rulebook.rulebook_sha256,
        decision_package_locator="controls/decisions.json",
        decision_package_file_sha256="a" * 64,
        decision_package_sha256="b" * 64,
        screening_implementation_sha256="c" * 64,
        screened_at=_AT.replace(hour=2),
        record_count=10,
        eligibility_rule_count=1,
        allocation_rule_codes=(),
        eligible_record_ids=tuple(f"eligible-{index:02d}" for index in range(1, 10)),
        excluded_record_ids=("excluded-01",),
        blocked_record_ids=(),
        items=items,
        ready_for_allocation_proposal=True,
        bound_assessment_evidence_read=False,
    )
    screening_path = root / "outputs/screening/REPORT.json"
    screening_path.parent.mkdir(parents=True)
    screening_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    screening = BenchmarkMetadataScreeningChainInspection.model_construct(
        report=SimpleNamespace(
            path=screening_path,
            file_sha256=hashlib.sha256(screening_path.read_bytes()).hexdigest(),
            report=report,
        ),
        population=SimpleNamespace(
            population=SimpleNamespace(population=population),
            projection_implementation_current=True,
        ),
        rulebook=SimpleNamespace(rulebook=rulebook),
        decisions=SimpleNamespace(),
        screening_implementation_current=True,
    )

    request = ClusteredPowerRequest.create(
        request_id="allocation-power-request-v1",
        formal_study_id="allocation-formal-v1",
        family=PowerAnalysisFamily.OBJECTIVE_H3,
        independent_unit=PowerIndependentUnit.HELD_OUT_TASK,
        pilot_report=PilotAnalysisBinding(
            report_kind=PowerAnalysisFamily.OBJECTIVE_H3,
            path="outputs/pilot.json",
            file_sha256="d" * 64,
            report_sha256="e" * 64,
        ),
        contrasts=(
            PowerContrastSpecification(
                contrast_id="full-vs-base",
                minimum_effect=0,
                smallest_effect_of_interest=0.2,
                dispersion_floor=0.1,
                effect_justification="A twenty-point gain is the smallest useful effect.",
                dispersion_floor_justification="A ten-point floor prevents optimistic power.",
            ),
        ),
        minimum_formal_independent_units=6,
        maximum_formal_independent_units=20,
        resource_geometry=PowerResourceGeometry(
            generation_conditions_per_independent_unit=2,
            generation_blocks_per_condition_unit=1,
        ),
    )
    request_path = root / "outputs/power/REQUEST.json"
    request_path.parent.mkdir(parents=True)
    request_path.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
    request_inspection = load_clustered_power_request(request_path)
    contrast = ContrastPowerResult(
        contrast_id="full-vs-base",
        minimum_effect=0,
        smallest_effect_of_interest=0.2,
        planning_margin=0.2,
        pilot_independent_unit_count=6,
        pilot_effect_estimate=0.1,
        pilot_sample_dispersion=0.1,
        bootstrap_dispersion_upper_bound=0.1,
        dispersion_floor=0.1,
        planning_dispersion=0.1,
        per_contrast_alpha=0.05,
        marginal_power_required_for_joint_target=0.8,
        normal_approximation_units=2,
        sign_flip_resolution_units=5,
        required_independent_units=6,
        within_declared_ceiling=True,
    )
    power = ClusteredPowerReport.create(
        request_id=request.request_id,
        formal_study_id=request.formal_study_id,
        family=request.family,
        independent_unit=request.independent_unit,
        request_sha256=request.request_sha256,
        request_file_sha256=request_inspection.file_sha256,
        alpha=request.alpha,
        target_joint_power=request.target_joint_power,
        dispersion_confidence=request.dispersion_confidence,
        dispersion_bootstrap_resamples=request.dispersion_bootstrap_resamples,
        bootstrap_seed=request.bootstrap_seed,
        minimum_formal_independent_units=request.minimum_formal_independent_units,
        pilot_report_file_sha256=request.pilot_report.file_sha256,
        pilot_report_semantic_sha256=request.pilot_report.report_sha256,
        resource_geometry=request.resource_geometry,
        contrast_results=(contrast,),
        recommended_independent_units=6,
        maximum_formal_independent_units=20,
        generation_trajectory_count=12,
        human_judgment_count=0,
        ready_for_formal_sample_size_freeze=True,
    )
    power_path = root / "outputs/power/REPORT.json"
    power_path.write_text(power.model_dump_json(indent=2) + "\n", encoding="utf-8")
    power_inspection = load_clustered_power_report(power_path)
    monkeypatch.setattr(allocation_module, "plan_clustered_power", lambda *args, **kwargs: power)
    return root, screening, power_inspection, request_inspection


def _plan(root, screening, power, request, *, seed: int = 17):
    return plan_benchmark_metadata_allocation(
        screening,
        power,
        request,
        workspace_root=root,
        plan_id=f"allocation-plan-seed-{seed}",
        random_seed=seed,
        cluster_field="source-paper-group",
        allocation_output_locator="outputs/allocation/REPORT.json",
        created_at=_AT.replace(hour=3),
        allow_projected_metadata_read=True,
    )


def test_powered_allocation_is_stratified_and_preserves_every_screened_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, screening, power, request = _fixture(tmp_path, monkeypatch)
    plan = _plan(root, screening, power, request)
    assert plan.ready_for_owner_approval is True
    assert plan.powered_independent_units == 6
    assert len(plan.strata) == 3
    assert "eligible-01" not in plan.model_dump_json()

    plan_path = root / "outputs/allocation/PLAN.json"
    save_benchmark_metadata_allocation_plan(plan, plan_path)
    plan_inspection = load_benchmark_metadata_allocation_plan(plan_path)
    monkeypatch.setattr(
        allocation_module,
        "inspect_benchmark_metadata_screening_chain",
        lambda *args, **kwargs: screening,
    )
    plan_replay = inspect_benchmark_metadata_allocation_plan_chain(
        plan_path,
        workspace_root=root,
    )
    assert plan_replay.plan.plan.allocation_performed is False
    approval = approve_benchmark_metadata_allocation(
        plan_inspection,
        confirmed_plan_sha256=plan.plan_sha256,
        approved_by="allocation-owner",
        approved_at=_AT.replace(hour=4),
    )
    approval_path = root / "outputs/allocation/APPROVAL.json"
    save_benchmark_metadata_allocation_approval(approval, approval_path)
    approval_inspection = load_benchmark_metadata_allocation_approval(approval_path)

    allocated = allocate_benchmark_metadata_population(
        screening,
        power,
        request,
        plan_inspection,
        approval_inspection,
        workspace_root=root,
        allocated_at=_AT.replace(hour=5),
        allow_projected_metadata_read=True,
    )
    assert len(allocated.selected_records) == 6
    assert len({item.source_group for item in allocated.selected_records}) == 6
    assert {item.selected_independent_units for item in allocated.strata} == {2}
    assert len(allocated.unsampled_eligible_record_ids) == 3
    assert allocated.excluded_record_ids == ("excluded-01",)
    assert allocated.blocked_record_ids == ()
    assert allocated.task_selection_frozen is True
    assert allocated.experiment_performed is False

    output = root / "outputs/allocation/REPORT.json"
    save_benchmark_metadata_allocation_report(allocated, output)
    assert load_benchmark_metadata_allocation_report(output).report == allocated
    replay = inspect_benchmark_metadata_allocation_chain(output, workspace_root=root)
    assert replay.report.report.formal_task_set_sha256 == allocated.formal_task_set_sha256


def test_allocation_plan_blocks_insufficient_distinct_source_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, screening, power, request = _fixture(tmp_path, monkeypatch)
    population = screening.population.population.population
    changed = []
    for index, record in enumerate(population.records):
        if record.record_id.startswith("eligible"):
            fields = tuple(
                field.model_copy(update={"values": (f"paper-{index // 2}",)})
                if field.semantic_field == "source-paper-group"
                else field
                for field in record.fields
            )
            record = record.model_copy(update={"fields": fields})
        changed.append(record)
    screening.population.population.population = population.model_copy(
        update={"records": tuple(changed)}
    )

    plan = _plan(root, screening, power, request)

    assert plan.ready_for_owner_approval is False
    assert "too-few-independent-units" in plan.blocker_codes
    plan_path = root / "outputs/allocation/BLOCKED.json"
    save_benchmark_metadata_allocation_plan(plan, plan_path)
    with pytest.raises(ValueError, match="blocked benchmark allocation"):
        approve_benchmark_metadata_allocation(
            load_benchmark_metadata_allocation_plan(plan_path),
            confirmed_plan_sha256=plan.plan_sha256,
            approved_by="allocation-owner",
            approved_at=_AT.replace(hour=4),
        )


def test_allocation_requires_explicit_projected_metadata_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, screening, power, request = _fixture(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="allow-projected-metadata-read"):
        plan_benchmark_metadata_allocation(
            screening,
            power,
            request,
            workspace_root=root,
            plan_id="allocation-plan-no-read",
            random_seed=17,
            cluster_field="source-paper-group",
            allocation_output_locator="outputs/allocation/REPORT.json",
            created_at=_AT.replace(hour=3),
            allow_projected_metadata_read=False,
        )


def test_allocation_plan_blocks_missing_stratum_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, screening, power, request = _fixture(tmp_path, monkeypatch)
    population = screening.population.population.population
    first = population.records[0].model_copy(
        update={
            "fields": tuple(
                field
                for field in population.records[0].fields
                if field.semantic_field != "source-paper-group"
            )
        }
    )
    screening.population.population.population = population.model_copy(
        update={"records": (first, *population.records[1:])}
    )

    plan = _plan(root, screening, power, request)

    assert plan.ready_for_owner_approval is False
    assert "missing-allocation-field-evidence" in plan.blocker_codes
    assert plan.allocatable_record_count == 8


def test_allocation_approval_rejects_implementation_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, screening, power, request = _fixture(tmp_path, monkeypatch)
    stale = _plan(root, screening, power, request).model_copy(
        update={"allocation_implementation_sha256": "0" * 64}
    )
    plan_path = root / "outputs/allocation/STALE.json"
    save_benchmark_metadata_allocation_plan(stale, plan_path)

    with pytest.raises(ValueError, match="implementation has drifted"):
        approve_benchmark_metadata_allocation(
            load_benchmark_metadata_allocation_plan(plan_path),
            confirmed_plan_sha256=stale.plan_sha256,
            approved_by="allocation-owner",
            approved_at=_AT.replace(hour=4),
        )

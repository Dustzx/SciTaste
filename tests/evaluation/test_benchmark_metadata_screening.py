from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scitaste.evaluation import (
    AcquiredItemReceipt,
    BenchmarkMetadataAllocationPolicy,
    BenchmarkMetadataPopulation,
    BenchmarkMetadataPopulationChainInspection,
    BenchmarkMetadataScreenDecisionPackage,
    BenchmarkMetadataScreenRule,
    BenchmarkMetadataScreenRulebook,
    BenchmarkRecordRuleDecision,
    BenchmarkScreenAssessmentAuthority,
    BenchmarkScreenEvidenceMode,
    BenchmarkScreenMissingDisposition,
    BenchmarkScreenRuleRole,
    BenchmarkScreenVerdict,
    DatasetAcquisitionReceipt,
    ProjectedBenchmarkMetadataRecord,
    ProjectedMetadataField,
    StructuredMetadataFormat,
    inspect_benchmark_metadata_screen_rulebook,
    inspect_benchmark_metadata_screening_chain,
    load_benchmark_metadata_population,
    load_benchmark_metadata_scope,
    load_benchmark_metadata_screen_decisions,
    load_benchmark_metadata_screen_rulebook,
    load_benchmark_metadata_screening_report,
    save_benchmark_metadata_population,
    save_benchmark_metadata_screen_decisions,
    save_benchmark_metadata_screening_report,
    screen_benchmark_metadata_population,
)
from scitaste.evaluation import benchmark_metadata_screening as screening_module

_ROOT = Path(__file__).resolve().parents[2]
_AT = datetime(2026, 9, 13, tzinfo=UTC)


def test_repository_rulebooks_cover_frozen_scopes_before_content_read() -> None:
    for name, expected_eligibility, expected_allocation in (
        ("innovatorbench", 5, ("exceeds-declared-formal-capacity-after-scientific-screen",)),
        ("expbench", 6, ()),
    ):
        rulebook = load_benchmark_metadata_screen_rulebook(
            _ROOT / f"configs/evaluation/screening/{name}_metadata_screen_rulebook_v1.json"
        )
        scope = load_benchmark_metadata_scope(
            _ROOT / f"docs/research/data/{name}_task_metadata_scope_v1.yaml"
        )

        report = inspect_benchmark_metadata_screen_rulebook(rulebook, scope)

        assert report.eligibility_rule_count == expected_eligibility
        assert report.allocation_rule_codes == expected_allocation
        assert report.ready_for_population_screening is True
        assert report.source_content_read is False
        assert report.selection_performed is False


def _screening_fixture(tmp_path: Path):
    root = tmp_path.resolve()
    scope_payload = {
        "schema_version": "1.0",
        "scope_id": "synthetic-screen-scope-v1",
        "project_id": "screen-project",
        "scientific_role": "objective-progress-task-universe-screen",
        "benchmark_resource_id": "synthetic-benchmark",
        "repository_commit": "a" * 40,
        "dataset_id": "synthetic-dataset",
        "dataset_revision": "b" * 40,
        "selection_state": "metadata-acquisition-proposed-subset-not-selected",
        "selection_rule": "Screen every projected record before allocation.",
        "task_config_paths": ["tasks/a.yaml", "tasks/b.yaml"],
        "required_screen_fields": ["category", "license-status"],
        "exclusion_codes": ["license-blocked"],
        "forbidden_shortcuts": ["do-not-use-current-resources"],
        "authorizes_dataset_archive_download": False,
        "authorizes_runtime_asset_download": False,
        "authorizes_ingestion": False,
        "authorizes_execution": False,
    }
    scope_path = root / "docs/scope.yaml"
    scope_path.parent.mkdir(parents=True)
    scope_path.write_text(yaml.safe_dump(scope_payload, sort_keys=False), encoding="utf-8")
    scope_hash = hashlib.sha256(scope_path.read_bytes()).hexdigest()
    rulebook = BenchmarkMetadataScreenRulebook(
        rulebook_id="synthetic-screen-rulebook-v1",
        project_id="screen-project",
        scope_id="synthetic-screen-scope-v1",
        scope_file_sha256=scope_hash,
        frozen_at=_AT,
        rules=(
            BenchmarkMetadataScreenRule(
                exclusion_code="license-blocked",
                role=BenchmarkScreenRuleRole.ELIGIBILITY,
                evidence_fields=("category", "license-status"),
                evidence_mode=BenchmarkScreenEvidenceMode.PROJECTED_METADATA,
                assessment_authority=(BenchmarkScreenAssessmentAuthority.DETERMINISTIC_METADATA),
                missing_evidence_disposition=BenchmarkScreenMissingDisposition.EXCLUDE,
                decision_standard="Exclude records whose license evidence is absent.",
            ),
        ),
        allocation_policy=BenchmarkMetadataAllocationPolicy(
            strata_fields=("category",),
        ),
    )
    rulebook_path = root / "configs/rulebook.json"
    rulebook_path.parent.mkdir(parents=True)
    rulebook_path.write_text(rulebook.model_dump_json(indent=2) + "\n", encoding="utf-8")
    rulebook_inspection = load_benchmark_metadata_screen_rulebook(rulebook_path)

    population = BenchmarkMetadataPopulation(
        project_id="screen-project",
        scope_id="synthetic-screen-scope-v1",
        plan_id="synthetic-projection-plan-v1",
        plan_locator="controls/plan.json",
        plan_file_sha256="1" * 64,
        plan_sha256="2" * 64,
        approval_id="synthetic-projection-approval-v1",
        approval_locator="controls/approval.json",
        approval_file_sha256="3" * 64,
        approval_sha256="4" * 64,
        audit_report_sha256="5" * 64,
        request_id="synthetic-request-v1",
        receipt_sha256="6" * 64,
        projected_at=_AT.replace(hour=2),
        media_type=StructuredMetadataFormat.YAML,
        record_unit="one-record-per-acquired-item",
        record_count=2,
        required_screen_fields=("category", "license-status"),
        missing_source_field_observation_count=1,
        records=(
            ProjectedBenchmarkMetadataRecord(
                record_id="record-a",
                source_item_id="record-a",
                source_sha256="7" * 64,
                fields=(
                    ProjectedMetadataField(
                        semantic_field="category",
                        availability="observed-source-field",
                        source_fields=("/category",),
                        source_field_present=True,
                        values=("vision",),
                    ),
                    ProjectedMetadataField(
                        semantic_field="license-status",
                        availability="observed-source-field",
                        source_fields=("/license",),
                        source_field_present=True,
                        values=("verified",),
                    ),
                ),
            ),
            ProjectedBenchmarkMetadataRecord(
                record_id="record-b",
                source_item_id="record-b",
                source_sha256="8" * 64,
                fields=(
                    ProjectedMetadataField(
                        semantic_field="category",
                        availability="observed-source-field",
                        source_fields=("/category",),
                        source_field_present=True,
                        values=("language",),
                    ),
                    ProjectedMetadataField(
                        semantic_field="license-status",
                        availability="absent-from-audited-source",
                        source_field_present=False,
                        values=(),
                    ),
                ),
            ),
        ),
    )
    population_path = root / "outputs/projects/screen-project/projections/POPULATION.json"
    save_benchmark_metadata_population(population, population_path)
    population_inspection = load_benchmark_metadata_population(population_path)

    controls = root / "controls"
    controls.mkdir()
    plan_path = controls / "plan.json"
    approval_path = controls / "approval.json"
    request_path = controls / "request.json"
    audit_path = controls / "audit.json"
    for path in (plan_path, approval_path, request_path, audit_path):
        path.write_text("{}\n", encoding="utf-8")
    receipt = DatasetAcquisitionReceipt.create(
        request_id="synthetic-request-v1",
        request_sha256="9" * 64,
        approved_by="fixture-owner",
        approved_at=_AT,
        acquired_at=_AT.replace(hour=1),
        approval_scope="download-only-no-ingestion",
        destination_root=("outputs/projects/screen-project/acquisitions/synthetic-request-v1/raw"),
        items=(
            AcquiredItemReceipt(
                item_id="record-a",
                source_url=f"https://example.test/{'a' * 40}/record-a",
                source_revision="a" * 40,
                destination="a.yaml",
                size_bytes=10,
                sha256="a" * 64,
            ),
        ),
        item_count=1,
        total_bytes=10,
        maximum_total_bytes=100,
        source_hosts=("example.test",),
    )
    receipt_path = controls / "receipt.json"
    receipt_path.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")

    chain = BenchmarkMetadataPopulationChainInspection.model_construct(
        population=population_inspection,
        plan=SimpleNamespace(
            path=plan_path,
            plan=SimpleNamespace(
                scope_locator=scope_path.relative_to(root).as_posix(),
                request_locator=request_path.relative_to(root).as_posix(),
                receipt_locator=receipt_path.relative_to(root).as_posix(),
                audit_report_locator=audit_path.relative_to(root).as_posix(),
            ),
        ),
        approval=SimpleNamespace(path=approval_path),
        audit=SimpleNamespace(report=SimpleNamespace(audited_at=_AT.replace(hour=1))),
        projection_implementation_current=True,
    )
    decisions = BenchmarkMetadataScreenDecisionPackage(
        package_id="synthetic-screen-decisions-v1",
        project_id="screen-project",
        scope_id="synthetic-screen-scope-v1",
        population_file_sha256=population_inspection.file_sha256,
        population_sha256=population.population_sha256,
        rulebook_file_sha256=rulebook_inspection.file_sha256,
        rulebook_sha256=rulebook.rulebook_sha256,
        frozen_at=_AT.replace(hour=3),
        decisions=(
            BenchmarkRecordRuleDecision(
                record_id="record-a",
                exclusion_code="license-blocked",
                verdict=BenchmarkScreenVerdict.PASS,
                evidence_fields=("category", "license-status"),
                assessment_authority=(BenchmarkScreenAssessmentAuthority.DETERMINISTIC_METADATA),
                assessor_id="deterministic-screen",
                rationale="The projected license field is present.",
            ),
            BenchmarkRecordRuleDecision(
                record_id="record-b",
                exclusion_code="license-blocked",
                verdict=BenchmarkScreenVerdict.EXCLUDE,
                evidence_fields=("category", "license-status"),
                assessment_authority=(BenchmarkScreenAssessmentAuthority.DETERMINISTIC_METADATA),
                assessor_id="deterministic-screen",
                rationale="The required license field is absent.",
            ),
        ),
    )
    decisions_path = root / "outputs/projects/screen-project/decisions/DECISIONS.json"
    save_benchmark_metadata_screen_decisions(decisions, decisions_path)
    return (
        root,
        chain,
        rulebook_inspection,
        load_benchmark_metadata_screen_decisions(decisions_path),
    )


def test_screening_retains_complete_population_and_defers_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, population, rulebook, decisions = _screening_fixture(tmp_path)
    report = screen_benchmark_metadata_population(
        population,
        rulebook,
        decisions,
        workspace_root=root,
        screened_at=_AT.replace(hour=4),
        allow_projected_metadata_read=True,
    )

    assert report.eligible_record_ids == ("record-a",)
    assert report.excluded_record_ids == ("record-b",)
    assert report.blocked_record_ids == ()
    assert report.ready_for_allocation_proposal is True
    assert report.complete_population_screened is True
    assert report.selection_performed is False
    assert report.allocation_performed is False
    assert report.formal_outcomes_consulted is False
    assert report.compute_inventory_consulted is False

    report_path = root / "outputs/projects/screen-project/screening/REPORT.json"
    save_benchmark_metadata_screening_report(report, report_path)
    loaded = load_benchmark_metadata_screening_report(report_path)
    monkeypatch.setattr(
        screening_module,
        "inspect_benchmark_metadata_population_chain",
        lambda path, workspace_root: population,
    )
    replay = inspect_benchmark_metadata_screening_chain(report_path, workspace_root=root)
    assert loaded.report.report_sha256 == report.report_sha256
    assert replay.screening_implementation_current is True


def test_screening_rejects_an_incomplete_record_rule_cartesian_product(tmp_path: Path) -> None:
    root, population, rulebook, decisions = _screening_fixture(tmp_path)
    incomplete = decisions.package.model_copy(update={"decisions": decisions.package.decisions[:1]})
    incomplete_path = root / "outputs/projects/screen-project/decisions/INCOMPLETE.json"
    save_benchmark_metadata_screen_decisions(incomplete, incomplete_path)

    with pytest.raises(ValueError, match="every record and eligibility rule"):
        screen_benchmark_metadata_population(
            population,
            rulebook,
            load_benchmark_metadata_screen_decisions(incomplete_path),
            workspace_root=root,
            screened_at=_AT.replace(hour=4),
            allow_projected_metadata_read=True,
        )


def test_scientific_eligibility_cannot_be_reclassified_as_allocation() -> None:
    with pytest.raises(ValueError, match="only a declared post-screen capacity code"):
        BenchmarkMetadataScreenRule(
            exclusion_code="license-blocked",
            role=BenchmarkScreenRuleRole.ALLOCATION,
            evidence_fields=("license-status",),
            evidence_mode=BenchmarkScreenEvidenceMode.PROJECTED_METADATA,
            assessment_authority=BenchmarkScreenAssessmentAuthority.SEEDED_ALLOCATION,
            missing_evidence_disposition=BenchmarkScreenMissingDisposition.CANNOT_ASSESS,
            decision_standard="Invalidly defer a scientific rule.",
        )

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.cli import main
from scitaste.evaluation import reference_selection_comparison as comparison_module
from scitaste.evaluation.reference_selection_comparison import (
    ReferenceSelectionDownstreamEnvelope,
    ReferenceSelectionFileBinding,
    ReferenceSelectionSourceLink,
    approve_reference_selection_comparison,
    freeze_reference_selection_comparison,
    inspect_reference_selection_comparison_chain,
    load_reference_selection_approval,
    load_reference_selection_plan,
    plan_reference_selection_comparison,
    plan_reference_selection_comparison_from_files,
    save_reference_selection_approval,
    save_reference_selection_plan,
    save_reference_selection_report,
)
from scitaste.evaluation.source_admission import (
    SourceAdmissionItemReport,
    SourceAdmissionReport,
    SourceAdmissionVerdict,
)
from scitaste.taste.intrinsic import TasteTask
from scitaste.taste.reference_mining import (
    ReferenceCandidateMetadata,
    ReferenceDecisionPattern,
    ReferenceEvidenceRole,
    ReferenceIsolationStatus,
    ReferenceMetadataIdentityStatus,
    ReferenceMetadataRelevanceStatus,
    ReferenceMiningBatch,
    ReferenceMiningNeed,
    ReferenceMiningProposal,
    ReferenceMiningRun,
    ReferenceQueryFamily,
    ReferenceRightsStatus,
    ReferenceSearchQuery,
    compile_reference_mining_report,
)

_AT = datetime(2026, 9, 13, tzinfo=UTC)
_SHA = "a" * 64
_PATTERNS = (
    ReferenceDecisionPattern.PROBLEM_SIGNIFICANCE,
    ReferenceDecisionPattern.DIAGNOSTIC_EXPERIMENT,
    ReferenceDecisionPattern.CLAIM_CALIBRATION,
)
_ROLES = (
    ReferenceEvidenceRole.CHALLENGE,
    ReferenceEvidenceRole.BOUNDARY,
    ReferenceEvidenceRole.ALTERNATIVE,
)
_DOMAINS = ("machine-learning", "scientific-discovery")


def _candidate(
    name: str,
    *,
    query_id: str,
    pattern: ReferenceDecisionPattern,
    roles: tuple[ReferenceEvidenceRole, ...],
    domain: str,
    citations: int,
    year: int,
) -> ReferenceCandidateMetadata:
    return ReferenceCandidateMetadata(
        candidate_id=f"candidate-{name}",
        source_group_id=f"group-{name}",
        title=f"Reference {name}",
        locator=f"https://doi.org/10.0000/{name}",
        discovery_query_ids=(query_id,),
        hypothesized_decision_patterns=(pattern,),
        hypothesized_evidence_roles=roles,
        domain_facets=(domain,),
        rights_status=ReferenceRightsStatus.COMPATIBLE_METADATA_ONLY,
        isolation_status=ReferenceIsolationStatus.ELIGIBLE_CANDIDATE,
        venue="Frozen venue metadata",
        citation_count=citations,
        publication_year=year,
        metadata_provider_ids=("openalex", "crossref"),
        metadata_identity_status=ReferenceMetadataIdentityStatus.CROSS_INDEX_CORROBORATED,
        metadata_title_variants=(f"Reference {name}",),
        metadata_relevance_status=ReferenceMetadataRelevanceStatus.ELIGIBLE,
        metadata_grounded_domain_facets=(domain,),
        best_result_rank=1,
        retrieval_observation_count=2,
    )


def _upstreams():
    need = ReferenceMiningNeed(
        mining_id="h0-reference-pool-v1",
        stage=TasteTask.IDEA,
        decision_question="Which references expose transferable scientific decisions?",
        candidate_actions=("qualify by content", "rank by frozen citations"),
        evidence_gap_ids=("source-quality",),
        required_decision_patterns=_PATTERNS,
        required_evidence_roles=_ROLES,
        required_domain_facets=_DOMAINS,
        max_query_count=6,
        max_batches=3,
        saturation_window=2,
        min_distinct_source_groups=2,
        max_per_source_group=1,
        max_cohort_size=6,
    )
    queries = tuple(
        ReferenceSearchQuery(
            query_id=f"query-{family.value}",
            family=family,
            query_text=f"scientific decision {family.value}",
            targeted_decision_patterns=_PATTERNS,
            targeted_evidence_roles=_ROLES,
            targeted_domain_facets=_DOMAINS,
        )
        for family in ReferenceQueryFamily
    )
    proposal = ReferenceMiningProposal(
        mining_id=need.mining_id,
        queries=queries,
        rationale="Freeze a shared, coverage-complete H0 candidate pool.",
    )
    query_ids = tuple(query.query_id for query in queries)
    candidates = (
        _candidate(
            "quality-a",
            query_id=query_ids[0],
            pattern=_PATTERNS[0],
            roles=(_ROLES[0],),
            domain=_DOMAINS[0],
            citations=5,
            year=2025,
        ),
        _candidate(
            "prestige-a",
            query_id=query_ids[1],
            pattern=_PATTERNS[0],
            roles=(_ROLES[0],),
            domain=_DOMAINS[0],
            citations=500,
            year=2025,
        ),
        _candidate(
            "quality-b",
            query_id=query_ids[2],
            pattern=_PATTERNS[1],
            roles=(_ROLES[1],),
            domain=_DOMAINS[1],
            citations=4,
            year=2024,
        ),
        _candidate(
            "prestige-b",
            query_id=query_ids[3],
            pattern=_PATTERNS[1],
            roles=(_ROLES[1],),
            domain=_DOMAINS[1],
            citations=450,
            year=2024,
        ),
        _candidate(
            "quality-c",
            query_id=query_ids[4],
            pattern=_PATTERNS[2],
            roles=(_ROLES[2],),
            domain=_DOMAINS[0],
            citations=3,
            year=2023,
        ),
        _candidate(
            "prestige-c",
            query_id=query_ids[5],
            pattern=_PATTERNS[2],
            roles=(_ROLES[2],),
            domain=_DOMAINS[0],
            citations=400,
            year=2023,
        ),
    )
    run = ReferenceMiningRun(
        need=need,
        proposal=proposal,
        batches=(
            ReferenceMiningBatch(
                batch_index=1,
                query_ids=query_ids,
                candidates=candidates,
            ),
            ReferenceMiningBatch(
                batch_index=2,
                query_ids=query_ids,
            ),
            ReferenceMiningBatch(
                batch_index=3,
                query_ids=query_ids,
            ),
        ),
    )
    mining_report = compile_reference_mining_report(run)
    admitted_names = {"quality-a", "quality-b", "quality-c"}
    items = tuple(
        SourceAdmissionItemReport(
            item_id=f"item-{candidate.candidate_id}",
            source_id=f"source-{candidate.candidate_id}",
            source_group_id=candidate.source_group_id,
            source_content_sha256=hashlib.sha256(candidate.candidate_id.encode()).hexdigest(),
            audit_binding_verified=True,
            rights_evidence_verified=True,
            rights_supported=True,
            quality_evidence_verified=True,
            reference_quality_screen_verified=(
                candidate.candidate_id.removeprefix("candidate-") in admitted_names
            ),
            dual_independent_quality_review_verified=(
                candidate.candidate_id.removeprefix("candidate-") in admitted_names
            ),
            source_isolation_evidence_verified=True,
            source_isolation_supported=True,
            disposition=(
                SourceAdmissionVerdict.ADMIT
                if candidate.candidate_id.removeprefix("candidate-") in admitted_names
                else SourceAdmissionVerdict.REJECT
            ),
            blockers=(),
        )
        for candidate in candidates
    )
    source_report = SourceAdmissionReport(
        schema_version="1.1",
        proposal_id="h0-source-admission-v1",
        proposal_sha256="1" * 64,
        project_id="h0-project",
        request_id="h0-source-request-v1",
        request_sha256="2" * 64,
        receipt_sha256="3" * 64,
        content_audit_report_sha256="4" * 64,
        frozen_source_count=len(items),
        admitted_source_ids=tuple(
            item.source_id for item in items if item.disposition is SourceAdmissionVerdict.ADMIT
        ),
        rejected_source_ids=tuple(
            item.source_id for item in items if item.disposition is SourceAdmissionVerdict.REJECT
        ),
        minimum_admitted_sources=3,
        ready_for_projection_proposal=True,
        items=items,
        blockers=(),
        no_source_content_read=False,
        derived_quality_projection_read=True,
    )
    links = tuple(
        ReferenceSelectionSourceLink(
            candidate_id=candidate.candidate_id,
            source_id=f"source-{candidate.candidate_id}",
        )
        for candidate in candidates
    )
    return run, mining_report, source_report, links


def _plan(root: Path | None = None):
    run, mining_report, source_report, links = _upstreams()
    downstream = ReferenceSelectionDownstreamEnvelope(
        held_out_decision_set_sha256="8" * 64,
        representation_protocol_sha256="9" * 64,
        execution_protocol_sha256="b" * 64,
        sources_per_condition=3,
        per_source_context_token_ceiling=2_000,
        total_context_token_ceiling=6_000,
    )
    if root is not None:
        evidence = root / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        run_path = evidence / "MINING_RUN.json"
        report_path = evidence / "MINING_REPORT.json"
        admission_path = evidence / "SOURCE_ADMISSION.json"
        run_path.write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
        report_path.write_text(mining_report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        admission_path.write_text(source_report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return plan_reference_selection_comparison_from_files(
            mining_run_path=run_path,
            mining_report_path=report_path,
            source_admission_report_path=admission_path,
            evidence_root=root,
            source_links=links,
            comparison_id="h0-quality-vs-prestige-v1",
            project_id="h0-project",
            report_output_locator="outputs/H0_SELECTION.json",
            metadata_snapshot_year=2026,
            minimum_observed_prestige_fraction=1.0,
            stable_tie_break_salt_sha256=_SHA,
            target_source_count=3,
            downstream=downstream,
            created_at=_AT,
        )
    return plan_reference_selection_comparison(
        run,
        mining_report,
        source_report,
        mining_run_binding=ReferenceSelectionFileBinding(
            locator="evidence/MINING_RUN.json",
            file_sha256="5" * 64,
            semantic_sha256=run.run_sha256,
        ),
        mining_report_binding=ReferenceSelectionFileBinding(
            locator="evidence/MINING_REPORT.json",
            file_sha256="6" * 64,
            semantic_sha256=mining_report.report_sha256,
        ),
        source_admission_binding=ReferenceSelectionFileBinding(
            locator="evidence/SOURCE_ADMISSION.json",
            file_sha256="7" * 64,
            semantic_sha256=source_report.report_sha256,
        ),
        source_links=links,
        comparison_id="h0-quality-vs-prestige-v1",
        project_id="h0-project",
        report_output_locator="outputs/H0_SELECTION.json",
        metadata_snapshot_year=2026,
        minimum_observed_prestige_fraction=1.0,
        stable_tie_break_salt_sha256=_SHA,
        target_source_count=3,
        downstream=downstream,
        created_at=_AT,
    )


def test_h0_selection_freezes_matched_quality_and_prestige_arms(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    plan_path = tmp_path / "controls/PLAN.json"
    save_reference_selection_plan(plan, plan_path)
    plan_inspection = load_reference_selection_plan(plan_path)
    approval = approve_reference_selection_comparison(
        plan_inspection,
        confirmed_plan_sha256=plan.plan_sha256,
        approved_by="h0-owner",
        approved_at=_AT.replace(hour=1),
    )
    approval_path = tmp_path / "controls/APPROVAL.json"
    save_reference_selection_approval(approval, approval_path)
    approval_inspection = load_reference_selection_approval(approval_path)

    report = freeze_reference_selection_comparison(
        plan_inspection,
        approval_inspection,
        workspace_root=tmp_path,
    )
    output = tmp_path / plan.report_output_locator
    save_reference_selection_report(report, output)
    replay = inspect_reference_selection_comparison_chain(output, workspace_root=tmp_path)

    assert plan.ready_for_owner_approval is True
    assert {item.candidate_id for item in report.quality_selected} == {
        "candidate-quality-a",
        "candidate-quality-b",
        "candidate-quality-c",
    }
    assert {item.candidate_id for item in report.prestige_selected} == {
        "candidate-prestige-a",
        "candidate-prestige-b",
        "candidate-prestige-c",
    }
    assert all(item.quality_count == item.prestige_count for item in report.strata)
    assert report.cross_arm_overlap_candidate_ids == ()
    assert report.quality_selection_consulted_prestige_signals is False
    assert report.prestige_selection_consulted_content_quality is False
    assert report.authorizes_experiment is False
    assert replay.implementation_current is True


def test_h0_plan_from_files_binds_exact_upstream_bytes(tmp_path: Path) -> None:
    run, mining_report, source_report, links = _upstreams()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    run_path = evidence / "MINING_RUN.json"
    report_path = evidence / "MINING_REPORT.json"
    admission_path = evidence / "SOURCE_ADMISSION.json"
    run_path.write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report_path.write_text(mining_report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    admission_path.write_text(source_report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    plan = plan_reference_selection_comparison_from_files(
        mining_run_path=run_path,
        mining_report_path=report_path,
        source_admission_report_path=admission_path,
        evidence_root=tmp_path,
        source_links=links,
        comparison_id="h0-quality-vs-prestige-v1",
        project_id="h0-project",
        report_output_locator="outputs/H0_SELECTION.json",
        metadata_snapshot_year=2026,
        minimum_observed_prestige_fraction=1.0,
        stable_tie_break_salt_sha256=_SHA,
        target_source_count=3,
        downstream=ReferenceSelectionDownstreamEnvelope(
            held_out_decision_set_sha256="8" * 64,
            representation_protocol_sha256="9" * 64,
            execution_protocol_sha256="b" * 64,
            sources_per_condition=3,
            per_source_context_token_ceiling=2_000,
            total_context_token_ceiling=6_000,
        ),
        created_at=_AT,
    )

    assert plan.mining_run.locator == "evidence/MINING_RUN.json"
    assert plan.mining_run.file_sha256 == hashlib.sha256(run_path.read_bytes()).hexdigest()
    assert plan.mining_report.semantic_sha256 == mining_report.report_sha256
    assert plan.source_admission_report.semantic_sha256 == source_report.report_sha256
    assert plan.ready_for_owner_approval is True


def test_h0_freeze_rejects_changed_upstream_bytes(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    plan_path = tmp_path / "controls/PLAN.json"
    save_reference_selection_plan(plan, plan_path)
    plan_inspection = load_reference_selection_plan(plan_path)
    approval = approve_reference_selection_comparison(
        plan_inspection,
        confirmed_plan_sha256=plan.plan_sha256,
        approved_by="h0-owner",
        approved_at=_AT.replace(hour=1),
    )
    approval_path = tmp_path / "controls/APPROVAL.json"
    save_reference_selection_approval(approval, approval_path)
    mining_report = tmp_path / plan.mining_report.locator
    mining_report.write_bytes(mining_report.read_bytes() + b" ")

    with pytest.raises(ValueError, match="bound upstream artifacts"):
        freeze_reference_selection_comparison(
            plan_inspection,
            load_reference_selection_approval(approval_path),
            workspace_root=tmp_path,
        )


def test_quality_arm_is_invariant_to_prestige_signal_changes() -> None:
    first = _plan()
    changed_candidates = tuple(
        item.model_copy(
            update={
                "citation_count": (
                    10_000 if item.candidate_id.startswith("candidate-quality") else 0
                )
            }
        )
        for item in first.candidates
    )
    second = first.model_copy(update={"candidates": changed_candidates})
    selections = tuple(
        comparison_module._select_quality(
            comparison_module._quality_views(plan.candidates),
            target_count=plan.target_source_count,
            required_patterns=plan.required_decision_patterns,
            required_roles=plan.required_evidence_roles,
            required_domains=plan.required_domain_facets,
            salt_sha256=plan.stable_tie_break_salt_sha256,
        )
        for plan in (first, second)
    )
    assert selections[0] == selections[1]


def test_ready_plan_cannot_hide_missing_quality_or_prestige_evidence() -> None:
    plan = _plan()
    candidates = tuple(
        item.model_copy(
            update={
                "content_grounded_admitted": False,
                "citation_count": None,
                "publication_year": None,
            }
        )
        for item in plan.candidates
    )

    with pytest.raises(ValidationError, match="omits an intrinsic blocker"):
        type(plan).model_validate(
            {
                **plan.model_dump(mode="json", exclude={"plan_sha256"}),
                "candidates": [item.model_dump(mode="json") for item in candidates],
                "blocker_codes": [],
                "ready_for_owner_approval": True,
            }
        )


def test_reference_selection_cli_runs_the_closed_plan_approval_freeze_chain(
    tmp_path: Path, capsys
) -> None:
    run, mining_report, source_report, links = _upstreams()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    run_path = evidence / "MINING_RUN.json"
    report_path = evidence / "MINING_REPORT.json"
    admission_path = evidence / "SOURCE_ADMISSION.json"
    run_path.write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report_path.write_text(mining_report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    admission_path.write_text(source_report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    plan_path = tmp_path / "controls/PLAN.json"
    source_link_args = [
        value
        for link in links
        for value in ("--source-link", f"{link.candidate_id}={link.source_id}")
    ]

    assert (
        main(
            [
                "evaluation",
                "reference-selection-plan",
                "--mining-run",
                str(run_path),
                "--mining-report",
                str(report_path),
                "--source-admission-report",
                str(admission_path),
                "--evidence-root",
                str(tmp_path),
                *source_link_args,
                "--comparison-id",
                "h0-quality-vs-prestige-v1",
                "--project-id",
                "h0-project",
                "--report-output",
                "outputs/H0_SELECTION.json",
                "--metadata-snapshot-year",
                "2026",
                "--minimum-observed-prestige-fraction",
                "1.0",
                "--stable-tie-break-salt-sha256",
                _SHA,
                "--target-source-count",
                "3",
                "--held-out-decision-set-sha256",
                "8" * 64,
                "--representation-protocol-sha256",
                "9" * 64,
                "--execution-protocol-sha256",
                "b" * 64,
                "--per-source-context-token-ceiling",
                "2000",
                "--created-at",
                _AT.isoformat(),
                "--output",
                str(plan_path),
                "--require-ready",
            ]
        )
        == 0
    )
    plan_summary = json.loads(capsys.readouterr().out)
    approval_path = tmp_path / "controls/APPROVAL.json"
    assert (
        main(
            [
                "evaluation",
                "reference-selection-approve",
                "--plan",
                str(plan_path),
                "--confirm-plan-sha256",
                plan_summary["plan_sha256"],
                "--approved-by",
                "h0-owner",
                "--approved-at",
                _AT.replace(hour=1).isoformat(),
                "--output",
                str(approval_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    output = tmp_path / "outputs/H0_SELECTION.json"
    assert (
        main(
            [
                "evaluation",
                "reference-selection-freeze",
                "--plan",
                str(plan_path),
                "--approval",
                str(approval_path),
                "--workspace-root",
                str(tmp_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    frozen = json.loads(capsys.readouterr().out)

    assert frozen["deterministic_replay_verified"] is True
    assert frozen["exact_stratum_parity"] is True
    assert frozen["model_calls_performed"] is False
    assert output.is_file()

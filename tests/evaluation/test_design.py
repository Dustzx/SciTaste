from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scitaste.evaluation import (
    ApprovalRecord,
    ComparisonBlock,
    EvaluationTask,
    EvaluationTrack,
    EvidenceRole,
    ExperimentDesignGate,
    ExperimentDesignState,
    ExternalResourceCorpus,
    FailureAttribution,
    FailureObservation,
    FrameworkRole,
    FrameworkSpec,
    RecursiveProjectContract,
    ResourceGateStatus,
    StatisticalDesign,
    attribute_failure,
    load_external_resource_corpus,
)

HASH = "a" * 64
CORPUS_PATH = Path("docs/research/data/autoresearch_evaluation_resources_v2.yaml")
RESOURCE_COMMITS = {
    "mlr-agent": "f728d571a992d71c8b526eeb4d9ab6bb5c8cc824",
    "ai-scientist-v2": "96bd51617cfdbb494a9fc283af00fe090edfae48",
}


def _admitted_corpus() -> ExternalResourceCorpus:
    corpus = load_external_resource_corpus(CORPUS_PATH).corpus
    admitted_ids = {"mlr-bench", "mlr-agent", "ai-scientist-v2"}
    resources = []
    for resource in corpus.resources:
        if resource.resource_id not in admitted_ids:
            resources.append(resource)
            continue
        gates = {
            name: decision.model_copy(
                update={
                    "status": (
                        ResourceGateStatus.NOT_APPLICABLE
                        if decision.status is ResourceGateStatus.NOT_APPLICABLE
                        else ResourceGateStatus.VERIFIED
                    )
                }
            )
            for name, decision in resource.gates.items()
        }
        resources.append(resource.model_copy(update={"gates": gates}))
    return corpus.model_copy(update={"resources": tuple(resources)})


def _framework(
    system_id: str,
    role: FrameworkRole,
    *,
    real: bool = True,
) -> FrameworkSpec:
    commit = RESOURCE_COMMITS.get(system_id, "deadbeef")
    return FrameworkSpec(
        system_id=system_id,
        role=role,
        implementation_ref=f"repo:{system_id}@{commit}",
        resource_id=system_id if role is FrameworkRole.EXTERNAL else None,
        independent_from_scitaste=role != FrameworkRole.SCITASTE,
        real_implementation=real,
        task_semantics_compatible=True,
        resource_telemetry_complete=True,
    )


def _design(*, approval: ApprovalRecord | None = None) -> ExperimentDesignState:
    corpus = _admitted_corpus()
    return ExperimentDesignState(
        design_id="iclr27-evaluation",
        design_version="proposal-v1",
        protocol_id="formal-v2",
        paper_claim="Scientific taste improves evidence-grounded research outcomes.",
        resource_corpus_sha256=corpus.semantic_sha256,
        frameworks=[
            _framework("scitaste-native", FrameworkRole.SCITASTE),
            _framework("mlr-agent", FrameworkRole.EXTERNAL),
            _framework("ai-scientist-v2", FrameworkRole.EXTERNAL),
            _framework("direct-agent", FrameworkRole.CONTROL),
        ],
        tasks=[
            EvaluationTask(
                task_id="mlr-task-1",
                track=EvaluationTrack.FULL_LIFECYCLE,
                benchmark_id="mlr-bench",
                benchmark_resource_id="mlr-bench",
                source_group_id="source-paper-1",
                asset_manifest_sha256=HASH,
                held_out=True,
                public_or_retrievable_assets=True,
                executable_success_signal=True,
                paper_required=True,
            ),
            EvaluationTask(
                task_id="self-case",
                track=EvaluationTrack.SELF_DEVELOPMENT,
                benchmark_id="scitaste",
                source_group_id="scitaste-self-development",
                asset_manifest_sha256="b" * 64,
                held_out=False,
                self_referential=True,
                overlaps_parent_evidence=True,
                public_or_retrievable_assets=True,
                executable_success_signal=True,
                paper_required=True,
            ),
        ],
        comparison_blocks=[
            ComparisonBlock(
                block_id="mlr-headline",
                track=EvaluationTrack.FULL_LIFECYCLE,
                evidence_role=EvidenceRole.HEADLINE,
                system_ids=[
                    "scitaste-native",
                    "mlr-agent",
                    "ai-scientist-v2",
                    "direct-agent",
                ],
                task_ids=["mlr-task-1"],
                seeds=[11, 22, 33],
                budget_ref="budgets/formal-v2.json",
                matched_backbone=True,
                matched_starting_information=True,
                matched_tool_permissions=True,
                matched_repair_policy=True,
            ),
            ComparisonBlock(
                block_id="self-process-case",
                track=EvaluationTrack.SELF_DEVELOPMENT,
                evidence_role=EvidenceRole.PROCESS_ONLY,
                system_ids=["scitaste-native", "direct-agent"],
                task_ids=["self-case"],
                seeds=[0],
                budget_ref="budgets/self-case.json",
                matched_backbone=False,
                matched_starting_information=False,
                matched_tool_permissions=False,
                matched_repair_policy=False,
            ),
        ],
        statistical_designs=[
            StatisticalDesign(
                track=EvaluationTrack.FULL_LIFECYCLE,
                experimental_unit="task-seed trajectory",
                primary_endpoint="blinded expert preference for evidence validity",
                estimand="paired mean preference under matched budgets",
                power_analysis_ref="analysis/power-v1.json",
                failure_policy="all failed and rescued runs remain outcomes",
                condition_blinded=True,
                min_reviewers_per_artifact=2,
                judge_validation_ref="analysis/judge-validation-v1.json",
            )
        ],
        recursion=RecursiveProjectContract(
            product_id="scitaste",
            self_development_project_id="scitaste-self-development",
            formal_project_prefix="scitaste-eval-formal-v2",
            feedback_creates_new_protocol=True,
            self_case_excluded_from_headline=True,
            paper_uses_admitted_evidence_only=True,
        ),
        approval=approval or ApprovalRecord(),
    )


def _gate(design: ExperimentDesignState):
    return ExperimentDesignGate().evaluate(design, resource_corpus=_admitted_corpus())


def test_complete_design_is_ready_but_not_authorized_without_approval() -> None:
    report = _gate(_design())

    assert report.design_complete is True
    assert report.ready_for_human_approval is True
    assert report.execution_authorized is False
    assert [item.code for item in report.authorization_blockers] == ["human_approval_required"]


def test_hash_bound_approval_authorizes_a_complete_design() -> None:
    proposal = _design()
    approved = _design(
        approval=ApprovalRecord(
            approved=True,
            approved_design_sha256=proposal.proposal_sha256,
            approved_by="author",
            approved_at="2026-09-13T09:00:00+08:00",
        )
    )

    report = _gate(approved)

    assert report.execution_authorized is True
    assert report.authorization_blockers == []


def test_self_development_case_cannot_enter_headline_estimate() -> None:
    design = _design()
    headline = design.comparison_blocks[0].model_copy(
        update={"task_ids": ["mlr-task-1", "self-case"]}
    )
    invalid = design.model_copy(
        update={"comparison_blocks": [headline, design.comparison_blocks[1]]}
    )

    report = _gate(invalid)

    assert "headline_task_not_independent" in {item.code for item in report.blockers}


def test_pseudo_external_system_blocks_design() -> None:
    design = _design()
    frameworks = [
        framework.model_copy(update={"real_implementation": False})
        if framework.system_id == "ai-scientist-v2"
        else framework
        for framework in design.frameworks
    ]

    report = _gate(design.model_copy(update={"frameworks": frameworks}))

    assert "pseudo_implementation" in {item.code for item in report.blockers}


def test_incomplete_headline_design_reports_independent_gate_failures() -> None:
    design = _design()
    frameworks = [
        framework.model_copy(
            update={
                "core_modified": framework.system_id == "mlr-agent",
                "task_semantics_compatible": framework.system_id != "mlr-agent",
                "resource_telemetry_complete": framework.system_id != "mlr-agent",
                "real_implementation": framework.system_id != "direct-agent",
            }
        )
        for framework in design.frameworks
    ]
    task = design.tasks[0].model_copy(
        update={
            "held_out": False,
            "self_referential": True,
            "overlaps_parent_evidence": True,
            "public_or_retrievable_assets": False,
            "executable_success_signal": False,
            "paper_required": False,
        }
    )
    headline = design.comparison_blocks[0].model_copy(
        update={
            "system_ids": ["mlr-agent", "direct-agent"],
            "matched_backbone": False,
            "matched_starting_information": False,
            "matched_tool_permissions": False,
            "matched_repair_policy": False,
        }
    )
    statistical = design.statistical_designs[0].model_copy(
        update={
            "power_analysis_ref": None,
            "condition_blinded": False,
            "min_reviewers_per_artifact": 0,
            "judge_validation_ref": None,
        }
    )
    recursion = design.recursion.model_copy(
        update={
            "feedback_creates_new_protocol": False,
            "self_case_excluded_from_headline": False,
            "paper_uses_admitted_evidence_only": False,
        }
    )
    incomplete = design.model_copy(
        update={
            "frameworks": frameworks,
            "tasks": [task, design.tasks[1]],
            "comparison_blocks": [headline, design.comparison_blocks[1]],
            "statistical_designs": [statistical],
            "recursion": recursion,
        }
    )

    report = _gate(incomplete)
    codes = {item.code for item in report.blockers}

    assert report.design_complete is False
    assert {
        "missing_scitaste_headline",
        "insufficient_external_systems",
        "external_core_modified",
        "incompatible_task_semantics",
        "incomplete_resource_telemetry",
        "pseudo_implementation",
        "headline_task_not_independent",
        "task_assets_unavailable",
        "task_not_executable",
        "full_lifecycle_without_paper",
        "unmatched_headline_block",
        "missing_power_analysis",
        "review_not_blinded",
        "insufficient_human_reviewers",
        "judge_not_validated",
        "mutable_formal_protocol",
        "self_case_in_headline",
        "paper_not_evidence_bound",
    } <= codes


def test_missing_full_lifecycle_headline_is_explicit() -> None:
    design = _design()
    blocks = [
        block.model_copy(update={"evidence_role": EvidenceRole.MECHANISM})
        if block.track == EvaluationTrack.FULL_LIFECYCLE
        else block
        for block in design.comparison_blocks
    ]

    report = _gate(design.model_copy(update={"comparison_blocks": blocks}))

    assert {item.code for item in report.blockers} == {"missing_full_lifecycle_headline"}


def test_real_audited_corpus_blocks_unready_benchmark_and_systems() -> None:
    corpus = load_external_resource_corpus(CORPUS_PATH).corpus
    design = _design().model_copy(update={"resource_corpus_sha256": corpus.semantic_sha256})

    report = ExperimentDesignGate().evaluate(design, resource_corpus=corpus)
    codes = {item.code for item in report.blockers}

    assert "external_resource_not_admitted" in codes
    assert "task_resource_not_admitted" in codes
    assert report.execution_authorized is False


def test_resource_corpus_is_required_and_hash_bound() -> None:
    design = _design()

    missing = ExperimentDesignGate().evaluate(design)
    mismatch = ExperimentDesignGate().evaluate(
        design.model_copy(update={"resource_corpus_sha256": "c" * 64}),
        resource_corpus=_admitted_corpus(),
    )

    assert {item.code for item in missing.blockers} == {"missing_resource_corpus"}
    assert {item.code for item in mismatch.blockers} == {"resource_corpus_hash_mismatch"}


def test_framework_implementation_must_bind_admitted_commit() -> None:
    design = _design()
    frameworks = [
        framework.model_copy(update={"implementation_ref": "repo:mlr-agent@wrong"})
        if framework.system_id == "mlr-agent"
        else framework
        for framework in design.frameworks
    ]

    report = _gate(design.model_copy(update={"frameworks": frameworks}))

    assert "framework_pin_mismatch" in {item.code for item in report.blockers}


def test_resource_references_must_be_closed() -> None:
    design = _design()
    frameworks = [
        framework.model_copy(update={"resource_id": "unknown-system"})
        if framework.system_id == "mlr-agent"
        else framework
        for framework in design.frameworks
    ]
    task = design.tasks[0].model_copy(update={"benchmark_resource_id": "unknown-benchmark"})

    report = _gate(
        design.model_copy(update={"frameworks": frameworks, "tasks": [task, design.tasks[1]]})
    )
    codes = {item.code for item in report.blockers}

    assert "unknown_framework_resource" in codes
    assert "unknown_task_resource" in codes


def test_external_framework_requires_resource_id() -> None:
    with pytest.raises(ValidationError, match="require an evaluation resource ID"):
        FrameworkSpec(
            system_id="external",
            role=FrameworkRole.EXTERNAL,
            implementation_ref="repo:external@deadbeef",
            independent_from_scitaste=True,
            real_implementation=True,
            task_semantics_compatible=True,
            resource_telemetry_complete=True,
        )


def test_approval_must_bind_current_proposal_hash() -> None:
    design = _design()
    approved = design.model_copy(
        update={
            "approval": ApprovalRecord(
                approved=True,
                approved_design_sha256="c" * 64,
                approved_by="author",
                approved_at="2026-09-13T09:00:00+08:00",
            )
        }
    )

    report = _gate(approved)

    assert report.execution_authorized is False
    assert [item.code for item in report.authorization_blockers] == ["approval_hash_mismatch"]


def test_design_rejects_unknown_block_references() -> None:
    design = _design()
    block = design.comparison_blocks[0].model_copy(
        update={"system_ids": ["scitaste-native", "missing-system"]}
    )

    with pytest.raises(ValidationError, match="unknown framework ids"):
        ExperimentDesignState.model_validate(
            design.model_dump(mode="json") | {"comparison_blocks": [block.model_dump()]}
        )


def _failure(**updates: bool | str) -> FailureObservation:
    values: dict[str, bool | str] = {
        "primary_state_sha256": HASH,
        "comparator_state_sha256": HASH,
        "primary_model_succeeded": False,
        "comparator_model_succeeded": False,
        "native_base_succeeded": False,
        "full_scitaste_succeeded": False,
        "proposed_plan_sound": False,
        "representable_by_framework": True,
        "executable_by_framework": True,
        "context_complete": True,
        "resource_or_environment_failure": False,
    }
    values.update(updates)
    return FailureObservation.model_validate(values)


def test_cross_model_success_is_only_a_model_limit_candidate_on_same_state() -> None:
    attribution = attribute_failure(_failure(comparator_model_succeeded=True))

    assert attribution == FailureAttribution.MODEL_LIMIT_CANDIDATE


def test_base_success_full_failure_is_framework_regression() -> None:
    attribution = attribute_failure(
        _failure(native_base_succeeded=True, full_scitaste_succeeded=False)
    )

    assert attribution == FailureAttribution.FRAMEWORK_INDUCED_REGRESSION


def test_sound_unrepresentable_plan_is_framework_limit() -> None:
    attribution = attribute_failure(
        _failure(proposed_plan_sound=True, representable_by_framework=False)
    )

    assert attribution == FailureAttribution.FRAMEWORK_LIMIT


def test_resource_failure_is_not_assigned_to_model_or_framework() -> None:
    attribution = attribute_failure(
        _failure(
            comparator_model_succeeded=True,
            native_base_succeeded=True,
            resource_or_environment_failure=True,
        )
    )

    assert attribution == FailureAttribution.RESOURCE_ENVIRONMENT_FAILURE


def test_missing_context_has_distinct_attribution() -> None:
    attribution = attribute_failure(_failure(context_complete=False))

    assert attribution == FailureAttribution.CONTEXT_TOOLING_GAP


def test_shared_failure_remains_unresolved() -> None:
    attribution = attribute_failure(_failure())

    assert attribution == FailureAttribution.UNRESOLVED

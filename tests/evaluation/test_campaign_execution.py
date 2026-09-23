from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

from scitaste.benchmark.study_models import StudyOutcome
from scitaste.evaluation import (
    AdapterEvidenceKind,
    AnalysisContract,
    CorpusParityDimension,
    EvaluationCampaignActivation,
    EvaluationCampaignLaunchConfig,
    EvaluationCampaignManifest,
    EvaluationCommandLauncher,
    ExecutionLane,
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    GpuModelResource,
    HumanReviewResource,
    IntegrityContract,
    NativeConditionPreflightReport,
    NativePathRequirement,
    PrelaunchApproval,
    PrelaunchSystem,
    PrelaunchTask,
    ProjectEvaluationCampaignRunner,
    ReadinessStatus,
    RetentionContract,
    ScientificLaneRole,
    SystemRole,
    approve_evaluation_campaign_activation,
    compile_evaluation_campaign_activation,
    compile_evaluation_cell_plan,
    load_prelaunch_manifest,
)
from scitaste.evaluation.campaign_execution import (
    _has_registered_primary_evaluation_attempt,
    _requires_formal_h4,
)
from scitaste.project import (
    ProjectEvaluationArtifact,
    ProjectEvaluationBundle,
    ProjectManifest,
    ProjectRun,
    ProjectRuntime,
)
from scitaste.project.models import content_sha256

SHA = "a" * 64


def _manifest() -> ExperimentPrelaunchManifest:
    systems = (
        PrelaunchSystem(
            system_id="scitaste-native",
            role=SystemRole.SCITASTE,
            implementation_ref="git://scitaste@0123456789abcdef",
            availability=ReadinessStatus.VERIFIED,
            real_implementation=True,
        ),
        PrelaunchSystem(
            system_id="native-base",
            role=SystemRole.ABLATION,
            implementation_ref="git://scitaste@0123456789abcdef#base",
            availability=ReadinessStatus.VERIFIED,
            real_implementation=True,
        ),
    )
    lane = ExecutionLane(
        lane_id="gpu-pilot",
        kind=ExecutionLaneKind.GPU,
        scientific_role=ScientificLaneRole.SMALL_MODEL_ROBUSTNESS,
        system_ids=tuple(item.system_id for item in systems),
        task_ids=("heldout-task",),
        seeds=(7,),
        repetitions=1,
        planned_cells=2,
        gpu_resource=GpuModelResource(
            host_alias="local-test",
            device_count=1,
            device_name="test-device",
            minimum_memory_mb_per_device=1,
            checkpoint_id="test-checkpoint",
            checkpoint_source_path="/weights/test-checkpoint",
            checkpoint_sha256=SHA,
            checkpoint_bytes=1,
            license_identifier="Apache-2.0",
            local_preflight_status=ReadinessStatus.VERIFIED,
            remote_inventory_status=ReadinessStatus.VERIFIED,
            remote_inventory_ref="evidence/inventory.json",
            remote_inventory_sha256=SHA,
            remote_checkpoint_status=ReadinessStatus.VERIFIED,
            remote_checkpoint_attestation_ref="evidence/checkpoint.json",
            remote_checkpoint_attestation_sha256=SHA,
            max_gpu_hours=1,
            max_storage_bytes=1_000_000,
            network_access=False,
        ),
    )
    payload = {
        "schema_version": "1.0",
        "manifest_id": "campaign-runtime-test",
        "protocol_id": "campaign-runtime-test",
        "protocol_version": "test-v1",
        "study_scope": "robustness",
        "scientific_question": "Can the exact authorized matrix execute and resume?",
        "claim_allowed": "Engineering execution evidence only.",
        "claim_forbidden": "No scientific effectiveness claim.",
        "source_commit": "0" * 40,
        "resource_corpus_sha256": SHA,
        "systems": systems,
        "tasks": (
            PrelaunchTask(
                task_id="heldout-task",
                benchmark_resource_id="benchmark-test",
                split="source-disjoint-test",
                selected_asset_manifest="evidence/task.json",
                asset_manifest_sha256=SHA,
                license_status=ReadinessStatus.VERIFIED,
                asset_status=ReadinessStatus.VERIFIED,
                held_out=True,
                source_group_disjoint=True,
            ),
        ),
        "lanes": (lane,),
        "human_review": HumanReviewResource(
            required=False,
            minimum_reviewers_per_artifact=0,
            condition_blinded=False,
            conflict_check_required=False,
            recruitment_status=ReadinessStatus.PENDING,
            rubric_status=ReadinessStatus.PENDING,
            adjudication_status=ReadinessStatus.PENDING,
            maximum_reviewer_hours=0,
        ),
        "retention": RetentionContract(
            output_root="outputs/projects/campaign-project/runs/campaign",
            archive_root="outputs/archive/campaign-project",
            maximum_output_bytes=1_000_000,
            retain_raw_provider_responses=True,
            retain_failed_runs=True,
            secrets_forbidden=True,
        ),
        "analysis": AnalysisContract(
            primary_outcome="Measured task progress.",
            estimand="Paired condition difference.",
            analysis_unit="held-out task",
            aggregation_method="paired mean",
            uncertainty_method="task-clustered interval",
            power_analysis_ref="evidence/power.json",
            power_analysis_sha256=SHA,
        ),
        "integrity": IntegrityContract(
            preregistration_ref="evidence/preregistration.md",
            preregistration_sha256=SHA,
            task_freeze_ref="evidence/tasks.json",
            task_freeze_sha256=SHA,
            failure_policy_ref="evidence/failures.md",
            failure_policy_sha256=SHA,
            repair_policy_ref="evidence/repairs.md",
            repair_policy_sha256=SHA,
            leakage_audit_ref="evidence/leakage.json",
            leakage_audit_sha256=SHA,
            judge_protocol_ref="evidence/judge.json",
            judge_protocol_sha256=SHA,
        ),
        "launch_order": (lane.lane_id,),
        "stop_rules": ("Stop at the exact cell resource ceiling.",),
        "approval": PrelaunchApproval(),
    }
    draft = ExperimentPrelaunchManifest.model_validate(payload)
    payload["approval"] = PrelaunchApproval(
        approved=True,
        approved_proposal_sha256=draft.proposal_sha256,
        approved_by="project-owner",
        approved_at="2026-09-14T00:00:00Z",
    )
    return ExperimentPrelaunchManifest.model_validate(payload)


def _publish_evaluation(
    runtime: ProjectRuntime, manifest: ExperimentPrelaunchManifest, *, authorized: bool
) -> None:
    plan = compile_evaluation_cell_plan(manifest)
    payloads = {
        "PRELAUNCH.yaml": yaml.safe_dump(
            manifest.model_dump(mode="json"), sort_keys=False
        ).encode(),
        "RESOURCE_CORPUS.yaml": b"schema_version: 'test'\nresources: []\n",
        "GATE_REPORT.json": b"{}\n",
        "CRITIC_REPORT.json": b"{}\n",
        "CELL_PLAN.json": (plan.model_dump_json(indent=2) + "\n").encode(),
    }
    names = {
        "prelaunch_manifest": "PRELAUNCH.yaml",
        "resource_corpus": "RESOURCE_CORPUS.yaml",
        "gate_report": "GATE_REPORT.json",
        "critic_report": "CRITIC_REPORT.json",
        "cell_plan": "CELL_PLAN.json",
    }
    files = {
        label: ProjectEvaluationArtifact(
            locator=locator,
            sha256=hashlib.sha256(payloads[locator]).hexdigest(),
            size_bytes=len(payloads[locator]),
        )
        for label, locator in names.items()
    }
    bundle_payload = {
        "schema_version": "1.0",
        "project_id": "campaign-project",
        "evaluation_id": "authorized-pilot",
        "manifest_id": manifest.manifest_id,
        "protocol_id": manifest.protocol_id,
        "study_scope": manifest.study_scope,
        "status": "execution_authorized" if authorized else "blocked",
        "proposal_sha256": manifest.proposal_sha256,
        "planned_cells": len(plan.cells),
        "system_ids": [item.system_id for item in manifest.systems],
        "task_ids": [item.task_id for item in manifest.tasks],
        "lane_ids": [item.lane_id for item in manifest.lanes],
        "api_resources": [],
        "gpu_resources": ["local-test/1xtest-device/test-checkpoint@sha256:" + SHA],
        "ready_for_author_review": authorized,
        "execution_authorized": authorized,
        "observed_source_commit": "0" * 40,
        "source_tree_clean": True,
        "readiness_blocker_codes": [] if authorized else ["adapter:not-ready"],
        "authorization_blocker_codes": [] if authorized else ["readiness_gates_failed"],
        "critic_blocking_codes": [],
        "cell_plan_blockers": [],
        "files": {key: value.model_dump(mode="json") for key, value in files.items()},
        "no_execution_performed": True,
    }
    bundle_payload["bundle_sha256"] = content_sha256(bundle_payload)
    runtime.publish_evaluation(
        "campaign-project",
        ProjectEvaluationBundle.model_validate(bundle_payload),
        artifact_payloads=payloads,
        expected_revision=0,
    )


def _outcome() -> StudyOutcome:
    return StudyOutcome(
        useful_results=1,
        proposed_ideas=1,
        valid_ideas=1,
        pilots=1,
        discarded_ideas=0,
        unproductive_experiments=0,
        total_experiments=1,
        gpu_hours_before_useful_signal=0.0,
        pivots=0,
        correct_pivots=0,
        evidence_sufficiency=0.8,
        reviewer_concerns_opened=0,
        reviewer_concerns_closed=0,
        total_claims=1,
        unsupported_claims=0,
    )


def _launch_config() -> EvaluationCampaignLaunchConfig:
    outcome = json.dumps(_outcome().model_dump(mode="json"), separators=(",", ":"))
    script = (
        "import json,os,pathlib;"
        "root=pathlib.Path(os.environ['SCITASTE_EVALUATION_CELL_DIR']);"
        "artifact=root/'paper.md';artifact.write_text('measured output\\n');"
        f"outcome={outcome};"
        "payload={'schema_version':'1.0','status':'succeeded','evidence_class':'real',"
        "'usage':{'request_count':1,'input_tokens':12,'output_tokens':3,"
        "'max_input_tokens_observed':12,'max_output_tokens_observed':3,"
        "'experiment_count':1},'outcome':outcome,'artifact_paths':['paper.md']};"
        "pathlib.Path(os.environ['SCITASTE_EVALUATION_CELL_RESULT']).write_text("
        "json.dumps(payload))"
    )
    launcher = EvaluationCommandLauncher(
        command=(sys.executable, "-c", script),
        timeout_seconds=30,
        gpu_count=1,
    )
    return EvaluationCampaignLaunchConfig(
        launchers={"scitaste-native": launcher, "native-base": launcher}
    )


def _fail_once_launch_config() -> EvaluationCampaignLaunchConfig:
    outcome = json.dumps(_outcome().model_dump(mode="json"), separators=(",", ":"))
    script = (
        "import json,os,pathlib;"
        "root=pathlib.Path(os.environ['SCITASTE_EVALUATION_CELL_DIR']);"
        "marker=root.parent/(root.name+'.attempted');first=not marker.exists();"
        "marker.write_text('attempted');"
        "artifact=root/'paper.md';"
        f"outcome={outcome};"
        "payload=({'schema_version':'1.0','status':'failed','evidence_class':'real',"
        "'usage':{'experiment_count':1},'error_code':'measured-first-attempt-failure'}"
        " if first else {'schema_version':'1.0','status':'succeeded','evidence_class':'real',"
        "'usage':{'experiment_count':1},'outcome':outcome,'artifact_paths':['paper.md']});"
        "artifact.write_text('measured output\\n') if not first else None;"
        "pathlib.Path(os.environ['SCITASTE_EVALUATION_CELL_RESULT']).write_text("
        "json.dumps(payload))"
    )
    fail_once = EvaluationCommandLauncher(
        command=(sys.executable, "-c", script),
        timeout_seconds=30,
        gpu_count=1,
    )
    always_succeed = _launch_config().launchers["native-base"]
    return EvaluationCampaignLaunchConfig(
        launchers={"scitaste-native": fail_once, "native-base": always_succeed}
    )


def _five_arm_activation_fixture(
    tmp_path: Path,
) -> tuple[
    ExperimentPrelaunchManifest,
    EvaluationCampaignLaunchConfig,
    EvaluationCampaignActivation,
    Path,
]:
    source = load_prelaunch_manifest(
        "configs/evaluation/prelaunch/qwen3vl2b_native_taste_mechanism_prepilot_v12.yaml"
    ).manifest
    payload = source.model_dump(mode="json")
    payload["schema_version"] = "1.6"
    payload["source_commit"] = "0" * 40
    payload["evidence_program"] = {
        "program_id": "activation-test-program",
        "manifest_ref": "evidence/program.yaml",
        "manifest_file_sha256": SHA,
        "proposal_sha256": SHA,
    }
    payload["approval"] = {"approved": False}
    evidence_root = tmp_path / "activation-evidence"
    report = NativeConditionPreflightReport(
        preflight_id="activation-test-preflight",
        proposal_sha256=SHA,
        source_commit="0" * 40,
        observed_head_commit="0" * 40,
        source_commit_available=True,
        source_commit_is_ancestor=True,
        static_action_path_verified=True,
        model_candidate_generation_verified=True,
        corpus_curation_runtime_verified=True,
        corpus_pair_verified=True,
        checkpoint_execution_verified=True,
        ready_for_experiment=True,
        verified_requirements=tuple(NativePathRequirement),
        pending_requirements=(),
        blocked_requirements=(),
        corpus_parity_status={
            dimension: ReadinessStatus.VERIFIED for dimension in CorpusParityDimension
        },
        blockers=(),
    )
    report_bytes = (report.model_dump_json(indent=2) + "\n").encode()
    for system in payload["systems"]:
        system["availability"] = "verified"
        system["implementation_ref"] = f"git://scitaste@{'0' * 40}#{system['system_id']}"
        reference = f"native-preflight/{system['system_id']}.json"
        destination = evidence_root / reference
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(report_bytes)
        system["adapter_preflight_ref"] = reference
        system["adapter_preflight_sha256"] = hashlib.sha256(report_bytes).hexdigest()
        system["adapter_evidence_kind"] = AdapterEvidenceKind.NATIVE_PREFLIGHT_REPORT.value
    for task in payload["tasks"]:
        task["license_status"] = "verified"
        task["asset_status"] = "verified"
    manifest = ExperimentPrelaunchManifest.model_validate(payload)
    plan = compile_evaluation_cell_plan(manifest)
    draft = compile_evaluation_campaign_activation(
        plan,
        activation_id="perception-five-arm-v1",
        project_id="campaign-project",
        evaluation_id="authorized-pilot",
        task_ids=("perception-temporal-action-loc",),
    )
    activation = approve_evaluation_campaign_activation(
        draft,
        confirm_activation_sha256=draft.activation_sha256,
        approved_by="project-owner",
        approved_at="2026-09-14T00:00:00Z",
    )
    outcome = json.dumps(_outcome().model_dump(mode="json"), separators=(",", ":"))
    script = (
        "import hashlib,json,os,pathlib;"
        "root=pathlib.Path(os.environ['SCITASTE_EVALUATION_CELL_DIR']);"
        "request=json.loads(pathlib.Path(os.environ['SCITASTE_EVALUATION_CELL_REQUEST']).read_text());"
        "cell=request['cell'];native=root/'native_benchmark';native.mkdir();"
        "baseline=(0.1263531695 if cell['task_id']=='perception-temporal-action-loc' "
        "else 0.1727912574);score=baseline+0.01;"
        "measurement={'schema_version':'1.0','cell_id':cell['cell_id'],"
        "'task_id':cell['task_id'],'condition_id':cell['system_id'],"
        f"'frozen_candidate_sha256':'{SHA}','heldout_receipt_sha256':'{SHA}',"
        "'metric_name':('mean-average-precision' if cell['task_id']=="
        "'perception-temporal-action-loc' else 'normalized-balanced-accuracy'),"
        "'metric_direction':'higher','heldout_score':score,"
        "'baseline_heldout_score':baseline,'directed_progress':0.01,"
        "'scorer_owned':True,'model_invocations_after_freeze':0};"
        "measurement['measurement_sha256']=hashlib.sha256(json.dumps(measurement,"
        "ensure_ascii=False,separators=(',',':'),sort_keys=True).encode()).hexdigest();"
        "(native/'OBJECTIVE_MEASUREMENT.json').write_text(json.dumps(measurement));"
        f"outcome={outcome};"
        "payload={'schema_version':'1.0','status':'succeeded','evidence_class':'real',"
        "'usage':{'request_count':1,'input_tokens':12,'output_tokens':3,"
        "'max_input_tokens_observed':12,'max_output_tokens_observed':3,"
        "'experiment_count':1},'outcome':outcome,"
        "'artifact_paths':['native_benchmark/OBJECTIVE_MEASUREMENT.json']};"
        "pathlib.Path(os.environ['SCITASTE_EVALUATION_CELL_RESULT']).write_text("
        "json.dumps(payload))"
    )
    launcher = EvaluationCommandLauncher(
        command=(sys.executable, "-c", script),
        timeout_seconds=30,
        gpu_count=1,
    )
    launch_config = EvaluationCampaignLaunchConfig(
        launchers={system.system_id: launcher for system in manifest.systems}
    )
    for reference in (
        "configs/evaluation/analysis/native_taste_mechanism_objective_v1.json",
        "src/scitaste/evaluation/runtime_assets/mlrc_objective_entrypoint.py",
    ):
        destination = evidence_root / reference
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(Path(reference).read_bytes())
    return manifest, launch_config, activation, evidence_root


def _runtime(tmp_path: Path, *, authorized: bool = True) -> ProjectRuntime:
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="campaign-project",
            title="Campaign project",
            research_direction="Exercise an authorized evaluation matrix.",
            status="active",
        )
    )
    _publish_evaluation(runtime, _manifest(), authorized=authorized)
    return runtime


def test_campaign_distinguishes_host_inventory_from_cell_gpu_allocation(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    gpu = manifest.lanes[0].gpu_resource
    assert gpu is not None
    lane = manifest.lanes[0].model_copy(
        update={
            "gpu_resource": gpu.model_copy(
                update={"device_count": 8, "allocated_device_count_per_cell": 1}
            )
        }
    )
    plan = compile_evaluation_cell_plan(manifest.model_copy(update={"lanes": (lane,)}))
    base = _launch_config()
    mismatched = base.model_copy(
        update={
            "launchers": {
                system_id: launcher.model_copy(update={"gpu_count": 2})
                for system_id, launcher in base.launchers.items()
            }
        }
    )
    runner = ProjectEvaluationCampaignRunner(ProjectRuntime(tmp_path / "outputs"), mismatched)

    _launches, blockers = runner._launches(
        "campaign-project", "allocation-check", plan.cells
    )

    assert set(blockers) == {
        "launcher:native-base:gpu-count-allocation-mismatch",
        "launcher:scitaste-native:gpu-count-allocation-mismatch",
    }


def test_development_on_off_pair_does_not_require_formal_h4_preparation() -> None:
    manifest = load_prelaunch_manifest(
        "configs/evaluation/prelaunch/mlrc_perception_native_development_hybrid_v2.yaml"
    ).manifest
    plan = compile_evaluation_cell_plan(manifest)

    assert plan.claim_estimand_kind is None
    assert _requires_formal_h4(plan, plan.cells) is False


def test_campaign_executes_real_subprocesses_and_resumes_exact_successes(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runner = ProjectEvaluationCampaignRunner(runtime, _launch_config())

    first = runner.run(
        project_id="campaign-project",
        evaluation_id="authorized-pilot",
        run_id="campaign-run",
        allow_execution=True,
        max_cells=1,
    )
    assert first.run_status == "partial"
    assert first.executed_cells == 1
    assert first.total_recorded_cells == 1

    completed = runner.run(
        project_id="campaign-project",
        evaluation_id="authorized-pilot",
        run_id="campaign-run",
        allow_execution=True,
        resume=True,
        max_cells=1,
    )
    assert completed.run_status == "cells_complete"
    assert completed.executed_cells == 1
    assert completed.recovered_successes == 1
    assert completed.succeeded_cells == 2
    result_path = runtime.projects_root / "campaign-project" / completed.result_set_locator
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert len(result["cell_results"]) == 2
    assert {item["status"] for item in result["cell_results"]} == {"succeeded"}
    assert {item["usage"]["request_count"] for item in result["cell_results"]} == {1}
    assert {item["usage"]["input_tokens"] for item in result["cell_results"]} == {12}
    assert {item["usage"]["output_tokens"] for item in result["cell_results"]} == {3}
    assert completed.next_required_stage == "objective_analysis_or_blind_review"
    assert completed.handoff_locator is not None
    handoff = json.loads(
        (runtime.projects_root / "campaign-project" / completed.handoff_locator).read_text(
            encoding="utf-8"
        )
    )
    assert handoff["result_set_sha256"] == completed.result_set_sha256
    assert handoff["next_interface"] == "project.evaluation.select-analysis-path"
    assert handoff["performs_next_stage"] is False


def test_campaign_refuses_unready_project_evaluation_without_starting_a_run(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, authorized=False)
    summary = ProjectEvaluationCampaignRunner(runtime, _launch_config()).run(
        project_id="campaign-project",
        evaluation_id="authorized-pilot",
        run_id="blocked-run",
        allow_execution=True,
    )

    assert summary.run_status == "blocked"
    assert "evaluation:not-execution-authorized" in summary.blocker_codes
    assert runtime.open("campaign-project").manifest.runs == []


def test_campaign_requires_activation_for_a_partial_cell_selection(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    cell_id = compile_evaluation_cell_plan(_manifest()).cells[0].cell_id

    with pytest.raises(ValueError, match="approved task-block activation"):
        ProjectEvaluationCampaignRunner(runtime, _launch_config()).run(
            project_id="campaign-project",
            evaluation_id="authorized-pilot",
            run_id="partial-without-activation",
            allow_execution=True,
            cell_ids=(cell_id,),
        )


def test_approved_complete_task_block_runs_without_claim_authority(tmp_path: Path) -> None:
    manifest, launch_config, activation, evidence_root = _five_arm_activation_fixture(tmp_path)
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="campaign-project",
            title="Campaign project",
            research_direction="Exercise a feasibility-only task block.",
            status="active",
        )
    )
    _publish_evaluation(runtime, manifest, authorized=False)

    summary = ProjectEvaluationCampaignRunner(
        runtime, launch_config, evidence_root=evidence_root
    ).run(
        project_id="campaign-project",
        evaluation_id="authorized-pilot",
        run_id="perception-feasibility",
        activation=activation,
        allow_execution=True,
    )

    assert summary.run_status == "feasibility_complete"
    assert summary.selected_cells == 5
    assert summary.executed_cells == 5
    assert summary.next_required_stage == "feasibility_review"
    root = runtime.projects_root / "campaign-project/runs/perception-feasibility"
    campaign = json.loads((root / "evaluation_campaign/CAMPAIGN.json").read_text())
    assert campaign["activation_sha256"] == activation.activation_sha256
    assert campaign["claim_authority"] is False
    handoff = json.loads((root / "evaluation_campaign/HANDOFF.json").read_text())
    assert len(handoff["planned_cell_ids"]) == 5
    assert handoff["next_interface"] == "project.evaluation.inspect-feasibility-block"
    assert handoff["performs_next_stage"] is False


def test_complete_native_objective_campaign_automatically_materializes_analysis(
    tmp_path: Path,
) -> None:
    manifest, launch_config, _activation, evidence_root = _five_arm_activation_fixture(tmp_path)
    payload = manifest.model_dump(mode="json")
    payload["approval"] = {"approved": False}
    draft = ExperimentPrelaunchManifest.model_validate(payload)
    payload["approval"] = PrelaunchApproval(
        approved=True,
        approved_proposal_sha256=draft.proposal_sha256,
        approved_by="project-owner",
        approved_at="2026-09-14T00:00:00Z",
    )
    approved = ExperimentPrelaunchManifest.model_validate(payload)
    runtime = ProjectRuntime(tmp_path / "outputs")
    runtime.create(
        ProjectManifest(
            project_id="campaign-project",
            title="Campaign project",
            research_direction="Close a native objective campaign.",
            status="active",
        )
    )
    _publish_evaluation(runtime, approved, authorized=True)

    summary = ProjectEvaluationCampaignRunner(
        runtime, launch_config, evidence_root=evidence_root
    ).run(
        project_id="campaign-project",
        evaluation_id="authorized-pilot",
        run_id="native-objective-closure",
        allow_execution=True,
    )

    assert summary.run_status == "analysis_complete"
    assert summary.executed_cells == 10
    assert summary.next_required_stage == "result_registration"
    assert summary.objective_measurement_set_locator is not None
    assert summary.objective_analysis_locator is not None
    assert summary.completed_result_set_locator is not None
    project_root = runtime.projects_root / "campaign-project"
    completed = json.loads(
        (project_root / summary.completed_result_set_locator).read_text(encoding="utf-8")
    )
    assert len(completed["cell_results"]) == 10
    assert len(completed["primary_comparisons"]) == 3
    handoff = json.loads(
        (project_root / "runs/native-objective-closure/evaluation_campaign/HANDOFF.json").read_text(
            encoding="utf-8"
        )
    )
    assert handoff["next_interface"] == "project.evaluation.register-result"
    assert handoff["result_set_locator"] == summary.completed_result_set_locator

    resumed = ProjectEvaluationCampaignRunner(
        runtime, launch_config, evidence_root=evidence_root
    ).run(
        project_id="campaign-project",
        evaluation_id="authorized-pilot",
        run_id="native-objective-closure",
        allow_execution=True,
        resume=True,
    )
    assert resumed.run_status == "analysis_complete"
    assert resumed.executed_cells == 0
    assert resumed.recovered_successes == 10
    assert resumed.completed_result_set_sha256 == summary.completed_result_set_sha256


def test_campaign_retains_failed_attempt_then_retries_only_when_explicit(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runner = ProjectEvaluationCampaignRunner(runtime, _fail_once_launch_config())

    failed = runner.run(
        project_id="campaign-project",
        evaluation_id="authorized-pilot",
        run_id="retry-run",
        allow_execution=True,
    )
    assert failed.run_status == "cells_complete_with_failures"
    assert failed.succeeded_cells == 1
    assert failed.failed_cells == 1
    assert failed.next_required_stage == "retry_or_accept_failures"
    failed_handoff = json.loads(
        (runtime.projects_root / "campaign-project" / failed.handoff_locator).read_text(
            encoding="utf-8"
        )
    )
    assert failed_handoff["next_interface"] == "project.evaluation.resolve-cell-failures"
    assert failed_handoff["explicit_retry_decision_required"] is True

    repaired = runner.run(
        project_id="campaign-project",
        evaluation_id="authorized-pilot",
        run_id="retry-run",
        allow_execution=True,
        resume=True,
        retry_failed_cells=True,
    )
    assert repaired.run_status == "cells_complete"
    assert repaired.executed_cells == 1
    assert repaired.recovered_successes == 1
    failed_attempts = list(
        (runtime.projects_root / "campaign-project/runs/retry-run/evaluation_campaign/cells").glob(
            "*/failed_attempts/attempt-001/CELL_RESULT.json"
        )
    )
    assert len(failed_attempts) == 1
    assert json.loads(failed_attempts[0].read_text(encoding="utf-8"))["status"] == "failed"


def test_campaign_archives_an_interrupted_cell_before_resume(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runner = ProjectEvaluationCampaignRunner(runtime, _launch_config())
    first = runner.run(
        project_id="campaign-project",
        evaluation_id="authorized-pilot",
        run_id="interrupted-run",
        allow_execution=True,
        max_cells=1,
    )
    assert first.run_status == "partial"

    result = json.loads(
        (
            runtime.projects_root
            / "campaign-project"
            / "runs/interrupted-run/evaluation_campaign/RESULT_SET.json"
        ).read_text(encoding="utf-8")
    )
    pending_cell_id = next(
        cell_id
        for cell_id in json.loads(
            (
                runtime.projects_root
                / "campaign-project"
                / "runs/interrupted-run/evaluation_campaign/CAMPAIGN.json"
            ).read_text(encoding="utf-8")
        )["selected_cell_ids"]
        if cell_id not in {item["cell_id"] for item in result["cell_results"]}
    )
    interrupted_dir = (
        runtime.projects_root
        / "campaign-project"
        / "runs/interrupted-run/evaluation_campaign/cells"
        / pending_cell_id
    )
    interrupted_dir.mkdir(parents=True)
    (interrupted_dir / "stdout.log").write_text("partial output\n", encoding="utf-8")

    completed = runner.run(
        project_id="campaign-project",
        evaluation_id="authorized-pilot",
        run_id="interrupted-run",
        allow_execution=True,
        resume=True,
    )
    assert completed.run_status == "cells_complete"
    archived = interrupted_dir / "failed_attempts/attempt-001/stdout.log"
    assert archived.read_text(encoding="utf-8") == "partial output\n"
    checkpoint = json.loads((interrupted_dir / "CHECKPOINT.json").read_text(encoding="utf-8"))
    assert checkpoint["attempt"] == 2


def test_exposed_h4_crash_consumes_reservation_and_closes_without_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    runner = ProjectEvaluationCampaignRunner(runtime, _launch_config())
    evaluation = runtime.open_evaluation("campaign-project", "authorized-pilot")
    evaluation_root = runtime.projects_root / "campaign-project/evaluations/authorized-pilot"
    plan = compile_evaluation_cell_plan(
        load_prelaunch_manifest(
            evaluation_root / evaluation.files["prelaunch_manifest"].locator
        ).manifest
    )
    cell = plan.cells[0]
    campaign = EvaluationCampaignManifest.create(
        schema_version="1.2",
        project_id="campaign-project",
        run_id="h4-crash-run",
        evaluation_id="authorized-pilot",
        evaluation_bundle_sha256=evaluation.bundle_sha256,
        proposal_sha256=plan.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        launch_config_sha256=runner.launch_config.config_sha256,
        selected_cell_ids=tuple(item.cell_id for item in plan.cells),
        formal_preparation_sha256="f" * 64,
        claim_authority=True,
        execution_authorized=True,
    )
    snapshot = runtime.begin_run(
        "campaign-project",
        ProjectRun(
            run_id=campaign.run_id,
            provider="scitaste-native",
            model="project-evaluation-campaign-runner",
            condition="authorized-evaluation-campaign",
            seed=0,
            status="running",
            evidence_scope="exact-authorized-cell-execution",
            stage_path="evaluation_campaign",
            evaluation_id=campaign.evaluation_id,
            campaign_manifest_sha256=campaign.manifest_sha256,
            formal_preparation_sha256=campaign.formal_preparation_sha256,
            claim_authority=True,
            h4_primary_attempt_consumed=False,
        ),
        expected_revision=runtime.open("campaign-project").revision,
    )
    root = runtime.projects_root / "campaign-project/runs/h4-crash-run/evaluation_campaign"
    cell_dir = root / "cells" / cell.cell_id
    native_root = cell_dir / "native_benchmark"
    native_root.mkdir(parents=True)
    (native_root / "H4_ARM_REQUEST.json").write_text("{}\n", encoding="utf-8")
    (cell_dir / "CELL_REQUEST.json").write_text("{}\n", encoding="utf-8")
    (cell_dir / "CELL_RESULT.json").write_text('{"partial": true}\n', encoding="utf-8")
    recovered_record = runner._failed_record(
        cell,
        runner.launch_config.launchers[cell.system_id],
        0.0,
        "h4-itt-bounded-failure",
        plan_sha256=plan.plan_sha256,
        experiment_count=1,
    )
    validated: list[str] = []
    monkeypatch.setattr(
        runner,
        "_validate_h4_recovery_arm",
        lambda _root, observed: validated.append(observed.cell_id),
    )
    monkeypatch.setattr(
        runner,
        "_h4_process_failure_record",
        lambda *args, **kwargs: recovered_record,
    )

    updated, recovered = runner._recover_exposed_h4_cells(
        "campaign-project",
        root,
        plan,
        (cell,),
        {},
        campaign,
        snapshot,
    )

    assert recovered == 1
    assert validated == [cell.cell_id]
    registered = next(item for item in updated.manifest.runs if item.run_id == campaign.run_id)
    assert (registered.model_extra or {})["h4_primary_attempt_consumed"] is True
    assert _has_registered_primary_evaluation_attempt(
        updated,
        evaluation_id=campaign.evaluation_id,
    )
    assert (cell_dir / "recovery/partial-CELL_RESULT.json-001").is_file()
    assert json.loads((cell_dir / "CELL_RESULT.json").read_text())["error_code"] == (
        "h4-itt-bounded-failure"
    )
    assert (cell_dir / "CHECKPOINT.json").is_file()

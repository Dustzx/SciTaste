"""Compile scorer-owned native cell artifacts into the generic objective schema."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from scitaste.evaluation.cell_plan import EvaluationCellPlan, PlannedEvaluationCell
from scitaste.evaluation.h4_execution import (
    H4ArmRunRequest,
    H4PairedResult,
    H4TerminalOutcomeReceipt,
    load_h4_arm_run_request,
)
from scitaste.evaluation.native_benchmark_adapter import pair_h4_objective_measurements
from scitaste.evaluation.native_measurement import NativeBenchmarkObjectiveMeasurement
from scitaste.evaluation.objective_analysis import (
    ObjectiveCellMeasurement,
    ObjectiveMeasurementSet,
    ObjectiveOutcomeContractInspection,
    ObjectiveTaskScoreContract,
    objective_cell_population_sha256,
)
from scitaste.evaluation.prelaunch import ExecutionLaneKind
from scitaste.evaluation.results import (
    EvaluationCellResult,
    EvaluationResultArtifact,
    EvaluationResultSet,
)
from scitaste.evaluation.task_research_loop import BenchmarkResearchLoopResult
from scitaste.evaluation.task_scoring import (
    BenchmarkFrozenCandidate,
    BenchmarkHeldoutExecutionReceipt,
    BenchmarkHeldoutRunRequest,
)
from scitaste.project.models import content_sha256

_MAX_MEASUREMENT_BYTES = 16 * 1024 * 1024
_MAX_H4_EVIDENCE_FILE_BYTES = 64 * 1024 * 1024
_H4_SYSTEM_IDS = {
    "full-scitaste-learned-policy",
    "native-base-without-learned-taste",
}


def collect_native_objective_measurements(
    plan: EvaluationCellPlan,
    results: EvaluationResultSet,
    contract: ObjectiveOutcomeContractInspection,
    *,
    project_root: str | Path,
    selected_cell_ids: tuple[str, ...],
) -> ObjectiveMeasurementSet:
    """Collect exact successful selected cells; failed cells remain scoreless floors."""

    root = Path(project_root).resolve(strict=True)
    if results.proposal_sha256 != plan.proposal_sha256 or results.plan_sha256 != plan.plan_sha256:
        raise ValueError("native measurement collection proposal or plan differs")
    planned = {cell.cell_id: cell for cell in plan.cells}
    selected = set(selected_cell_ids)
    if not selected or selected - set(planned):
        raise ValueError("native measurement collection selected unknown cells")
    records = {record.cell_id: record for record in results.cell_results}
    if selected - set(records):
        raise ValueError("native measurement collection requires every selected cell result")
    if set(records) - selected:
        raise ValueError("native measurement collection contains cells outside its campaign")
    task_scores = {item.task_id: item for item in contract.contract.task_scores}

    measurements: list[ObjectiveCellMeasurement] = []
    h4_pairs: dict[
        tuple[str, int, int],
        dict[str, tuple[H4ArmRunRequest, NativeBenchmarkObjectiveMeasurement]],
    ] = {}
    for cell_id in selected_cell_ids:
        cell = planned[cell_id]
        record = records[cell_id]
        h4_cell = cell.system_id in _H4_SYSTEM_IDS
        try:
            task_score = task_scores[cell.task_id]
        except KeyError as exc:
            raise ValueError(
                f"objective outcome contract has no selected task: {cell.task_id}"
            ) from exc
        if record.status == "failed":
            if record.error_code == "h4-itt-bounded-failure":
                native = _validate_h4_itt_failure(
                    root,
                    cell=cell,
                    record=record,
                    task_score=task_score,
                )
                request = _load_h4_arm_request(root, cell=cell, record=record, plan=plan)
                _validate_h4_evidence_tree(
                    root,
                    record,
                    plan=plan,
                    cell=cell,
                    request=request,
                    native=native,
                )
                h4_pairs.setdefault((cell.task_id, cell.seed, cell.repetition), {})[
                    cell.system_id
                ] = (request, native)
            elif h4_cell:
                raise ValueError(
                    f"planned H4 cell lacks a closed ITT terminal outcome: {cell.cell_id}"
                )
            continue
        artifact = _measurement_artifact(record.artifacts)
        path = _verified_project_artifact(root, artifact)
        native = NativeBenchmarkObjectiveMeasurement.model_validate_json(path.read_bytes())
        if h4_cell and native.schema_version != "1.1":
            raise ValueError(f"planned H4 cell used a legacy measurement: {cell.cell_id}")
        if native.schema_version == "1.1":
            if not h4_cell:
                raise ValueError(f"non-H4 cell used an H4 measurement: {cell.cell_id}")
            request = _load_h4_arm_request(root, cell=cell, record=record, plan=plan)
            _validate_h4_evidence_tree(
                root,
                record,
                plan=plan,
                cell=cell,
                request=request,
                native=native,
            )
            h4_pairs.setdefault((cell.task_id, cell.seed, cell.repetition), {})[cell.system_id] = (
                request,
                native,
            )
        if (
            native.cell_id != cell.cell_id
            or native.task_id != cell.task_id
            or native.condition_id != cell.system_id
        ):
            raise ValueError(f"native objective measurement identity differs: {cell.cell_id}")
        if native.metric_name != task_score.metric_id:
            raise ValueError(f"native objective metric differs: {cell.cell_id}")
        if native.metric_direction != task_score.direction.value:
            raise ValueError(f"native objective direction differs: {cell.cell_id}")
        if abs(native.baseline_heldout_score - task_score.starting_score) > 1e-12:
            raise ValueError(f"native objective starting score differs: {cell.cell_id}")
        measurements.append(
            ObjectiveCellMeasurement.create(
                cell_id=cell.cell_id,
                result_record_sha256=record.record_sha256,
                metric_id=task_score.metric_id,
                metric_version=task_score.metric_version,
                raw_score=native.heldout_score,
                score_artifact=artifact,
            )
        )

    paired_results = _validate_h4_pairs(h4_pairs)

    return ObjectiveMeasurementSet.create(
        schema_version="1.1" if paired_results else "1.0",
        project_id=results.project_id,
        evaluation_id=results.evaluation_id,
        proposal_sha256=plan.proposal_sha256,
        plan_sha256=plan.plan_sha256,
        cell_result_population_sha256=objective_cell_population_sha256(results),
        objective_outcome_contract_sha256=contract.file_sha256,
        measurements=tuple(measurements),
        h4_paired_results=paired_results,
    )


def validate_h4_objective_cell_evidence(
    plan: EvaluationCellPlan,
    cell: PlannedEvaluationCell,
    record: EvaluationCellResult,
    task_score: ObjectiveTaskScoreContract,
    *,
    project_root: str | Path,
) -> tuple[H4ArmRunRequest, NativeBenchmarkObjectiveMeasurement]:
    """Revalidate one H4 cell for every public analysis/registration entry point."""

    if cell.system_id not in _H4_SYSTEM_IDS:
        raise ValueError("H4 evidence validation received a non-H4 cell")
    root = Path(project_root).resolve(strict=True)
    if record.status == "failed":
        if record.error_code != "h4-itt-bounded-failure":
            raise ValueError(f"planned H4 cell has an open failure: {cell.cell_id}")
        native = _validate_h4_itt_failure(
            root,
            cell=cell,
            record=record,
            task_score=task_score,
        )
    else:
        artifact = _measurement_artifact(record.artifacts)
        native = NativeBenchmarkObjectiveMeasurement.model_validate_json(
            _verified_project_artifact(root, artifact).read_bytes()
        )
        if (
            native.schema_version != "1.1"
            or native.outcome_status != "measured"
            or native.cell_id != cell.cell_id
            or native.task_id != cell.task_id
            or native.condition_id != cell.system_id
            or native.metric_name != task_score.metric_id
            or native.metric_direction != task_score.direction.value
            or native.baseline_heldout_score != task_score.starting_score
        ):
            raise ValueError(f"native H4 measured evidence differs: {cell.cell_id}")
    request = _load_h4_arm_request(root, cell=cell, record=record, plan=plan)
    _validate_h4_evidence_tree(
        root,
        record,
        plan=plan,
        cell=cell,
        request=request,
        native=native,
    )
    return request, native


def _validate_h4_itt_failure(
    root: Path,
    *,
    cell: PlannedEvaluationCell,
    record: EvaluationCellResult,
    task_score: ObjectiveTaskScoreContract,
) -> NativeBenchmarkObjectiveMeasurement:
    """Verify a treatment-exposed H4 terminal failure before assigning its floor."""

    artifact = _measurement_artifact(record.artifacts)
    path = _verified_project_artifact(root, artifact)
    native = NativeBenchmarkObjectiveMeasurement.model_validate_json(path.read_bytes())
    expected_penalty = (
        task_score.raw_minimum - task_score.starting_score
        if task_score.direction.value == "higher"
        else task_score.starting_score - task_score.raw_maximum
    )
    if (
        native.schema_version != "1.1"
        or native.outcome_status != "itt_bounded_failure"
        or native.cell_id != cell.cell_id
        or native.task_id != cell.task_id
        or native.condition_id != cell.system_id
        or native.metric_name != task_score.metric_id
        or native.metric_direction != task_score.direction.value
        or abs(native.baseline_heldout_score - task_score.starting_score) > 1e-12
        or abs(native.directed_progress - expected_penalty) > 1e-12
    ):
        raise ValueError(f"native H4 ITT failure evidence differs: {cell.cell_id}")
    return native


def _load_h4_arm_request(
    root: Path,
    *,
    cell: PlannedEvaluationCell,
    record: EvaluationCellResult,
    plan: EvaluationCellPlan,
) -> H4ArmRunRequest:
    matches = [
        artifact
        for artifact in record.artifacts
        if PurePosixPath(artifact.locator).name == "H4_ARM_REQUEST.json"
    ]
    if len(matches) != 1:
        raise ValueError("native H4 cell requires one arm-run request artifact")
    request = load_h4_arm_run_request(_verified_project_artifact(root, matches[0]))
    if (
        request.plan_sha256 != plan.plan_sha256
        or request.cell_id != cell.cell_id
        or request.task_id != cell.task_id
        or request.condition.value != cell.system_id
        or request.seed != cell.seed
        or request.repetition != cell.repetition
    ):
        raise ValueError(f"native H4 arm request differs from plan cell: {cell.cell_id}")
    return request


def _validate_h4_pairs(
    pairs: dict[
        tuple[str, int, int],
        dict[str, tuple[H4ArmRunRequest, NativeBenchmarkObjectiveMeasurement]],
    ],
) -> tuple[H4PairedResult, ...]:
    if not pairs:
        return ()
    expected = {
        "full-scitaste-learned-policy",
        "native-base-without-learned-taste",
    }
    paired_results = []
    for (task_id, seed, repetition), arms in sorted(pairs.items()):
        if set(arms) != expected:
            raise ValueError(
                f"native H4 objective population is not paired: {task_id}/{seed}/{repetition}"
            )
        on_request, on_measurement = arms["full-scitaste-learned-policy"]
        off_request, off_measurement = arms["native-base-without-learned-taste"]
        paired_results.append(
            pair_h4_objective_measurements(
                on_request,
                on_measurement,
                off_request,
                off_measurement,
                pair_id=f"h4-{task_id}-{seed}-{repetition}",
            )
        )
    return tuple(paired_results)


def _validate_h4_evidence_tree(
    root: Path,
    record: EvaluationCellResult,
    *,
    plan: EvaluationCellPlan,
    cell: PlannedEvaluationCell,
    request: H4ArmRunRequest,
    native: NativeBenchmarkObjectiveMeasurement,
) -> None:
    matches = [
        artifact
        for artifact in record.artifacts
        if PurePosixPath(artifact.locator).name == "EVIDENCE_INDEX.json"
    ]
    if len(matches) != 1:
        raise ValueError("native H4 cell requires one evidence-tree index")
    index_path = _verified_project_artifact(root, matches[0])
    try:
        payload = json.loads(index_path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("native H4 evidence-tree index is invalid") from exc
    claimed_index_sha256 = payload.get("evidence_index_sha256")
    unsigned_index = dict(payload)
    unsigned_index.pop("evidence_index_sha256", None)
    if claimed_index_sha256 != content_sha256(unsigned_index):
        raise ValueError("native H4 evidence index hash differs")
    entries = payload.get("evidence_files")
    if payload.get("schema_version") != "1.1" or not isinstance(entries, list):
        raise ValueError("native H4 evidence-tree index schema differs")
    if not 1 <= len(entries) <= 5_000 or payload.get("evidence_tree_sha256") != content_sha256(
        tuple(entries)
    ):
        raise ValueError("native H4 evidence-tree population differs")
    native_root = index_path.parent.resolve(strict=True)
    observed: dict[str, Path] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "locator",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("native H4 evidence-tree entry is invalid")
        pure = PurePosixPath(str(entry["locator"]))
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise ValueError("native H4 evidence-tree locator is unsafe")
        candidate = native_root.joinpath(*pure.parts)
        current = native_root
        for part in pure.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("native H4 evidence tree cannot traverse a symbolic link")
        resolved = candidate.resolve(strict=True)
        if (
            not resolved.is_relative_to(native_root)
            or not resolved.is_file()
            or not 1 <= resolved.stat().st_size <= _MAX_H4_EVIDENCE_FILE_BYTES
            or resolved.stat().st_size != entry["size_bytes"]
            or _sha256_file(resolved) != entry["sha256"]
        ):
            raise ValueError("native H4 evidence-tree file differs")
        observed[pure.as_posix()] = resolved
    if "H4_ARM_REQUEST.json" not in observed or not (
        {"development_loop/RESULT.json", "H4_TERMINAL_OUTCOME.json"} & observed
    ):
        raise ValueError("native H4 evidence tree lacks terminal receipts")
    observed_request = H4ArmRunRequest.model_validate_json(
        observed["H4_ARM_REQUEST.json"].read_bytes()
    )
    if observed_request != request:
        raise ValueError("native H4 evidence-tree arm request differs")
    measurement_path = observed.get("OBJECTIVE_MEASUREMENT.json")
    if (
        measurement_path is None
        or NativeBenchmarkObjectiveMeasurement.model_validate_json(measurement_path.read_bytes())
        != native
    ):
        raise ValueError("native H4 evidence-tree objective measurement differs")
    if (
        native.schema_version != "1.1"
        or native.cell_id != request.cell_id
        or native.task_id != request.task_id
        or native.condition_id != request.condition.value
        or native.h4_execution_profile_sha256 != request.profile_sha256
        or native.h4_arm_run_request_sha256 != request.request_sha256
        or native.lifecycle_policy_weight != request.lifecycle_policy_weight
        or native.metric_name != request.primary_metric
        or native.metric_direction != request.metric_direction
        or native.baseline_heldout_score != request.baseline_heldout_score
    ):
        raise ValueError("native H4 measurement and arm request differ")
    expected_links = {
        "campaign_manifest_sha256": request.campaign_manifest_sha256,
        "plan_sha256": plan.plan_sha256,
        "cell_sha256": content_sha256(cell),
        "task_spec_fingerprint": request.task_spec_fingerprint,
        "loop_result_sha256": native.loop_result_sha256,
        "heldout_receipt_sha256": native.heldout_receipt_sha256,
        "objective_measurement_sha256": native.measurement_sha256,
        "terminal_outcome_receipt_sha256": (
            native.terminal_evidence_sha256
            if native.outcome_status == "itt_bounded_failure"
            else None
        ),
    }
    if any(payload.get(key) != value for key, value in expected_links.items()):
        raise ValueError("native H4 evidence index semantic links differ")

    loop = _load_h4_loop_result(observed, native, request, cell)
    candidate = _load_h4_frozen_candidate(observed, native, request, loop)
    heldout = _load_h4_heldout_receipt(observed, native, request, candidate)
    if native.outcome_status == "measured":
        if (
            loop is None
            or candidate is None
            or heldout is None
            or heldout.status != "succeeded"
            or native.terminal_evidence_sha256 != loop.result_sha256
            or "H4_TERMINAL_OUTCOME.json" in observed
        ):
            raise ValueError("native H4 measured terminal evidence differs")
        _validate_h4_success_usage(
            record,
            cell=cell,
            request=request,
            loop=loop,
        )
        return
    _validate_h4_terminal_outcome(
        observed,
        record=record,
        cell=cell,
        request=request,
        native=native,
        loop=loop,
        heldout=heldout,
    )


def _validate_h4_success_usage(
    record: EvaluationCellResult,
    *,
    cell: PlannedEvaluationCell,
    request: H4ArmRunRequest,
    loop: BenchmarkResearchLoopResult,
) -> None:
    """Close successful H4 runner telemetry against the evidence-producing loop."""

    requests = sum(item.decision_sha256 is not None for item in loop.iterations)
    expected = (
        requests,
        loop.input_tokens,
        loop.output_tokens,
        loop.max_input_tokens_observed,
        loop.max_output_tokens_observed,
        (loop.model_cost_usd if cell.lane_kind is ExecutionLaneKind.API_ONLY else None),
        loop.development_experiment_count + 1,
    )
    observed = (
        record.usage.request_count,
        record.usage.input_tokens,
        record.usage.output_tokens,
        record.usage.max_input_tokens_observed,
        record.usage.max_output_tokens_observed,
        record.usage.api_cost,
        record.usage.experiment_count,
    )
    if record.schema_version != "1.1" or observed != expected:
        raise ValueError("native H4 successful resource accounting differs")
    if requests > request.maximum_patch_iterations:
        raise ValueError("native H4 successful request count exceeds the arm ceiling")
    if cell.lane_kind is ExecutionLaneKind.API_ONLY and (
        requests > int(cell.resource.max_requests or 0)
        or loop.input_tokens + loop.output_tokens > int(cell.resource.max_total_tokens or 0)
        or loop.max_input_tokens_observed > int(cell.resource.max_input_tokens_per_call or 0)
        or loop.max_output_tokens_observed > int(cell.resource.max_output_tokens_per_call or 0)
        or loop.model_cost_usd > float(cell.resource.max_cost or 0)
    ):
        raise ValueError("native H4 successful usage exceeds cell authority")


def _load_h4_loop_result(
    observed: dict[str, Path],
    native: NativeBenchmarkObjectiveMeasurement,
    request: H4ArmRunRequest,
    cell: PlannedEvaluationCell,
) -> BenchmarkResearchLoopResult | None:
    path = observed.get("development_loop/RESULT.json")
    if native.loop_result_sha256 is None:
        if path is not None:
            raise ValueError("native H4 evidence has an unbound loop result")
        return None
    if path is None:
        raise ValueError("native H4 measurement lacks its loop result")
    loop = BenchmarkResearchLoopResult.model_validate_json(path.read_bytes())
    if (
        loop.result_sha256 != native.loop_result_sha256
        or loop.h4_arm_run_request_sha256 != request.request_sha256
        or loop.schema_version != "1.1"
        or loop.task_spec_fingerprint != request.task_spec_fingerprint
        or loop.cell_binding_sha256 != request.cell_binding_sha256
        or loop.condition_guidance_sha256 != request.condition_guidance_sha256
        or request.cell_id != cell.cell_id
    ):
        raise ValueError("native H4 loop result binding differs")
    return loop


def _load_h4_frozen_candidate(
    observed: dict[str, Path],
    native: NativeBenchmarkObjectiveMeasurement,
    request: H4ArmRunRequest,
    loop: BenchmarkResearchLoopResult | None,
) -> BenchmarkFrozenCandidate | None:
    path = observed.get("FROZEN_CANDIDATE.json")
    if native.frozen_candidate_sha256 is None:
        if path is not None:
            raise ValueError("native H4 evidence has an unbound frozen candidate")
        return None
    if path is None or loop is None:
        raise ValueError("native H4 measurement lacks its frozen candidate chain")
    candidate = BenchmarkFrozenCandidate.model_validate_json(path.read_bytes())
    if (
        candidate.candidate_sha256 != native.frozen_candidate_sha256
        or candidate.cell_id != request.cell_id
        or candidate.campaign_manifest_sha256 != request.campaign_manifest_sha256
        or candidate.task_spec_fingerprint != request.task_spec_fingerprint
        or candidate.workspace_receipt_sha256 != request.prepared_workspace_receipt_sha256
        or candidate.loop_result_sha256 != loop.result_sha256
        or candidate.cell_binding_sha256 != request.cell_binding_sha256
        or candidate.best_iteration != loop.best_iteration
        or candidate.editable_surface_sha256 != loop.best_editable_surface_sha256
        or candidate.protected_surface_sha256 != request.protected_surface_sha256
    ):
        raise ValueError("native H4 frozen candidate binding differs")
    return candidate


def _load_h4_heldout_receipt(
    observed: dict[str, Path],
    native: NativeBenchmarkObjectiveMeasurement,
    request: H4ArmRunRequest,
    candidate: BenchmarkFrozenCandidate | None,
) -> BenchmarkHeldoutExecutionReceipt | None:
    path = observed.get("heldout/execution/RESULT.json")
    if native.heldout_receipt_sha256 is None:
        if path is not None:
            raise ValueError("native H4 evidence has an unbound held-out receipt")
        return None
    request_path = observed.get("heldout/REQUEST.json")
    if path is None or request_path is None or candidate is None:
        raise ValueError("native H4 measurement lacks its held-out receipt")
    heldout_request = BenchmarkHeldoutRunRequest.model_validate_json(request_path.read_bytes())
    heldout = BenchmarkHeldoutExecutionReceipt.model_validate_json(path.read_bytes())
    if (
        heldout.receipt_sha256 != native.heldout_receipt_sha256
        or heldout.request_sha256 != heldout_request.fingerprint
        or heldout.frozen_candidate_sha256 != candidate.candidate_sha256
        or heldout_request.frozen_candidate_sha256 != candidate.candidate_sha256
        or heldout_request.cell_id != request.cell_id
        or heldout_request.campaign_manifest_sha256 != request.campaign_manifest_sha256
        or heldout_request.cell_binding_sha256 != request.cell_binding_sha256
        or heldout_request.spec_fingerprint != request.task_spec_fingerprint
        or heldout_request.prepared_workspace_receipt_sha256
        != request.prepared_workspace_receipt_sha256
        or heldout_request.seed != request.seed
        or heldout.spec_fingerprint != request.task_spec_fingerprint
        or heldout.workspace_receipt_sha256 != request.prepared_workspace_receipt_sha256
        or heldout.execution_profile_fingerprint != heldout_request.execution_profile_fingerprint
        or heldout.resource_verification_receipt_sha256
        != heldout_request.resource_verification_receipt_sha256
        or heldout.baseline_heldout_score != native.baseline_heldout_score
    ):
        raise ValueError("native H4 held-out receipt binding differs")
    if heldout.status == "succeeded":
        assert heldout.objective is not None
        if (
            heldout.objective.task_id != request.task_id
            or heldout.objective.score != native.heldout_score
            or heldout.objective_delta_from_baseline
            != heldout.objective.score - heldout.baseline_heldout_score
        ):
            raise ValueError("native H4 held-out objective differs")
    return heldout


def _validate_h4_terminal_outcome(
    observed: dict[str, Path],
    *,
    record: EvaluationCellResult,
    cell: PlannedEvaluationCell,
    request: H4ArmRunRequest,
    native: NativeBenchmarkObjectiveMeasurement,
    loop: BenchmarkResearchLoopResult | None,
    heldout: BenchmarkHeldoutExecutionReceipt | None,
) -> None:
    path = observed.get("H4_TERMINAL_OUTCOME.json")
    if path is None:
        raise ValueError("native H4 failure lacks a terminal outcome receipt")
    terminal = H4TerminalOutcomeReceipt.model_validate_json(path.read_bytes())
    if (
        terminal.receipt_sha256 != native.terminal_evidence_sha256
        or terminal.profile_sha256 != request.profile_sha256
        or terminal.arm_run_request_sha256 != request.request_sha256
        or terminal.campaign_manifest_sha256 != request.campaign_manifest_sha256
        or terminal.cell_id != cell.cell_id
        or terminal.task_id != cell.task_id
        or terminal.condition is not request.condition
    ):
        raise ValueError("native H4 terminal outcome identity differs")
    usage = terminal.resource_usage
    token_telemetry = (
        usage.request_count,
        usage.input_tokens,
        usage.output_tokens,
        usage.max_input_tokens_observed,
        usage.max_output_tokens_observed,
    )
    if terminal.usage_accounting == "measured":
        if any(value is None for value in token_telemetry):
            raise ValueError("native H4 measured terminal token usage is incomplete")
        if (cell.lane_kind is ExecutionLaneKind.API_ONLY and usage.api_cost is None) or (
            cell.lane_kind is ExecutionLaneKind.GPU and usage.api_cost is not None
        ):
            raise ValueError("native H4 terminal usage lane kind differs")
    elif usage.model_dump(mode="json") != _h4_authorized_failure_ceiling(
        cell,
        request,
    ):
        raise ValueError("native H4 conservative terminal ceiling is not authorized")
    if (
        usage.request_count != record.usage.request_count
        or usage.input_tokens != record.usage.input_tokens
        or usage.output_tokens != record.usage.output_tokens
        or usage.max_input_tokens_observed != record.usage.max_input_tokens_observed
        or usage.max_output_tokens_observed != record.usage.max_output_tokens_observed
        or usage.api_cost != record.usage.api_cost
        or usage.experiment_count != record.usage.experiment_count
    ):
        raise ValueError("native H4 terminal resource accounting differs")
    if loop is not None:
        observed_requests = sum(item.decision_sha256 is not None for item in loop.iterations)
        expected_experiments = loop.development_experiment_count + int(heldout is not None)
        actual_usage = (
            observed_requests,
            loop.input_tokens,
            loop.output_tokens,
            loop.max_input_tokens_observed,
            loop.max_output_tokens_observed,
            None if usage.api_cost is None else loop.model_cost_usd,
            expected_experiments,
        )
        terminal_usage = (
            usage.request_count,
            usage.input_tokens,
            usage.output_tokens,
            usage.max_input_tokens_observed,
            usage.max_output_tokens_observed,
            usage.api_cost,
            usage.experiment_count,
        )
        if terminal.usage_accounting == "measured" and terminal_usage != actual_usage:
            raise ValueError("native H4 measured terminal usage differs from its loop")
        if terminal.usage_accounting == "conservative-authorized-ceiling" and any(
            ceiling is not None and actual > ceiling
            for actual, ceiling in zip(actual_usage, terminal_usage, strict=True)
        ):
            raise ValueError("native H4 loop usage exceeds its conservative terminal ceiling")
    if terminal.usage_accounting == "measured":
        if usage.experiment_count > request.maximum_patch_iterations + 2:
            raise ValueError("native H4 measured experiments exceed the arm ceiling")
        if cell.lane_kind is ExecutionLaneKind.API_ONLY and (
            int(usage.request_count or 0) > int(cell.resource.max_requests or 0)
            or int(usage.input_tokens or 0) + int(usage.output_tokens or 0)
            > int(cell.resource.max_total_tokens or 0)
            or int(usage.max_input_tokens_observed or 0)
            > int(cell.resource.max_input_tokens_per_call or 0)
            or int(usage.max_output_tokens_observed or 0)
            > int(cell.resource.max_output_tokens_per_call or 0)
            or float(usage.api_cost or 0) > float(cell.resource.max_cost or 0)
        ):
            raise ValueError("native H4 measured terminal usage exceeds cell authority")
    if terminal.failure_stage == "development":
        if (
            loop is None
            or loop.status != "failed"
            or heldout is not None
            or terminal.error_code != "development-loop-failed"
            or terminal.failure_artifact_sha256 != loop.result_sha256
            or terminal.last_valid_predecessor_sha256
            != loop.iterations[-1].iteration_receipt_sha256
            or terminal.usage_accounting != "measured"
        ):
            raise ValueError("native H4 development terminal semantics differ")
    elif terminal.failure_stage == "heldout":
        if (
            loop is None
            or loop.status == "failed"
            or heldout is None
            or heldout.status != "failed"
            or terminal.error_code != (heldout.error_code or "heldout-scoring-failed")
            or terminal.failure_artifact_sha256 != heldout.receipt_sha256
            or terminal.last_valid_predecessor_sha256 != native.frozen_candidate_sha256
            or terminal.usage_accounting != "measured"
        ):
            raise ValueError("native H4 held-out terminal semantics differ")
    elif terminal.failure_stage == "adapter-exception":
        failure_path = observed.get("FAILURE.json")
        expected_predecessor = _latest_h4_evidence_predecessor(
            observed,
            request=request,
            loop=loop,
            heldout=heldout,
        )
        if (
            failure_path is None
            or terminal.error_code != "native-benchmark-adapter-failed"
            or terminal.failure_artifact_sha256 != _sha256_file(failure_path)
            or terminal.last_valid_predecessor_sha256 != expected_predecessor
            or terminal.usage_accounting != "conservative-authorized-ceiling"
        ):
            raise ValueError("native H4 adapter terminal semantics differ")
    else:
        failure_path = observed.get("FAILURE.json")
        expected_predecessor = _latest_h4_evidence_predecessor(
            observed,
            request=request,
            loop=loop,
            heldout=heldout,
        )
        if (
            failure_path is None
            or terminal.error_code
            not in {
                "nonzero-exit",
                "adapter-result-missing",
                "timeout",
                "launcher-error",
                "adapter-result-invalid",
                "orchestrator-interrupted-after-arm-exposure",
            }
            or terminal.failure_artifact_sha256 != _sha256_file(failure_path)
            or terminal.last_valid_predecessor_sha256 != expected_predecessor
            or terminal.usage_accounting != "conservative-authorized-ceiling"
        ):
            raise ValueError("native H4 campaign terminal semantics differ")


def _h4_authorized_failure_ceiling(
    cell: PlannedEvaluationCell,
    request: H4ArmRunRequest,
) -> dict[str, object]:
    if cell.lane_kind is ExecutionLaneKind.API_ONLY:
        return {
            "request_count": cell.resource.max_requests,
            "input_tokens": cell.resource.max_total_tokens,
            "output_tokens": 0,
            "max_input_tokens_observed": cell.resource.max_input_tokens_per_call,
            "max_output_tokens_observed": cell.resource.max_output_tokens_per_call,
            "api_cost": cell.resource.max_cost,
            "experiment_count": request.maximum_patch_iterations + 2,
        }
    return {
        "request_count": None,
        "input_tokens": None,
        "output_tokens": None,
        "max_input_tokens_observed": None,
        "max_output_tokens_observed": None,
        "api_cost": None,
        "experiment_count": request.maximum_patch_iterations + 2,
    }


def _latest_h4_evidence_predecessor(
    observed: dict[str, Path],
    *,
    request: H4ArmRunRequest,
    loop: BenchmarkResearchLoopResult | None,
    heldout: BenchmarkHeldoutExecutionReceipt | None,
) -> str:
    predecessor = request.request_sha256
    if loop is not None:
        predecessor = loop.result_sha256
    candidate_path = observed.get("FROZEN_CANDIDATE.json")
    if candidate_path is not None:
        candidate = BenchmarkFrozenCandidate.model_validate_json(candidate_path.read_bytes())
        if candidate.loop_result_sha256 != (loop.result_sha256 if loop else None):
            raise ValueError("native H4 candidate predecessor differs")
        predecessor = candidate.candidate_sha256
    if heldout is not None:
        predecessor = heldout.receipt_sha256
    return predecessor


def _measurement_artifact(
    artifacts: tuple[EvaluationResultArtifact, ...],
) -> EvaluationResultArtifact:
    matches = [
        artifact
        for artifact in artifacts
        if PurePosixPath(artifact.locator).name == "OBJECTIVE_MEASUREMENT.json"
    ]
    if len(matches) != 1:
        raise ValueError("successful native cell requires one objective measurement artifact")
    return matches[0]


def _verified_project_artifact(root: Path, artifact: EvaluationResultArtifact) -> Path:
    candidate = root.joinpath(*PurePosixPath(artifact.locator).parts)
    current = root
    for part in PurePosixPath(artifact.locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("native objective measurement cannot traverse a symbolic link")
    resolved = candidate.resolve(strict=True)
    if (
        not resolved.is_relative_to(root)
        or not resolved.is_file()
        or resolved.stat().st_size < 1
        or resolved.stat().st_size > _MAX_MEASUREMENT_BYTES
        or resolved.stat().st_size != artifact.size_bytes
        or _sha256_file(resolved) != artifact.sha256
    ):
        raise ValueError("native objective measurement artifact differs from its result record")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["collect_native_objective_measurements"]

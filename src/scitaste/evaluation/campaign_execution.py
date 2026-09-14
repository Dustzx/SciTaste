"""Project-owned execution of authorized evaluation-cell campaigns.

This module is the execution bridge between the no-run ``EvaluationCellPlan``
and the existing result-analysis/admission pipeline.  It deliberately does not
design a study, approve resources, analyze outcomes, or manufacture reviews.
It runs only cells whose exact registered proposal is already execution-
authorized and retains a restart-safe result for every attempted cell.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.benchmark.study_execution import ProcessRunner, SubprocessRunner
from scitaste.benchmark.study_models import StudyOutcome
from scitaste.evaluation.campaign_activation import (
    EvaluationCampaignActivation,
    validate_evaluation_campaign_activation,
)
from scitaste.evaluation.cell_plan import (
    EvaluationCellPlan,
    PlannedEvaluationCell,
    load_evaluation_cell_plan,
)
from scitaste.evaluation.prelaunch import (
    AdapterEvidenceKind,
    ConfirmatoryEstimandKind,
    ExecutionLaneKind,
    ExperimentPrelaunchManifest,
    ScientificEndpointKind,
    load_prelaunch_manifest,
)
from scitaste.evaluation.results import (
    EvaluationCellResult,
    EvaluationCellUsage,
    EvaluationResultArtifact,
    EvaluationResultSet,
)
from scitaste.project import (
    ProjectEvaluationBundle,
    ProjectRun,
    ProjectRuntime,
    ProjectSnapshot,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONFIG_BYTES = 1_048_576
_MAX_RESULT_BYTES = 16 * 1024 * 1024
_BASE_ENVIRONMENT = ("PATH", "LANG", "LC_ALL", "TMPDIR", "CUDA_VISIBLE_DEVICES")


class EvaluationCommandLauncher(BaseModel):
    """Shell-free adapter command for one registered system implementation."""

    model_config = _CONFIG

    command: tuple[str, ...] = Field(min_length=1, max_length=100)
    timeout_seconds: float = Field(gt=0, le=7 * 24 * 3600)
    gpu_count: int = Field(default=0, ge=0, le=64)
    pass_environment: tuple[str, ...] = Field(default=(), max_length=50)

    @field_validator("command")
    @classmethod
    def command_is_nonempty(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("evaluation launcher command arguments cannot be empty")
        return values

    @field_validator("pass_environment")
    @classmethod
    def environment_names_are_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("evaluation launcher environment names must be unique")
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", value) for value in values):
            raise ValueError("evaluation launcher environment names must be uppercase identifiers")
        return values


class EvaluationCampaignLaunchConfig(BaseModel):
    """Content-addressed system-to-adapter binding for one campaign."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    launchers: dict[str, EvaluationCommandLauncher] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def system_ids_are_safe(self) -> EvaluationCampaignLaunchConfig:
        for system_id in self.launchers:
            validate_entry_id(system_id, field_name="evaluation launcher system_id")
        return self

    @property
    def config_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


class EvaluationAdapterUsage(BaseModel):
    """Adapter-reported counters; elapsed and GPU allocation remain runner-owned."""

    model_config = _CONFIG

    request_count: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    max_input_tokens_observed: int | None = Field(default=None, ge=0)
    max_output_tokens_observed: int | None = Field(default=None, ge=0)
    api_cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    experiment_count: int = Field(ge=0)


class EvaluationAdapterResult(BaseModel):
    """Bounded result file produced by a condition adapter."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["succeeded", "failed"]
    evidence_class: Literal["real", "synthetic"]
    usage: EvaluationAdapterUsage
    outcome: StudyOutcome | None = None
    artifact_paths: tuple[str, ...] = Field(default=(), max_length=200)
    error_code: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$",
    )

    @model_validator(mode="after")
    def success_and_failure_are_distinct(self) -> EvaluationAdapterResult:
        if self.status == "succeeded":
            if self.outcome is None or not self.artifact_paths or self.error_code is not None:
                raise ValueError(
                    "a successful evaluation adapter result requires outcome/artifacts"
                )
        elif self.outcome is not None or self.error_code is None:
            raise ValueError("a failed evaluation adapter result requires only an error code")
        if len(self.artifact_paths) != len(set(self.artifact_paths)):
            raise ValueError("evaluation adapter artifact paths must be unique")
        return self


class EvaluationCampaignManifest(BaseModel):
    """Immutable execution identity published before the first cell starts."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    project_id: str
    run_id: str
    evaluation_id: str
    evaluation_bundle_sha256: str = Field(pattern=_SHA256)
    proposal_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    launch_config_sha256: str = Field(pattern=_SHA256)
    selected_cell_ids: tuple[str, ...] = Field(min_length=1, max_length=10_000)
    activation_sha256: str | None = Field(default=None, pattern=_SHA256)
    claim_authority: bool = True
    execution_authorized: Literal[True] = True
    manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def manifest_is_self_hashed(self) -> EvaluationCampaignManifest:
        for value, label in (
            (self.project_id, "project_id"),
            (self.run_id, "run_id"),
            (self.evaluation_id, "evaluation_id"),
        ):
            if label == "project_id":
                validate_project_id(value)
            else:
                validate_entry_id(value, field_name=label)
        if len(self.selected_cell_ids) != len(set(self.selected_cell_ids)):
            raise ValueError("evaluation campaign selected cell IDs must be unique")
        if self.schema_version == "1.0":
            if self.activation_sha256 is not None or not self.claim_authority:
                raise ValueError("campaign manifest v1.0 cannot bind a feasibility activation")
        elif self.activation_sha256 is None or self.claim_authority:
            raise ValueError("activated campaign must be feasibility-only and content-bound")
        expected = content_sha256(self._identity_payload())
        if self.manifest_sha256 != expected:
            raise ValueError("evaluation campaign manifest hash mismatch")
        return self

    def _identity_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.schema_version == "1.0":
            payload.pop("activation_sha256", None)
            payload.pop("claim_authority", None)
        return payload

    @classmethod
    def create(cls, **values: object) -> EvaluationCampaignManifest:
        payload = {"schema_version": "1.0", **values}
        payload.pop("manifest_sha256", None)
        unsigned = cls.model_construct(manifest_sha256="0" * 64, **payload)
        return cls(**payload, manifest_sha256=content_sha256(unsigned._identity_payload()))


class EvaluationCellCheckpoint(BaseModel):
    """Exact completion fence for one cell attempt."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    cell_id: str
    attempt: int = Field(ge=1)
    campaign_manifest_sha256: str = Field(pattern=_SHA256)
    cell_sha256: str = Field(pattern=_SHA256)
    request_sha256: str = Field(pattern=_SHA256)
    command_sha256: str = Field(pattern=_SHA256)
    result_sha256: str = Field(pattern=_SHA256)
    evidence_sha256: dict[str, str] = Field(min_length=1, max_length=250)
    checkpoint_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def checkpoint_is_self_hashed(self) -> EvaluationCellCheckpoint:
        if any(not key or not _is_sha256(value) for key, value in self.evidence_sha256.items()):
            raise ValueError("evaluation checkpoint evidence hashes are invalid")
        expected = content_sha256(self.model_dump(mode="json", exclude={"checkpoint_sha256"}))
        if self.checkpoint_sha256 != expected:
            raise ValueError("evaluation cell checkpoint hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> EvaluationCellCheckpoint:
        payload = {"schema_version": "1.0", **values}
        payload.pop("checkpoint_sha256", None)
        return cls(**payload, checkpoint_sha256=content_sha256(payload))


class EvaluationCellLaunch(BaseModel):
    model_config = _CONFIG

    cell_id: str
    system_id: str
    task_id: str
    lane_kind: ExecutionLaneKind
    command: tuple[str, ...]
    cell_directory: str


class EvaluationCampaignSummary(BaseModel):
    """Compact state transition returned to CLI and orchestration layers."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    project_id: str
    run_id: str
    evaluation_id: str
    project_revision: int = Field(ge=0)
    run_status: Literal[
        "blocked",
        "planned",
        "partial",
        "feasibility_complete",
        "feasibility_complete_with_failures",
        "cells_complete",
        "cells_complete_with_failures",
        "analysis_complete",
    ]
    selected_cells: int = Field(ge=0)
    executed_cells: int = Field(ge=0)
    recovered_successes: int = Field(ge=0)
    succeeded_cells: int = Field(ge=0)
    failed_cells: int = Field(ge=0)
    total_recorded_cells: int = Field(ge=0)
    blocker_codes: tuple[str, ...] = ()
    next_required_stage: Literal[
        "execution_authorization",
        "cell_execution",
        "retry_or_accept_failures",
        "feasibility_review",
        "objective_analysis_or_blind_review",
        "result_registration",
    ]
    dry_run: bool
    result_set_locator: str | None = None
    result_set_sha256: str | None = Field(default=None, pattern=_SHA256)
    handoff_locator: str | None = None
    handoff_sha256: str | None = Field(default=None, pattern=_SHA256)
    objective_measurement_set_locator: str | None = None
    objective_measurement_set_sha256: str | None = Field(default=None, pattern=_SHA256)
    objective_analysis_locator: str | None = None
    objective_analysis_sha256: str | None = Field(default=None, pattern=_SHA256)
    completed_result_set_locator: str | None = None
    completed_result_set_sha256: str | None = Field(default=None, pattern=_SHA256)
    launches: tuple[EvaluationCellLaunch, ...] = ()


class EvaluationCampaignHandoff(BaseModel):
    """Exact execution-to-analysis/review cursor; it grants no new authority."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    project_id: str
    run_id: str
    evaluation_id: str
    campaign_manifest_sha256: str = Field(pattern=_SHA256)
    proposal_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    result_set_locator: str
    result_set_sha256: str = Field(pattern=_SHA256)
    planned_cell_ids: tuple[str, ...] = Field(min_length=1, max_length=10_000)
    recorded_cell_ids: tuple[str, ...] = Field(max_length=10_000)
    failed_cell_ids: tuple[str, ...] = Field(max_length=10_000)
    next_interface: Literal[
        "project.evaluation.run-campaign",
        "project.evaluation.resolve-cell-failures",
        "project.evaluation.inspect-feasibility-block",
        "project.evaluation.objective-score-and-analyze",
        "project.evaluation.register-result",
        "project.evaluation.prepare-blind-review",
        "project.evaluation.select-analysis-path",
    ]
    required_inputs: tuple[str, ...] = Field(min_length=1, max_length=20)
    resume_safe: bool
    explicit_retry_decision_required: bool
    independent_human_action_required: bool
    authorizes_execution: Literal[False] = False
    performs_next_stage: Literal[False] = False
    handoff_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def handoff_is_closed_and_self_hashed(self) -> EvaluationCampaignHandoff:
        for value, label in (
            (self.project_id, "project_id"),
            (self.run_id, "run_id"),
            (self.evaluation_id, "evaluation_id"),
        ):
            if label == "project_id":
                validate_project_id(value)
            else:
                validate_entry_id(value, field_name=label)
        if len(self.planned_cell_ids) != len(set(self.planned_cell_ids)):
            raise ValueError("campaign handoff planned cell IDs must be unique")
        if len(self.recorded_cell_ids) != len(set(self.recorded_cell_ids)):
            raise ValueError("campaign handoff recorded cell IDs must be unique")
        if len(self.failed_cell_ids) != len(set(self.failed_cell_ids)):
            raise ValueError("campaign handoff failed cell IDs must be unique")
        if set(self.recorded_cell_ids) - set(self.planned_cell_ids):
            raise ValueError("campaign handoff contains unplanned result cells")
        if set(self.failed_cell_ids) - set(self.recorded_cell_ids):
            raise ValueError("campaign handoff failures must have result records")
        expected = content_sha256(self.model_dump(mode="json", exclude={"handoff_sha256"}))
        if self.handoff_sha256 != expected:
            raise ValueError("evaluation campaign handoff hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> EvaluationCampaignHandoff:
        payload = {"schema_version": "1.0", **values}
        payload.pop("handoff_sha256", None)
        unsigned = cls.model_construct(handoff_sha256="0" * 64, **payload)
        return cls(
            **payload,
            handoff_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"handoff_sha256"})
            ),
        )


@dataclass(frozen=True)
class _CampaignInputs:
    snapshot: ProjectSnapshot
    evaluation: ProjectEvaluationBundle
    manifest: ExperimentPrelaunchManifest
    plan: EvaluationCellPlan


@dataclass(frozen=True)
class _ObjectiveClosure:
    measurement_set_locator: str
    measurement_set_sha256: str
    analysis_locator: str | None = None
    analysis_sha256: str | None = None
    completed_result_set_locator: str | None = None
    completed_result_set_sha256: str | None = None
    completed_result_set: EvaluationResultSet | None = None


class ProjectEvaluationCampaignRunner:
    """Execute one exact authorized evaluation plan inside its owning project."""

    def __init__(
        self,
        runtime: ProjectRuntime,
        launch_config: EvaluationCampaignLaunchConfig,
        *,
        process_runner: ProcessRunner | None = None,
        clock: Callable[[], float] = time.perf_counter,
        evidence_root: str | Path = ".",
    ) -> None:
        self.runtime = runtime
        self.launch_config = launch_config
        self.process_runner = process_runner or SubprocessRunner()
        self.clock = clock
        self.evidence_root = Path(evidence_root)

    def run(
        self,
        *,
        project_id: str,
        evaluation_id: str,
        run_id: str,
        allow_execution: bool = False,
        resume: bool = False,
        retry_failed_cells: bool = False,
        cell_ids: tuple[str, ...] | None = None,
        activation: EvaluationCampaignActivation | None = None,
        max_cells: int | None = None,
        dry_run: bool = False,
    ) -> EvaluationCampaignSummary:
        validate_project_id(project_id)
        validate_entry_id(evaluation_id, field_name="evaluation_id")
        validate_entry_id(run_id, field_name="run_id")
        if max_cells is not None and max_cells < 1:
            raise ValueError("max_cells must be positive")
        inputs = self._inputs(project_id, evaluation_id)
        if activation is None:
            selected = self._select_cells(inputs.plan, cell_ids=cell_ids)
            if len(selected) != len(inputs.plan.cells):
                raise ValueError(
                    "partial evaluation selection requires an approved task-block activation"
                )
        else:
            selected = validate_evaluation_campaign_activation(
                activation,
                inputs.plan,
                project_id=project_id,
                evaluation_id=evaluation_id,
            )
            if cell_ids is not None and set(cell_ids) != set(activation.selected_cell_ids):
                raise ValueError("campaign cell selection differs from its activation")
        launches, launch_blockers = self._launches(project_id, run_id, selected)
        blockers = self._readiness_blockers(inputs, selected, launch_blockers, activation)
        if blockers or dry_run:
            return EvaluationCampaignSummary(
                schema_version="1.1",
                project_id=project_id,
                run_id=run_id,
                evaluation_id=evaluation_id,
                project_revision=inputs.snapshot.revision,
                run_status="blocked" if blockers else "planned",
                selected_cells=len(selected),
                executed_cells=0,
                recovered_successes=0,
                succeeded_cells=0,
                failed_cells=0,
                total_recorded_cells=0,
                blocker_codes=tuple(blockers),
                next_required_stage=("execution_authorization" if blockers else "cell_execution"),
                dry_run=True,
                launches=tuple(launches),
            )
        if not allow_execution:
            raise ValueError("evaluation execution requires allow_execution=true")

        campaign = EvaluationCampaignManifest.create(
            schema_version="1.1" if activation is not None else "1.0",
            project_id=project_id,
            run_id=run_id,
            evaluation_id=evaluation_id,
            evaluation_bundle_sha256=inputs.evaluation.bundle_sha256,
            proposal_sha256=inputs.plan.proposal_sha256,
            plan_sha256=inputs.plan.plan_sha256,
            launch_config_sha256=self.launch_config.config_sha256,
            selected_cell_ids=tuple(cell.cell_id for cell in selected),
            activation_sha256=(activation.activation_sha256 if activation is not None else None),
            claim_authority=activation is None,
            execution_authorized=True,
        )
        snapshot = self._begin_or_resume(inputs.snapshot, campaign, resume=resume)
        root = self._campaign_root(project_id, run_id)
        root.mkdir(parents=True, exist_ok=True)
        with self._locked(root):
            self._materialize_manifest(root, campaign)
            records = self._load_records(project_id, root, inputs.plan, campaign)
            executed = 0
            recovered = 0
            for cell in selected:
                if max_cells is not None and executed >= max_cells:
                    break
                previous = records.get(cell.cell_id)
                if previous is not None and previous.status == "succeeded":
                    self._verify_checkpoint(project_id, root, cell, previous, campaign)
                    recovered += 1
                    continue
                if previous is not None and not retry_failed_cells:
                    self._verify_checkpoint(project_id, root, cell, previous, campaign)
                    continue
                self._archive_attempt(root, cell.cell_id, previous)
                record = self._run_cell(project_id, root, cell, campaign)
                records[cell.cell_id] = record
                executed += 1
                self._save_result_set(project_id, root, evaluation_id, inputs.plan, records)

            result_set = self._save_result_set(
                project_id, root, evaluation_id, inputs.plan, records
            )
            selected_ids = {cell.cell_id for cell in selected}
            selected_complete = selected_ids <= set(records)
            failed = sum(record.status == "failed" for record in records.values())
            status: Literal[
                "partial",
                "feasibility_complete",
                "feasibility_complete_with_failures",
                "cells_complete",
                "cells_complete_with_failures",
                "analysis_complete",
            ]
            if selected_complete:
                if failed:
                    status = (
                        "cells_complete_with_failures"
                        if campaign.claim_authority
                        else "feasibility_complete_with_failures"
                    )
                elif campaign.claim_authority:
                    status = "cells_complete"
                else:
                    status = "feasibility_complete"
            else:
                status = "partial"
            closure = self._objective_closure(
                inputs,
                campaign,
                result_set,
                root,
                selected_complete=selected_complete,
                failed=failed,
            )
            if status == "cells_complete" and closure is not None:
                status = "analysis_complete"
            locator = (
                closure.completed_result_set_locator
                if closure is not None and closure.completed_result_set_locator is not None
                else self._result_set_locator(run_id)
            )
            handed_results = (
                closure.completed_result_set
                if closure is not None and closure.completed_result_set is not None
                else result_set
            )
            handoff = self._handoff(
                campaign=campaign,
                manifest=inputs.manifest,
                plan=inputs.plan,
                records=records,
                result_set=handed_results,
                result_set_locator=locator,
                analysis_complete=status == "analysis_complete",
            )
            _atomic_json_write(root / "HANDOFF.json", handoff.model_dump(mode="json"))
            snapshot = self.runtime.update_run(
                project_id,
                run_id,
                expected_revision=snapshot.revision,
                status=status,
                stage_path="evaluation_campaign",
                artifact=locator,
                evaluation_id=evaluation_id,
                campaign_manifest_sha256=campaign.manifest_sha256,
                result_set_sha256=handed_results.result_set_sha256,
                handoff_sha256=handoff.handoff_sha256,
                objective_measurement_set_sha256=(
                    closure.measurement_set_sha256 if closure is not None else None
                ),
                objective_analysis_sha256=(
                    closure.analysis_sha256 if closure is not None else None
                ),
                recorded_cells=len(records),
                succeeded_cells=sum(record.status == "succeeded" for record in records.values()),
                failed_cells=failed,
                next_required_stage=(
                    "retry_or_accept_failures"
                    if status == "cells_complete_with_failures"
                    else "feasibility_review"
                    if status
                    in {"feasibility_complete", "feasibility_complete_with_failures"}
                    else "objective_analysis_or_blind_review"
                    if status == "cells_complete"
                    else "result_registration"
                    if status == "analysis_complete"
                    else "cell_execution"
                ),
            )
        return EvaluationCampaignSummary(
            schema_version="1.1",
            project_id=project_id,
            run_id=run_id,
            evaluation_id=evaluation_id,
            project_revision=snapshot.revision,
            run_status=status,
            selected_cells=len(selected),
            executed_cells=executed,
            recovered_successes=recovered,
            succeeded_cells=sum(record.status == "succeeded" for record in records.values()),
            failed_cells=failed,
            total_recorded_cells=len(records),
            next_required_stage=(
                "retry_or_accept_failures"
                if status == "cells_complete_with_failures"
                else "feasibility_review"
                if status in {"feasibility_complete", "feasibility_complete_with_failures"}
                else "objective_analysis_or_blind_review"
                if status == "cells_complete"
                else "result_registration"
                if status == "analysis_complete"
                else "cell_execution"
            ),
            dry_run=False,
            result_set_locator=locator,
            result_set_sha256=handed_results.result_set_sha256,
            handoff_locator=f"runs/{run_id}/evaluation_campaign/HANDOFF.json",
            handoff_sha256=handoff.handoff_sha256,
            objective_measurement_set_locator=(
                closure.measurement_set_locator if closure is not None else None
            ),
            objective_measurement_set_sha256=(
                closure.measurement_set_sha256 if closure is not None else None
            ),
            objective_analysis_locator=(closure.analysis_locator if closure is not None else None),
            objective_analysis_sha256=(closure.analysis_sha256 if closure is not None else None),
            completed_result_set_locator=(
                closure.completed_result_set_locator if closure is not None else None
            ),
            completed_result_set_sha256=(
                closure.completed_result_set_sha256 if closure is not None else None
            ),
            launches=tuple(launches),
        )

    @staticmethod
    def _handoff(
        *,
        campaign: EvaluationCampaignManifest,
        manifest: ExperimentPrelaunchManifest,
        plan: EvaluationCellPlan,
        records: dict[str, EvaluationCellResult],
        result_set: EvaluationResultSet,
        result_set_locator: str,
        analysis_complete: bool,
    ) -> EvaluationCampaignHandoff:
        planned = campaign.selected_cell_ids
        recorded = tuple(cell_id for cell_id in planned if cell_id in records)
        failed = tuple(cell_id for cell_id in recorded if records[cell_id].status == "failed")
        if len(recorded) < len(planned):
            next_interface = "project.evaluation.run-campaign"
            required_inputs = ("remaining-authorized-cell-results",)
            resume_safe = True
            retry_required = False
            human_required = False
        elif failed and campaign.claim_authority:
            next_interface = "project.evaluation.resolve-cell-failures"
            required_inputs = ("explicit-retry-or-accept-failure-decision",)
            resume_safe = True
            retry_required = True
            human_required = False
        elif analysis_complete:
            next_interface = "project.evaluation.register-result"
            required_inputs = ("completed-objective-result-set",)
            resume_safe = False
            retry_required = False
            human_required = False
        elif not campaign.claim_authority:
            next_interface = "project.evaluation.inspect-feasibility-block"
            required_inputs = (
                "failure-and-resource-demand-review",
                "explicit-next-block-decision",
            )
            resume_safe = False
            retry_required = False
            human_required = True
        elif manifest.primary_endpoint is ScientificEndpointKind.OBJECTIVE_PROGRESS:
            next_interface = "project.evaluation.objective-score-and-analyze"
            required_inputs = (
                "bound-objective-outcome-contract",
                "task-scorer-produced-measurement-set",
            )
            resume_safe = False
            retry_required = False
            human_required = False
        elif manifest.primary_endpoint is ScientificEndpointKind.BLINDED_PACKAGE_PREFERENCE:
            next_interface = "project.evaluation.prepare-blind-review"
            required_inputs = (
                "condition-blinded-review-packages",
                "conflict-cleared-independent-reviewers",
            )
            resume_safe = False
            retry_required = False
            human_required = True
        else:
            next_interface = "project.evaluation.select-analysis-path"
            required_inputs = ("registered-endpoint-specific-analysis-contract",)
            resume_safe = False
            retry_required = False
            human_required = False
        return EvaluationCampaignHandoff.create(
            schema_version=(
                "1.1" if campaign.activation_sha256 is not None or analysis_complete else "1.0"
            ),
            project_id=campaign.project_id,
            run_id=campaign.run_id,
            evaluation_id=campaign.evaluation_id,
            campaign_manifest_sha256=campaign.manifest_sha256,
            proposal_sha256=campaign.proposal_sha256,
            plan_sha256=campaign.plan_sha256,
            result_set_locator=result_set_locator,
            result_set_sha256=result_set.result_set_sha256,
            planned_cell_ids=planned,
            recorded_cell_ids=recorded,
            failed_cell_ids=failed,
            next_interface=next_interface,
            required_inputs=required_inputs,
            resume_safe=resume_safe,
            explicit_retry_decision_required=retry_required,
            independent_human_action_required=human_required,
        )

    def _inputs(self, project_id: str, evaluation_id: str) -> _CampaignInputs:
        snapshot = self.runtime.open(project_id)
        evaluation = self.runtime.open_evaluation(project_id, evaluation_id)
        evaluation_root = self.runtime.projects_root / project_id / "evaluations" / evaluation_id
        manifest = load_prelaunch_manifest(
            evaluation_root / evaluation.files["prelaunch_manifest"].locator
        ).manifest
        plan = load_evaluation_cell_plan(evaluation_root / evaluation.files["cell_plan"].locator)
        if (
            manifest.proposal_sha256 != evaluation.proposal_sha256
            or plan.proposal_sha256 != evaluation.proposal_sha256
        ):
            raise ValueError("registered evaluation proposal, manifest, and plan differ")
        return _CampaignInputs(
            snapshot=snapshot,
            evaluation=evaluation,
            manifest=manifest,
            plan=plan,
        )

    @staticmethod
    def _select_cells(
        plan: EvaluationCellPlan,
        *,
        cell_ids: tuple[str, ...] | None,
    ) -> tuple[PlannedEvaluationCell, ...]:
        known = {cell.cell_id for cell in plan.cells}
        requested = set(cell_ids or known)
        unknown = requested - known
        if unknown:
            raise ValueError("unknown evaluation cells: " + ", ".join(sorted(unknown)))
        selected = tuple(cell for cell in plan.cells if cell.cell_id in requested)
        if not selected:
            raise ValueError("evaluation campaign selected no cells")
        return selected

    def _readiness_blockers(
        self,
        inputs: _CampaignInputs,
        selected: tuple[PlannedEvaluationCell, ...],
        launch_blockers: list[str],
        activation: EvaluationCampaignActivation | None,
    ) -> list[str]:
        blockers = list(launch_blockers)
        if activation is None:
            if not inputs.evaluation.execution_authorized:
                blockers.append("evaluation:not-execution-authorized")
            if not inputs.plan.ready_for_launch_preparation:
                blockers.extend(f"plan:{code}" for code in inputs.plan.plan_blockers)
            if not inputs.plan.proposal_author_approved:
                blockers.append("proposal:owner-approval-missing")
        else:
            blockers.extend(self._activation_blockers(inputs, selected, activation))
        for cell in selected:
            blockers.extend(f"cell:{cell.cell_id}:{code}" for code in cell.readiness_blockers)
        return sorted(set(blockers))

    def _activation_blockers(
        self,
        inputs: _CampaignInputs,
        selected: tuple[PlannedEvaluationCell, ...],
        activation: EvaluationCampaignActivation,
    ) -> list[str]:
        blockers: list[str] = []
        if not activation.approval.approved:
            blockers.append("activation:owner-approval-missing")
        if inputs.manifest.schema_version != "1.6":
            blockers.append("activation:typed-prelaunch-v1.6-required")
        if inputs.manifest.study_scope != "pilot":
            blockers.append("activation:pilot-scope-required")
        if inputs.manifest.primary_endpoint is not ScientificEndpointKind.OBJECTIVE_PROGRESS:
            blockers.append("activation:objective-endpoint-required")
        if inputs.manifest.analysis is None or inputs.manifest.integrity is None:
            blockers.append("activation:protocol-contract-incomplete")
        if (
            inputs.manifest.source_commit is None
            or inputs.evaluation.observed_source_commit != inputs.manifest.source_commit
            or inputs.evaluation.source_tree_clean is not True
        ):
            blockers.append("activation:registered-source-integrity-unverified")
        systems = {system.system_id: system for system in inputs.manifest.systems}
        for system_id in {cell.system_id for cell in selected}:
            system = systems[system_id]
            if system.adapter_evidence_kind is not AdapterEvidenceKind.NATIVE_PREFLIGHT_REPORT:
                blockers.append(f"activation:{system_id}:native-preflight-report-required")
                continue
            if system.adapter_preflight_ref is None or system.adapter_preflight_sha256 is None:
                blockers.append(f"activation:{system_id}:native-preflight-report-unbound")
                continue
            try:
                from scitaste.evaluation.native_condition_preflight import (
                    NativeConditionPreflightReport,
                )

                report_path = self._activation_evidence_file(
                    system.adapter_preflight_ref,
                    system.adapter_preflight_sha256,
                )
                report = NativeConditionPreflightReport.model_validate_json(
                    report_path.read_bytes()
                )
                if report.source_commit != inputs.manifest.source_commit:
                    blockers.append(f"activation:{system_id}:native-preflight-source-drift")
                if not report.ready_for_experiment:
                    blockers.append(f"activation:{system_id}:native-preflight-not-ready")
            except (OSError, ValueError):
                blockers.append(f"activation:{system_id}:native-preflight-report-invalid")
        analysis = inputs.manifest.analysis
        if analysis is not None:
            if (
                analysis.objective_outcome_contract_ref is None
                or analysis.objective_outcome_contract_sha256 is None
            ):
                blockers.append("activation:objective-outcome-contract-unbound")
            else:
                try:
                    self._activation_evidence_file(
                        analysis.objective_outcome_contract_ref,
                        analysis.objective_outcome_contract_sha256,
                    )
                except (OSError, ValueError):
                    blockers.append("activation:objective-outcome-contract-invalid")
        return blockers

    def _activation_evidence_file(self, locator: str, expected_sha256: str) -> Path:
        pure = PurePosixPath(locator)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise ValueError("activation evidence path is unsafe")
        root = self.evidence_root.resolve(strict=True)
        candidate = root
        for part in pure.parts:
            candidate /= part
            if candidate.is_symlink():
                raise ValueError("activation evidence cannot traverse a symbolic link")
        resolved = candidate.resolve(strict=True)
        if (
            not resolved.is_relative_to(root)
            or not resolved.is_file()
            or resolved.stat().st_size < 1
            or resolved.stat().st_size > _MAX_RESULT_BYTES
            or _file_sha256(resolved) != expected_sha256
        ):
            raise ValueError("activation evidence is missing, oversized, or changed")
        return resolved

    def _objective_closure(
        self,
        inputs: _CampaignInputs,
        campaign: EvaluationCampaignManifest,
        results: EvaluationResultSet,
        campaign_root: Path,
        *,
        selected_complete: bool,
        failed: int,
    ) -> _ObjectiveClosure | None:
        analysis = inputs.manifest.analysis
        claim = analysis.claim_admission if analysis is not None else None
        if (
            not selected_complete
            or (failed and campaign.claim_authority)
            or inputs.manifest.primary_endpoint is not ScientificEndpointKind.OBJECTIVE_PROGRESS
            or claim is None
            or claim.estimand_kind
            not in {
                ConfirmatoryEstimandKind.NATIVE_TASTE_CAUSAL,
                ConfirmatoryEstimandKind.NATIVE_TASTE_MECHANISMS,
            }
        ):
            return None
        if (
            analysis.objective_outcome_contract_ref is None
            or analysis.objective_outcome_contract_sha256 is None
        ):
            raise ValueError("native objective campaign lacks a bound outcome contract")

        from scitaste.evaluation.objective_analysis import (
            ObjectiveAnalysisMaterialization,
            ObjectiveAnalysisReport,
            analyze_objective_outcomes,
            bind_objective_measurement_set,
            complete_objective_result_set,
            load_objective_measurement_set,
            load_objective_outcome_contract,
            materialize_objective_analysis,
            primary_comparisons_from_objective_report,
            save_completed_objective_result_set,
            save_objective_measurement_set,
        )
        from scitaste.evaluation.objective_measurement_collection import (
            collect_native_objective_measurements,
        )

        contract = load_objective_outcome_contract(
            self.evidence_root / PurePosixPath(analysis.objective_outcome_contract_ref)
        )
        if contract.file_sha256 != analysis.objective_outcome_contract_sha256:
            raise ValueError("native objective outcome contract differs from prelaunch")
        project_root = self.runtime.projects_root / campaign.project_id
        measurements = collect_native_objective_measurements(
            inputs.plan,
            results,
            contract,
            project_root=project_root,
            selected_cell_ids=campaign.selected_cell_ids,
        )
        measurement_path = campaign_root / "OBJECTIVE_MEASUREMENTS.json"
        if measurement_path.exists():
            if load_objective_measurement_set(measurement_path) != measurements:
                raise ValueError("existing objective measurement set differs on resume")
        else:
            save_objective_measurement_set(measurements, measurement_path)
        measurement_artifact = bind_objective_measurement_set(
            measurement_path,
            project_root=project_root,
        )
        measurement_locator = measurement_path.relative_to(project_root).as_posix()
        if not campaign.claim_authority:
            return _ObjectiveClosure(
                measurement_set_locator=measurement_locator,
                measurement_set_sha256=measurements.measurement_set_sha256,
            )

        analysis_path = campaign_root / "OBJECTIVE_ANALYSIS.json"
        completed_path = campaign_root / "COMPLETED_RESULT_SET.json"
        if analysis_path.exists() or completed_path.exists():
            if not analysis_path.is_file() or not completed_path.is_file():
                raise ValueError("objective closure is only partially materialized")
            expected_report = analyze_objective_outcomes(
                inputs.manifest,
                inputs.plan,
                results,
                contract,
                measurements,
                project_root=project_root,
                evidence_root=self.evidence_root,
                project_id=campaign.project_id,
                evaluation_id=campaign.evaluation_id,
            )
            observed_report = ObjectiveAnalysisReport.model_validate_json(
                analysis_path.read_bytes()
            )
            if observed_report != expected_report:
                raise ValueError("existing objective analysis differs on resume")
            analysis_artifact = EvaluationResultArtifact(
                locator=analysis_path.relative_to(project_root).as_posix(),
                sha256=_file_sha256(analysis_path),
                size_bytes=analysis_path.stat().st_size,
            )
            comparisons = primary_comparisons_from_objective_report(
                observed_report,
                contract.contract,
                analysis_artifact=analysis_artifact,
                measurement_set_artifact=measurement_artifact,
            )
            materialized = ObjectiveAnalysisMaterialization(
                report=observed_report,
                analysis_artifact=analysis_artifact,
                primary_comparisons=comparisons,
                output_path=analysis_path,
            )
            completed = complete_objective_result_set(results, materialized)
            observed_completed = EvaluationResultSet.model_validate_json(
                completed_path.read_bytes()
            )
            if observed_completed != completed:
                raise ValueError("existing completed objective result differs on resume")
            return _ObjectiveClosure(
                measurement_set_locator=measurement_locator,
                measurement_set_sha256=measurements.measurement_set_sha256,
                analysis_locator=analysis_path.relative_to(project_root).as_posix(),
                analysis_sha256=observed_report.report_sha256,
                completed_result_set_locator=(
                    completed_path.relative_to(project_root).as_posix()
                ),
                completed_result_set_sha256=completed.result_set_sha256,
                completed_result_set=completed,
            )
        materialized = materialize_objective_analysis(
            inputs.manifest,
            inputs.plan,
            results,
            contract,
            measurements,
            measurement_artifact,
            project_root=project_root,
            evidence_root=self.evidence_root,
            project_id=campaign.project_id,
            evaluation_id=campaign.evaluation_id,
            output_path=analysis_path.relative_to(project_root).as_posix(),
        )
        completed = complete_objective_result_set(results, materialized)
        save_completed_objective_result_set(
            completed,
            completed_path.relative_to(project_root).as_posix(),
            project_root=project_root,
        )
        return _ObjectiveClosure(
            measurement_set_locator=measurement_locator,
            measurement_set_sha256=measurements.measurement_set_sha256,
            analysis_locator=analysis_path.relative_to(project_root).as_posix(),
            analysis_sha256=materialized.report.report_sha256,
            completed_result_set_locator=completed_path.relative_to(project_root).as_posix(),
            completed_result_set_sha256=completed.result_set_sha256,
            completed_result_set=completed,
        )

    def _launches(
        self,
        project_id: str,
        run_id: str,
        selected: tuple[PlannedEvaluationCell, ...],
    ) -> tuple[list[EvaluationCellLaunch], list[str]]:
        launches: list[EvaluationCellLaunch] = []
        blockers: list[str] = []
        for cell in selected:
            launcher = self.launch_config.launchers.get(cell.system_id)
            if launcher is None:
                blockers.append(f"launcher:{cell.system_id}:missing")
                continue
            if cell.lane_kind is ExecutionLaneKind.API_ONLY:
                if launcher.gpu_count:
                    blockers.append(f"launcher:{cell.system_id}:api-gpu-count-must-be-zero")
                key_env = cell.resource.api_key_env
                if key_env not in launcher.pass_environment:
                    blockers.append(f"launcher:{cell.system_id}:api-key-env-not-bound")
            elif launcher.gpu_count < 1:
                blockers.append(f"launcher:{cell.system_id}:gpu-count-missing")
            root = self._campaign_root(project_id, run_id)
            cell_dir = (root / "cells" / cell.cell_id).resolve()
            try:
                command = self._render_command(cell, launcher, cell_dir)
            except ValueError as exc:
                blockers.append(f"launcher:{cell.system_id}:{exc}")
                continue
            launches.append(
                EvaluationCellLaunch(
                    cell_id=cell.cell_id,
                    system_id=cell.system_id,
                    task_id=cell.task_id,
                    lane_kind=cell.lane_kind,
                    command=command,
                    cell_directory=str(cell_dir),
                )
            )
        return launches, blockers

    def _begin_or_resume(
        self,
        snapshot: ProjectSnapshot,
        campaign: EvaluationCampaignManifest,
        *,
        resume: bool,
    ) -> ProjectSnapshot:
        registered = next(
            (item for item in snapshot.manifest.runs if item.run_id == campaign.run_id), None
        )
        if resume:
            if registered is None:
                raise ValueError("cannot resume an unknown evaluation campaign")
            extra = registered.model_extra or {}
            expected = (
                registered.condition,
                registered.stage_path,
                extra.get("evaluation_id"),
                extra.get("campaign_manifest_sha256"),
            )
            actual = (
                "authorized-evaluation-campaign",
                "evaluation_campaign",
                campaign.evaluation_id,
                campaign.manifest_sha256,
            )
            if expected != actual:
                raise ValueError("resume campaign identity differs from the registered run")
            return self.runtime.update_run(
                campaign.project_id,
                campaign.run_id,
                expected_revision=snapshot.revision,
                status="running",
                resume_attempt=int(extra.get("resume_attempt", 0)) + 1,
            )
        if registered is not None:
            raise FileExistsError(self._campaign_root(campaign.project_id, campaign.run_id).parent)
        return self.runtime.begin_run(
            campaign.project_id,
            ProjectRun(
                run_id=campaign.run_id,
                provider="scitaste-native",
                model="project-evaluation-campaign-runner",
                condition="authorized-evaluation-campaign",
                seed=0,
                status="running",
                evidence_scope="exact-authorized-cell-execution",
                stage_path="evaluation_campaign",
                artifact=self._result_set_locator(campaign.run_id),
                evaluation_id=campaign.evaluation_id,
                proposal_sha256=campaign.proposal_sha256,
                plan_sha256=campaign.plan_sha256,
                launch_config_sha256=campaign.launch_config_sha256,
                campaign_manifest_sha256=campaign.manifest_sha256,
                activation_sha256=campaign.activation_sha256,
                claim_authority=campaign.claim_authority,
                resume_attempt=0,
            ),
            expected_revision=snapshot.revision,
        )

    def _run_cell(
        self,
        project_id: str,
        root: Path,
        cell: PlannedEvaluationCell,
        campaign: EvaluationCampaignManifest,
    ) -> EvaluationCellResult:
        cell_dir = root / "cells" / cell.cell_id
        cell_dir.mkdir(parents=True, exist_ok=True)
        request_path = cell_dir / "CELL_REQUEST.json"
        adapter_result_path = cell_dir / "ADAPTER_RESULT.json"
        stdout_path = cell_dir / "stdout.log"
        stderr_path = cell_dir / "stderr.log"
        record_path = cell_dir / "CELL_RESULT.json"
        launcher = self.launch_config.launchers[cell.system_id]
        command = self._render_command(cell, launcher, cell_dir.resolve())
        request = {
            "schema_version": "1.0",
            "project_id": project_id,
            "evaluation_id": campaign.evaluation_id,
            "campaign_manifest_sha256": campaign.manifest_sha256,
            "plan_sha256": campaign.plan_sha256,
            "cell": cell.model_dump(mode="json"),
            "adapter_result_path": str(adapter_result_path.resolve()),
        }
        _atomic_json_write(request_path, request)
        adapter_result_path.unlink(missing_ok=True)
        started = self.clock()
        try:
            environment = self._environment(
                launcher, cell, request_path, adapter_result_path, cell_dir
            )
            process = self.process_runner.run(
                list(command),
                cwd=cell_dir,
                environment=environment,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout_seconds=self._timeout(cell, launcher),
            )
            elapsed = max(0.0, self.clock() - started)
            if process.returncode != 0:
                record = self._failed_record(
                    cell,
                    launcher,
                    elapsed,
                    "nonzero-exit",
                    plan_sha256=campaign.plan_sha256,
                    experiment_count=1,
                )
            elif not adapter_result_path.is_file():
                record = self._failed_record(
                    cell,
                    launcher,
                    elapsed,
                    "adapter-result-missing",
                    plan_sha256=campaign.plan_sha256,
                    experiment_count=1,
                )
            else:
                record = self._record_from_adapter(
                    project_id,
                    cell,
                    launcher,
                    elapsed,
                    _load_adapter_result(adapter_result_path),
                    cell_dir,
                    campaign.plan_sha256,
                )
        except subprocess.TimeoutExpired:
            elapsed = max(0.0, self.clock() - started)
            record = self._failed_record(
                cell,
                launcher,
                elapsed,
                "timeout",
                plan_sha256=campaign.plan_sha256,
                experiment_count=1,
            )
        except (OSError, ValueError) as exc:
            elapsed = max(0.0, self.clock() - started)
            code = "launcher-error" if isinstance(exc, OSError) else "adapter-result-invalid"
            _atomic_json_write(
                cell_dir / "FAILURE.json",
                {"schema_version": "1.0", "error_code": code, "error": str(exc)[:2_000]},
            )
            record = self._failed_record(
                cell,
                launcher,
                elapsed,
                code,
                plan_sha256=campaign.plan_sha256,
                experiment_count=1,
            )
        _atomic_json_write(record_path, record.model_dump(mode="json"))
        self._write_checkpoint(project_id, root, cell, record, campaign, command)
        return record

    def _record_from_adapter(
        self,
        project_id: str,
        cell: PlannedEvaluationCell,
        launcher: EvaluationCommandLauncher,
        elapsed: float,
        result: EvaluationAdapterResult,
        cell_dir: Path,
        plan_sha256: str,
    ) -> EvaluationCellResult:
        usage = self._usage(cell, launcher, elapsed, result.usage)
        artifacts = tuple(
            self._artifact(project_id, cell_dir, locator) for locator in result.artifact_paths
        )
        budget_error = _budget_error(cell, result.usage, usage, artifacts)
        status = result.status
        error_code = result.error_code
        outcome = result.outcome
        if budget_error is not None:
            status, error_code, outcome = "failed", budget_error, None
        return EvaluationCellResult.create(
            cell_id=cell.cell_id,
            proposal_sha256=cell.proposal_sha256,
            plan_sha256=plan_sha256,
            cell_sha256=content_sha256(cell),
            resource_sha256=cell.resource.resource_sha256,
            status=status,
            evidence_class=result.evidence_class,
            usage=usage,
            outcome=outcome,
            artifacts=artifacts,
            error_code=error_code,
        )

    def _failed_record(
        self,
        cell: PlannedEvaluationCell,
        launcher: EvaluationCommandLauncher,
        elapsed: float,
        error_code: str,
        *,
        plan_sha256: str,
        experiment_count: int,
    ) -> EvaluationCellResult:
        return EvaluationCellResult.create(
            cell_id=cell.cell_id,
            proposal_sha256=cell.proposal_sha256,
            plan_sha256=plan_sha256,
            cell_sha256=content_sha256(cell),
            resource_sha256=cell.resource.resource_sha256,
            status="failed",
            evidence_class="real",
            usage=self._usage(
                cell,
                launcher,
                elapsed,
                EvaluationAdapterUsage(experiment_count=experiment_count),
            ),
            error_code=error_code,
        )

    @staticmethod
    def _usage(
        cell: PlannedEvaluationCell,
        launcher: EvaluationCommandLauncher,
        elapsed: float,
        usage: EvaluationAdapterUsage,
    ) -> EvaluationCellUsage:
        if cell.lane_kind is ExecutionLaneKind.API_ONLY:
            return EvaluationCellUsage(
                request_count=usage.request_count or 0,
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                api_cost=usage.api_cost or 0.0,
                gpu_hours=None,
                wall_time_hours=elapsed / 3600,
                experiment_count=usage.experiment_count,
            )
        return EvaluationCellUsage(
            request_count=usage.request_count,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            api_cost=None,
            gpu_hours=elapsed * launcher.gpu_count / 3600,
            wall_time_hours=elapsed / 3600,
            experiment_count=usage.experiment_count,
        )

    def _artifact(self, project_id: str, cell_dir: Path, locator: str) -> EvaluationResultArtifact:
        pure = PurePosixPath(locator)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise ValueError("adapter artifact locator must be relative and normalized")
        candidate = cell_dir
        for part in pure.parts:
            candidate /= part
            if candidate.is_symlink():
                raise ValueError("adapter artifacts cannot traverse symbolic links")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file() or not resolved.is_relative_to(cell_dir.resolve()):
            raise ValueError("adapter artifact must be a regular file owned by its cell")
        project_root = (self.runtime.projects_root / project_id).resolve(strict=True)
        relative = resolved.relative_to(project_root).as_posix()
        size = resolved.stat().st_size
        if size < 1:
            raise ValueError("adapter artifacts cannot be empty")
        return EvaluationResultArtifact(
            locator=relative,
            sha256=_file_sha256(resolved),
            size_bytes=size,
        )

    def _write_checkpoint(
        self,
        project_id: str,
        root: Path,
        cell: PlannedEvaluationCell,
        record: EvaluationCellResult,
        campaign: EvaluationCampaignManifest,
        command: tuple[str, ...],
    ) -> None:
        cell_dir = root / "cells" / cell.cell_id
        evidence: dict[str, str] = {}
        for path in sorted(cell_dir.iterdir()):
            if path.name == "CHECKPOINT.json" or not path.is_file() or path.is_symlink():
                continue
            evidence[path.name] = _file_sha256(path)
        for artifact in record.artifacts:
            path = self.runtime.projects_root / project_id / artifact.locator
            evidence[f"artifact:{artifact.locator}"] = _file_sha256(path)
        checkpoint = EvaluationCellCheckpoint.create(
            cell_id=cell.cell_id,
            attempt=_attempt_number(cell_dir),
            campaign_manifest_sha256=campaign.manifest_sha256,
            cell_sha256=content_sha256(cell),
            request_sha256=_file_sha256(cell_dir / "CELL_REQUEST.json"),
            command_sha256=content_sha256(list(command)),
            result_sha256=record.record_sha256,
            evidence_sha256=dict(sorted(evidence.items())),
        )
        _atomic_json_write(cell_dir / "CHECKPOINT.json", checkpoint.model_dump(mode="json"))

    def _verify_checkpoint(
        self,
        project_id: str,
        root: Path,
        cell: PlannedEvaluationCell,
        record: EvaluationCellResult,
        campaign: EvaluationCampaignManifest,
    ) -> None:
        cell_dir = root / "cells" / cell.cell_id
        checkpoint_path = cell_dir / "CHECKPOINT.json"
        record_path = cell_dir / "CELL_RESULT.json"
        checkpoint = EvaluationCellCheckpoint.model_validate_json(checkpoint_path.read_bytes())
        observed = EvaluationCellResult.model_validate_json(record_path.read_bytes())
        if observed != record or checkpoint.result_sha256 != record.record_sha256:
            raise ValueError(f"evaluation cell record/checkpoint mismatch: {cell.cell_id}")
        if (
            checkpoint.campaign_manifest_sha256 != campaign.manifest_sha256
            or checkpoint.cell_sha256 != content_sha256(cell)
        ):
            raise ValueError(f"evaluation cell checkpoint identity mismatch: {cell.cell_id}")
        for locator, digest in checkpoint.evidence_sha256.items():
            path = (
                self.runtime.projects_root / project_id / locator.removeprefix("artifact:")
                if locator.startswith("artifact:")
                else cell_dir / locator
            )
            if not path.is_file() or path.is_symlink() or _file_sha256(path) != digest:
                raise ValueError(f"evaluation cell checkpoint evidence drift: {locator}")

    def _load_records(
        self,
        project_id: str,
        root: Path,
        plan: EvaluationCellPlan,
        campaign: EvaluationCampaignManifest,
    ) -> dict[str, EvaluationCellResult]:
        result_set_path = root / "RESULT_SET.json"
        aggregate: dict[str, EvaluationCellResult] = {}
        if result_set_path.is_file():
            result_set = EvaluationResultSet.model_validate_json(result_set_path.read_bytes())
            if (
                result_set.project_id != project_id
                or result_set.evaluation_id != campaign.evaluation_id
                or result_set.proposal_sha256 != plan.proposal_sha256
                or result_set.plan_sha256 != plan.plan_sha256
            ):
                raise ValueError("existing campaign result set has another identity")
            aggregate = {item.cell_id: item for item in result_set.cell_results}
        observed: dict[str, EvaluationCellResult] = {}
        by_id = {cell.cell_id: cell for cell in plan.cells}
        cells_root = root / "cells"
        if cells_root.is_dir():
            for record_path in cells_root.glob("*/CELL_RESULT.json"):
                record = EvaluationCellResult.model_validate_json(record_path.read_bytes())
                cell = by_id.get(record.cell_id)
                if cell is None or record_path.parent.name != record.cell_id:
                    raise ValueError("campaign contains an unplanned cell result")
                if record.cell_id in observed:
                    raise ValueError("campaign contains duplicate cell results")
                self._verify_checkpoint(project_id, root, cell, record, campaign)
                observed[record.cell_id] = record
        if any(observed.get(cell_id) != record for cell_id, record in aggregate.items()):
            raise ValueError("aggregate and checkpointed campaign cell results differ")
        return observed

    @staticmethod
    def _save_result_set(
        project_id: str,
        root: Path,
        evaluation_id: str,
        plan: EvaluationCellPlan,
        records: dict[str, EvaluationCellResult],
    ) -> EvaluationResultSet:
        order = {cell.cell_id: index for index, cell in enumerate(plan.cells)}
        result_set = EvaluationResultSet.create(
            project_id=project_id,
            evaluation_id=evaluation_id,
            proposal_sha256=plan.proposal_sha256,
            plan_sha256=plan.plan_sha256,
            cell_results=tuple(sorted(records.values(), key=lambda item: order[item.cell_id])),
            blind_reviews=(),
            primary_comparisons=(),
        )
        _atomic_json_write(root / "RESULT_SET.json", result_set.model_dump(mode="json"))
        return result_set

    def _archive_attempt(
        self,
        root: Path,
        cell_id: str,
        previous: EvaluationCellResult | None,
    ) -> None:
        cell_dir = root / "cells" / cell_id
        if not cell_dir.exists():
            if previous is not None:
                raise ValueError("aggregate cell record has no owned cell directory")
            return
        if previous is None and any(
            (cell_dir / name).exists() for name in ("CELL_RESULT.json", "CHECKPOINT.json")
        ):
            raise ValueError("existing completed cell directory has no aggregate result")
        archive_root = cell_dir / "failed_attempts"
        movable = [path for path in cell_dir.iterdir() if path.name != "failed_attempts"]
        if not movable:
            return
        archive_root.mkdir(exist_ok=True)
        destination = archive_root / f"attempt-{_next_archive_number(archive_root):03d}"
        temporary = Path(tempfile.mkdtemp(prefix=".attempt-", dir=archive_root))
        try:
            for source in movable:
                os.replace(source, temporary / source.name)
            os.replace(temporary, destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def _materialize_manifest(self, root: Path, campaign: EvaluationCampaignManifest) -> None:
        path = root / "CAMPAIGN.json"
        if path.is_file():
            observed = EvaluationCampaignManifest.model_validate_json(path.read_bytes())
            if observed != campaign:
                raise ValueError("existing campaign manifest has another identity")
            return
        existing = [item for item in root.iterdir() if item.name not in {".campaign.lock"}]
        if existing:
            raise ValueError("campaign output exists without an identity manifest")
        _atomic_json_write(path, campaign.model_dump(mode="json"))

    def _render_command(
        self,
        cell: PlannedEvaluationCell,
        launcher: EvaluationCommandLauncher,
        cell_dir: Path,
    ) -> tuple[str, ...]:
        values = {
            "cell_id": cell.cell_id,
            "system_id": cell.system_id,
            "task_id": cell.task_id,
            "lane_id": cell.lane_id,
            "seed": str(cell.seed),
            "repetition": str(cell.repetition),
            "cell_dir": str(cell_dir),
            "cell_request": str(cell_dir / "CELL_REQUEST.json"),
            "cell_result": str(cell_dir / "ADAPTER_RESULT.json"),
        }
        rendered: list[str] = []
        for source in launcher.command:
            value = source
            for name, replacement in values.items():
                value = value.replace("{" + name + "}", replacement)
            if re.search(r"\{[a-z_]+\}", value):
                raise ValueError("unknown-placeholder")
            rendered.append(value)
        return tuple(rendered)

    @staticmethod
    def _environment(
        launcher: EvaluationCommandLauncher,
        cell: PlannedEvaluationCell,
        request_path: Path,
        result_path: Path,
        cell_dir: Path,
    ) -> dict[str, str]:
        missing = [name for name in launcher.pass_environment if name not in os.environ]
        if missing:
            raise ValueError("required environment variables are missing: " + ", ".join(missing))
        environment = {name: os.environ[name] for name in _BASE_ENVIRONMENT if name in os.environ}
        environment.update({name: os.environ[name] for name in launcher.pass_environment})
        environment.update(
            {
                "PYTHONUNBUFFERED": "1",
                "SCITASTE_EVALUATION_CELL_REQUEST": str(request_path.resolve()),
                "SCITASTE_EVALUATION_CELL_RESULT": str(result_path.resolve()),
                "SCITASTE_EVALUATION_CELL_DIR": str(cell_dir.resolve()),
                "SCITASTE_EVALUATION_CELL_ID": cell.cell_id,
            }
        )
        return environment

    @staticmethod
    def _timeout(cell: PlannedEvaluationCell, launcher: EvaluationCommandLauncher) -> float:
        if cell.lane_kind is ExecutionLaneKind.API_ONLY:
            return launcher.timeout_seconds
        assert cell.resource.max_gpu_hours is not None and launcher.gpu_count > 0
        return min(
            launcher.timeout_seconds,
            cell.resource.max_gpu_hours * 3600 / launcher.gpu_count,
        )

    def _campaign_root(self, project_id: str, run_id: str) -> Path:
        return self.runtime.projects_root / project_id / "runs" / run_id / "evaluation_campaign"

    @staticmethod
    def _result_set_locator(run_id: str) -> str:
        return f"runs/{run_id}/evaluation_campaign/RESULT_SET.json"

    @contextmanager
    def _locked(self, root: Path):
        with (root / ".campaign.lock").open("a+b") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another runner owns this evaluation campaign") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_evaluation_campaign_launch_config(
    path: str | Path,
) -> EvaluationCampaignLaunchConfig:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("evaluation campaign launch config must be a regular file")
    raw = candidate.read_bytes()
    if not raw or len(raw) > _MAX_CONFIG_BYTES:
        raise ValueError("evaluation campaign launch config has an invalid size")
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError("evaluation campaign launch config must contain one mapping")
    return EvaluationCampaignLaunchConfig.model_validate(payload)


def _load_adapter_result(path: Path) -> EvaluationAdapterResult:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_RESULT_BYTES:
        raise ValueError("evaluation adapter result must be a bounded regular file")
    return EvaluationAdapterResult.model_validate_json(path.read_bytes())


def _budget_error(
    cell: PlannedEvaluationCell,
    reported: EvaluationAdapterUsage,
    usage: EvaluationCellUsage,
    artifacts: tuple[EvaluationResultArtifact, ...],
) -> str | None:
    resource = cell.resource
    if cell.lane_kind is ExecutionLaneKind.API_ONLY:
        required = (
            reported.request_count,
            reported.input_tokens,
            reported.output_tokens,
            reported.max_input_tokens_observed,
            reported.max_output_tokens_observed,
            reported.api_cost,
        )
        if any(value is None for value in required):
            return "api-telemetry-incomplete"
        assert reported.request_count is not None
        assert reported.input_tokens is not None
        assert reported.output_tokens is not None
        assert reported.max_input_tokens_observed is not None
        assert reported.max_output_tokens_observed is not None
        assert reported.api_cost is not None
        if reported.request_count > int(resource.max_requests or 0):
            return "request-budget-exceeded"
        if reported.input_tokens + reported.output_tokens > int(resource.max_total_tokens or 0):
            return "token-budget-exceeded"
        if reported.max_input_tokens_observed > int(resource.max_input_tokens_per_call or 0):
            return "input-token-call-budget-exceeded"
        if reported.max_output_tokens_observed > int(resource.max_output_tokens_per_call or 0):
            return "output-token-call-budget-exceeded"
        if reported.api_cost > float(resource.max_cost or 0):
            return "cost-budget-exceeded"
    else:
        local_model_telemetry = (
            reported.request_count,
            reported.input_tokens,
            reported.output_tokens,
            reported.max_input_tokens_observed,
            reported.max_output_tokens_observed,
        )
        if reported.api_cost is not None:
            return "gpu-telemetry-kind-mismatch"
        if any(value is not None for value in local_model_telemetry) and any(
            value is None for value in local_model_telemetry
        ):
            return "local-model-telemetry-incomplete"
        if (usage.gpu_hours or 0) > float(resource.max_gpu_hours or 0):
            return "gpu-budget-exceeded"
        if sum(item.size_bytes for item in artifacts) > int(resource.max_storage_bytes or 0):
            return "storage-budget-exceeded"
    return None


def _atomic_json_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _attempt_number(cell_dir: Path) -> int:
    return 1 + len(tuple(cell_dir.glob("failed_attempts/attempt-*")))


def _next_archive_number(root: Path) -> int:
    observed = [
        int(item.name.removeprefix("attempt-"))
        for item in root.glob("attempt-[0-9][0-9][0-9]")
        if item.name.removeprefix("attempt-").isdigit()
    ]
    return max(observed, default=0) + 1


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "EvaluationAdapterResult",
    "EvaluationAdapterUsage",
    "EvaluationCampaignHandoff",
    "EvaluationCampaignLaunchConfig",
    "EvaluationCampaignManifest",
    "EvaluationCampaignSummary",
    "EvaluationCellCheckpoint",
    "EvaluationCellLaunch",
    "EvaluationCommandLauncher",
    "ProjectEvaluationCampaignRunner",
    "load_evaluation_campaign_launch_config",
]

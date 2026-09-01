"""Fixed-candidate intrinsic scientific-taste calibration."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.backends.base import PreferenceBackend, PreferenceRequest, Usage
from scitaste.schema.actions import ResearchAction


class TasteTask(StrEnum):
    IDEA = "idea"
    EXPERIMENT = "experiment"
    EVIDENCE = "evidence"
    WRITING = "writing"
    REVIEW = "review"
    VISUAL = "visual"


class CalibrationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    task: TasteTask
    stage: str
    decision_context: str = Field(min_length=1)
    candidate_actions: list[ResearchAction] = Field(min_length=2)
    preferred_action_id: str
    scripted_selection_id: str | None = None

    @model_validator(mode="after")
    def references_are_valid(self) -> CalibrationCase:
        candidate_ids = {action.action_id for action in self.candidate_actions}
        if len(candidate_ids) != len(self.candidate_actions):
            raise ValueError("candidate action ids must be unique")
        if self.preferred_action_id not in candidate_ids:
            raise ValueError("preferred_action_id must be a candidate")
        if (
            self.scripted_selection_id is not None
            and self.scripted_selection_id not in candidate_ids
        ):
            raise ValueError("scripted_selection_id must be a candidate")
        return self

    def to_request(self, *, seed: int) -> PreferenceRequest:
        return PreferenceRequest(
            request_id=self.case_id,
            task=self.task.value,
            stage=self.stage,
            decision_context=self.decision_context,
            candidate_actions=self.candidate_actions,
            seed=seed,
        )


class CalibrationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str
    version: str
    description: str
    cases: list[CalibrationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> CalibrationSuite:
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("calibration case ids must be unique")
        return self


class CalibrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    task: TasteTask
    selected_action_id: str
    preferred_action_id: str
    correct: bool
    confidence: float
    rationale: str
    backend: str
    model: str
    cached: bool
    usage: Usage


class TaskMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int
    accuracy: float
    mean_confidence: float
    brier_score: float
    expected_calibration_error: float


class CalibrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str
    suite_version: str
    backend: str
    model: str
    seed: int
    overall: TaskMetrics
    by_task: dict[TasteTask, TaskMetrics]
    results: list[CalibrationResult]


class BackendProtocolError(ValueError):
    """Raised when a backend violates the fixed-candidate response contract."""


class IntrinsicTasteCalibrator:
    """Evaluate a backend with no retrieval, exemplars, or trainable adapters."""

    def __init__(self, backend: PreferenceBackend, *, seed: int = 0) -> None:
        self.backend = backend
        self.seed = seed

    def evaluate(self, suite: CalibrationSuite) -> CalibrationReport:
        results: list[CalibrationResult] = []
        for case in suite.cases:
            request = case.to_request(seed=self.seed)
            response = self.backend.rank(request)
            candidate_ids = {action.action_id for action in case.candidate_actions}
            if response.request_id != case.case_id:
                raise BackendProtocolError("backend response request_id does not match case")
            if response.request_fingerprint != request.fingerprint:
                raise BackendProtocolError("backend response fingerprint does not match request")
            if response.selected_action_id not in candidate_ids:
                raise BackendProtocolError(
                    f"backend selected unknown action {response.selected_action_id!r}"
                )
            results.append(
                CalibrationResult(
                    case_id=case.case_id,
                    task=case.task,
                    selected_action_id=response.selected_action_id,
                    preferred_action_id=case.preferred_action_id,
                    correct=response.selected_action_id == case.preferred_action_id,
                    confidence=response.confidence,
                    rationale=response.rationale,
                    backend=response.backend,
                    model=response.model,
                    cached=response.cached,
                    usage=response.usage,
                )
            )

        model_names = {result.model for result in results}
        if len(model_names) != 1:
            raise BackendProtocolError("one calibration report cannot mix models")
        task_groups = {
            task: [result for result in results if result.task == task]
            for task in TasteTask
            if any(result.task == task for result in results)
        }
        return CalibrationReport(
            suite_id=suite.suite_id,
            suite_version=suite.version,
            backend=self.backend.name,
            model=next(iter(model_names)),
            seed=self.seed,
            overall=_metrics(results),
            by_task={task: _metrics(items) for task, items in task_groups.items()},
            results=results,
        )


def load_calibration_suite(path: str | Path) -> CalibrationSuite:
    source = Path(path)
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    return CalibrationSuite.model_validate(data)


def save_calibration_report(report: CalibrationReport, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _metrics(results: list[CalibrationResult]) -> TaskMetrics:
    count = len(results)
    accuracy = sum(result.correct for result in results) / count
    mean_confidence = sum(result.confidence for result in results) / count
    brier = sum((result.confidence - float(result.correct)) ** 2 for result in results) / count
    return TaskMetrics(
        count=count,
        accuracy=round(accuracy, 6),
        mean_confidence=round(mean_confidence, 6),
        brier_score=round(brier, 6),
        expected_calibration_error=round(_ece(results), 6),
    )


def _ece(results: list[CalibrationResult], bins: int = 5) -> float:
    total = len(results)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            result
            for result in results
            if lower <= result.confidence <= upper
            and (index == bins - 1 or result.confidence < upper)
        ]
        if not members:
            continue
        bin_accuracy = sum(result.correct for result in members) / len(members)
        bin_confidence = sum(result.confidence for result in members) / len(members)
        error += len(members) / total * abs(bin_accuracy - bin_confidence)
    return error

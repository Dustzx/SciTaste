"""Deterministic proxies for evaluating evidence-grounded generated workspaces.

These measurements describe interface structure and local service latency.  They
do not simulate people and must not be reported as task success, comprehension,
preference, workload, or scientific-decision quality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter_ns
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.generative_ui.generation import (
    GeneratedWorkspaceDocument,
    WorkspaceGenerationRequest,
    WorkspaceGenerationService,
)
from scitaste.generative_ui.intent import IntentGoal, QuickIntentCatalog, QuickIntentRequest
from scitaste.generative_ui.registry import TrustedComponent
from scitaste.generative_ui.safety import ProjectIdentifier, SafeIdentifier, Sha256
from scitaste.generative_ui.workspace import (
    ProjectProgressQuery,
    WorkspaceSurfaceFactory,
    WorkspaceView,
)
from scitaste.project import ProjectRuntime

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
LatencyOperation = Literal[
    "project_progress",
    "quick_intent_catalog",
    "generated_workspace",
]


class TaskProxyMeasurement(BaseModel):
    """One quick intent measured without inferring a human outcome."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    quick_intent_id: SafeIdentifier
    goal: IntentGoal
    source_views: tuple[WorkspaceView, ...] = Field(min_length=1)
    fixed_view_count: int = Field(ge=1)
    generated_view_count: Literal[1] = 1
    fixed_views_avoided: int = Field(ge=0)
    fixed_view_reduction: float = Field(ge=0, le=1, allow_inf_nan=False)
    component_count: int = Field(ge=1)
    focused_component_rank: int = Field(ge=1)
    visible_evidence_ref_count: int = Field(ge=1)
    grounded_component_count: int = Field(ge=1)
    execution_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def counts_are_consistent(self) -> TaskProxyMeasurement:
        if self.fixed_view_count != len(self.source_views):
            raise ValueError("fixed view count must equal distinct source views")
        if self.fixed_views_avoided != self.fixed_view_count - 1:
            raise ValueError("fixed views avoided must use the one-workspace baseline")
        expected = self.fixed_views_avoided / self.fixed_view_count
        if not math.isclose(self.fixed_view_reduction, expected, abs_tol=1e-12):
            raise ValueError("fixed view reduction is inconsistent")
        if self.focused_component_rank > self.component_count:
            raise ValueError("focused component rank is outside the generated workspace")
        if self.grounded_component_count != self.component_count:
            raise ValueError("every measured component must remain evidence grounded")
        return self


class InterfaceProxyReport(BaseModel):
    """Aggregate navigation and information-load proxies for one exact snapshot."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    measurement_kind: Literal["automated-structural-proxy"] = "automated-structural-proxy"
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    planner_mode: Literal["deterministic"] = "deterministic"
    measurements: tuple[TaskProxyMeasurement, ...] = Field(min_length=1)
    task_count: int = Field(ge=1)
    mean_fixed_view_count: float = Field(ge=1, allow_inf_nan=False)
    mean_fixed_views_avoided: float = Field(ge=0, allow_inf_nan=False)
    mean_fixed_view_reduction: float = Field(ge=0, le=1, allow_inf_nan=False)
    mean_component_count: float = Field(ge=1, allow_inf_nan=False)
    focus_first_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    interpretation_boundary: Literal["not-human-usability-or-scientific-effectiveness"] = (
        "not-human-usability-or-scientific-effectiveness"
    )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def tasks_and_snapshot_are_coherent(self) -> InterfaceProxyReport:
        ids = [item.quick_intent_id for item in self.measurements]
        if len(ids) != len(set(ids)):
            raise ValueError("task proxy quick intent IDs must be unique")
        count = len(self.measurements)
        expected = {
            "task_count": count,
            "mean_fixed_view_count": sum(item.fixed_view_count for item in self.measurements)
            / count,
            "mean_fixed_views_avoided": sum(item.fixed_views_avoided for item in self.measurements)
            / count,
            "mean_fixed_view_reduction": sum(
                item.fixed_view_reduction for item in self.measurements
            )
            / count,
            "mean_component_count": sum(item.component_count for item in self.measurements) / count,
            "focus_first_rate": sum(item.focused_component_rank == 1 for item in self.measurements)
            / count,
        }
        for field, value in expected.items():
            observed = getattr(self, field)
            if isinstance(value, float):
                if not math.isclose(observed, value, abs_tol=1e-12):
                    raise ValueError(f"{field} is inconsistent with task measurements")
            elif observed != value:
                raise ValueError(f"{field} is inconsistent with task measurements")
        return self


class LatencyDistribution(BaseModel):
    """Wall-clock distribution for one local read-only application operation."""

    model_config = _MODEL_CONFIG

    operation: LatencyOperation
    sample_count: int = Field(ge=1)
    minimum_ms: float = Field(ge=0, allow_inf_nan=False)
    median_ms: float = Field(ge=0, allow_inf_nan=False)
    p95_ms: float = Field(ge=0, allow_inf_nan=False)
    maximum_ms: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def percentiles_are_ordered(self) -> LatencyDistribution:
        if not self.minimum_ms <= self.median_ms <= self.p95_ms <= self.maximum_ms:
            raise ValueError("latency percentiles must be ordered")
        return self


class LocalResponseReport(BaseModel):
    """Environment-bound latency sample; never a portable performance guarantee."""

    model_config = _MODEL_CONFIG

    schema_version: Literal["1.0"] = "1.0"
    measurement_kind: Literal["local-service-latency"] = "local-service-latency"
    project_id: ProjectIdentifier
    snapshot_revision: int = Field(ge=0)
    snapshot_sha256: Sha256
    benchmark_quick_intent_id: SafeIdentifier
    warmup_count: int = Field(ge=0)
    distributions: tuple[LatencyDistribution, ...] = Field(min_length=3, max_length=3)
    interpretation_boundary: Literal["environment-specific-not-user-task-time"] = (
        "environment-specific-not-user-task-time"
    )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def operations_are_complete(self) -> LocalResponseReport:
        operations = [item.operation for item in self.distributions]
        if operations != [
            "project_progress",
            "quick_intent_catalog",
            "generated_workspace",
        ]:
            raise ValueError("local response report operations are incomplete or unordered")
        return self


def evaluate_project_task_proxies(
    runtime: ProjectRuntime,
    project_id: str,
) -> InterfaceProxyReport:
    """Measure generated composition against its distinct fixed source views."""

    service = WorkspaceGenerationService(runtime)
    catalog = service.quick_catalog(project_id)
    measurements: list[TaskProxyMeasurement] = []
    for descriptor in catalog.intents:
        document = service.generate(_request(catalog, descriptor.quick_intent_id))
        measurements.append(_measure_document(document, descriptor.quick_intent_id))
    count = len(measurements)
    return InterfaceProxyReport(
        project_id=catalog.snapshot.project_id,
        snapshot_revision=catalog.snapshot.snapshot_revision,
        snapshot_sha256=catalog.snapshot.snapshot_sha256,
        measurements=tuple(measurements),
        task_count=count,
        mean_fixed_view_count=sum(item.fixed_view_count for item in measurements) / count,
        mean_fixed_views_avoided=sum(item.fixed_views_avoided for item in measurements) / count,
        mean_fixed_view_reduction=sum(item.fixed_view_reduction for item in measurements) / count,
        mean_component_count=sum(item.component_count for item in measurements) / count,
        focus_first_rate=sum(item.focused_component_rank == 1 for item in measurements) / count,
    )


def benchmark_local_responses(
    runtime: ProjectRuntime,
    project_id: str,
    *,
    sample_count: int = 20,
    warmup_count: int = 2,
) -> LocalResponseReport:
    """Benchmark local composition without HTTP, browser rendering, or provider calls."""

    if sample_count < 1:
        raise ValueError("sample_count must be positive")
    if warmup_count < 0:
        raise ValueError("warmup_count cannot be negative")
    service = WorkspaceGenerationService(runtime)
    workspace = WorkspaceSurfaceFactory(runtime)
    initial_catalog = service.quick_catalog(project_id)
    if not initial_catalog.intents:
        raise ValueError("latency benchmark requires at least one quick intent")
    quick_intent_id = initial_catalog.intents[0].quick_intent_id
    generation_request = _request(initial_catalog, quick_intent_id)

    def progress() -> object:
        return workspace.build_surface(ProjectProgressQuery(project_id=project_id))

    def catalog() -> object:
        return service.quick_catalog(project_id)

    def generated() -> object:
        return service.generate(generation_request)

    operations = (
        ("project_progress", progress),
        ("quick_intent_catalog", catalog),
        ("generated_workspace", generated),
    )
    distributions: list[LatencyDistribution] = []
    for operation, callback in operations:
        for _ in range(warmup_count):
            callback()
        samples = []
        for _ in range(sample_count):
            started = perf_counter_ns()
            callback()
            samples.append((perf_counter_ns() - started) / 1_000_000)
        distributions.append(_distribution(operation, samples))

    confirmed_catalog = service.quick_catalog(project_id)
    if confirmed_catalog.snapshot != initial_catalog.snapshot:
        raise ValueError("project changed during the local latency benchmark")
    return LocalResponseReport(
        project_id=initial_catalog.snapshot.project_id,
        snapshot_revision=initial_catalog.snapshot.snapshot_revision,
        snapshot_sha256=initial_catalog.snapshot.snapshot_sha256,
        benchmark_quick_intent_id=quick_intent_id,
        warmup_count=warmup_count,
        distributions=tuple(distributions),
    )


def _measure_document(
    document: GeneratedWorkspaceDocument,
    quick_intent_id: str,
) -> TaskProxyMeasurement:
    if (
        document.status != "generated"
        or document.intent is None
        or document.renderer is None
        or not document.placements
    ):
        raise ValueError("task proxy requires a successfully generated workspace")
    source_views = tuple(dict.fromkeys(item.source_view for item in document.placements))
    focus_components = _FOCUS_COMPONENTS[document.intent.goal]
    ranks = [
        index
        for index, component in enumerate(document.renderer.components, start=1)
        if component.renderer in focus_components
    ]
    if not ranks:
        raise ValueError("generated workspace omits its goal-focused component")
    known_evidence = {item.evidence_id for item in document.renderer.snapshot.evidence_refs}
    visible_evidence = {
        evidence_id
        for component in document.renderer.components
        for evidence_id in component.evidence_ref_ids
    }
    grounded = sum(
        set(component.evidence_ref_ids) <= known_evidence
        for component in document.renderer.components
    )
    fixed_view_count = len(source_views)
    avoided = fixed_view_count - 1
    return TaskProxyMeasurement(
        quick_intent_id=quick_intent_id,
        goal=document.intent.goal,
        source_views=source_views,
        fixed_view_count=fixed_view_count,
        fixed_views_avoided=avoided,
        fixed_view_reduction=avoided / fixed_view_count,
        component_count=len(document.renderer.components),
        focused_component_rank=min(ranks),
        visible_evidence_ref_count=len(visible_evidence),
        grounded_component_count=grounded,
        execution_authority=document.execution_authority,
    )


def _request(
    catalog: QuickIntentCatalog,
    quick_intent_id: str,
) -> WorkspaceGenerationRequest:
    return WorkspaceGenerationRequest(
        quick_catalog_fingerprint=catalog.fingerprint,
        intent_request=QuickIntentRequest(
            project_id=catalog.snapshot.project_id,
            snapshot_revision=catalog.snapshot.snapshot_revision,
            snapshot_sha256=catalog.snapshot.snapshot_sha256,
            quick_intent_id=quick_intent_id,
        ),
    )


def _distribution(
    operation: LatencyOperation,
    samples: list[float],
) -> LatencyDistribution:
    ordered = sorted(samples)
    return LatencyDistribution(
        operation=operation,
        sample_count=len(ordered),
        minimum_ms=round(ordered[0], 6),
        median_ms=round(_quantile(ordered, 0.5), 6),
        p95_ms=round(_quantile(ordered, 0.95), 6),
        maximum_ms=round(ordered[-1], 6),
    )


def _quantile(ordered: list[float], probability: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


_FOCUS_COMPONENTS = {
    IntentGoal.PROGRESS_REVIEW: frozenset({TrustedComponent.PROJECT_PROGRESS_BOARD}),
    IntentGoal.BLOCKER_DIAGNOSIS: frozenset(
        {TrustedComponent.RUN_BLOCKER_PANEL, TrustedComponent.BLOCKER_LIST}
    ),
    IntentGoal.RUN_COMPARISON: frozenset(
        {TrustedComponent.RUN_COMPARISON_PANEL, TrustedComponent.DECISION_COMPARISON}
    ),
    IntentGoal.PAPER_EVIDENCE_REVIEW: frozenset(
        {
            TrustedComponent.PAPER_PREVIEW,
            TrustedComponent.EVIDENCE_INVENTORY,
            TrustedComponent.CLAIM_MATRIX,
            TrustedComponent.REVIEWER_QUEUE,
        }
    ),
    IntentGoal.NEXT_STEP_REVIEW: frozenset({TrustedComponent.PROJECT_PROGRESS_BOARD}),
    IntentGoal.RESEARCH_LANDSCAPE_REVIEW: frozenset(
        {TrustedComponent.RESEARCH_LANDSCAPE_MAP}
    ),
}


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure non-human Generative UI structure and local latency."
    )
    parser.add_argument("--outputs-root", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--latency-samples", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    args = parser.parse_args()
    runtime = ProjectRuntime(args.outputs_root)
    latency = benchmark_local_responses(
        runtime,
        args.project_id,
        sample_count=args.latency_samples,
        warmup_count=args.warmups,
    )
    structural = evaluate_project_task_proxies(runtime, args.project_id)
    payload = {
        "latency": {
            **latency.model_dump(mode="json"),
            "fingerprint": latency.fingerprint,
        },
        "structural": {
            **structural.model_dump(mode="json"),
            "fingerprint": structural.fingerprint,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

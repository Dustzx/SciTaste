"""Execute content-bound local role-conformance requests with resident models."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from scitaste.backends.local_transformers import (
    LocalTransformersConfig,
    TransformersTextRuntime,
)
from scitaste.evaluation.model_role_conformance import ExecutionKind
from scitaste.evaluation.model_role_conformance_campaign import (
    CampaignReadiness,
    ConformanceDispatchRequest,
    _outputs_root_from_campaign,
    _verify_launch_binding,
    import_model_node_runtime_receipts,
    load_bytebound_campaign_plan,
)
from scitaste.model_nodes.facade import ModelNodeFacade, ModelNodeFacadeRequest
from scitaste.model_nodes.local_transformers import (
    StructuredLocalGenerationRuntime,
    StructuredLocalTransformersBackend,
)
from scitaste.model_nodes.profiles import load_model_node_profile_set
from scitaste.model_nodes.registry import first_party_node_types
from scitaste.model_nodes.runtime import ModelNodeRuntime, RuntimeOutcome
from scitaste.model_nodes.runtime_config import (
    LocalRuntimeBackend,
    ModelNodeRuntimeConfig,
    load_model_node_runtime_config,
)
from scitaste.project import ProjectRuntime

_CONFIG = ConfigDict(extra="forbid", frozen=True)


class LocalBatchExecutionItem(BaseModel):
    model_config = _CONFIG

    request_id: str
    candidate_id: str
    model_identity: str
    outcome: str
    task_succeeded: bool | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    imported: bool
    blockers: tuple[str, ...] = ()


class LocalBatchExecutionStatus(BaseModel):
    model_config = _CONFIG

    campaign_id: str
    selected_request_ids: tuple[str, ...]
    executed_request_ids: tuple[str, ...]
    runtime_group_count: int = Field(ge=0)
    resident_model_reuse_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    task_succeeded_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    items: tuple[LocalBatchExecutionItem, ...]
    failures_retained: bool = True


def execute_local_model_role_batch(
    plan_path: str | Path,
    *,
    request_ids: tuple[str, ...] = (),
    candidate_ids: tuple[str, ...] = (),
    max_requests: int | None = None,
    allow_local: bool = False,
    stop_on_failure: bool = False,
    runtime_factory: Callable[
        [LocalTransformersConfig], StructuredLocalGenerationRuntime
    ] = TransformersTextRuntime,
) -> LocalBatchExecutionStatus:
    """Run an explicit local subset while loading each exact checkpoint once.

    The durable model-node runtime remains authoritative for admission, ledgers,
    recordings, and budgets.  This layer only groups compatible requests so a
    checkpoint stays resident between otherwise independent invocations.
    """

    if not allow_local:
        raise ValueError("local batch execution requires explicit allow_local=True")
    if not request_ids and not candidate_ids:
        raise ValueError("local batch execution requires request_ids or candidate_ids")
    if max_requests is not None and max_requests < 1:
        raise ValueError("max_requests must be positive")

    source = Path(plan_path).resolve(strict=True)
    campaign_root = source.parent
    plan = load_bytebound_campaign_plan(source)
    request_by_id = {item.request_id: item for item in plan.requests}
    unknown_requests = set(request_ids) - set(request_by_id)
    if unknown_requests:
        raise ValueError(f"unknown campaign request IDs: {sorted(unknown_requests)!r}")
    known_candidates = {item.candidate.candidate.candidate_id for item in plan.requests}
    unknown_candidates = set(candidate_ids) - known_candidates
    if unknown_candidates:
        raise ValueError(f"unknown campaign candidate IDs: {sorted(unknown_candidates)!r}")

    selected = [
        item
        for item in plan.requests
        if (not request_ids or item.request_id in request_ids)
        and (not candidate_ids or item.candidate.candidate.candidate_id in candidate_ids)
    ]
    if max_requests is not None:
        selected = selected[:max_requests]
    if not selected:
        raise ValueError("local batch selection is empty")
    for request in selected:
        if request.resource.execution_kind is not ExecutionKind.LOCAL:
            raise ValueError(f"request {request.request_id} is not a local-model request")
        if request.readiness is not CampaignReadiness.LAUNCH_READY:
            raise ValueError(f"request {request.request_id} is not launch-ready")
        _verify_launch_binding(request, campaign_root=campaign_root)

    outputs_root = _outputs_root_from_campaign(campaign_root, plan)
    project_runtime = ProjectRuntime(outputs_root)
    snapshot = project_runtime.open(plan.project_id)
    facade = ModelNodeFacade(ModelNodeRuntime(project_runtime, node_types=first_party_node_types()))
    prepared = [_load_request(campaign_root, request) for request in selected]
    groups: dict[str, list[tuple[ConformanceDispatchRequest, ModelNodeRuntimeConfig, object]]] = {}
    for item in prepared:
        request, config, _ = item
        groups.setdefault(_runtime_compatibility_key(config), []).append(item)

    rows: list[LocalBatchExecutionItem] = []
    executed: list[str] = []
    stop = False
    for group in groups.values():
        shared_config = _shared_runtime_config([item[1] for item in group])
        shared_runtime = runtime_factory(shared_config)
        for request, config, profile in group:
            backend = StructuredLocalTransformersBackend(
                config.backend.config,
                runtime=shared_runtime,
            )
            facade_request = ModelNodeFacadeRequest(
                project_id=request.project_id,
                run_id=request.project_run_id,
                invocation_id=request.request_id,
                request_id=config.request_id,
                expected_project_revision=snapshot.revision,
                node_name=config.node_name,
                node_input=config.node_input,
                state_projection=config.state_projection,
                trigger=config.trigger,
                profile=profile,
                policy=config.policy,
                backend_mode=config.backend_mode,
                seed=config.seed,
            )
            planned = facade.plan(
                facade_request,
                backend=backend,
                allow_local=True,
            )
            if planned.receipt.blockers:
                rows.append(
                    _row(
                        request,
                        config,
                        outcome="not-executed",
                        blockers=planned.receipt.blockers,
                    )
                )
                stop = stop_on_failure
                if stop:
                    break
                continue
            result = facade.execute(
                facade_request,
                backend=backend,
                allow_local=True,
            )
            receipt = result.receipt
            executed.append(request.request_id)
            rows.append(
                _row(
                    request,
                    config,
                    outcome=receipt.outcome.value,
                    input_tokens=receipt.telemetry.input_tokens,
                    output_tokens=receipt.telemetry.output_tokens,
                    latency_ms=receipt.telemetry.latency_ms,
                    blockers=receipt.blockers,
                )
            )
            if receipt.outcome not in {RuntimeOutcome.ACCEPTED, RuntimeOutcome.REJECTED}:
                stop = stop_on_failure
                if stop:
                    break
        if stop:
            break

    importable = tuple(
        item.request_id
        for item in rows
        if item.outcome in {RuntimeOutcome.ACCEPTED.value, RuntimeOutcome.REJECTED.value}
    )
    if importable:
        import_model_node_runtime_receipts(source, request_ids=importable)
        imported_ids = set(importable)
        updated_rows = []
        for item in rows:
            if item.request_id not in imported_ids:
                updated_rows.append(item)
                continue
            result_path = campaign_root / "receipts" / item.request_id / "RUN_RESULT.json"
            payload = json.loads(result_path.read_bytes())
            updated_rows.append(
                item.model_copy(
                    update={
                        "imported": True,
                        "task_succeeded": payload["measurements"]["success"] == 1.0,
                    }
                )
            )
        rows = updated_rows

    outcomes = [item.outcome for item in rows]
    return LocalBatchExecutionStatus(
        campaign_id=plan.campaign_id,
        selected_request_ids=tuple(item.request_id for item in selected),
        executed_request_ids=tuple(executed),
        runtime_group_count=len(groups),
        resident_model_reuse_count=max(0, len(executed) - len(groups)),
        accepted_count=outcomes.count(RuntimeOutcome.ACCEPTED.value),
        rejected_count=outcomes.count(RuntimeOutcome.REJECTED.value),
        failed_count=sum(
            item not in {RuntimeOutcome.ACCEPTED.value, RuntimeOutcome.REJECTED.value}
            for item in outcomes
        ),
        task_succeeded_count=sum(item.task_succeeded is True for item in rows),
        input_tokens=sum(item.input_tokens for item in rows),
        output_tokens=sum(item.output_tokens for item in rows),
        items=tuple(rows),
    )


def _load_request(
    campaign_root: Path,
    request: ConformanceDispatchRequest,
) -> tuple[ConformanceDispatchRequest, ModelNodeRuntimeConfig, object]:
    binding = request.existing_runner_binding
    assert binding is not None
    assert binding.runtime_config_ref is not None
    assert binding.profile_set_ref is not None
    config = load_model_node_runtime_config(campaign_root / binding.runtime_config_ref).config
    if not isinstance(config.backend, LocalRuntimeBackend):
        raise ValueError("local campaign request does not bind a local runtime backend")
    profiles = load_model_node_profile_set(campaign_root / binding.profile_set_ref)
    profile = profiles.profiles[request.candidate.profile.profile_id]
    return request, config, profile


def _runtime_compatibility_key(config: ModelNodeRuntimeConfig) -> str:
    assert isinstance(config.backend, LocalRuntimeBackend)
    payload = config.backend.config.model_dump(
        mode="json",
        exclude={"max_new_tokens", "max_context_tokens", "max_retries"},
    )
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _shared_runtime_config(configs: list[ModelNodeRuntimeConfig]) -> LocalTransformersConfig:
    local = []
    for config in configs:
        if not isinstance(config.backend, LocalRuntimeBackend):
            raise ValueError("batch group contains a non-local backend")
        local.append(config.backend.config)
    return local[0].model_copy(
        update={
            "max_new_tokens": max(item.max_new_tokens for item in local),
            "max_context_tokens": max(item.max_context_tokens for item in local),
            "max_retries": max(item.max_retries for item in local),
        }
    )


def _row(
    request: ConformanceDispatchRequest,
    config: ModelNodeRuntimeConfig,
    *,
    outcome: str,
    task_succeeded: bool | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: float = 0.0,
    imported: bool = False,
    blockers: tuple[str, ...] = (),
) -> LocalBatchExecutionItem:
    assert isinstance(config.backend, LocalRuntimeBackend)
    return LocalBatchExecutionItem(
        request_id=request.request_id,
        candidate_id=request.candidate.candidate.candidate_id,
        model_identity=config.backend.config.model_identity,
        outcome=outcome,
        task_succeeded=task_succeeded,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        imported=imported,
        blockers=blockers,
    )


__all__ = [
    "LocalBatchExecutionItem",
    "LocalBatchExecutionStatus",
    "execute_local_model_role_batch",
]

"""Real prompt-only control for matched autonomous-research evaluation cells.

The control intentionally has no retrieval, Taste Library, tools, code execution,
memory, or repair loop. A successful adapter call produces a proposal manuscript
whose empirical claims remain unsupported; it never masquerades as a completed
idea-to-paper trajectory.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.evaluation.cell_plan import PlannedEvaluationCell
from scitaste.evaluation.prelaunch import ExecutionLaneKind, SystemRole
from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.models import (
    CumulativeProjectBudget,
    NodeAdmissionBudget,
    ProviderGenerationEnvelope,
    StructuredModelRequest,
)
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTRACT_BYTES = 4 * 1024 * 1024


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _pretty_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _invocation_payload(invocation: DirectAgentInvocation) -> dict[str, object]:
    return invocation.model_dump(
        mode="json",
        exclude={"fingerprint": True, "approval": {"approval_sha256": True}},
    )


def _task_payload(task: DirectAgentTaskPackage) -> dict[str, object]:
    return task.model_dump(mode="json", exclude={"fingerprint"})


class DirectAgentTaskPackage(BaseModel):
    """Exact task information visible to the prompt-only control."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    task_id: str = Field(min_length=1, max_length=200)
    benchmark_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1_000)
    objective: str = Field(min_length=1, max_length=20_000)
    starting_information: tuple[str, ...] = Field(default=(), max_length=50)
    constraints: tuple[str, ...] = Field(min_length=1, max_length=50)
    required_deliverables: tuple[str, ...] = Field(min_length=1, max_length=50)
    evaluation_summary: str = Field(min_length=1, max_length=10_000)
    hidden_evaluation_content_included: Literal[False] = False

    @field_validator("starting_information", "constraints", "required_deliverables")
    @classmethod
    def entries_are_nonempty_and_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("direct-agent task entries cannot be empty")
        if len(values) != len(set(values)):
            raise ValueError("direct-agent task entries must be unique")
        return values

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class DirectAgentBudget(BaseModel):
    model_config = _CONFIG

    max_provider_calls: Literal[1] = 1
    max_request_bytes: int = Field(gt=0, le=4 * 1024 * 1024)
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_total_tokens: int = Field(gt=0)
    max_cost_usd: float = Field(gt=0, allow_inf_nan=False)
    max_latency_ms: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def total_fits_token_parts(self) -> DirectAgentBudget:
        if self.max_total_tokens > self.max_input_tokens + self.max_output_tokens:
            raise ValueError("direct-agent total token ceiling exceeds its input/output parts")
        return self


class DirectAgentCellApproval(BaseModel):
    """Exact human approval binding; the matched runner remains the authority source."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    approved: Literal[True] = True
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: datetime
    proposal_sha256: str = Field(pattern=_SHA256)
    plan_sha256: str = Field(pattern=_SHA256)
    cell_id: str = Field(pattern=r"^cell-[0-9a-f]{24}$")
    scope: Literal["one-cell"] = "one-cell"

    @field_validator("approved_at")
    @classmethod
    def approval_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("direct-agent approval timestamp must be timezone-aware")
        return value

    @computed_field
    @property
    def approval_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))


class DirectAgentInvocation(BaseModel):
    """One content-bound prompt-only cell invocation."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    plan_sha256: str = Field(pattern=_SHA256)
    cell: PlannedEvaluationCell
    task_package_ref: str = Field(min_length=1, max_length=1_000)
    task_package_sha256: str = Field(pattern=_SHA256)
    backend_config_sha256: str = Field(pattern=_SHA256)
    budget: DirectAgentBudget
    approval: DirectAgentCellApproval
    prompt_version: Literal["prompt-only-research-control-v1"] = "prompt-only-research-control-v1"

    @model_validator(mode="after")
    def invocation_is_one_approved_control_cell(self) -> DirectAgentInvocation:
        if not self.cell.ready_for_launch_preparation:
            raise ValueError("direct-agent invocation requires a preparation-ready cell")
        if self.cell.system_id != "direct-agent" or self.cell.system_role is not SystemRole.CONTROL:
            raise ValueError("direct-agent invocation must bind the registered direct control")
        if self.cell.lane_kind is not ExecutionLaneKind.API_ONLY:
            raise ValueError("prompt-only direct-agent control requires an API lane")
        if self.approval.proposal_sha256 != self.cell.proposal_sha256:
            raise ValueError("direct-agent approval proposal differs from its cell")
        if self.approval.plan_sha256 != self.plan_sha256:
            raise ValueError("direct-agent approval plan differs from its invocation")
        if self.approval.cell_id != self.cell.cell_id:
            raise ValueError("direct-agent approval names another cell")
        resource = self.cell.resource
        if (
            self.budget.max_input_tokens > int(resource.max_input_tokens_per_call or 0)
            or self.budget.max_output_tokens > int(resource.max_output_tokens_per_call or 0)
            or self.budget.max_total_tokens > int(resource.max_total_tokens or 0)
            or self.budget.max_cost_usd > float(resource.max_cost or 0)
        ):
            raise ValueError("direct-agent budget exceeds the proposal lane ceilings")
        return self

    @computed_field
    @property
    def fingerprint(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"fingerprint"}))


class DirectAgentIdea(BaseModel):
    model_config = _CONFIG

    title: str = Field(min_length=1, max_length=1_000)
    problem: str = Field(min_length=1, max_length=10_000)
    proposed_contribution: str = Field(min_length=1, max_length=10_000)


class DirectAgentHypothesis(BaseModel):
    model_config = _CONFIG

    statement: str = Field(min_length=1, max_length=10_000)
    falsification_condition: str = Field(min_length=1, max_length=10_000)


class DirectAgentExperimentPlan(BaseModel):
    model_config = _CONFIG

    design: str = Field(min_length=1, max_length=20_000)
    primary_metric: str = Field(min_length=1, max_length=1_000)
    baselines: tuple[str, ...] = Field(min_length=1, max_length=20)
    validity_risks: tuple[str, ...] = Field(min_length=1, max_length=20)


class DirectAgentClaim(BaseModel):
    model_config = _CONFIG

    statement: str = Field(min_length=1, max_length=5_000)
    support_status: Literal["unsupported-until-executed"]


class DirectAgentPaperSection(BaseModel):
    model_config = _CONFIG

    heading: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=30_000)


class PromptOnlyResearchPackage(BaseModel):
    """Model output that cannot represent completed experimental evidence."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    idea: DirectAgentIdea
    hypothesis: DirectAgentHypothesis
    experiment_plan: DirectAgentExperimentPlan
    claims: tuple[DirectAgentClaim, ...] = Field(min_length=1, max_length=30)
    paper_title: str = Field(min_length=1, max_length=1_000)
    paper_abstract: str = Field(min_length=1, max_length=10_000)
    paper_sections: tuple[DirectAgentPaperSection, ...] = Field(min_length=3, max_length=20)
    self_review_limitations: tuple[str, ...] = Field(min_length=1, max_length=30)
    execution_status: Literal["not-executed"]
    reported_empirical_results: Literal[False]
    independent_review_performed: Literal[False]


class DirectAgentRunReceipt(BaseModel):
    """Hash-bound adapter success; scientific completion deliberately remains false."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    invocation_id: str
    invocation_fingerprint: str = Field(pattern=_SHA256)
    approval_sha256: str = Field(pattern=_SHA256)
    task_package_sha256: str = Field(pattern=_SHA256)
    backend_config_sha256: str = Field(pattern=_SHA256)
    request_fingerprint: str = Field(pattern=_SHA256)
    raw_response_sha256: str = Field(pattern=_SHA256)
    provider: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    artifact_sha256: dict[str, str]
    adapter_completed: Literal[True] = True
    provider_calls: Literal[1] = 1
    prompt_only_control: Literal[True] = True
    tool_calls_performed: Literal[False] = False
    retrieval_performed: Literal[False] = False
    experiment_executed: Literal[False] = False
    empirical_evidence_produced: Literal[False] = False
    independent_review_performed: Literal[False] = False
    eligible_as_complete_idea_to_paper_evidence: Literal[False] = False

    @model_validator(mode="after")
    def artifacts_are_closed(self) -> DirectAgentRunReceipt:
        required = {
            "invocation.json",
            "model_request.json",
            "paper_proposal.md",
            "provider_response.json",
            "research_package.json",
            "self_review.md",
            "task_package.json",
        }
        if set(self.artifact_sha256) != required:
            raise ValueError("direct-agent receipt requires its complete reproducibility bundle")
        return self


class DirectAgentLoadedInvocation(BaseModel):
    model_config = _CONFIG

    invocation: DirectAgentInvocation
    source_sha256: str = Field(pattern=_SHA256)


class DirectAgentLoadedTask(BaseModel):
    model_config = _CONFIG

    task: DirectAgentTaskPackage
    source_sha256: str = Field(pattern=_SHA256)


def load_direct_agent_invocation(path: str | Path) -> DirectAgentLoadedInvocation:
    raw = _read_bounded_regular(path, label="direct-agent invocation")
    return DirectAgentLoadedInvocation(
        invocation=DirectAgentInvocation.model_validate_json(raw),
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )


def load_direct_agent_task(
    invocation: DirectAgentInvocation,
    *,
    task_root: str | Path,
) -> DirectAgentLoadedTask:
    path = _resolve_bounded(task_root, invocation.task_package_ref)
    raw = _read_bounded_regular(path, label="direct-agent task package")
    observed = hashlib.sha256(raw).hexdigest()
    if observed != invocation.task_package_sha256:
        raise ValueError("direct-agent task package hash mismatch")
    task = DirectAgentTaskPackage.model_validate_json(raw)
    if task.task_id != invocation.cell.task_id:
        raise ValueError("direct-agent task package belongs to another cell task")
    return DirectAgentLoadedTask(task=task, source_sha256=observed)


def run_live_direct_agent(
    *,
    invocation_path: str | Path,
    task_root: str | Path,
    backend_config_path: str | Path,
    output_dir: str | Path,
    allow_live: bool = False,
) -> DirectAgentRunReceipt:
    """Run exactly one approved provider call; no tool or experiment path exists."""

    if not allow_live:
        raise ValueError("direct-agent live execution requires allow_live=true")
    loaded = load_direct_agent_invocation(invocation_path)
    invocation = loaded.invocation
    task = load_direct_agent_task(invocation, task_root=task_root).task
    raw_config = _read_bounded_regular(backend_config_path, label="direct-agent backend config")
    if hashlib.sha256(raw_config).hexdigest() != invocation.backend_config_sha256:
        raise ValueError("direct-agent backend configuration hash mismatch")
    config = load_structured_openai_compatible_config(backend_config_path)
    resource = invocation.cell.resource
    if (config.provider, config.model, config.api_key_env) != (
        resource.provider_id,
        resource.model_id,
        resource.api_key_env,
    ):
        raise ValueError("direct-agent backend identity differs from the planned cell resource")
    if not config.live_enabled:
        raise ValueError("direct-agent backend configuration is not live-enabled")
    if config.max_retries != 0:
        raise ValueError("one-call direct-agent cells prohibit provider retries")
    if config.timeout_seconds * 1000 > invocation.budget.max_latency_ms:
        raise ValueError("direct-agent backend timeout exceeds the approved cell budget")
    if config.max_output_tokens < invocation.budget.max_output_tokens:
        raise ValueError("direct-agent backend output ceiling is below the approved cell budget")
    return execute_direct_agent(
        invocation,
        task,
        StructuredOpenAICompatibleBackend(config),
        output_dir=output_dir,
    )


def execute_direct_agent(
    invocation: DirectAgentInvocation,
    task: DirectAgentTaskPackage,
    backend: StructuredModelBackend,
    *,
    output_dir: str | Path,
) -> DirectAgentRunReceipt:
    """Provider-neutral core used by the live wrapper and isolated contract tests."""

    invocation = DirectAgentInvocation.model_validate(_invocation_payload(invocation))
    task = DirectAgentTaskPackage.model_validate(_task_payload(task))
    if task.task_id != invocation.cell.task_id:
        raise ValueError("direct-agent task identity differs from the invocation cell")
    resource = invocation.cell.resource
    if (backend.name, backend.model) != (resource.provider_id, resource.model_id):
        raise ValueError("direct-agent backend differs from the invocation resource")
    request = _model_request(invocation, task)
    request_bytes = len(request.model_dump_json().encode())
    if request_bytes > invocation.budget.max_request_bytes:
        raise ValueError("direct-agent request exceeds its byte ceiling")
    response = backend.complete(request)
    if response.request_fingerprint != request.fingerprint:
        raise ValueError("direct-agent response belongs to another request")
    if response.backend != resource.provider_id or response.model not in {
        resource.model_id,
        resource.model_revision,
    }:
        raise ValueError("direct-agent provider response identity differs from the cell")
    if response.tool_calls:
        raise ValueError("prompt-only direct-agent control rejects provider tool calls")
    if response.raw_response is None:
        raise ValueError("direct-agent control requires retained raw provider response bytes")
    if response.usage.cost_usd is None:
        raise ValueError("direct-agent control requires provider cost telemetry")
    total_tokens = response.usage.input_tokens + response.usage.output_tokens
    budget = invocation.budget
    if (
        response.usage.input_tokens > budget.max_input_tokens
        or response.usage.output_tokens > budget.max_output_tokens
        or total_tokens > budget.max_total_tokens
        or response.usage.cost_usd > budget.max_cost_usd
        or response.latency_ms > budget.max_latency_ms
    ):
        raise ValueError("direct-agent provider telemetry exceeds the approved budget")
    package = PromptOnlyResearchPackage.model_validate(response.output_payload)
    root = Path(output_dir)
    artifacts = {
        "invocation.json": _pretty_json(_invocation_payload(invocation)),
        "model_request.json": request.model_dump_json(indent=2) + "\n",
        "research_package.json": package.model_dump_json(indent=2) + "\n",
        "paper_proposal.md": _paper_markdown(package),
        "provider_response.json": response.raw_response,
        "self_review.md": _self_review_markdown(package),
        "task_package.json": _pretty_json(_task_payload(task)),
    }
    artifact_sha256 = {
        name: hashlib.sha256(content.encode()).hexdigest() for name, content in artifacts.items()
    }
    receipt = DirectAgentRunReceipt(
        invocation_id=invocation.invocation_id,
        invocation_fingerprint=invocation.fingerprint,
        approval_sha256=invocation.approval.approval_sha256,
        task_package_sha256=invocation.task_package_sha256,
        backend_config_sha256=invocation.backend_config_sha256,
        request_fingerprint=request.fingerprint,
        raw_response_sha256=response.raw_response_sha256,
        provider=response.backend,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        total_tokens=total_tokens,
        cost_usd=response.usage.cost_usd,
        latency_ms=response.latency_ms,
        artifact_sha256=artifact_sha256,
    )
    _prepare_empty_output(root)
    for name, content in artifacts.items():
        _atomic_write(root / name, content)
    _atomic_write(root / "RUN_RECEIPT.json", receipt.model_dump_json(indent=2) + "\n")
    return receipt


def _model_request(
    invocation: DirectAgentInvocation,
    task: DirectAgentTaskPackage,
) -> StructuredModelRequest:
    budget = invocation.budget
    resource = invocation.cell.resource
    return StructuredModelRequest(
        request_id=invocation.invocation_id,
        node_name="prompt-only-direct-agent",
        stage="idea-to-paper-control",
        state_snapshot_id=invocation.cell.cell_id,
        expected_backend=str(resource.provider_id),
        expected_model=str(resource.model_id),
        policy_id=invocation.prompt_version,
        policy_fingerprint=invocation.fingerprint,
        system_instruction=(
            "Act as one prompt-only research model. You have no retrieval, memory, tools, code "
            "execution, experiment results, Scientific Taste controller, repair loop, or "
            "independent reviewer. Develop the visible task into an honest research proposal. "
            "Never claim that an experiment ran and never invent empirical results. Return only "
            "one JSON object satisfying output_schema. Every claim must remain "
            "unsupported-until-executed, execution_status must be not-executed, and both "
            "reported_empirical_results and independent_review_performed must be false."
        ),
        input_payload={
            "task": task.model_dump(mode="json", exclude={"fingerprint"}),
            "control_condition": {
                "retrieval": False,
                "taste": False,
                "tools": False,
                "code_execution": False,
                "memory": False,
                "repair_loop": False,
            },
        },
        output_schema=PromptOnlyResearchPackage.model_json_schema(mode="serialization"),
        seed=invocation.cell.seed,
        prompt_version=invocation.prompt_version,
        profile_id="prompt-only-direct-agent-v1",
        profile_fingerprint=invocation.fingerprint,
        generation_envelope=ProviderGenerationEnvelope(
            max_request_bytes=budget.max_request_bytes,
            max_output_tokens=budget.max_output_tokens,
            context_window_tokens=budget.max_input_tokens + budget.max_output_tokens,
            deterministic_seed_supported=False,
        ),
        admission_budget=NodeAdmissionBudget(
            max_request_bytes=budget.max_request_bytes,
            max_input_tokens=budget.max_input_tokens,
            max_output_tokens=budget.max_output_tokens,
            max_total_tokens=budget.max_total_tokens,
            max_latency_ms=budget.max_latency_ms,
            max_response_cost_usd=budget.max_cost_usd,
        ),
        cumulative_project_budget=CumulativeProjectBudget(
            max_invocations=1,
            max_total_tokens=budget.max_total_tokens,
            max_api_cost_usd=budget.max_cost_usd,
        ),
    )


def _paper_markdown(package: PromptOnlyResearchPackage) -> str:
    sections = "\n\n".join(
        f"## {section.heading}\n\n{section.content}" for section in package.paper_sections
    )
    return (
        f"# {package.paper_title}\n\n## Abstract\n\n{package.paper_abstract}\n\n{sections}\n\n"
        "## Evidence status\n\nNo experiment was executed in this prompt-only control; all "
        "empirical claims remain unsupported until execution.\n"
    )


def _self_review_markdown(package: PromptOnlyResearchPackage) -> str:
    limitations = "\n".join(f"- {item}" for item in package.self_review_limitations)
    return (
        "# Self-review (not independent)\n\n"
        f"{limitations}\n\n"
        "This model-authored self-review is not an independent or venue review.\n"
    )


def _read_bounded_regular(path: str | Path, *, label: str) -> bytes:
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError(f"{label} cannot be a symlink")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_CONTRACT_BYTES:
        raise ValueError(f"{label} must be a bounded regular file")
    return resolved.read_bytes()


def _resolve_bounded(root: str | Path, locator: str) -> Path:
    base = Path(root).resolve(strict=True)
    pure = PurePosixPath(locator)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("direct-agent task locator is not repository-relative")
    current = base
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("direct-agent task locator crosses a symlink")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(base):
        raise ValueError("direct-agent task locator escapes its task root")
    return resolved


def _prepare_empty_output(root: Path) -> None:
    if root.is_symlink():
        raise ValueError("direct-agent output cannot be a symlink")
    if root.exists():
        if not root.is_dir() or any(root.iterdir()):
            raise FileExistsError("direct-agent output directory must be absent or empty")
    else:
        root.mkdir(parents=True)


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "DirectAgentBudget",
    "DirectAgentCellApproval",
    "DirectAgentClaim",
    "DirectAgentExperimentPlan",
    "DirectAgentHypothesis",
    "DirectAgentIdea",
    "DirectAgentInvocation",
    "DirectAgentLoadedInvocation",
    "DirectAgentLoadedTask",
    "DirectAgentPaperSection",
    "DirectAgentRunReceipt",
    "DirectAgentTaskPackage",
    "PromptOnlyResearchPackage",
    "execute_direct_agent",
    "load_direct_agent_invocation",
    "load_direct_agent_task",
    "run_live_direct_agent",
]

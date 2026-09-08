"""Auditable research intake for project-owned full-workflow launches."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.discovery.loop import load_discovery_scenario
from scitaste.evidence.workflow import load_evidence_scenario
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.state.research_state import ResourceBudget
from scitaste.visual.workflow import load_figure_scenario
from scitaste.writing.workflow import load_communication_scenario

IntakeRole = Literal[
    "research-brief",
    "discovery-scenario",
    "evidence-scenario",
    "communication-scenario",
    "figure-scenario",
]
StageName = Literal["discovery", "evidence", "communication", "figure"]

_STAGE_ROLES: dict[StageName, IntakeRole] = {
    "discovery": "discovery-scenario",
    "evidence": "evidence-scenario",
    "communication": "communication-scenario",
    "figure": "figure-scenario",
}
_OWNED_LOCATORS: dict[IntakeRole, str] = {
    "research-brief": "intake/BRIEF.yaml",
    "discovery-scenario": "intake/scenarios/discovery.yaml",
    "evidence-scenario": "intake/scenarios/evidence.yaml",
    "communication-scenario": "intake/scenarios/communication.yaml",
    "figure-scenario": "intake/scenarios/figure.yaml",
}


class ResearchBrief(BaseModel):
    """User-owned question, constraints, and evidence expectations."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    brief_id: str
    project_id: str
    question: str = Field(min_length=10, max_length=2_000)
    objective: str = Field(min_length=10, max_length=2_000)
    research_direction: str = Field(min_length=1, max_length=500)
    target_domain: str = Field(min_length=1, max_length=200)
    target_venue: str | None = Field(default=None, max_length=200)
    resource_budget: ResourceBudget
    required_evidence_types: tuple[str, ...] = Field(min_length=1, max_length=32)
    success_criteria: tuple[str, ...] = Field(min_length=1, max_length=32)
    constraints: tuple[str, ...] = Field(default=(), max_length=32)
    prohibited_claims: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("brief_id")
    @classmethod
    def brief_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="brief_id")

    @field_validator("project_id")
    @classmethod
    def project_id_is_canonical(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator(
        "required_evidence_types",
        "success_criteria",
        "constraints",
        "prohibited_claims",
    )
    @classmethod
    def list_values_are_bounded_and_unique(
        cls, values: tuple[str, ...], info: object
    ) -> tuple[str, ...]:
        field_name = getattr(info, "field_name", "values")
        if any(not item or len(item) > 500 for item in values):
            raise ValueError(f"{field_name} entries must contain 1 to 500 characters")
        if len(values) != len(set(values)):
            raise ValueError(f"{field_name} entries must be unique")
        return values


class WorkflowIntakeBinding(BaseModel):
    """Hash binding from one registered source to its run-owned copy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: IntakeRole
    source_name: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    owned_locator: str = Field(min_length=1)


class WorkflowLaunchPlan(BaseModel):
    """Self-hashed, deterministic admission result for one workflow launch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    brief_id: str
    research_question: str
    objective: str
    workflow_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    planning_mode: Literal["deterministic-registered-inputs-v1"]
    readiness: Literal["ready"]
    stage_sequence: tuple[StageName, ...]
    resource_budget: ResourceBudget
    required_evidence_types: tuple[str, ...]
    configured_evidence_types: tuple[str, ...]
    success_criteria: tuple[str, ...]
    constraints: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    input_bindings: tuple[WorkflowIntakeBinding, ...]
    model_authority: Literal["proposal-only"]
    execution_authority: Literal["deterministic-admission-required"]
    limitations: tuple[str, ...]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("project_id")
    @classmethod
    def project_id_is_canonical(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id", "brief_id")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=getattr(info, "field_name", "identifier"))

    @model_validator(mode="after")
    def plan_is_closed_and_self_hashed(self) -> WorkflowLaunchPlan:
        expected_roles = tuple(_OWNED_LOCATORS)
        observed_roles = tuple(item.role for item in self.input_bindings)
        if observed_roles != expected_roles:
            raise ValueError("launch plan input bindings are incomplete or out of order")
        if self.stage_sequence != tuple(_STAGE_ROLES):
            raise ValueError("launch plan stage sequence is not canonical")
        expected_hash = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected_hash:
            raise ValueError("launch plan hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> WorkflowLaunchPlan:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


@dataclass(frozen=True)
class WorkflowIntakeInspection:
    """Validated sources and the launch plan that binds them."""

    brief: ResearchBrief
    plan: WorkflowLaunchPlan
    source_paths: Mapping[IntakeRole, Path]


@dataclass(frozen=True)
class PreparedWorkflowIntake:
    """Run-owned intake paths safe for stage execution."""

    brief: ResearchBrief
    plan: WorkflowLaunchPlan
    scenario_paths: Mapping[StageName, Path]

    def summary(self) -> dict[str, object]:
        return {
            "brief_id": self.brief.brief_id,
            "question": self.brief.question,
            "planning_mode": self.plan.planning_mode,
            "readiness": self.plan.readiness,
            "plan": "intake/PLAN.json",
            "plan_sha256": self.plan.record_sha256,
            "model_authority": self.plan.model_authority,
            "execution_authority": self.plan.execution_authority,
        }


def load_research_brief(path: str | Path) -> ResearchBrief:
    """Load a strict YAML or JSON research brief."""

    brief_path = Path(path).resolve()
    payload = yaml.safe_load(brief_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("research brief must be a mapping")
    return ResearchBrief.model_validate(payload)


def inspect_workflow_intake(
    brief_path: str | Path,
    *,
    project_id: str,
    run_id: str,
    research_direction: str,
    target_domain: str,
    target_venue: str | None,
    workflow_config_sha256: str,
    scenario_paths: Mapping[StageName, Path],
) -> WorkflowIntakeInspection:
    """Validate the brief and registered scenarios without mutating outputs."""

    validate_entry_id(run_id, field_name="run_id")
    resolved_brief_path = Path(brief_path).resolve()
    brief = load_research_brief(resolved_brief_path)
    observed_identity = (
        brief.project_id,
        brief.research_direction,
        brief.target_domain,
        brief.target_venue,
    )
    expected_identity = (project_id, research_direction, target_domain, target_venue)
    if observed_identity != expected_identity:
        raise ValueError("research brief identity does not match full-workflow config")

    missing = [stage for stage in _STAGE_ROLES if stage not in scenario_paths]
    if missing:
        raise ValueError(f"workflow intake is missing scenarios: {', '.join(missing)}")
    resolved_scenarios = {stage: Path(scenario_paths[stage]).resolve() for stage in _STAGE_ROLES}
    discovery = load_discovery_scenario(resolved_scenarios["discovery"])
    evidence = load_evidence_scenario(resolved_scenarios["evidence"])
    communication = load_communication_scenario(resolved_scenarios["communication"])
    load_figure_scenario(resolved_scenarios["figure"])

    if discovery.resource_budget != brief.resource_budget:
        raise ValueError("research brief budget must match the executable discovery budget")

    configured_evidence = set(evidence.claim.required_evidence_types)
    configured_evidence.add(evidence.interpretation.evidence_type)
    for claim in communication.claims:
        configured_evidence.update(claim.required_evidence_types)
    for concern in communication.review_feedback:
        configured_evidence.update(concern.required_evidence_types)
    uncovered = configured_evidence.difference(brief.required_evidence_types)
    if uncovered:
        raise ValueError(
            "research brief does not authorize configured evidence types: "
            + ", ".join(sorted(uncovered))
        )

    sources: dict[IntakeRole, Path] = {"research-brief": resolved_brief_path}
    sources.update({_STAGE_ROLES[stage]: path for stage, path in resolved_scenarios.items()})
    bindings = tuple(
        WorkflowIntakeBinding(
            role=role,
            source_name=sources[role].name,
            source_sha256=_file_sha256(sources[role]),
            owned_locator=_OWNED_LOCATORS[role],
        )
        for role in _OWNED_LOCATORS
    )
    plan = WorkflowLaunchPlan.create(
        project_id=project_id,
        run_id=run_id,
        brief_id=brief.brief_id,
        research_question=brief.question,
        objective=brief.objective,
        workflow_config_sha256=workflow_config_sha256,
        planning_mode="deterministic-registered-inputs-v1",
        readiness="ready",
        stage_sequence=tuple(_STAGE_ROLES),
        resource_budget=brief.resource_budget,
        required_evidence_types=brief.required_evidence_types,
        configured_evidence_types=tuple(sorted(configured_evidence)),
        success_criteria=brief.success_criteria,
        constraints=brief.constraints,
        prohibited_claims=brief.prohibited_claims,
        input_bindings=bindings,
        model_authority="proposal-only",
        execution_authority="deterministic-admission-required",
        limitations=(
            "Question-to-scenario semantic alignment is declared by the brief owner, "
            "not model-verified.",
            "This plan admits registered scenario inputs; it does not autonomously "
            "synthesize them.",
            "A ready plan is an execution admission record, not an effectiveness claim.",
        ),
    )
    return WorkflowIntakeInspection(brief=brief, plan=plan, source_paths=sources)


def materialize_workflow_intake(
    inspection: WorkflowIntakeInspection,
    *,
    run_root: str | Path,
) -> PreparedWorkflowIntake:
    """Copy registered inputs into the run and publish or verify its plan."""

    root = Path(run_root)
    _require_safe_intake_root(root)
    for binding in inspection.plan.input_bindings:
        source = inspection.source_paths[binding.role]
        if _file_sha256(source) != binding.source_sha256:
            raise ValueError(f"workflow intake source changed after inspection: {binding.role}")
        _copy_or_verify(source, root / binding.owned_locator, binding.source_sha256)
    plan_path = root / "intake" / "PLAN.json"
    if plan_path.is_symlink():
        raise ValueError("workflow launch plan must be a physical file")
    if plan_path.exists():
        observed = WorkflowLaunchPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        if observed != inspection.plan:
            raise ValueError("existing workflow launch plan does not match requested intake")
    else:
        _atomic_bytes(
            plan_path,
            (inspection.plan.model_dump_json(indent=2) + "\n").encode("utf-8"),
        )
    return _prepared_intake(inspection.plan, inspection.brief, root)


def verify_workflow_intake(
    inspection: WorkflowIntakeInspection,
    *,
    run_root: str | Path,
) -> PreparedWorkflowIntake:
    """Verify an already materialized intake without repairing it."""

    root = Path(run_root)
    _require_safe_intake_root(root)
    plan_path = root / "intake" / "PLAN.json"
    if plan_path.is_symlink():
        raise ValueError("workflow launch plan must be a physical file")
    observed = WorkflowLaunchPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    if observed != inspection.plan:
        raise ValueError("materialized workflow launch plan does not match requested intake")
    for binding in inspection.plan.input_bindings:
        if _file_sha256(root / binding.owned_locator) != binding.source_sha256:
            raise ValueError(f"materialized workflow intake is invalid: {binding.role}")
    return _prepared_intake(inspection.plan, inspection.brief, root)


def _prepared_intake(
    plan: WorkflowLaunchPlan,
    brief: ResearchBrief,
    run_root: Path,
) -> PreparedWorkflowIntake:
    role_bindings = {binding.role: binding for binding in plan.input_bindings}
    return PreparedWorkflowIntake(
        brief=brief,
        plan=plan,
        scenario_paths={
            stage: run_root / role_bindings[role].owned_locator
            for stage, role in _STAGE_ROLES.items()
        },
    )


def _copy_or_verify(source: Path, destination: Path, expected_sha256: str) -> None:
    if destination.is_symlink():
        raise ValueError(f"workflow intake copy must be a physical file: {destination}")
    if destination.exists():
        if not destination.is_file() or _file_sha256(destination) != expected_sha256:
            raise ValueError(f"existing workflow intake copy is invalid: {destination}")
        return
    _atomic_bytes(destination, source.read_bytes())
    if _file_sha256(destination) != expected_sha256:
        raise ValueError(f"workflow intake copy failed verification: {destination}")


def _require_safe_intake_root(run_root: Path) -> None:
    if run_root.is_symlink():
        raise ValueError("workflow run root must be a physical directory")
    for directory in (run_root / "intake", run_root / "intake" / "scenarios"):
        if directory.is_symlink():
            raise ValueError("workflow intake directories must not be symlinks")


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

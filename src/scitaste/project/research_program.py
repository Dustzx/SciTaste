"""Project-owned orchestration for one complete autonomous-research program.

The controller deliberately does not launch providers, GPUs, scorers, or external
systems.  It advances only by content-binding artifacts that already exist inside
the owning project.  This keeps orchestration separate from execution authority.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.project.models import (
    ProjectRun,
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.project.runtime import ProjectRuntime

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"

ResearchProgramPhaseId = Literal[
    "task-acquisition-proposed",
    "acquired-quarantined",
    "task-admitted-and-split-frozen",
    "models-and-systems-frozen",
    "idea-candidates-generated",
    "idea-decision-locked",
    "experiment-plan-frozen",
    "development-execution",
    "candidate-frozen",
    "hidden-scoring",
    "evidence-admission",
    "paper-assembly",
    "dual-ai-review",
    "ai-adjudication",
    "review-driven-revision",
    "final-ai-review-and-package-freeze",
    "complete",
]

_PHASE_IDS: tuple[ResearchProgramPhaseId, ...] = (
    "task-acquisition-proposed",
    "acquired-quarantined",
    "task-admitted-and-split-frozen",
    "models-and-systems-frozen",
    "idea-candidates-generated",
    "idea-decision-locked",
    "experiment-plan-frozen",
    "development-execution",
    "candidate-frozen",
    "hidden-scoring",
    "evidence-admission",
    "paper-assembly",
    "dual-ai-review",
    "ai-adjudication",
    "review-driven-revision",
    "final-ai-review-and-package-freeze",
    "complete",
)

ReviewOutcome = Literal["agreement", "disagreement", "accepted", "revision_required"]
RevisionTarget = Literal[
    "experiment-plan-frozen",
    "development-execution",
    "evidence-admission",
    "paper-assembly",
    "review-driven-revision",
]
ScientificResultAuthority = Literal[
    "none",
    "benchmark-hidden-scorer",
    "admitted-evidence-only",
]
LaunchAuthorityFlag = Literal[
    "--allow-download",
    "--allow-api",
    "--allow-gpu",
    "--allow-external-system",
]


class ResearchProgramRunStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETE = "complete"


class ResearchProgramTransitionDisposition(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    RESUMED = "resumed"


class PhaseExecutionAuthority(StrEnum):
    PROJECT_ARTIFACT = "project-artifact-attestation"
    TASK_EXCLUDED_SELECTION = "task-excluded-selection-attestation"
    EXTERNAL_EXECUTOR = "external-executor-attestation"
    SCORER_ONLY = "scorer-only-attestation"
    INDEPENDENT_AI = "independent-ai-attestation"
    INDEPENDENT_AI_ADJUDICATOR = "independent-ai-adjudicator-attestation"


class ResearchProgramPhaseContract(BaseModel):
    """One immutable phase interface derived from the v3 lifecycle."""

    model_config = _CONFIG

    phase_id: ResearchProgramPhaseId
    required_artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    default_next_phase_id: ResearchProgramPhaseId | None
    conditional_next: dict[str, ResearchProgramPhaseId] = Field(default_factory=dict)
    scitaste_interfaces: tuple[str, ...] = Field(min_length=1, max_length=12)
    resource_roles: tuple[str, ...] = Field(min_length=1, max_length=12)
    execution_authority: PhaseExecutionAuthority
    accepted_semantic_validator_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    controller_may_launch_external_work: Literal[False] = False
    scientific_result_authority: ScientificResultAuthority

    @model_validator(mode="after")
    def phase_is_closed(self) -> ResearchProgramPhaseContract:
        for value in self.required_artifact_ids:
            validate_entry_id(value, field_name="required artifact ID")
        if len(self.required_artifact_ids) != len(set(self.required_artifact_ids)):
            raise ValueError("required artifact IDs must be unique")
        if len(self.accepted_semantic_validator_ids) != len(
            set(self.accepted_semantic_validator_ids)
        ):
            raise ValueError("semantic validator IDs must be unique")
        if self.phase_id == "dual-ai-review":
            if self.conditional_next != {
                "agreement": "review-driven-revision",
                "disagreement": "ai-adjudication",
            }:
                raise ValueError("dual AI review must route disagreement to AI adjudication")
            if self.default_next_phase_id is not None:
                raise ValueError("dual AI review uses only conditional transitions")
        elif self.conditional_next:
            raise ValueError("only dual AI review may use the v3 conditional transition")
        if self.phase_id == "complete" and self.default_next_phase_id is not None:
            raise ValueError("complete must be terminal")
        return self


class ResearchProgramContract(BaseModel):
    """Exact v3 program and model inventory compiled for one project."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    program_id: str
    source_program_id: str
    source_program_schema_version: Literal["3.0", "4.0"]
    source_program_locator: Literal["inputs/experiment_program.yaml"]
    source_program_file_sha256: str = Field(pattern=_SHA256)
    model_inventory_id: str
    model_inventory_locator: Literal["inputs/model_inventory.yaml"]
    model_inventory_file_sha256: str = Field(pattern=_SHA256)
    model_selection_gate: Literal["task-excluded-conformance"]
    phases: tuple[ResearchProgramPhaseContract, ...] = Field(min_length=17, max_length=17)
    blocked_external_system_ids: tuple[str, ...]
    planning_is_scientific_result: Literal[False] = False
    controller_authorizes_api_calls: Literal[False] = False
    controller_authorizes_gpu_work: Literal[False] = False
    controller_authorizes_downloads: Literal[False] = False
    controller_authorizes_external_system_substitution: Literal[False] = False
    contract_sha256: str = Field(pattern=_SHA256)

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("program_id", "source_program_id", "model_inventory_id")
    @classmethod
    def ids_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "identifier")))

    @model_validator(mode="after")
    def contract_is_closed(self) -> ResearchProgramContract:
        if tuple(item.phase_id for item in self.phases) != _PHASE_IDS:
            raise ValueError("research program phases differ from the complete v3 lifecycle")
        for index, phase in enumerate(self.phases):
            expected_next = (
                None
                if phase.phase_id in {"dual-ai-review", "complete"}
                else self.phases[index + 1].phase_id
            )
            if phase.default_next_phase_id != expected_next:
                raise ValueError("research program default transition differs from complete v3")
        if len(self.blocked_external_system_ids) != len(set(self.blocked_external_system_ids)):
            raise ValueError("blocked external systems must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"contract_sha256"}))
        if self.contract_sha256 != expected:
            raise ValueError("research program contract hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ResearchProgramContract:
        payload = {"schema_version": "1.0", **values}
        payload.pop("contract_sha256", None)
        unsigned = cls.model_construct(contract_sha256="0" * 64, **payload)
        return cls(
            **payload,
            contract_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"contract_sha256"})
            ),
        )


class ResearchProgramArtifactBinding(BaseModel):
    """Content binding to a non-empty regular artifact in the owning project."""

    model_config = _CONFIG

    artifact_id: str
    project_relative_locator: str
    sha256: str = Field(pattern=_SHA256)
    size_bytes: int = Field(gt=0)

    @field_validator("artifact_id")
    @classmethod
    def artifact_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="artifact_id")

    @field_validator("project_relative_locator")
    @classmethod
    def locator_is_owned(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="program artifact locator")


class ResearchProgramB0ValidationReceipt(BaseModel):
    """Development-only proof that a phase shape ran; it can never become evidence."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    block_id: Literal["B0-task-excluded-complete-pipeline-conformance"]
    phase_id: Literal["hidden-scoring"]
    source_receipt_locator: str
    source_receipt_sha256: str = Field(pattern=_SHA256)
    completed_at: datetime
    formal_evidence: Literal[False] = False
    headline_eligible: Literal[False] = False
    scientific_result_established: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("source_receipt_locator")
    @classmethod
    def source_locator_is_owned(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="B0 source receipt")

    @model_validator(mode="after")
    def receipt_is_closed(self) -> ResearchProgramB0ValidationReceipt:
        if self.completed_at.utcoffset() is None:
            raise ValueError("B0 validation completion must be timezone-aware")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("B0 validation receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ResearchProgramB0ValidationReceipt:
        payload = {"schema_version": "1.0", **values}
        payload.pop("receipt_sha256", None)
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        return cls(
            **payload,
            receipt_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


class ResearchProgramTransition(BaseModel):
    """One append-only, hash-chained lifecycle event."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    program_id: str
    contract_sha256: str = Field(pattern=_SHA256)
    sequence: int = Field(ge=1)
    from_phase_id: ResearchProgramPhaseId
    to_phase_id: ResearchProgramPhaseId | None
    disposition: ResearchProgramTransitionDisposition
    artifact_bindings: tuple[ResearchProgramArtifactBinding, ...] = Field(default=(), max_length=32)
    semantic_validator_ids: tuple[str, ...] = Field(default=(), max_length=12)
    recorded_at: datetime
    reason: str | None = Field(default=None, min_length=1, max_length=4_000)
    review_outcome: ReviewOutcome | None = None
    revision_target: RevisionTarget | None = None
    previous_transition_sha256: str | None = Field(default=None, pattern=_SHA256)
    artifacts_completed_outside_controller: bool
    controller_launched_api: Literal[False] = False
    controller_launched_gpu: Literal[False] = False
    controller_launched_download: Literal[False] = False
    controller_launched_external_system: Literal[False] = False
    establishes_scientific_result_by_itself: Literal[False] = False
    transition_sha256: str = Field(pattern=_SHA256)

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("program_id")
    @classmethod
    def program_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="program_id")

    @model_validator(mode="after")
    def transition_is_closed(self) -> ResearchProgramTransition:
        if self.recorded_at.utcoffset() is None:
            raise ValueError("transition timestamp must be timezone-aware")
        artifact_ids = [item.artifact_id for item in self.artifact_bindings]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("transition artifact IDs must be unique")
        if len(self.semantic_validator_ids) != len(set(self.semantic_validator_ids)):
            raise ValueError("transition semantic validator IDs must be unique")
        completed = self.disposition is ResearchProgramTransitionDisposition.COMPLETED
        if completed != self.artifacts_completed_outside_controller:
            raise ValueError("only a completed phase may attest completed external artifacts")
        if not completed and self.artifact_bindings:
            raise ValueError("blocked, failed, and resumed transitions cannot bind phase results")
        if completed != bool(self.semantic_validator_ids):
            raise ValueError("only completed transitions carry semantic validation evidence")
        if self.disposition in {
            ResearchProgramTransitionDisposition.BLOCKED,
            ResearchProgramTransitionDisposition.FAILED,
        }:
            if self.to_phase_id != self.from_phase_id or self.reason is None:
                raise ValueError("blocked or failed transitions remain in phase and require reason")
        if self.disposition is ResearchProgramTransitionDisposition.RESUMED:
            if self.to_phase_id != self.from_phase_id or self.reason is not None:
                raise ValueError(
                    "resume must remain in phase and cannot invent a resolution reason"
                )
        if self.from_phase_id == "dual-ai-review" and completed:
            if self.review_outcome not in {"agreement", "disagreement"}:
                raise ValueError("dual AI review requires agreement or disagreement")
        elif self.from_phase_id == "final-ai-review-and-package-freeze" and completed:
            if self.review_outcome not in {"accepted", "revision_required"}:
                raise ValueError("final AI review requires accepted or revision_required")
        elif self.review_outcome is not None:
            raise ValueError("review outcome is valid only on an AI review phase")
        if self.review_outcome == "revision_required":
            if self.revision_target is None or self.to_phase_id != self.revision_target:
                raise ValueError("revision-required review must choose its exact return phase")
        elif self.revision_target is not None:
            raise ValueError("revision target is valid only when revision is required")
        expected = content_sha256(self.model_dump(mode="json", exclude={"transition_sha256"}))
        if self.transition_sha256 != expected:
            raise ValueError("research program transition hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ResearchProgramTransition:
        payload = {"schema_version": "1.0", **values}
        payload.pop("transition_sha256", None)
        unsigned = cls.model_construct(transition_sha256="0" * 64, **payload)
        return cls(
            **payload,
            transition_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"transition_sha256"})
            ),
        )


class ResearchProgramState(BaseModel):
    """Current immutable projection of the append-only transition chain."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    program_id: str
    contract_sha256: str = Field(pattern=_SHA256)
    sequence: int = Field(ge=0)
    status: ResearchProgramRunStatus
    current_phase_id: ResearchProgramPhaseId
    next_actionable_phase_id: ResearchProgramPhaseId | None
    final_review_accepted: bool = False
    transition_locators: tuple[str, ...] = ()
    transition_sha256s: tuple[str, ...] = ()
    state_sha256: str = Field(pattern=_SHA256)

    @field_validator("project_id")
    @classmethod
    def project_id_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("program_id")
    @classmethod
    def program_id_is_safe(cls, value: str) -> str:
        return validate_entry_id(value, field_name="program_id")

    @field_validator("transition_locators")
    @classmethod
    def transition_locators_are_local(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            locator = validate_relative_locator(value, field_name="transition locator")
            if PurePosixPath(locator).parts[0] != "transitions":
                raise ValueError("transition locators must remain under transitions/")
        return values

    @model_validator(mode="after")
    def state_is_closed(self) -> ResearchProgramState:
        if not (self.sequence == len(self.transition_locators) == len(self.transition_sha256s)):
            raise ValueError("state sequence must match its complete transition chain")
        if len(self.transition_locators) != len(set(self.transition_locators)):
            raise ValueError("transition locators must be unique")
        if self.status is ResearchProgramRunStatus.COMPLETE:
            if (
                self.current_phase_id != "complete"
                or self.next_actionable_phase_id is not None
                or not self.final_review_accepted
            ):
                raise ValueError("complete status requires accepted final review and no next phase")
        elif self.next_actionable_phase_id != self.current_phase_id:
            raise ValueError("an incomplete program must expose its current actionable phase")
        expected = content_sha256(self.model_dump(mode="json", exclude={"state_sha256"}))
        if self.state_sha256 != expected:
            raise ValueError("research program state hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ResearchProgramState:
        payload = {"schema_version": "1.0", **values}
        payload.pop("state_sha256", None)
        unsigned = cls.model_construct(state_sha256="0" * 64, **payload)
        return cls(
            **payload,
            state_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"state_sha256"})),
        )


class ResearchProgramLaunchPlan(BaseModel):
    """Typed dispatch boundary for the current phase; it grants no authority."""

    model_config = _CONFIG

    phase_id: ResearchProgramPhaseId
    scitaste_interfaces: tuple[str, ...]
    execution_authority: PhaseExecutionAuthority
    required_authority_flags: tuple[LaunchAuthorityFlag, ...]
    authority_rule: Literal["none", "all-listed", "at-least-one-listed"]
    automatic_after_exact_input_binding: bool
    exact_interface_arguments_bound: Literal[False] = False
    implicit_dispatch_permitted: Literal[False] = False
    external_system_substitution_permitted: Literal[False] = False
    next_action: Literal[
        "bind-interface-inputs",
        "obtain-explicit-resource-authority-and-bind-inputs",
        "terminal",
    ]


class ResearchProgramStatus(BaseModel):
    """Verified project program plus its exact current phase contract."""

    model_config = _CONFIG

    contract: ResearchProgramContract
    state: ResearchProgramState
    current_phase: ResearchProgramPhaseContract
    required_artifact_ids: tuple[str, ...]
    can_advance: bool
    required_action: Literal[
        "provide-completed-artifacts",
        "resolve-blocker-then-resume",
        "repair-failure-then-resume",
        "none",
    ]
    history_verified: Literal[True] = True
    bound_artifacts_verified: Literal[True] = True
    no_external_work_performed: Literal[True] = True
    next_action_launch_plan: ResearchProgramLaunchPlan | None


_PHASE_METADATA: dict[
    ResearchProgramPhaseId,
    tuple[
        tuple[str, ...],
        tuple[str, ...],
        PhaseExecutionAuthority,
        ScientificResultAuthority,
    ],
] = {
    "task-acquisition-proposed": (
        ("scitaste evaluation acquisition-request",),
        ("benchmark-assets", "license-and-provenance"),
        PhaseExecutionAuthority.PROJECT_ARTIFACT,
        "none",
    ),
    "acquired-quarantined": (
        (
            "scitaste evaluation acquisition-download",
            "scitaste evaluation acquisition-content-audit",
        ),
        ("benchmark-assets", "network-and-storage"),
        PhaseExecutionAuthority.EXTERNAL_EXECUTOR,
        "none",
    ),
    "task-admitted-and-split-frozen": (
        ("scitaste evaluation task-package", "scitaste evaluation task-selection"),
        ("benchmark-assets", "hidden-scorer"),
        PhaseExecutionAuthority.PROJECT_ARTIFACT,
        "none",
    ),
    "models-and-systems-frozen": (
        ("scitaste resource inspect", "scitaste model-node runtime plan"),
        ("research-agent", "code-agent", "judge", "task-training"),
        PhaseExecutionAuthority.TASK_EXCLUDED_SELECTION,
        "none",
    ),
    "idea-candidates-generated": (
        ("scitaste project discovery advance",),
        ("research-agent", "reference-corpus"),
        PhaseExecutionAuthority.EXTERNAL_EXECUTOR,
        "none",
    ),
    "idea-decision-locked": (
        ("scitaste taste lock-prospective-decision-v2",),
        ("research-agent", "taste-library"),
        PhaseExecutionAuthority.PROJECT_ARTIFACT,
        "none",
    ),
    "experiment-plan-frozen": (
        (
            "scitaste evaluation cell-plan",
            "scitaste evaluation campaign-activation-plan",
        ),
        ("benchmark-assets", "api-budget", "gpu-budget"),
        PhaseExecutionAuthority.PROJECT_ARTIFACT,
        "none",
    ),
    "development-execution": (
        ("scitaste study project-run", "scitaste substrate project execute"),
        ("code-agent", "task-training", "api", "gpu"),
        PhaseExecutionAuthority.EXTERNAL_EXECUTOR,
        "none",
    ),
    "candidate-frozen": (
        ("scitaste evaluation executable-candidate",),
        ("checkpoint", "environment", "source-code"),
        PhaseExecutionAuthority.PROJECT_ARTIFACT,
        "none",
    ),
    "hidden-scoring": (
        ("scitaste evaluation objective-analyze", "scitaste study evaluate"),
        ("hidden-scorer",),
        PhaseExecutionAuthority.SCORER_ONLY,
        "benchmark-hidden-scorer",
    ),
    "evidence-admission": (
        ("scitaste project evaluation register-result",),
        ("evidence-graph", "failure-ledger"),
        PhaseExecutionAuthority.PROJECT_ARTIFACT,
        "admitted-evidence-only",
    ),
    "paper-assembly": (
        ("scitaste project paper build-draft",),
        ("writing-agent", "venue-taste"),
        PhaseExecutionAuthority.EXTERNAL_EXECUTOR,
        "none",
    ),
    "dual-ai-review": (
        (
            "scitaste project paper review prepare",
            "scitaste project paper review model-input",
            "scitaste project paper review runtime-config",
            "scitaste model-node runtime execute",
            "scitaste project paper review import-model-report",
        ),
        ("judge-primary-a", "judge-primary-b"),
        PhaseExecutionAuthority.INDEPENDENT_AI,
        "none",
    ),
    "ai-adjudication": (
        (
            "scitaste model-node runtime execute",
            "scitaste project paper review import-model-report",
            "scitaste evaluation review-finality",
        ),
        ("judge-adjudicator",),
        PhaseExecutionAuthority.INDEPENDENT_AI_ADJUDICATOR,
        "none",
    ),
    "review-driven-revision": (
        (
            "scitaste project paper review respond",
            "scitaste project paper build-revision",
        ),
        ("research-agent", "code-agent", "writing-agent"),
        PhaseExecutionAuthority.EXTERNAL_EXECUTOR,
        "none",
    ),
    "final-ai-review-and-package-freeze": (
        (
            "scitaste project paper review prepare",
            "scitaste project paper review import-model-report",
            "scitaste evaluation review-finality",
        ),
        ("judge-primary-a", "judge-primary-b"),
        PhaseExecutionAuthority.INDEPENDENT_AI,
        "none",
    ),
    "complete": (
        ("scitaste project status",),
        ("evidence-package", "resource-ledger"),
        PhaseExecutionAuthority.PROJECT_ARTIFACT,
        "none",
    ),
}

_PHASE_LAUNCH_FLAGS: dict[
    ResearchProgramPhaseId,
    tuple[tuple[LaunchAuthorityFlag, ...], Literal["none", "all-listed", "at-least-one-listed"]],
] = {
    "task-acquisition-proposed": ((), "none"),
    "acquired-quarantined": (("--allow-download",), "all-listed"),
    "task-admitted-and-split-frozen": ((), "none"),
    "models-and-systems-frozen": (("--allow-api", "--allow-gpu"), "at-least-one-listed"),
    "idea-candidates-generated": (("--allow-api", "--allow-gpu"), "at-least-one-listed"),
    "idea-decision-locked": ((), "none"),
    "experiment-plan-frozen": ((), "none"),
    "development-execution": (
        ("--allow-api", "--allow-gpu", "--allow-external-system"),
        "at-least-one-listed",
    ),
    "candidate-frozen": ((), "none"),
    "hidden-scoring": (("--allow-gpu",), "all-listed"),
    "evidence-admission": ((), "none"),
    "paper-assembly": (("--allow-api", "--allow-gpu"), "at-least-one-listed"),
    "dual-ai-review": (("--allow-api", "--allow-gpu"), "at-least-one-listed"),
    "ai-adjudication": (("--allow-api", "--allow-gpu"), "at-least-one-listed"),
    "review-driven-revision": (("--allow-api", "--allow-gpu"), "at-least-one-listed"),
    "final-ai-review-and-package-freeze": (
        ("--allow-api", "--allow-gpu"),
        "at-least-one-listed",
    ),
    "complete": ((), "none"),
}

_PHASE_SEMANTIC_VALIDATORS: dict[ResearchProgramPhaseId, tuple[str, ...]] = {
    phase_id: ("hash-bound-phase-artifacts-v1",) for phase_id in _PHASE_IDS
}
_PHASE_SEMANTIC_VALIDATORS.update(
    {
        "models-and-systems-frozen": ("model-role-selection-task-excluded-v1",),
        "idea-decision-locked": ("prospective-taste-predecision-lock-v2",),
        "hidden-scoring": (
            "scorer-owned-heldout-measurement-v1",
            "development-only-b0-validation-v1",
        ),
        "evidence-admission": ("project-evaluation-result-admission-v1",),
        "dual-ai-review": ("registered-independent-dual-ai-review-v1",),
        "ai-adjudication": ("ai-paper-review-disagreement-adjudication-v1",),
        "final-ai-review-and-package-freeze": ("ai-paper-review-operational-finality-v1",),
    }
)


class ResearchProgramRuntime:
    """Initialize, verify, and advance project-owned complete research programs."""

    def __init__(self, outputs_root: str | Path) -> None:
        self.project_runtime = ProjectRuntime(outputs_root)

    def initialize(
        self,
        *,
        project_id: str,
        program_path: str | Path,
        model_inventory_path: str | Path,
        expected_revision: int,
    ) -> ResearchProgramStatus:
        snapshot = self.project_runtime.open(project_id)
        if snapshot.revision != expected_revision:
            raise ValueError(
                f"stale project revision {expected_revision}; current is {snapshot.revision}"
            )
        project_root = self.project_runtime.projects_root / project_id
        source_program = Path(program_path).expanduser().resolve()
        source_inventory = Path(model_inventory_path).expanduser().resolve()
        program_bytes, program_payload = _load_yaml_bytes(source_program, "experiment program")
        inventory_bytes, inventory_payload = _load_yaml_bytes(
            source_inventory, "model role inventory"
        )
        contract = _compile_contract(
            project_id=project_id,
            program_payload=program_payload,
            program_bytes=program_bytes,
            inventory_payload=inventory_payload,
            inventory_bytes=inventory_bytes,
        )
        snapshot = self.project_runtime.begin_run(
            project_id,
            ProjectRun(
                run_id=contract.program_id,
                provider="scitaste-native",
                model="task-excluded-selection-pending",
                condition=f"complete-autoresearch-program-v{contract.source_program_schema_version[0]}",
                seed=0,
                status="program-initializing",
                evidence_scope="orchestration-only-no-scientific-result",
                stage_path="program",
                artifact="program/STATE.json",
            ),
            expected_revision=expected_revision,
        )
        target = project_root / "runs" / contract.program_id / "program"
        try:
            with _locked(target / ".program.lock"):
                (target / "inputs").mkdir()
                (target / "transitions").mkdir()
                _write_bytes_exclusive(
                    target / contract.source_program_locator,
                    program_bytes,
                )
                _write_bytes_exclusive(
                    target / contract.model_inventory_locator,
                    inventory_bytes,
                )
                _write_json_exclusive(target / "PROGRAM.json", contract)
                state = ResearchProgramState.create(
                    project_id=project_id,
                    program_id=contract.program_id,
                    contract_sha256=contract.contract_sha256,
                    sequence=0,
                    status=ResearchProgramRunStatus.ACTIVE,
                    current_phase_id=_PHASE_IDS[0],
                    next_actionable_phase_id=_PHASE_IDS[0],
                    final_review_accepted=False,
                    transition_locators=(),
                    transition_sha256s=(),
                )
                _write_json_exclusive(target / "STATE.json", state)
            self.project_runtime.update_run(
                project_id,
                contract.program_id,
                expected_revision=snapshot.revision,
                status="running",
            )
        except BaseException:
            try:
                current = self.project_runtime.open(project_id)
                self.project_runtime.update_run(
                    project_id,
                    contract.program_id,
                    expected_revision=current.revision,
                    status="failed-initialization",
                )
            except (OSError, ValueError):
                pass
            raise
        return self.status(project_id=project_id, program_id=contract.program_id)

    def status(self, *, project_id: str, program_id: str) -> ResearchProgramStatus:
        root = self._program_root(project_id, program_id)
        contract = ResearchProgramContract.model_validate_json(
            _read_bounded(root / "PROGRAM.json", 4 * 1024 * 1024)
        )
        if contract.project_id != project_id or contract.program_id != program_id:
            raise ValueError("research program belongs to another project or program ID")
        for locator, expected in (
            (contract.source_program_locator, contract.source_program_file_sha256),
            (contract.model_inventory_locator, contract.model_inventory_file_sha256),
        ):
            path = _contained_regular_file(root, locator)
            if _file_sha256(path) != expected:
                raise ValueError(f"bound research program input drifted: {locator}")
        state = ResearchProgramState.model_validate_json(
            _read_bounded(root / "STATE.json", 16 * 1024 * 1024)
        )
        if (
            state.project_id != project_id
            or state.program_id != program_id
            or state.contract_sha256 != contract.contract_sha256
        ):
            raise ValueError("research program state targets another contract")
        self._verify_history(root, contract, state)
        phase = _phase(contract, state.current_phase_id)
        action = {
            ResearchProgramRunStatus.ACTIVE: "provide-completed-artifacts",
            ResearchProgramRunStatus.BLOCKED: "resolve-blocker-then-resume",
            ResearchProgramRunStatus.FAILED: "repair-failure-then-resume",
            ResearchProgramRunStatus.COMPLETE: "none",
        }[state.status]
        return ResearchProgramStatus(
            contract=contract,
            state=state,
            current_phase=phase,
            required_artifact_ids=(
                phase.required_artifact_ids
                if state.status is ResearchProgramRunStatus.ACTIVE
                else ()
            ),
            can_advance=state.status is ResearchProgramRunStatus.ACTIVE,
            required_action=action,
            next_action_launch_plan=(
                None if state.status is ResearchProgramRunStatus.COMPLETE else _launch_plan(phase)
            ),
        )

    def advance(
        self,
        *,
        project_id: str,
        program_id: str,
        artifact_locators: Mapping[str, str],
        disposition: ResearchProgramTransitionDisposition = (
            ResearchProgramTransitionDisposition.COMPLETED
        ),
        reason: str | None = None,
        review_outcome: ReviewOutcome | None = None,
        revision_target: RevisionTarget | None = None,
        recorded_at: datetime | None = None,
        attest_artifacts_complete: bool = False,
    ) -> ResearchProgramStatus:
        root = self._program_root(project_id, program_id)
        with _locked(root / ".program.lock"):
            current = self.status(project_id=project_id, program_id=program_id)
            state = current.state
            contract = current.contract
            phase = current.current_phase
            if state.status is not ResearchProgramRunStatus.ACTIVE:
                raise ValueError("blocked or failed research program must be resumed first")
            if disposition is ResearchProgramTransitionDisposition.RESUMED:
                raise ValueError("use resume() for a resumed transition")
            bindings: tuple[ResearchProgramArtifactBinding, ...] = ()
            semantic_validator_ids: tuple[str, ...] = ()
            if disposition is ResearchProgramTransitionDisposition.COMPLETED:
                if not attest_artifacts_complete:
                    raise ValueError(
                        "completed phase requires explicit artifact completion attestation"
                    )
                expected = set(phase.required_artifact_ids)
                if set(artifact_locators) != expected:
                    raise ValueError(
                        "completed phase artifacts differ from its contract: "
                        f"missing={sorted(expected - set(artifact_locators))}, "
                        f"extra={sorted(set(artifact_locators) - expected)}"
                    )
                bindings = tuple(
                    self._bind_artifact(project_id, artifact_id, artifact_locators[artifact_id])
                    for artifact_id in phase.required_artifact_ids
                )
                try:
                    semantic_validator_ids = _validate_phase_artifacts(
                        self.project_runtime,
                        project_id=project_id,
                        phase_id=phase.phase_id,
                        bindings=bindings,
                        review_outcome=review_outcome,
                    )
                except ValueError as exc:
                    if not str(exc).startswith("unsupported_validator:"):
                        raise
                    disposition = ResearchProgramTransitionDisposition.BLOCKED
                    bindings = ()
                    semantic_validator_ids = ()
                    reason = str(exc)
                    review_outcome = None
                    revision_target = None
                    to_phase = phase.phase_id
                else:
                    to_phase = _completed_destination(
                        phase.phase_id,
                        phase.default_next_phase_id,
                        review_outcome=review_outcome,
                        revision_target=revision_target,
                    )
                    if phase.phase_id == "complete" and not state.final_review_accepted:
                        raise ValueError(
                            "program cannot complete before an accepted final AI review"
                        )
            else:
                if artifact_locators or attest_artifacts_complete:
                    raise ValueError(
                        "blocked and failed transitions do not bind completed artifacts"
                    )
                if review_outcome is not None or revision_target is not None:
                    raise ValueError("blocked and failed transitions cannot claim a review outcome")
                to_phase = phase.phase_id
            accepted = state.final_review_accepted
            if phase.phase_id == "final-ai-review-and-package-freeze":
                accepted = review_outcome == "accepted"
            transition = ResearchProgramTransition.create(
                project_id=project_id,
                program_id=program_id,
                contract_sha256=contract.contract_sha256,
                sequence=state.sequence + 1,
                from_phase_id=phase.phase_id,
                to_phase_id=to_phase,
                disposition=disposition,
                artifact_bindings=bindings,
                semantic_validator_ids=semantic_validator_ids,
                recorded_at=recorded_at or datetime.now(UTC),
                reason=reason,
                review_outcome=review_outcome,
                revision_target=revision_target,
                previous_transition_sha256=(
                    state.transition_sha256s[-1] if state.transition_sha256s else None
                ),
                artifacts_completed_outside_controller=(
                    disposition is ResearchProgramTransitionDisposition.COMPLETED
                ),
            )
            locator = (
                f"transitions/{transition.sequence:06d}-{transition.transition_sha256[:12]}.json"
            )
            _write_json_exclusive(root / locator, transition)
            terminal = phase.phase_id == "complete" and (
                disposition is ResearchProgramTransitionDisposition.COMPLETED
            )
            next_state = ResearchProgramState.create(
                project_id=project_id,
                program_id=program_id,
                contract_sha256=contract.contract_sha256,
                sequence=transition.sequence,
                status=(
                    ResearchProgramRunStatus.COMPLETE
                    if terminal
                    else ResearchProgramRunStatus.BLOCKED
                    if disposition is ResearchProgramTransitionDisposition.BLOCKED
                    else ResearchProgramRunStatus.FAILED
                    if disposition is ResearchProgramTransitionDisposition.FAILED
                    else ResearchProgramRunStatus.ACTIVE
                ),
                current_phase_id=(phase.phase_id if to_phase is None else to_phase),
                next_actionable_phase_id=(
                    None if terminal else (phase.phase_id if to_phase is None else to_phase)
                ),
                final_review_accepted=accepted,
                transition_locators=(*state.transition_locators, locator),
                transition_sha256s=(
                    *state.transition_sha256s,
                    transition.transition_sha256,
                ),
            )
            _atomic_json(root / "STATE.json", next_state)
        return self.status(project_id=project_id, program_id=program_id)

    def resume(
        self,
        *,
        project_id: str,
        program_id: str,
        recorded_at: datetime | None = None,
    ) -> ResearchProgramStatus:
        root = self._program_root(project_id, program_id)
        with _locked(root / ".program.lock"):
            current = self.status(project_id=project_id, program_id=program_id)
            state = current.state
            if state.status not in {
                ResearchProgramRunStatus.BLOCKED,
                ResearchProgramRunStatus.FAILED,
            }:
                raise ValueError("resume requires a blocked or failed program")
            transition = ResearchProgramTransition.create(
                project_id=project_id,
                program_id=program_id,
                contract_sha256=current.contract.contract_sha256,
                sequence=state.sequence + 1,
                from_phase_id=state.current_phase_id,
                to_phase_id=state.current_phase_id,
                disposition=ResearchProgramTransitionDisposition.RESUMED,
                artifact_bindings=(),
                semantic_validator_ids=(),
                recorded_at=recorded_at or datetime.now(UTC),
                reason=None,
                review_outcome=None,
                revision_target=None,
                previous_transition_sha256=(
                    state.transition_sha256s[-1] if state.transition_sha256s else None
                ),
                artifacts_completed_outside_controller=False,
            )
            locator = (
                f"transitions/{transition.sequence:06d}-{transition.transition_sha256[:12]}.json"
            )
            _write_json_exclusive(root / locator, transition)
            next_state = ResearchProgramState.create(
                project_id=project_id,
                program_id=program_id,
                contract_sha256=current.contract.contract_sha256,
                sequence=transition.sequence,
                status=ResearchProgramRunStatus.ACTIVE,
                current_phase_id=state.current_phase_id,
                next_actionable_phase_id=state.current_phase_id,
                final_review_accepted=state.final_review_accepted,
                transition_locators=(*state.transition_locators, locator),
                transition_sha256s=(
                    *state.transition_sha256s,
                    transition.transition_sha256,
                ),
            )
            _atomic_json(root / "STATE.json", next_state)
        return self.status(project_id=project_id, program_id=program_id)

    def _program_root(self, project_id: str, program_id: str) -> Path:
        validate_project_id(project_id)
        validate_entry_id(program_id, field_name="program_id")
        snapshot = self.project_runtime.open(project_id)
        run = next(
            (item for item in snapshot.manifest.runs if item.run_id == program_id),
            None,
        )
        if run is None or run.stage_path != "program" or run.artifact != "program/STATE.json":
            raise ValueError("research program is not registered as a project run")
        root = self.project_runtime.projects_root / project_id / "runs" / program_id / "program"
        if not root.is_dir() or root.is_symlink():
            raise FileNotFoundError(root)
        return root

    def _bind_artifact(
        self,
        project_id: str,
        artifact_id: str,
        locator: str,
    ) -> ResearchProgramArtifactBinding:
        self.project_runtime.open(project_id)
        path = _contained_regular_file(self.project_runtime.projects_root / project_id, locator)
        size = path.stat().st_size
        if size <= 0:
            raise ValueError(f"research program artifact is empty: {locator}")
        return ResearchProgramArtifactBinding(
            artifact_id=artifact_id,
            project_relative_locator=locator,
            sha256=_file_sha256(path),
            size_bytes=size,
        )

    def _verify_history(
        self,
        root: Path,
        contract: ResearchProgramContract,
        state: ResearchProgramState,
    ) -> None:
        previous: ResearchProgramTransition | None = None
        current_phase: ResearchProgramPhaseId = _PHASE_IDS[0]
        current_status = ResearchProgramRunStatus.ACTIVE
        final_review_accepted = False
        project_root = root.parents[2]
        for sequence, (locator, expected_hash) in enumerate(
            zip(state.transition_locators, state.transition_sha256s, strict=True), 1
        ):
            transition = ResearchProgramTransition.model_validate_json(
                _read_bounded(_contained_regular_file(root, locator), 4 * 1024 * 1024)
            )
            if (
                transition.sequence != sequence
                or transition.transition_sha256 != expected_hash
                or transition.contract_sha256 != contract.contract_sha256
                or transition.project_id != contract.project_id
                or transition.program_id != contract.program_id
            ):
                raise ValueError("research program transition chain identity mismatch")
            if transition.from_phase_id != current_phase:
                raise ValueError("research program transition chain phase mismatch")
            if transition.previous_transition_sha256 != (
                previous.transition_sha256 if previous is not None else None
            ):
                raise ValueError("research program transition hash chain mismatch")
            phase = _phase(contract, transition.from_phase_id)
            _verify_transition_semantics(phase, transition, final_review_accepted)
            observed_validators = (
                _validate_phase_artifacts(
                    self.project_runtime,
                    project_id=contract.project_id,
                    phase_id=phase.phase_id,
                    bindings=transition.artifact_bindings,
                    review_outcome=transition.review_outcome,
                )
                if transition.disposition is ResearchProgramTransitionDisposition.COMPLETED
                else ()
            )
            if transition.semantic_validator_ids != observed_validators:
                raise ValueError("research program semantic validation trace mismatch")
            for binding in transition.artifact_bindings:
                artifact = _contained_regular_file(
                    project_root,
                    binding.project_relative_locator,
                )
                if (
                    artifact.stat().st_size != binding.size_bytes
                    or _file_sha256(artifact) != binding.sha256
                ):
                    raise ValueError(
                        "bound research program artifact drifted: "
                        f"{binding.project_relative_locator}"
                    )
            if transition.disposition is ResearchProgramTransitionDisposition.BLOCKED:
                current_status = ResearchProgramRunStatus.BLOCKED
            elif transition.disposition is ResearchProgramTransitionDisposition.FAILED:
                current_status = ResearchProgramRunStatus.FAILED
            elif transition.disposition is ResearchProgramTransitionDisposition.RESUMED:
                if current_status not in {
                    ResearchProgramRunStatus.BLOCKED,
                    ResearchProgramRunStatus.FAILED,
                }:
                    raise ValueError("resume transition does not follow a blocked or failed state")
                current_status = ResearchProgramRunStatus.ACTIVE
            else:
                if current_status is not ResearchProgramRunStatus.ACTIVE:
                    raise ValueError("completed transition follows an unresolved blocked state")
                if transition.from_phase_id == "final-ai-review-and-package-freeze":
                    final_review_accepted = transition.review_outcome == "accepted"
                if transition.from_phase_id == "complete":
                    current_status = ResearchProgramRunStatus.COMPLETE
                else:
                    current_status = ResearchProgramRunStatus.ACTIVE
                if transition.to_phase_id is not None:
                    current_phase = transition.to_phase_id
            previous = transition
        if (
            current_phase != state.current_phase_id
            or current_status is not state.status
            or final_review_accepted != state.final_review_accepted
        ):
            raise ValueError("research program state differs from its transition history")


def _launch_plan(phase: ResearchProgramPhaseContract) -> ResearchProgramLaunchPlan:
    flags, rule = _PHASE_LAUNCH_FLAGS[phase.phase_id]
    terminal = phase.phase_id == "complete"
    return ResearchProgramLaunchPlan(
        phase_id=phase.phase_id,
        scitaste_interfaces=phase.scitaste_interfaces,
        execution_authority=phase.execution_authority,
        required_authority_flags=flags,
        authority_rule=rule,
        automatic_after_exact_input_binding=not flags and not terminal,
        next_action=(
            "terminal"
            if terminal
            else "obtain-explicit-resource-authority-and-bind-inputs"
            if flags
            else "bind-interface-inputs"
        ),
    )


def _validate_phase_artifacts(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    phase_id: ResearchProgramPhaseId,
    bindings: tuple[ResearchProgramArtifactBinding, ...],
    review_outcome: ReviewOutcome | None,
) -> tuple[str, ...]:
    """Re-run typed scientific gates; ordinary planning phases remain hash-bound."""

    by_id = {item.artifact_id: item for item in bindings}
    project_root = runtime.projects_root / project_id

    def artifact(artifact_id: str) -> Path:
        binding = by_id[artifact_id]
        return _contained_regular_file(project_root, binding.project_relative_locator)

    try:
        if phase_id == "models-and-systems-frozen":
            from scitaste.evaluation.model_role_conformance import (
                ModelRole,
                SelectionStatus,
                load_model_role_selection,
            )

            selection = load_model_role_selection(artifact("task-excluded-model-selection"))
            selected = {item.role: item for item in selection.selections}
            judge = selected.get(ModelRole.JUDGE)
            if (
                selection.status is not SelectionStatus.COMPLETE
                or not selection.headline_eligible
                or selection.missing_roles
                or set(selected) != set(ModelRole)
                or judge is None
                or not judge.headline_independent
            ):
                raise ValueError(
                    "model-role selection is incomplete or lacks an identity-distinct judge"
                )
            return ("model-role-selection-task-excluded-v1",)

        if phase_id == "idea-decision-locked":
            from scitaste.taste.trajectory_reconstruction import (
                load_taste_prospective_decision_lock,
            )

            lock = load_taste_prospective_decision_lock(artifact("selected-idea"))
            if lock.source_project_id != project_id or lock.schema_version != "2.0":
                raise ValueError("prospective v2 decision lock belongs to another project")
            return ("prospective-taste-predecision-lock-v2",)

        if phase_id == "hidden-scoring":
            from scitaste.evaluation.native_measurement import (
                NativeBenchmarkObjectiveMeasurement,
            )
            from scitaste.evaluation.task_scoring import BenchmarkHeldoutExecutionReceipt

            receipt_path = artifact("isolated-inference-receipt")
            score_path = artifact("score-output")
            try:
                receipt = BenchmarkHeldoutExecutionReceipt.model_validate_json(
                    receipt_path.read_text(encoding="utf-8")
                )
                measurement = NativeBenchmarkObjectiveMeasurement.model_validate_json(
                    score_path.read_text(encoding="utf-8")
                )
            except ValueError:
                b0_receipt = ResearchProgramB0ValidationReceipt.model_validate_json(
                    score_path.read_text(encoding="utf-8")
                )
                source_binding = by_id["isolated-inference-receipt"]
                if (
                    b0_receipt.project_id != project_id
                    or b0_receipt.source_receipt_locator != source_binding.project_relative_locator
                    or b0_receipt.source_receipt_sha256 != source_binding.sha256
                ):
                    raise ValueError(
                        "development-only B0 validation does not bind its source receipt"
                    ) from None
                return ("development-only-b0-validation-v1",)
            if (
                measurement.heldout_receipt_sha256 != receipt.receipt_sha256
                or measurement.frozen_candidate_sha256 != receipt.frozen_candidate_sha256
                or (receipt.status == "succeeded") != (measurement.outcome_status == "measured")
            ):
                raise ValueError("scorer-owned measurement does not bind the held-out receipt")
            return ("scorer-owned-heldout-measurement-v1",)

        if phase_id == "evidence-admission":
            from scitaste.evaluation.results import EvaluationOutcomeAssessment

            result_binding = by_id["claim-result-links"]
            result_parts = PurePosixPath(result_binding.project_relative_locator).parts
            if (
                len(result_parts) != 3
                or result_parts[0] != "evaluation-results"
                or result_parts[2] != "RESULT.json"
            ):
                raise ValueError("claim-result-links must reference a registered RESULT.json")
            bundle = runtime.open_evaluation_result(project_id, result_parts[1])
            if (
                bundle.status != "complete"
                or not bundle.scientific_evidence_complete
                or not bundle.headline_eligible
            ):
                raise ValueError("registered evaluation evidence is incomplete or non-headline")
            assessment = EvaluationOutcomeAssessment.model_validate_json(
                artifact("validity-findings").read_text(encoding="utf-8")
            )
            expected_assessment = (
                PurePosixPath("evaluation-results")
                / result_parts[1]
                / bundle.files["assessment"].locator
            ).as_posix()
            if (
                by_id["validity-findings"].project_relative_locator != expected_assessment
                or assessment.assessment_sha256 != bundle.assessment_sha256
                or assessment.status != "complete"
                or not assessment.scientific_evidence_complete
            ):
                raise ValueError("evidence admission does not bind its registered assessment")
            return ("project-evaluation-result-admission-v1",)

        if phase_id == "dual-ai-review":
            review_id = _registered_review_id(by_id["two-raw-reviews"])
            from scitaste.review.venue import (
                inspect_venue_review,
                load_venue_review_reports,
            )

            inspect_venue_review(runtime, project_id, review_id)
            reports = load_venue_review_reports(runtime, project_id, review_id)
            if len(reports) != 2:
                raise ValueError("dual AI review requires exactly two registered reports")
            identities = []
            for report in reports:
                provenance = report.model_invocation
                if (
                    report.reviewer.reviewer_kind != "independent_model"
                    or not report.reviewer.independent
                    or report.reviewer.conflict_status != "cleared"
                    or provenance is None
                ):
                    raise ValueError("dual review requires two provenance-bound independent AIs")
                identities.append(
                    (
                        report.reviewer.reviewer_id,
                        provenance.returned_provider,
                        provenance.returned_model,
                        provenance.run_id,
                        provenance.raw_response_sha256,
                    )
                )
            if any(len({item[index] for item in identities}) != 2 for index in range(5)):
                raise ValueError(
                    "dual AI reviewer, model, run, and response identities must differ"
                )
            observed = (
                "agreement"
                if reports[0].initial_recommendation == reports[1].initial_recommendation
                else "disagreement"
            )
            if review_outcome != observed:
                raise ValueError("declared dual-review outcome differs from registered reports")
            return ("registered-independent-dual-ai-review-v1",)

        if phase_id in {"ai-adjudication", "final-ai-review-and-package-freeze"}:
            from scitaste.evaluation.review_authority import (
                OperationalReviewNode,
                OperationalReviewVerdict,
                load_ai_operational_review_closure,
            )

            artifact_id = (
                "adjudication-response"
                if phase_id == "ai-adjudication"
                else "final-dual-ai-disposition"
            )
            closure = load_ai_operational_review_closure(artifact(artifact_id))
            if closure.node is not OperationalReviewNode.PAPER_REVIEW:
                raise ValueError("AI review closure must target the paper-review node")
            subject = _contained_regular_file(project_root, closure.subject_locator)
            if _file_sha256(subject) != closure.subject_sha256:
                raise ValueError("AI review closure subject has drifted")
            if phase_id == "ai-adjudication":
                if closure.adjudicator_review is None:
                    raise ValueError("review disagreement requires a distinct third AI")
                return ("ai-paper-review-disagreement-adjudication-v1",)
            expected = (
                OperationalReviewVerdict.ACCEPT
                if review_outcome == "accepted"
                else OperationalReviewVerdict.REJECT
            )
            if closure.final_verdict is not expected:
                raise ValueError("final review route differs from the operational AI verdict")
            return ("ai-paper-review-operational-finality-v1",)
    except (OSError, ValueError) as exc:
        raise ValueError(f"unsupported_validator:{phase_id}:{exc}") from exc

    return ("hash-bound-phase-artifacts-v1",)


def _registered_review_id(binding: ResearchProgramArtifactBinding) -> str:
    parts = PurePosixPath(binding.project_relative_locator).parts
    if len(parts) != 3 or parts[0] != "reviews" or parts[2] != "ROUND.json":
        raise ValueError("two-raw-reviews must reference registered reviews/<id>/ROUND.json")
    return validate_entry_id(parts[1], field_name="review_id")


_V4_REQUIRED_CAPABILITIES = {
    "research-goal-and-task-intake",
    "literature-and-reference-acquisition",
    "source-quality-admission",
    "grounded-taste-abstraction",
    "candidate-idea-and-hypothesis-generation",
    "taste-guided-selection-and-abstention",
    "experiment-design-and-preregistration",
    "role-and-resource-allocation",
    "implementation-and-bounded-repair",
    "experiment-execution-and-telemetry",
    "candidate-freeze-and-hidden-scoring",
    "evidence-analysis-and-contradiction-accounting",
    "claim-evidence-linked-paper-generation",
    "independent-dual-ai-review",
    "disagreement-adjudication",
    "review-driven-revision",
    "final-review-and-package-freeze",
}


def _validate_capability_driven_v4(program_payload: Mapping[str, object]) -> None:
    """Reject v4 plans that regress to a checkpoint-driven partial workflow."""

    supersedes = program_payload.get("supersedes")
    program_id = program_payload.get("program_id")
    predecessor_by_program = {
        "scitaste-iclr2027-capability-driven-autoresearch-program-v5": (
            "scitaste-iclr2027-capability-driven-autoresearch-program-v4"
        ),
        "scitaste-iclr2027-capability-driven-autoresearch-program-v6": (
            "scitaste-iclr2027-capability-driven-autoresearch-program-v5"
        ),
        "scitaste-iclr2027-capability-driven-autoresearch-program-v7": (
            "scitaste-iclr2027-capability-driven-autoresearch-program-v6"
        ),
        "scitaste-iclr2027-capability-driven-autoresearch-program-v8": (
            "scitaste-iclr2027-capability-driven-autoresearch-program-v7"
        ),
        "scitaste-iclr2027-capability-driven-autoresearch-program-v9": (
            "scitaste-iclr2027-capability-driven-autoresearch-program-v8"
        ),
    }
    expected_predecessor = predecessor_by_program.get(
        program_id,
        "scitaste-iclr2027-complete-autoresearch-program-v3",
    )
    if not isinstance(supersedes, dict) or supersedes.get("program_id") != expected_predecessor:
        raise ValueError("capability-driven program has the wrong explicit predecessor")

    completeness = program_payload.get("automation_completeness")
    if not isinstance(completeness, dict):
        raise ValueError("program v4 lacks the automation completeness contract")
    raw_capabilities = completeness.get("required_capabilities")
    if (
        not isinstance(raw_capabilities, list)
        or set(raw_capabilities) != _V4_REQUIRED_CAPABILITIES
        or completeness.get("success_requires_all_capabilities") is not True
        or completeness.get("partial_pipeline_may_be_reported_as_complete") is not False
    ):
        raise ValueError("program v4 does not require the complete research workflow")
    feedback = completeness.get("required_feedback_loops")
    if not isinstance(feedback, dict) or any(
        feedback.get(key) != "required"
        for key in ("review_to_paper", "review_to_evidence", "review_to_experiment_plan")
    ):
        raise ValueError("program v4 must preserve review-driven return paths")

    tracks = program_payload.get("research_tracks")
    if not isinstance(tracks, list):
        raise ValueError("program v4 lacks the complete research-track matrix")
    by_study = {item.get("study_id"): item for item in tracks if isinstance(item, dict)}
    if set(by_study) != {"E0", "E1", "E2", "E3", "E4"}:
        raise ValueError("program v4 must bind E0 through E4 exactly once")
    if by_study["E2"].get("title_authority") is not True:
        raise ValueError("program v4 title authority must remain with objective E2")
    terminal = by_study["E3"].get("required_terminal_artifacts")
    if not isinstance(terminal, list) or set(terminal) != {
        "paper",
        "two-reviews",
        "revision",
        "final-disposition",
    }:
        raise ValueError("program v4 E3 must end in a reviewed and revised paper package")

    selection = program_payload.get("model_selection")
    if not isinstance(selection, dict):
        raise ValueError("program v4 lacks capability-driven model selection")
    downloads = selection.get("owner_download_authority")
    role_gates = selection.get("role_gates")
    if (
        selection.get("fixed_primary_model_id") is not None
        or selection.get("inventory_presence_selects_model") is not False
        or selection.get("qwen3_vl_2b_status") != "low-cost-lower-bound-only"
        or selection.get("qwen3_vl_2b_may_be_headline_default") is not False
        or not isinstance(downloads, dict)
        or downloads.get("automatic_single_resource_max_bytes") != 10 * 1024**3
        or not isinstance(role_gates, dict)
        or set(role_gates)
        != {
            "research_agent",
            "code_agent",
            "judge",
            "embedding",
            "task_training",
        }
    ):
        raise ValueError("program v4 model selection is not capability-driven and expandable")

    if program_id in {
        "scitaste-iclr2027-capability-driven-autoresearch-program-v7",
        "scitaste-iclr2027-capability-driven-autoresearch-program-v8",
        "scitaste-iclr2027-capability-driven-autoresearch-program-v9",
    }:
        if (
            selection.get("candidate_universe_authority")
            != "recent-related-work-and-idea-task-fit-first"
            or selection.get("available_inventory_role")
            != "execution-cost-optimization-only-after-scientific-fit"
        ):
            raise ValueError("program v7 must derive models from related work before inventory")
        model_strata = program_payload.get("model_strata")
        if not isinstance(model_strata, dict) or set(model_strata) != {
            "scientific_agent_models",
            "benchmark_task_models",
            "embedding_models",
        }:
            raise ValueError("program v7 must separate agent, task, and embedding models")
        task_models = model_strata.get("benchmark_task_models")
        if not isinstance(task_models, dict) or not str(
            task_models.get("separation_rule", "")
        ).startswith("Research-agent model selection and benchmark task-model selection"):
            raise ValueError("program v7 conflates scientific agents with benchmark task models")
        review_panel = program_payload.get("review_panel_contract")
        if (
            not isinstance(review_panel, dict)
            or review_panel.get("reviewer_count") != 2
            or review_panel.get("reviewers_must_be_identity_distinct") is not True
            or review_panel.get("reviewers_must_be_generator_disjoint") is not True
            or review_panel.get("adjudicator_required_on_disagreement") is not True
        ):
            raise ValueError("program v7 lacks the independent review and adjudication panel")
        realization = program_payload.get("workflow_realization")
        agent_loop = realization.get("agent_loop") if isinstance(realization, dict) else None
        if (
            not isinstance(realization, dict)
            or realization.get("actual_execution_required") is not True
            or realization.get("paper_only-or-simulated-results-count_as_complete") is not False
            or not isinstance(agent_loop, list)
            or len(agent_loop) < 18
        ):
            raise ValueError("program v7 does not realize the complete executable workflow")


def _compile_contract(
    *,
    project_id: str,
    program_payload: dict[str, object],
    program_bytes: bytes,
    inventory_payload: dict[str, object],
    inventory_bytes: bytes,
) -> ResearchProgramContract:
    source_schema_version = program_payload.get("schema_version")
    if source_schema_version not in {"3.0", "4.0"}:
        raise ValueError("complete research controller requires program schema 3.0 or 4.0")
    program_id = program_payload.get("program_id")
    if not isinstance(program_id, str):
        raise ValueError("experiment program_id is missing")
    lifecycle = program_payload.get("lifecycle_state_machine")
    if not isinstance(lifecycle, dict) or lifecycle.get("initial_state") != _PHASE_IDS[0]:
        raise ValueError("experiment program lacks the complete v3 lifecycle")
    raw_states = lifecycle.get("states")
    if not isinstance(raw_states, list) or len(raw_states) != len(_PHASE_IDS):
        raise ValueError("experiment program lifecycle state count is incomplete")
    phases: list[ResearchProgramPhaseContract] = []
    for expected_id, raw in zip(_PHASE_IDS, raw_states, strict=True):
        if not isinstance(raw, dict) or raw.get("state_id") != expected_id:
            raise ValueError("experiment program lifecycle order differs from complete v3")
        required = raw.get("required_artifacts")
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ValueError(f"phase {expected_id} lacks typed required artifacts")
        conditional = raw.get("conditional_next", {})
        if not isinstance(conditional, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in conditional.items()
        ):
            raise ValueError(f"phase {expected_id} has an invalid conditional transition")
        default_next = raw.get("next")
        if default_next is not None and not isinstance(default_next, str):
            raise ValueError(f"phase {expected_id} has an invalid next phase")
        interfaces, roles, authority, result_authority = _PHASE_METADATA[expected_id]
        phases.append(
            ResearchProgramPhaseContract(
                phase_id=expected_id,
                required_artifact_ids=tuple(required),
                default_next_phase_id=default_next,
                conditional_next=conditional,
                scitaste_interfaces=interfaces,
                resource_roles=roles,
                execution_authority=authority,
                accepted_semantic_validator_ids=_PHASE_SEMANTIC_VALIDATORS[expected_id],
                scientific_result_authority=result_authority,
            )
        )
    model_selection = program_payload.get("model_selection")
    if not isinstance(model_selection, dict) or (
        model_selection.get("selection_data") != "task-excluded-conformance-suite-only"
    ):
        raise ValueError("program model selection is not task-excluded")
    selection_policy = inventory_payload.get("selection_policy")
    if not isinstance(selection_policy, dict) or (
        selection_policy.get("required_gate") != "task-excluded-conformance"
    ):
        raise ValueError("model inventory does not require task-excluded conformance")
    inventory_id = inventory_payload.get("inventory_id")
    if not isinstance(inventory_id, str):
        raise ValueError("model inventory_id is missing")
    inventory_binding = program_payload.get("model_inventory_binding")
    if not isinstance(inventory_binding, dict) or (
        inventory_binding.get("inventory_id") != inventory_id
        or inventory_binding.get("inventory_file_sha256") != _bytes_sha256(inventory_bytes)
        or inventory_binding.get("inventory_presence_selects_model") is not False
    ):
        raise ValueError("experiment program does not bind the exact non-selecting model inventory")
    systems = program_payload.get("system_matrix")
    if not isinstance(systems, list):
        raise ValueError("experiment program system matrix is missing")
    blocked_systems = tuple(
        item["system_id"]
        for item in systems
        if isinstance(item, dict)
        and isinstance(item.get("system_id"), str)
        and str(item.get("current_status", "")).startswith("blocked-")
    )
    boundary = program_payload.get("scientific_boundaries")
    if (
        not isinstance(boundary, dict)
        or boundary.get("pseudo_implementation_of_blocked_system_allowed") is not False
    ):
        raise ValueError("program must forbid pseudo-implementation of blocked systems")
    if source_schema_version == "4.0":
        _validate_capability_driven_v4(program_payload)
    return ResearchProgramContract.create(
        project_id=project_id,
        program_id=program_id,
        source_program_id=program_id,
        source_program_schema_version=source_schema_version,
        source_program_locator="inputs/experiment_program.yaml",
        source_program_file_sha256=_bytes_sha256(program_bytes),
        model_inventory_id=inventory_id,
        model_inventory_locator="inputs/model_inventory.yaml",
        model_inventory_file_sha256=_bytes_sha256(inventory_bytes),
        model_selection_gate="task-excluded-conformance",
        phases=tuple(phases),
        blocked_external_system_ids=blocked_systems,
    )


def _completed_destination(
    phase_id: ResearchProgramPhaseId,
    default_next: ResearchProgramPhaseId | None,
    *,
    review_outcome: ReviewOutcome | None,
    revision_target: RevisionTarget | None,
) -> ResearchProgramPhaseId | None:
    if phase_id == "dual-ai-review":
        if review_outcome == "agreement":
            return "review-driven-revision"
        if review_outcome == "disagreement":
            return "ai-adjudication"
        raise ValueError("dual AI review requires --review-outcome agreement|disagreement")
    if phase_id == "final-ai-review-and-package-freeze":
        if review_outcome == "accepted":
            if revision_target is not None:
                raise ValueError("accepted final review cannot select a revision target")
            return "complete"
        if review_outcome == "revision_required":
            if revision_target is None:
                raise ValueError("revision_required must select an exact revision target")
            return revision_target
        raise ValueError("final AI review requires --review-outcome accepted|revision_required")
    if review_outcome is not None or revision_target is not None:
        raise ValueError("review routing options are valid only on review phases")
    return default_next


def _verify_transition_semantics(
    phase: ResearchProgramPhaseContract,
    transition: ResearchProgramTransition,
    final_review_accepted: bool,
) -> None:
    if transition.disposition is ResearchProgramTransitionDisposition.COMPLETED:
        if {item.artifact_id for item in transition.artifact_bindings} != set(
            phase.required_artifact_ids
        ):
            raise ValueError("completed transition does not bind every required phase artifact")
        expected_destination = _completed_destination(
            phase.phase_id,
            phase.default_next_phase_id,
            review_outcome=transition.review_outcome,
            revision_target=transition.revision_target,
        )
        if transition.to_phase_id != expected_destination:
            raise ValueError("completed transition destination differs from its phase contract")
        if not set(transition.semantic_validator_ids).issubset(
            phase.accepted_semantic_validator_ids
        ):
            raise ValueError("transition used a validator outside its phase contract")
        if phase.phase_id == "complete" and not final_review_accepted:
            raise ValueError("complete transition lacks an accepted final AI review")
    elif transition.to_phase_id != phase.phase_id:
        raise ValueError("non-completed transition must remain in its phase")


def _phase(
    contract: ResearchProgramContract,
    phase_id: ResearchProgramPhaseId,
) -> ResearchProgramPhaseContract:
    return next(item for item in contract.phases if item.phase_id == phase_id)


def _load_yaml_bytes(path: Path, label: str) -> tuple[bytes, dict[str, object]]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    raw = path.read_bytes()
    if not raw or len(raw) > 16 * 1024 * 1024:
        raise ValueError(f"{label} must be a bounded non-empty YAML file")
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root must be a mapping")
    return raw, payload


def _contained_regular_file(root: Path, locator: str) -> Path:
    validate_relative_locator(locator, field_name="contained file locator")
    root = root.resolve()
    candidate = root.joinpath(*PurePosixPath(locator).parts)
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlink is not allowed in bound artifact path: {locator}")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _read_bounded(path: Path, maximum_bytes: int) -> str:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    if path.stat().st_size > maximum_bytes:
        raise ValueError(f"research program file exceeds {maximum_bytes} bytes: {path}")
    return path.read_text(encoding="utf-8")


def _bytes_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bytes_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_exclusive(path: Path, value: BaseModel) -> None:
    _write_bytes_exclusive(path, (value.model_dump_json(indent=2) + "\n").encode("utf-8"))


def _atomic_json(path: Path, value: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = [
    "PhaseExecutionAuthority",
    "ResearchProgramArtifactBinding",
    "ResearchProgramB0ValidationReceipt",
    "ResearchProgramContract",
    "ResearchProgramLaunchPlan",
    "ResearchProgramPhaseContract",
    "ResearchProgramPhaseId",
    "ResearchProgramRunStatus",
    "ResearchProgramRuntime",
    "ResearchProgramState",
    "ResearchProgramStatus",
    "ResearchProgramTransition",
    "ResearchProgramTransitionDisposition",
    "ReviewOutcome",
    "RevisionTarget",
    "ScientificResultAuthority",
]

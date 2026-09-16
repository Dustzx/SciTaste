"""Prospective development trajectories for outcome-updated Scientific Taste.

This module is deliberately separate from the Native/Base causal protocol.  It
collects development-only decisions before execution, joins strictly later
scientific outcomes, and emits quarantined Taste episode candidates.  It never
admits an episode or updates a policy by itself.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.evaluation.h4_execution import build_h4_benchmark_action_menu
from scitaste.evaluation.interactive_research import (
    InteractiveAgentDecision,
    InteractiveAgentProposal,
    InteractiveGuidance,
    InteractiveGuidanceEnvelope,
    InteractiveResearchContext,
    InteractiveResearchRunReceipt,
    guidance_action_complied,
    load_interactive_research_run_receipt,
)
from scitaste.evaluation.research_workload import (
    ResearchWorkloadContract,
    ResearchWorkloadParadigm,
)
from scitaste.project.idea_revision import (
    ProjectIdeaRevisionBinding,
    idea_scientific_contract_sha256,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.project.runtime import ProjectRuntime
from scitaste.schema.actions import ResearchAction
from scitaste.state.research_state import (
    ExperimentPlan,
    ResearchStage,
    ResearchState,
    ResourceBudget,
    ResourceUsage,
)
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.episodes import (
    TasteCreditAssignment,
    TasteCreditDirection,
    TasteEpisodeCandidate,
    TasteEpisodeConfounder,
    TasteEpisodeDecisionContext,
    TasteEpisodeEvidence,
    TasteEpisodeEvidenceRole,
    TasteEpisodeOutcome,
    TasteOutcomeFamily,
    TasteOutcomePolarity,
)
from scitaste.taste.trajectory_reconstruction import (
    TasteProcessEpisodeProposal,
    TasteProcessEvidenceBinding,
    TasteProspectiveDecisionLockReceipt,
    TasteTrajectoryAssignmentTiming,
    TasteTrajectorySamplingPlan,
    attach_prospective_taste_outcome,
    compile_prospective_taste_episode_v2,
    load_taste_prospective_decision_lock,
    lock_prospective_taste_decision,
    save_taste_process_episode_proposal,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_ARTIFACT_BYTES = 64 * 1_048_576


class InteractiveTasteDevelopmentProtocol(BaseModel):
    """One source-disjoint task contract used only to grow development Taste."""

    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    protocol_id: str
    project_id: str
    benchmark_id: str
    workload_paradigm: Literal[ResearchWorkloadParadigm.TRAINING_FREE] = (
        ResearchWorkloadParadigm.TRAINING_FREE
    )
    workload_contract: ResearchWorkloadContract | None = None
    task_id: str
    source_group_id: str
    task_sha256: str = Field(pattern=_SHA256)
    environment_sha256: str | None = Field(default=None, pattern=_SHA256)
    toolbox_sha256: str = Field(pattern=_SHA256)
    target_domain: str
    target_venue: str = "ICLR 2027"
    primary_metric: str
    metric_direction: Literal["higher", "lower"]
    failure_primary_value: float = Field(allow_inf_nan=False)
    max_turns: int = Field(ge=1, le=20)
    max_experiments: int = Field(ge=1, le=1_000)
    source_identity_registry_sha256: str = Field(pattern=_SHA256)
    controller_backbone_sha256: str = Field(pattern=_SHA256)
    decision_provider: Literal["scitaste-native"] = "scitaste-native"
    decision_model: Literal["deterministic-utility-controller"] = "deterministic-utility-controller"
    prompt_version: str
    seed: int = Field(ge=0)
    condition_id: Literal["development-foundation"] = "development-foundation"
    resource_envelope_sha256: str = Field(pattern=_SHA256)
    research_agent_sha256: str = Field(pattern=_SHA256)
    tool_policy_sha256: str = Field(pattern=_SHA256)
    repair_policy_sha256: str = Field(pattern=_SHA256)
    executor_sha256: str = Field(pattern=_SHA256)
    idea_scientific_contract_sha256: str = Field(pattern=_SHA256)
    idea_revision_binding_sha256: str = Field(pattern=_SHA256)
    episode_sampling_rule: Literal[
        "all-compliant-turns",
        "earliest-executed-nonterminal-after-observation",
        "preassigned-action-stratum-v1",
    ] = "all-compliant-turns"
    maximum_episode_candidates: int = Field(default=20, ge=1, le=20)
    candidate_credit_projection: Literal[
        "shared-terminal-v1",
        "action-local-scientific-v4",
        "allocation-local-v5",
    ] = "shared-terminal-v1"
    episode_target_action: Literal["EXPERIMENT", "REFINE", "STOP"] | None = None
    episode_target_turn: int | None = Field(default=None, ge=2, le=20)
    protocol_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def protocol_is_closed(self) -> InteractiveTasteDevelopmentProtocol:
        validate_project_id(self.project_id)
        for value, label in (
            (self.protocol_id, "interactive development protocol_id"),
            (self.benchmark_id, "interactive development benchmark_id"),
            (self.task_id, "interactive development task_id"),
            (self.source_group_id, "interactive development source_group_id"),
        ):
            validate_entry_id(value, field_name=label)
        if self.workload_contract is not None and (
            self.workload_contract.paradigm is not ResearchWorkloadParadigm.TRAINING_FREE
            or self.workload_contract.task_id != self.task_id
        ):
            raise ValueError("interactive development workload differs from its T0 task")
        excluded = {"protocol_sha256"}
        if "workload_paradigm" not in self.model_fields_set:
            excluded.add("workload_paradigm")
        if "workload_contract" not in self.model_fields_set:
            excluded.add("workload_contract")
        if self.environment_sha256 is None:
            excluded.add("environment_sha256")
        sampling_fields = {
            "episode_sampling_rule",
            "maximum_episode_candidates",
            "candidate_credit_projection",
            "episode_target_action",
            "episode_target_turn",
        }
        if self.schema_version == "1.0":
            excluded.update(sampling_fields - self.model_fields_set)
        elif self.schema_version == "1.1":
            if (
                self.episode_sampling_rule
                != "earliest-executed-nonterminal-after-observation"
                or self.maximum_episode_candidates != 1
                or self.candidate_credit_projection != "action-local-scientific-v4"
                or self.episode_target_action is not None
                or self.episode_target_turn is not None
            ):
                raise ValueError(
                    "interactive development v1.1 requires one outcome-independent "
                    "post-observation action-local candidate"
                )
        elif (
            self.episode_sampling_rule != "preassigned-action-stratum-v1"
            or self.maximum_episode_candidates != 1
            or self.candidate_credit_projection != "allocation-local-v5"
            or self.episode_target_action is None
            or (
                self.episode_target_action == "STOP"
                and self.episode_target_turn is not None
            )
            or (
                self.episode_target_action != "STOP"
                and self.episode_target_turn is None
            )
        ):
            raise ValueError(
                "interactive development v1.2 requires one prospectively assigned "
                "allocation-local action stratum"
            )
        expected = content_sha256(self.model_dump(mode="json", exclude=excluded))
        if self.protocol_sha256 != expected:
            raise ValueError("interactive development protocol hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> InteractiveTasteDevelopmentProtocol:
        workload_contract = values.get("workload_contract")
        if workload_contract is None:
            workload_contract = ResearchWorkloadContract.create(
                contract_id=f"{values['protocol_id']}-workload",
                task_id=str(values["task_id"]),
                paradigm=ResearchWorkloadParadigm.TRAINING_FREE,
                task_model_weight_updates=False,
                candidate_checkpoint_required=False,
            )
        payload = {
            "schema_version": "1.0",
            "workload_paradigm": ResearchWorkloadParadigm.TRAINING_FREE,
            **values,
            "workload_contract": workload_contract,
        }
        payload.pop("protocol_sha256", None)
        excluded = {"protocol_sha256"}
        if payload["schema_version"] == "1.0":
            excluded.update(
                {
                    "episode_sampling_rule",
                    "maximum_episode_candidates",
                    "candidate_credit_projection",
                    "episode_target_action",
                    "episode_target_turn",
                }
                - values.keys()
            )
        unsigned = cls.model_construct(protocol_sha256="0" * 64, **payload)
        return cls(
            **payload,
            protocol_sha256=content_sha256(unsigned.model_dump(mode="json", exclude=excluded)),
        )


class InteractiveDevelopmentEpisodeItem(BaseModel):
    model_config = _CONFIG

    turn: int = Field(ge=1)
    lock_sha256: str = Field(pattern=_SHA256)
    attachment_sha256: str = Field(pattern=_SHA256)
    projection_sha256: str = Field(pattern=_SHA256)
    proposal_sha256: str = Field(pattern=_SHA256)
    candidate_id: str
    candidate_sha256: str = Field(pattern=_SHA256)
    lock_locator: str
    attachment_locator: str
    projection_locator: str
    proposal_locator: str
    candidate_locator: str


class InteractiveDevelopmentEpisodeBatch(BaseModel):
    """Quarantined projection; independent review remains mandatory."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    batch_id: str
    project_id: str
    run_id: str
    task_id: str
    source_group_id: str
    protocol_sha256: str = Field(pattern=_SHA256)
    sampling_plan_sha256: str = Field(pattern=_SHA256)
    receipt_sha256: str = Field(pattern=_SHA256)
    items: tuple[InteractiveDevelopmentEpisodeItem, ...]
    independent_attribution_review_required: Literal[True] = True
    policy_update_authorized: Literal[False] = False
    formal_evidence: Literal[False] = False
    batch_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def batch_is_closed(self) -> InteractiveDevelopmentEpisodeBatch:
        validate_project_id(self.project_id)
        validate_entry_id(self.batch_id, field_name="interactive development batch_id")
        validate_entry_id(self.run_id, field_name="interactive development run_id")
        turns = [item.turn for item in self.items]
        if turns != sorted(set(turns)):
            raise ValueError("interactive development batch turns must be sorted and unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"batch_sha256"}))
        if self.batch_sha256 != expected:
            raise ValueError("interactive development batch hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> InteractiveDevelopmentEpisodeBatch:
        payload = {"schema_version": "1.0", **values}
        payload.pop("batch_sha256", None)
        unsigned = cls.model_construct(batch_sha256="0" * 64, **payload)
        return cls(
            **payload,
            batch_sha256=content_sha256(unsigned.model_dump(mode="json", exclude={"batch_sha256"})),
        )


class DevelopmentTasteGuidanceProvider:
    """Lock no-policy controller decisions before an interactive tool can run."""

    def __init__(
        self,
        protocol: InteractiveTasteDevelopmentProtocol,
        controller: TasteController,
        *,
        sampling_plan: TasteTrajectorySamplingPlan,
        runtime: ProjectRuntime,
        current_idea_revision: ProjectIdeaRevisionBinding,
        expected_project_revision: int,
        lock_root: str | Path,
    ) -> None:
        if controller.mode is not TasteMode.INTRINSIC:
            raise ValueError("development foundation requires intrinsic Taste mode")
        if (
            controller.lifecycle_policy is not None
            or controller.family_conditioned_policy is not None
        ):
            raise ValueError("development foundation must precede lifecycle-policy fitting")
        if controller.preference_backend is not None:
            raise ValueError("development foundation cannot add a preference model")
        if controller.candidate_generation_backend is not None:
            raise ValueError("development foundation requires a fixed action menu")
        if controller.critics_enabled:
            raise ValueError("development foundation requires the fixed critic-free backbone")
        if controller.intervention_backbone_sha256 != protocol.controller_backbone_sha256:
            raise ValueError("development controller backbone differs from protocol")
        if controller.preference_prompt_version != protocol.prompt_version:
            raise ValueError("development controller prompt version differs from protocol")
        if controller.seed != protocol.seed:
            raise ValueError("development controller seed differs from protocol")
        if sampling_plan.assignment_timing is not TasteTrajectoryAssignmentTiming.PROSPECTIVE:
            raise ValueError("interactive development requires a prospective sampling plan")
        if not sampling_plan.source_absent_when_frozen:
            raise ValueError("interactive development plan must predate its decisions")
        if sampling_plan.project_id != protocol.project_id:
            raise ValueError("interactive development plan belongs to another project")
        if sampling_plan.source_group_id != protocol.source_group_id:
            raise ValueError("interactive development source group differs from protocol")
        if sampling_plan.observed_project_revision != expected_project_revision:
            raise ValueError("interactive development plan revision differs")
        if (
            current_idea_revision.binding_sha256 != protocol.idea_revision_binding_sha256
            or idea_scientific_contract_sha256(current_idea_revision)
            != protocol.idea_scientific_contract_sha256
        ):
            raise ValueError("interactive development protocol and current Idea differ")
        snapshot = runtime.open(protocol.project_id)
        if snapshot.revision != expected_project_revision:
            raise ValueError("interactive development project revision drifted")
        run_root = (
            runtime.projects_root / protocol.project_id / "runs" / sampling_plan.source_run_id
        )
        resolved_lock_root = Path(lock_root).expanduser().resolve()
        if not resolved_lock_root.is_relative_to(run_root.resolve()):
            raise ValueError("interactive development lock root escapes its project run")
        self.protocol = protocol
        self.controller = controller
        self.sampling_plan = sampling_plan
        self.runtime = runtime
        self.current_idea_revision = current_idea_revision
        self.expected_project_revision = expected_project_revision
        self.lock_root = resolved_lock_root
        self._locks: list[TasteProspectiveDecisionLockReceipt] = []
        self._lock_paths: list[Path] = []

    @property
    def locks(self) -> tuple[TasteProspectiveDecisionLockReceipt, ...]:
        return tuple(self._locks)

    @property
    def lock_paths(self) -> tuple[Path, ...]:
        """Return the effective lock for each turn, including accepted stop requests."""

        return tuple(self._lock_paths)

    def guide(self, context: InteractiveResearchContext) -> InteractiveGuidanceEnvelope:
        self._validate_context(context)
        used_experiments = self.protocol.max_experiments - context.remaining_experiments
        state = _interactive_state(
            context,
            max_experiments=self.protocol.max_experiments,
            used_experiments=used_experiments,
            target_domain=self.protocol.target_domain,
            target_venue=self.protocol.target_venue,
        )
        actions, preferred_action_type = _development_bootstrap_actions(context)
        decision = self.controller.decide(
            state=state,
            candidate_actions=actions,
            current_idea_revision=self.current_idea_revision,
        )
        if decision.selected_action.type.value != preferred_action_type:
            raise ValueError("development bootstrap policy did not select its intended action")
        selected = decision.selected_action
        instruction = (
            "Stop experimentation and submit the strongest currently supported hypothesis."
            if selected.type.value == "STOP"
            else selected.description
        )
        target_turn = self.protocol.episode_target_turn
        if (
            self.protocol.episode_sampling_rule == "preassigned-action-stratum-v1"
            and self.protocol.episode_target_action != "STOP"
            and target_turn is not None
            and context.turn <= target_turn
        ):
            instruction = (
                f"{instruction} This prospective development cohort requires the locked "
                f"{self.protocol.episode_target_action} allocation at turn {target_turn} to "
                "be executed before submission; do not submit a hypothesis on this turn."
            )
        guidance = InteractiveGuidance(
            action_id=selected.action_id,
            action_type=selected.type.value,
            instruction=instruction,
            decision_sha256=content_sha256(selected),
        )
        lock_path = self.lock_root / f"turn-{context.turn:03d}" / "LOCK.json"
        lock = lock_prospective_taste_decision(
            self.sampling_plan,
            runtime=self.runtime,
            state=state,
            decision=decision,
            current_idea_revision=self.current_idea_revision,
            expected_project_revision=self.expected_project_revision,
            output=lock_path,
        )
        self._locks.append(lock)
        self._lock_paths.append(lock_path)
        return InteractiveGuidanceEnvelope.create(
            guidance=guidance,
            audit={
                "schema_version": "1.0",
                "development_only": True,
                "protocol_sha256": self.protocol.protocol_sha256,
                "sampling_plan_sha256": self.sampling_plan.plan_sha256,
                "prospective_lock_sha256": lock.lock_sha256,
                "controller_decision": decision.model_dump(mode="json"),
            },
        )

    def adjudicate_submission(
        self,
        context: InteractiveResearchContext,
        initial_guidance: InteractiveGuidanceEnvelope,
        decision: InteractiveAgentDecision,
    ) -> InteractiveGuidanceEnvelope:
        """Approve only a structured, evidence-covered request to stop early."""

        self._validate_submission_adjudication_context(context, initial_guidance)
        target_turn = self.protocol.episode_target_turn
        if (
            self.protocol.episode_sampling_rule == "preassigned-action-stratum-v1"
            and self.protocol.episode_target_action != "STOP"
            and target_turn is not None
            and context.turn <= target_turn
        ):
            return InteractiveGuidanceEnvelope.create(
                guidance=initial_guidance.guidance,
                audit={
                    **initial_guidance.audit,
                    "submission_adjudication": {
                        "approved": False,
                        "reason": "prospective-target-action-not-yet-executed",
                        "target_action": self.protocol.episode_target_action,
                        "target_turn": target_turn,
                    },
                    "agent_decision_sha256": decision.decision_sha256,
                },
            )
        gate = _development_submission_stop_gate(context, decision.proposal)
        if not gate["approved"]:
            return initial_guidance
        state = _interactive_state(
            context,
            max_experiments=self.protocol.max_experiments,
            used_experiments=self.protocol.max_experiments - context.remaining_experiments,
            target_domain=self.protocol.target_domain,
            target_venue=self.protocol.target_venue,
        )
        actions, preferred_action_type = _development_bootstrap_actions(
            context,
            preferred_override="STOP",
        )
        stop_decision = self.controller.decide(
            state=state,
            candidate_actions=actions,
            current_idea_revision=self.current_idea_revision,
        )
        if stop_decision.selected_action.type.value != preferred_action_type:
            raise ValueError("development stop adjudication did not select STOP")
        selected = stop_decision.selected_action
        lock_path = self.lock_root / f"turn-{context.turn:03d}-stop-request" / "LOCK.json"
        lock = lock_prospective_taste_decision(
            self.sampling_plan,
            runtime=self.runtime,
            state=state,
            decision=stop_decision,
            current_idea_revision=self.current_idea_revision,
            expected_project_revision=self.expected_project_revision,
            output=lock_path,
        )
        initial_lock = self._locks[-1]
        self._locks[-1] = lock
        self._lock_paths[-1] = lock_path
        guidance = InteractiveGuidance(
            action_id=selected.action_id,
            action_type="STOP",
            instruction="Submit the strongest currently supported hypothesis.",
            decision_sha256=content_sha256(selected),
        )
        return InteractiveGuidanceEnvelope.create(
            guidance=guidance,
            audit={
                "schema_version": "1.0",
                "development_only": True,
                "protocol_sha256": self.protocol.protocol_sha256,
                "sampling_plan_sha256": self.sampling_plan.plan_sha256,
                "submission_adjudication": gate,
                "agent_decision_sha256": decision.decision_sha256,
                "agent_visible_guidance": initial_guidance.model_dump(mode="json"),
                "initial_prospective_lock_sha256": initial_lock.lock_sha256,
                "effective_prospective_lock_sha256": lock.lock_sha256,
                "controller_decision": stop_decision.model_dump(mode="json"),
            },
        )

    def _validate_submission_adjudication_context(
        self,
        context: InteractiveResearchContext,
        initial_guidance: InteractiveGuidanceEnvelope,
    ) -> None:
        if context.turn != len(self._locks):
            raise ValueError("submission adjudication must follow the current turn lock")
        current_lock = self._locks[-1]
        if current_lock.selected_action_id != initial_guidance.guidance.action_id:
            raise ValueError("submission adjudication guidance differs from its initial lock")
        if initial_guidance.guidance.action_type == "STOP":
            raise ValueError("an existing STOP decision cannot request stop adjudication")

    def _validate_context(self, context: InteractiveResearchContext) -> None:
        if context.project_id != self.protocol.project_id:
            raise ValueError("interactive development context belongs to another project")
        if context.run_id != self.sampling_plan.source_run_id:
            raise ValueError("interactive development run differs from sampling plan")
        if context.condition_id != self.protocol.condition_id:
            raise ValueError("interactive development condition differs from protocol")
        for observed, expected, label in (
            (context.task_id, self.protocol.task_id, "task"),
            (context.task_sha256, self.protocol.task_sha256, "task content"),
            (context.toolbox_sha256, self.protocol.toolbox_sha256, "toolbox"),
            (
                context.resource_envelope_sha256,
                self.protocol.resource_envelope_sha256,
                "resource envelope",
            ),
            (
                context.research_agent_sha256,
                self.protocol.research_agent_sha256,
                "research agent",
            ),
        ):
            if observed != expected:
                raise ValueError(f"interactive development {label} differs from protocol")
        if (
            self.protocol.environment_sha256 is not None
            and context.environment_sha256 != self.protocol.environment_sha256
        ):
            raise ValueError("interactive development hidden environment differs from protocol")
        if context.turn == 1 and context.remaining_turns != self.protocol.max_turns:
            raise ValueError("interactive development turn budget differs from protocol")
        if context.turn == 1 and context.remaining_experiments != self.protocol.max_experiments:
            raise ValueError("interactive development experiment budget differs from protocol")
        if context.turn != len(self._locks) + 1:
            raise ValueError("interactive development decisions must be locked in turn order")


def finalize_interactive_development_episodes(
    protocol: InteractiveTasteDevelopmentProtocol,
    sampling_plan: TasteTrajectorySamplingPlan,
    *,
    runtime: ProjectRuntime,
    current_idea_revision: ProjectIdeaRevisionBinding,
    expected_project_revision: int,
    lock_paths: tuple[str | Path, ...],
    receipt_path: str | Path,
    output_root: str | Path,
    curated_turn: int | None = None,
    historical_source_projection: bool = False,
    curated_credit_projection: Literal[
        "action-local-scientific-v4",
        "allocation-local-v5",
    ]
    | None = None,
) -> InteractiveDevelopmentEpisodeBatch:
    """Join delayed run evidence without granting review or policy authority."""

    receipt = load_interactive_research_run_receipt(receipt_path)
    if (
        receipt.project_id != protocol.project_id
        or receipt.run_id != sampling_plan.source_run_id
        or receipt.task_id != protocol.task_id
        or receipt.condition_id != protocol.condition_id
    ):
        raise ValueError("interactive development receipt differs from frozen protocol")
    if len(lock_paths) != len(receipt.turns):
        raise ValueError("interactive development lock coverage differs from executed turns")
    run_root = (
        runtime.projects_root / protocol.project_id / "runs" / sampling_plan.source_run_id
    ).resolve()
    receipt_source = Path(receipt_path).expanduser().resolve()
    if not receipt_source.is_relative_to(run_root):
        raise ValueError("interactive development receipt escapes its project run")
    receipt_locator = receipt_source.relative_to(run_root).as_posix()
    root = Path(output_root).expanduser().resolve()
    if not root.is_relative_to(run_root):
        raise ValueError("interactive development episode output escapes its project run")

    observed_at = datetime.now(UTC)
    actual_outcome = {
        "schema_version": "1.0",
        "run_status": receipt.status,
        "task_id": receipt.task_id,
        "environment_sha256": receipt.environment_sha256,
        "experiment_count": receipt.experiment_count,
        "code_call_count": receipt.code_call_count,
        "objective_score": (
            receipt.objective_score.model_dump(mode="json")
            if receipt.objective_score is not None
            else None
        ),
        "terminal_error": receipt.terminal_error,
        "receipt_sha256": receipt.receipt_sha256,
    }
    if curated_turn is None:
        selected_lock_paths = _selected_development_lock_paths(protocol, receipt, lock_paths)
    else:
        if not historical_source_projection:
            raise ValueError("curated turn requires an explicit historical source projection")
        if not 1 <= curated_turn <= len(receipt.turns):
            raise ValueError("curated turn is absent from the terminal receipt")
        selected_lock_paths = (lock_paths[curated_turn - 1],)
    if curated_credit_projection is not None and curated_turn is None:
        raise ValueError("curated credit projection requires an explicit curated turn")
    items: list[InteractiveDevelopmentEpisodeItem] = []
    for lock_path in selected_lock_paths:
        lock_source = Path(lock_path).expanduser().resolve()
        if not lock_source.is_relative_to(run_root):
            raise ValueError("interactive development lock escapes its project run")
        lock = load_taste_prospective_decision_lock(lock_source)
        turn = _lock_turn(lock)
        record = receipt.turns[turn - 1]
        if not guidance_action_complied(
            record.guidance.guidance.action_type,
            record.decision.proposal.action,
        ):
            # The lock and terminal receipt remain immutable audit evidence, but
            # a model action that ignored the controller cannot become a Taste
            # supervision candidate even before independent review.
            continue
        turn_root = root / f"turn-{turn:03d}"
        attachment_path = turn_root / "OUTCOME_ATTACHMENT.json"
        projection_path = turn_root / "COMPLETED_DECISION.json"
        attachment, projection = attach_prospective_taste_outcome(
            sampling_plan,
            lock,
            source_root=run_root,
            executor_result_id=f"interactive-receipt-{receipt.receipt_sha256}",
            observed_at=observed_at,
            actual_outcome=actual_outcome,
            evidence=(
                TasteProcessEvidenceBinding(
                    evidence_id="outcome-receipt",
                    role=TasteEpisodeEvidenceRole.OUTCOME,
                    locator=receipt_locator,
                ),
            ),
            output=attachment_path,
            projection_output=projection_path,
        )
        state_path = run_root / PurePosixPath(lock.state_snapshot_locator)
        state = ResearchState.model_validate_json(_bounded_file(state_path))
        polarity = _outcome_polarity(protocol, receipt)
        outcome_family = TasteOutcomeFamily.DESIGN if turn == 1 else TasteOutcomeFamily.ADAPTATION
        outcome_id = f"interactive-terminal-{turn:03d}"
        credit_id = f"interactive-credit-{turn:03d}"
        proposal = TasteProcessEpisodeProposal.create(
            proposal_id=f"{sampling_plan.source_run_id}-proposal-{turn:03d}",
            plan_id=sampling_plan.plan_id,
            plan_sha256=sampling_plan.plan_sha256,
            capture_sha256=attachment.attachment_sha256,
            inventory_sha256=projection.projection_sha256,
            decision_id=lock.decision_id,
            candidate_id=f"{sampling_plan.source_run_id}-turn-{turn:03d}",
            producer_id="interactive-outcome-projection-v1",
            observed_at=attachment.observed_at,
            state_summary=(
                f"Outcome-blind turn {turn} on {protocol.task_id}; remaining experiments "
                f"were {state.executor_context.get('remaining_experiments', 'unknown')} and "
                f"the preceding history hash was "
                f"{state.executor_context.get('interactive_history_sha256', 'unknown')}."
            ),
            decision_context=TasteEpisodeDecisionContext(
                remaining_experiments=_remaining_experiment_bucket(
                    protocol.max_experiments - int(state.resource_usage.experiments)
                ),
                failure_count="zero",
                no_improvement_streak="zero",
                score_trend="unknown",
                best_vs_baseline="unknown",
            ),
            decision_principle=projection.completed_decision.rationale,
            why_preferred=(
                "The frozen controller selected this high-level research action before the "
                "agent acted or the terminal scientific score was observed."
            ),
            outcomes=(
                TasteEpisodeOutcome(
                    outcome_id=outcome_id,
                    family=outcome_family,
                    summary=_outcome_summary(receipt),
                    horizon="terminal hidden-objective score after the complete bounded trajectory",
                    polarity=polarity,
                    evidence_ids=("outcome-receipt",),
                ),
            ),
            credit_assignments=(
                TasteCreditAssignment(
                    credit_id=credit_id,
                    family=outcome_family,
                    direction=TasteCreditDirection.MIXED,
                    outcome_ids=(outcome_id,),
                    confounder_ids=("research-agent", "shared-terminal-outcome"),
                    rationale=(
                        "The selected action temporally preceded the terminal result, but the "
                        "result also reflects the frozen research model, later turns, and task. "
                        "This is a reviewable attribution hypothesis, not causal credit."
                    ),
                    confidence=0.5,
                ),
            ),
            applicability_conditions=(
                "interactive hidden-law research with a fixed high-level action menu",
                "the same current SciTaste Idea and frozen research-model identity",
            ),
            failure_conditions=(
                "the terminal score is not attributable to this turn-level action",
                "the task or model distribution differs materially from development",
            ),
            counterfactual_probe=(
                "Under the same predecision state and resource envelope, would another fixed "
                "high-level action have yielded a better terminal hidden-objective score?"
            ),
            evidence=(
                TasteProcessEvidenceBinding(
                    evidence_id="locked-decision",
                    role=TasteEpisodeEvidenceRole.DECISION,
                    locator=lock.immutable_decision_locator,
                ),
                TasteProcessEvidenceBinding(
                    evidence_id="locked-state",
                    role=TasteEpisodeEvidenceRole.DECISION_STATE,
                    locator=lock.state_snapshot_locator,
                ),
                TasteProcessEvidenceBinding(
                    evidence_id="outcome-receipt",
                    role=TasteEpisodeEvidenceRole.OUTCOME,
                    locator=receipt_locator,
                ),
            ),
            domain_tags=(protocol.target_domain, "newtonbench"),
            venue_tags=(protocol.target_venue,),
            confounders=(
                TasteEpisodeConfounder(
                    confounder_id="research-agent",
                    description=(
                        "The terminal result depends on the frozen research agent and symbolic "
                        "judge as well as the controller action."
                    ),
                    resolution="controlled",
                ),
                TasteEpisodeConfounder(
                    confounder_id="shared-terminal-outcome",
                    description=(
                        "Every turn in one trajectory shares the same terminal outcome, so turns "
                        "are not independent policy-training units."
                    ),
                    resolution="partially-controlled",
                ),
            ),
            missing_evidence_questions=(
                "Independent reviewers must decide whether this action deserves beneficial, "
                "harmful, or no credit.",
            ),
        )
        proposal_path = turn_root / "EPISODE_PROPOSAL.json"
        candidate_path = turn_root / "EPISODE_CANDIDATE.json"
        save_taste_process_episode_proposal(proposal, proposal_path)
        candidate = compile_prospective_taste_episode_v2(
            sampling_plan,
            lock,
            attachment,
            projection,
            proposal,
            runtime=runtime,
            current_idea_revision=current_idea_revision,
            expected_project_revision=expected_project_revision,
            output=candidate_path,
            historical_source_projection=historical_source_projection,
        )
        credit_projection = curated_credit_projection or protocol.candidate_credit_projection
        record = receipt.turns[turn - 1]
        action_local_evidence_available = (
            _candidate_has_observed_successor(receipt, turn)
            or record.decision.proposal.action == "submit_hypothesis"
        )
        if credit_projection in {"action-local-scientific-v4", "allocation-local-v5"} and (
            action_local_evidence_available
        ):
            refinement = (
                refine_interactive_allocation_candidate
                if credit_projection == "allocation-local-v5"
                else refine_interactive_development_candidate
            )
            candidate = refinement(candidate, receipt, turn=turn)
            candidate_path = turn_root / (
                "ALLOCATION_CREDIT_CANDIDATE.json"
                if credit_projection == "allocation-local-v5"
                else "SCIENTIFIC_CREDIT_CANDIDATE.json"
            )
            _write_new_json(candidate_path, candidate.model_dump_json(indent=2) + "\n")
        items.append(
            InteractiveDevelopmentEpisodeItem(
                turn=turn,
                lock_sha256=lock.lock_sha256,
                attachment_sha256=attachment.attachment_sha256,
                projection_sha256=projection.projection_sha256,
                proposal_sha256=proposal.proposal_sha256,
                candidate_id=candidate.candidate_id,
                candidate_sha256=candidate.candidate_sha256,
                lock_locator=lock_source.relative_to(run_root).as_posix(),
                attachment_locator=attachment_path.relative_to(run_root).as_posix(),
                projection_locator=projection_path.relative_to(run_root).as_posix(),
                proposal_locator=proposal_path.relative_to(run_root).as_posix(),
                candidate_locator=candidate_path.relative_to(run_root).as_posix(),
            )
        )
    batch = InteractiveDevelopmentEpisodeBatch.create(
        batch_id=(
            f"{sampling_plan.source_run_id}-episodes-v1"
            if curated_turn is None
            else f"{sampling_plan.source_run_id}-curated-turn-{curated_turn:03d}-v1"
        ),
        project_id=protocol.project_id,
        run_id=sampling_plan.source_run_id,
        task_id=protocol.task_id,
        source_group_id=protocol.source_group_id,
        protocol_sha256=protocol.protocol_sha256,
        sampling_plan_sha256=sampling_plan.plan_sha256,
        receipt_sha256=receipt.receipt_sha256,
        items=tuple(sorted(items, key=lambda item: item.turn)),
    )
    _write_new_json(root / "BATCH.json", batch.model_dump_json(indent=2) + "\n")
    return batch


def _selected_development_lock_paths(
    protocol: InteractiveTasteDevelopmentProtocol,
    receipt: InteractiveResearchRunReceipt,
    lock_paths: tuple[str | Path, ...],
) -> tuple[str | Path, ...]:
    """Apply the frozen sampling rule without inspecting terminal score or credit."""

    if protocol.episode_sampling_rule == "all-compliant-turns":
        return lock_paths[: protocol.maximum_episode_candidates]
    if protocol.episode_sampling_rule == "preassigned-action-stratum-v1":
        target_action = protocol.episode_target_action
        target_turn = protocol.episode_target_turn
        if target_action is None:
            raise ValueError("preassigned development sampling lacks an action stratum")
        for index, record in enumerate(receipt.turns):
            if record.turn != index + 1:
                raise ValueError("interactive development receipt turns are not contiguous")
            prior_observation_exists = any(
                prior.observation is not None for prior in receipt.turns[:index]
            )
            if not prior_observation_exists:
                continue
            if target_action == "STOP":
                action_matches = record.guidance.guidance.action_type == "STOP"
            else:
                action_matches = (
                    record.turn == target_turn
                    and record.guidance.guidance.action_type == target_action
                )
            if not action_matches or not guidance_action_complied(
                record.guidance.guidance.action_type,
                record.decision.proposal.action,
            ):
                continue
            local_evidence_available = (
                record.decision.proposal.action == "submit_hypothesis"
                or (
                    record.observation is not None
                    and index + 1 < len(receipt.turns)
                )
            )
            if local_evidence_available:
                return (lock_paths[index],)
            if target_action != "STOP" and record.turn == target_turn:
                return ()
        return ()
    for index, record in enumerate(receipt.turns):
        if record.turn != index + 1:
            raise ValueError("interactive development receipt turns are not contiguous")
        prior_observation_exists = any(
            prior.observation is not None for prior in receipt.turns[:index]
        )
        if not prior_observation_exists:
            continue
        action_type = record.guidance.guidance.action_type
        if action_type == "STOP":
            continue
        if not guidance_action_complied(action_type, record.decision.proposal.action):
            continue
        if record.observation is None:
            continue
        return (lock_paths[index],)
    return ()


def _candidate_has_observed_successor(
    receipt: InteractiveResearchRunReceipt,
    turn: int,
) -> bool:
    return turn < len(receipt.turns) and receipt.turns[turn].turn == turn + 1


def refine_interactive_development_candidate(
    candidate: TasteEpisodeCandidate,
    receipt: InteractiveResearchRunReceipt,
    *,
    turn: int,
    outcome_evidence: TasteEpisodeEvidence | None = None,
) -> TasteEpisodeCandidate:
    """Replace shared terminal credit with evidence-bound local scientific credit.

    The prospective decision and its immutable evidence are unchanged.  This
    refinement only proposes a narrower attribution target: compliant action,
    immediate observation, and the successor belief update.  Independent
    reviewers still decide whether the proposed credit is admissible.
    """

    if candidate.channel.value != "internal-outcome":
        raise ValueError("interactive credit refinement requires an internal outcome")
    if candidate.source_project_id != receipt.project_id:
        raise ValueError("interactive candidate and receipt belong to different projects")
    if not 1 <= turn <= len(receipt.turns):
        raise ValueError("interactive credit turn is absent from the receipt")
    record = receipt.turns[turn - 1]
    if record.turn != turn:
        raise ValueError("interactive receipt turns are not contiguous")
    if record.guidance.guidance.action_id != candidate.selected_action_id:
        raise ValueError("interactive candidate differs from the locked guidance")
    controller = record.guidance.audit.get("controller_decision")
    if not isinstance(controller, dict) or controller.get("decision_id") != candidate.decision_id:
        raise ValueError("interactive candidate differs from the locked controller decision")

    action_type = record.guidance.guidance.action_type
    model_action = record.decision.proposal.action
    if not guidance_action_complied(action_type, model_action):
        raise ValueError("research-agent action did not comply with the locked Taste action")
    if model_action in {"run_experiments", "run_code"} and record.observation is None:
        raise ValueError("compliant scientific action has no retained observation")
    successor = receipt.turns[turn] if turn < len(receipt.turns) else None
    if model_action != "submit_hypothesis" and successor is None:
        raise ValueError("nonterminal scientific action has no observed successor update")

    review_evidence = candidate.evidence
    if outcome_evidence is not None:
        if outcome_evidence.role is not TasteEpisodeEvidenceRole.OUTCOME:
            raise ValueError("scientific credit outcome projection must have outcome role")
        review_evidence = (
            *(
                item
                for item in candidate.evidence
                if item.role is not TasteEpisodeEvidenceRole.OUTCOME
            ),
            outcome_evidence,
        )
    outcome_evidence_ids = tuple(
        item.evidence_id
        for item in review_evidence
        if item.role is TasteEpisodeEvidenceRole.OUTCOME
    )
    if not outcome_evidence_ids:
        raise ValueError("interactive candidate has no terminal receipt evidence")
    observation_sha256 = record.observation_sha256 or "none"
    is_submission = model_action == "submit_hypothesis"
    successor_summary = (
        "The action submitted the terminal hypothesis."
        if successor is None
        else (
            f"The next model action was {successor.decision.proposal.action!r}; its rationale "
            f"was: {_bounded_summary(successor.decision.proposal.rationale, 2_000)}"
        )
    )
    terminal_summary = _outcome_summary(receipt)
    local_polarity, credit_direction = _scientific_credit_orientation(
        receipt,
        is_submission=is_submission,
    )
    outcome_id = f"interactive-local-scientific-progress-{turn:03d}"
    credit_id = f"interactive-local-credit-{turn:03d}"
    state_summary = (
        f"Prospectively adjudicated turn {turn}; the controller approved STOP from the "
        "structured evidence-state and coverage gate before the research agent submission "
        "was scored."
        if is_submission
        else (
            f"Prospectively locked turn {turn}; the research agent complied with "
            f"{action_type} via {model_action}, and the resulting observation was retained."
        )
    )
    why_preferred = (
        "The effective STOP lock preceded scorer access, preserved the remaining experiment "
        "budget, and permitted only the already-proposed hypothesis to be evaluated."
        if is_submission
        else (
            f"The locked action was executed rather than merely narrated. Its immediate "
            f"observation hash is {observation_sha256}. {successor_summary}"
        )
    )
    outcome_summary = (
        "The evidence-backed STOP request was prospectively approved; the submitted hypothesis "
        f"then received the retained objective result. {terminal_summary}"
        if is_submission
        else (
            f"Compliant {model_action} produced observation {observation_sha256}. "
            f"{successor_summary} {terminal_summary}"
        )
    )
    credit_confounder_ids = (
        ("research-agent", "objective-scorer")
        if is_submission
        else ("research-agent", "later-trajectory-decisions")
    )
    successful_submission = (
        is_submission
        and receipt.status == "completed"
        and receipt.objective_score is not None
        and receipt.objective_score.primary_value > 0
    )
    credit_rationale = (
        (
            "Proposed benefit is limited to approving a supported stop before scoring and "
            "avoiding additional experiments whose declared marginal information value passed "
            "the frozen gate. It does not attribute hypothesis discovery or scorer correctness "
            "to the controller."
            if successful_submission
            else (
                "Proposed harm is limited to approving STOP before the retained objective scorer "
                "rejected the submitted hypothesis. It does not attribute hypothesis formation "
                "or scorer behavior to the controller, and it remains a reviewable attribution "
                "rather than established causal blame."
            )
        )
        if is_submission
        else (
            "Proposed benefit is limited to producing the retained observation and enabling the "
            "documented successor update. It does not assign the shared terminal score to this "
            "turn or claim that later decisions were caused by the controller alone."
        )
    )
    applicability_primary = (
        "interactive work with a prospectively approved evidence-backed stop request"
        if is_submission
        else "interactive work with an executable action and retained observation"
    )
    payload = {
        name: getattr(candidate, name)
        for name in type(candidate).model_fields
        if name != "candidate_sha256"
    }
    payload.update(
        {
            "candidate_id": f"{candidate.candidate_id}-scientific-credit-v4",
            "attribution_producer_id": "interactive-scientific-credit-v4",
            "evidence": review_evidence,
            "state_summary": state_summary,
            "why_preferred": why_preferred,
            "outcomes": (
                TasteEpisodeOutcome(
                    outcome_id=outcome_id,
                    family=(
                        TasteOutcomeFamily.DESIGN if turn == 1 else TasteOutcomeFamily.ADAPTATION
                    ),
                    summary=outcome_summary,
                    horizon=(
                        "stop adjudication, objective scoring, and conserved experiment budget"
                        if is_submission
                        else ("immediate observation, successor belief update, and terminal score")
                    ),
                    polarity=local_polarity,
                    evidence_ids=outcome_evidence_ids,
                ),
            ),
            "credit_assignments": (
                TasteCreditAssignment(
                    credit_id=credit_id,
                    family=(
                        TasteOutcomeFamily.DESIGN if turn == 1 else TasteOutcomeFamily.ADAPTATION
                    ),
                    direction=credit_direction,
                    outcome_ids=(outcome_id,),
                    confounder_ids=credit_confounder_ids,
                    rationale=credit_rationale,
                    confidence=0.5,
                ),
            ),
            "applicability_conditions": (
                applicability_primary,
                "the research agent complies with the prospectively locked high-level action",
                (
                    "objective scoring occurs only after the effective STOP lock"
                    if is_submission
                    else "a successor belief update is visible before terminal scoring"
                ),
            ),
            "failure_conditions": (
                (
                    (
                        "the submitted hypothesis fails the retained objective scorer"
                        if successful_submission
                        else "the submitted hypothesis passes the retained objective scorer"
                    )
                    if is_submission
                    else "the successor update is unsupported by the immediate observation"
                ),
                (
                    "another experiment has material expected information value under the "
                    "same evidence"
                    if is_submission
                    else (
                        "the same update would follow under a cheaper or more informative "
                        "alternative"
                    )
                ),
                "the research agent does not comply with the locked high-level action",
            ),
            "counterfactual_probe": (
                (
                    "Under the same evidence state and remaining budget, would another experiment "
                    "improve objective correctness enough to justify its cost?"
                )
                if is_submission
                else (
                    "Under the same predecision state and remaining budget, would another "
                    "available action have produced evidence supporting a stronger successor "
                    "update?"
                )
            ),
            "confounders": (
                TasteEpisodeConfounder(
                    confounder_id="research-agent",
                    description=(
                        (
                            "The research model discovered and wrote the submitted hypothesis; the "
                            "controller only adjudicated whether to stop."
                        )
                        if is_submission
                        else (
                            "The research model chose concrete parameters and interpreted the "
                            "observation after receiving high-level Taste guidance."
                        )
                    ),
                    resolution="controlled",
                ),
                TasteEpisodeConfounder(
                    confounder_id=(
                        "objective-scorer" if is_submission else "later-trajectory-decisions"
                    ),
                    description=(
                        (
                            "The hidden objective scorer, not the controller, determines whether "
                            "the submitted scientific law is correct."
                        )
                        if is_submission
                        else (
                            "Later decisions determine the terminal score, which is retained only "
                            "as context and is not assigned wholesale to this turn."
                        )
                    ),
                    resolution=("controlled" if is_submission else "partially-controlled"),
                ),
            ),
            "missing_evidence_questions": (
                (
                    "Did the evidence-state and coverage gate justify STOP before scorer access?"
                    if is_submission
                    else (
                        "Do the retained observation and successor rationale support beneficial "
                        "local credit?"
                    )
                ),
                (
                    "Would another experiment have changed the objectively correct submission?"
                    if is_submission
                    else (
                        "Would an available alternative have yielded stronger information at "
                        "equal cost?"
                    )
                ),
            ),
        }
    )
    return TasteEpisodeCandidate.create(**payload)


def refine_interactive_allocation_candidate(
    candidate: TasteEpisodeCandidate,
    receipt: InteractiveResearchRunReceipt,
    *,
    turn: int,
    outcome_evidence: TasteEpisodeEvidence | None = None,
) -> TasteEpisodeCandidate:
    """Project the same locked action as a budget-allocation decision.

    The v4 projection asks whether the executed scientific action earned local
    credit.  This v5 projection makes the controller's orthogonal decision
    explicit: which fixed meta-action should receive the next bounded unit of
    research effort given the observed trajectory state.  It changes no lock,
    action, observation, outcome, or credit orientation.
    """

    refined = refine_interactive_development_candidate(
        candidate,
        receipt,
        turn=turn,
        outcome_evidence=outcome_evidence,
    )
    selected = next(
        item for item in refined.alternatives if item.action_id == refined.selected_action_id
    )
    context = refined.decision_context
    if context is None:
        raise ValueError("allocation-local projection requires a decision-state context")
    context_summary = ", ".join(
        f"{name}={value}"
        for name, value in context.model_dump(mode="json").items()
    )
    payload = {
        name: getattr(refined, name)
        for name in type(refined).model_fields
        if name != "candidate_sha256"
    }
    payload.update(
        {
            "candidate_id": f"{candidate.candidate_id}-allocation-credit-v5",
            "attribution_producer_id": "interactive-allocation-credit-v5",
            "state_summary": (
                f"Before outcome access at prospectively locked turn {turn}, the controller "
                f"had to allocate the next bounded research step from a fixed meta-action "
                f"menu under trajectory state {context_summary}."
            ),
            "decision_principle": (
                "Allocate the next experiment, analysis step, refinement, or stop decision "
                "from observed trajectory state and remaining budget; the selected action's "
                "scientific content is downstream of this allocation judgment."
            ),
            "why_preferred": (
                f"The prospectively locked controller allocated the next unit of effort to "
                f"{selected.action_type} rather than the other fixed feasible actions. "
                f"The retained local evidence chain is: {refined.why_preferred}"
            ),
            "applicability_conditions": (
                "a controller must allocate remaining experiments, calls, or time among a "
                "fixed feasible research-action menu",
                f"the predecision trajectory state matches {context_summary}",
                *refined.applicability_conditions,
            ),
            "failure_conditions": (
                "the decision under review is scientific content selection rather than "
                "allocation of the next bounded research step",
                *refined.failure_conditions,
            ),
            "counterfactual_probe": (
                f"Under the identical predecision state ({context_summary}) and budget, "
                f"would allocating the next unit to another fixed meta-action have produced "
                f"a better evidence update or a better-supported stop?"
            ),
            "missing_evidence_questions": (
                "Did the retained successor update justify allocating this unit of research "
                "effort to the selected meta-action?",
                *refined.missing_evidence_questions,
            ),
        }
    )
    return TasteEpisodeCandidate.create(**payload)


def _scientific_credit_orientation(
    receipt: InteractiveResearchRunReceipt,
    *,
    is_submission: bool,
) -> tuple[TasteOutcomePolarity, TasteCreditDirection]:
    """Keep terminal STOP credit signed while limiting nonterminal credit locally."""

    objective_supported = (
        receipt.status == "completed"
        and receipt.objective_score is not None
        and receipt.objective_score.primary_value > 0
    )
    if is_submission:
        return (
            (TasteOutcomePolarity.SUPPORTS, TasteCreditDirection.BENEFICIAL)
            if objective_supported
            else (TasteOutcomePolarity.CHALLENGES, TasteCreditDirection.HARMFUL)
        )
    return (
        TasteOutcomePolarity.SUPPORTS if objective_supported else TasteOutcomePolarity.MIXED,
        TasteCreditDirection.BENEFICIAL,
    )


def save_interactive_taste_development_protocol(
    protocol: InteractiveTasteDevelopmentProtocol,
    path: str | Path,
) -> Path:
    return _write_new_json(path, protocol.model_dump_json(indent=2) + "\n")


def load_interactive_taste_development_protocol(
    path: str | Path,
) -> InteractiveTasteDevelopmentProtocol:
    return InteractiveTasteDevelopmentProtocol.model_validate_json(_bounded_file(Path(path)))


def _interactive_state(
    context: InteractiveResearchContext,
    *,
    max_experiments: int,
    used_experiments: int,
    target_domain: str,
    target_venue: str,
) -> ResearchState:
    return ResearchState(
        revision=context.turn - 1,
        project_id=context.project_id,
        research_direction=context.task_prompt,
        target_domain=target_domain,
        target_venue=target_venue,
        resource_budget=ResourceBudget(max_experiments=max_experiments),
        resource_usage=ResourceUsage(experiments=float(used_experiments)),
        current_stage=ResearchStage.EVIDENCE,
        current_experiment_plan=ExperimentPlan(
            plan_id=f"{context.run_id}-interactive-plan",
            objective="Discover and test the hidden scientific relationship.",
            falsifies=["The current proposed law does not predict controlled observations."],
            estimated_cost={"experiments": float(context.remaining_experiments)},
            target_evidence_type="interactive-controlled-experiment",
            counterfactuals=["change one factor while holding the others fixed"],
            matched_baselines=["same task, model, tools, and budget"],
            expected_information_gain=1.0,
        ),
        executor_context={
            "remaining_experiments": _remaining_experiment_bucket(context.remaining_experiments),
            "remaining_turns": context.remaining_turns,
            "failure_count": "zero",
            "no_improvement_streak": "unknown",
            "score_trend": "unknown",
            "best_vs_baseline": "unknown",
            "interactive_turn": context.turn,
            "interactive_history_sha256": content_sha256(context.history),
        },
    )


def _remaining_experiment_bucket(value: int) -> Literal["zero", "one", "two-to-three", "four-plus"]:
    if value <= 0:
        return "zero"
    if value == 1:
        return "one"
    if value <= 3:
        return "two-to-three"
    return "four-plus"


def _lock_turn(lock: TasteProspectiveDecisionLockReceipt) -> int:
    action_id = lock.selected_action_id
    parts = action_id.split("-")
    if len(parts) < 3 or parts[0] != "h4" or not parts[1].isdigit():
        raise ValueError("interactive development lock has an unknown action identity")
    return int(parts[1])


def _outcome_polarity(
    protocol: InteractiveTasteDevelopmentProtocol,
    receipt: InteractiveResearchRunReceipt,
) -> TasteOutcomePolarity:
    score = receipt.objective_score
    if receipt.status != "completed" or score is None:
        return TasteOutcomePolarity.UNRESOLVED
    value = score.primary_value
    better = (
        value > protocol.failure_primary_value
        if protocol.metric_direction == "higher"
        else value < protocol.failure_primary_value
    )
    return TasteOutcomePolarity.SUPPORTS if better else TasteOutcomePolarity.CHALLENGES


def _outcome_summary(receipt: InteractiveResearchRunReceipt) -> str:
    if receipt.objective_score is None:
        return (
            f"The bounded trajectory ended with status {receipt.status!r} and no objective "
            "scientific score; the failure is retained rather than imputed."
        )
    score = receipt.objective_score
    return (
        f"The complete bounded trajectory ended with status {receipt.status!r}; hidden "
        f"scoring reported {score.primary_metric}={score.primary_value} and retained all "
        "turn, experiment, token, cost, and failure telemetry."
    )


def _development_bootstrap_actions(
    context: InteractiveResearchContext,
    *,
    preferred_override: Literal["STOP"] | None = None,
) -> tuple[tuple[ResearchAction, ...], str]:
    """Give pre-fit development decisions semantic rather than random tie-breaking."""

    if preferred_override is not None:
        preferred = preferred_override
    elif context.remaining_experiments == 0:
        preferred = "STOP"
    elif context.turn == 1:
        preferred = "PROBE"
    elif context.turn == 2:
        preferred = "ANALYZE"
    elif context.turn == 3:
        preferred = "EXPERIMENT"
    else:
        preferred = "REFINE"
    experiment_cost = float(min(context.max_experiments_per_turn, context.remaining_experiments))
    actions = tuple(
        action.model_copy(
            update={
                "expected_cost": (
                    {} if action.type.value == "STOP" else {"experiments": experiment_cost}
                ),
                "expected_value": {
                    "information_gain": (10.0 if action.type.value == preferred else 0.0)
                },
                "tags": [
                    *action.tags,
                    *(
                        ["development-bootstrap-preferred"]
                        if action.type.value == preferred
                        else []
                    ),
                ],
            }
        )
        for action in build_h4_benchmark_action_menu(iteration=context.turn)
    )
    return actions, preferred


def _development_submission_stop_gate(
    context: InteractiveResearchContext,
    proposal: InteractiveAgentProposal,
) -> dict[str, JsonValue]:
    """Gate a stop request using structured belief plus observable evidence coverage."""

    phases: list[str] = []
    experiment_count = 0
    distinct_experiments: set[str] = set()
    parameter_values: dict[str, set[str]] = {}
    observation_count = 0
    for item in context.history:
        phase = item.get("high_level_action")
        if isinstance(phase, str):
            phases.append(phase)
        action = item.get("model_action")
        if isinstance(action, dict) and action.get("action") == "run_experiments":
            experiments = action.get("experiments")
            if isinstance(experiments, list):
                experiment_count += len(experiments)
                distinct_experiments.update(content_sha256(value) for value in experiments)
                for experiment in experiments:
                    if not isinstance(experiment, dict):
                        continue
                    parameters = experiment.get("parameters")
                    if not isinstance(parameters, dict):
                        continue
                    for name, value in parameters.items():
                        if isinstance(name, str):
                            parameter_values.setdefault(name, set()).add(content_sha256(value))
        observation = item.get("observation")
        if isinstance(observation, dict):
            results = observation.get("results")
            if isinstance(results, list):
                observation_count += len(results)
            elif results is not None:
                observation_count += 1
    varied_parameter_count = sum(len(values) >= 2 for values in parameter_values.values())
    required_varied_parameters = min(2, len(parameter_values))
    checks = {
        "submission_action": proposal.action == "submit_hypothesis",
        "structured_support": proposal.evidence_status == "candidate-supported",
        "confidence_threshold": proposal.evidence_confidence >= 0.9,
        "low_next_experiment_value": proposal.next_experiment_value <= 0.1,
        "minimum_experiment_count": experiment_count >= 6,
        "minimum_distinct_experiments": len(distinct_experiments) >= 6,
        "parameter_variation": (
            required_varied_parameters >= 1 and varied_parameter_count >= required_varied_parameters
        ),
        "complete_observation_coverage": observation_count >= experiment_count > 0,
    }
    return {
        "policy": "structured-belief-plus-experimental-coverage-v3",
        "approved": all(checks.values()),
        "checks": checks,
        "evidence_status": proposal.evidence_status,
        "evidence_confidence": proposal.evidence_confidence,
        "next_experiment_value": proposal.next_experiment_value,
        "completed_phases": phases,
        "experiment_count": experiment_count,
        "distinct_experiment_count": len(distinct_experiments),
        "parameter_count": len(parameter_values),
        "varied_parameter_count": varied_parameter_count,
        "required_varied_parameter_count": required_varied_parameters,
        "observation_count": observation_count,
    }


def _bounded_summary(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 1] + "…"


def _bounded_file(path: Path) -> bytes:
    source = path.expanduser().resolve()
    if source.is_symlink() or not source.is_file():
        raise ValueError("interactive development artifact must be a regular file")
    if not 1 <= source.stat().st_size <= _MAX_ARTIFACT_BYTES:
        raise ValueError("interactive development artifact exceeds its byte ceiling")
    return source.read_bytes()


def _write_new_json(path: str | Path, contents: str) -> Path:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(contents.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    return target


__all__ = [
    "DevelopmentTasteGuidanceProvider",
    "InteractiveDevelopmentEpisodeBatch",
    "InteractiveDevelopmentEpisodeItem",
    "InteractiveTasteDevelopmentProtocol",
    "finalize_interactive_development_episodes",
    "load_interactive_taste_development_protocol",
    "save_interactive_taste_development_protocol",
]

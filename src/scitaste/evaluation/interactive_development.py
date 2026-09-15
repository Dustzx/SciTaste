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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.h4_execution import build_h4_benchmark_action_menu
from scitaste.evaluation.interactive_research import (
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

    schema_version: Literal["1.0"] = "1.0"
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
        unsigned = cls.model_construct(protocol_sha256="0" * 64, **payload)
        return cls(
            **payload,
            protocol_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"protocol_sha256"})
            ),
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

    @property
    def locks(self) -> tuple[TasteProspectiveDecisionLockReceipt, ...]:
        return tuple(self._locks)

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
        guidance = InteractiveGuidance(
            action_id=selected.action_id,
            action_type=selected.type.value,
            instruction=(
                "Stop experimentation and submit the strongest currently supported hypothesis."
                if selected.type.value == "STOP"
                else selected.description
            ),
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
    items: list[InteractiveDevelopmentEpisodeItem] = []
    for lock_path in lock_paths:
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
        )
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
        batch_id=f"{sampling_plan.source_run_id}-episodes-v1",
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


def refine_interactive_development_candidate(
    candidate: TasteEpisodeCandidate,
    receipt: InteractiveResearchRunReceipt,
    *,
    turn: int,
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

    outcome_evidence_ids = tuple(
        item.evidence_id
        for item in candidate.evidence
        if item.role is TasteEpisodeEvidenceRole.OUTCOME
    )
    if not outcome_evidence_ids:
        raise ValueError("interactive candidate has no terminal receipt evidence")
    observation_sha256 = record.observation_sha256 or "none"
    successor_summary = (
        "The action submitted the terminal hypothesis."
        if successor is None
        else (
            f"The next model action was {successor.decision.proposal.action!r}; its rationale "
            f"was: {_bounded_summary(successor.decision.proposal.rationale, 2_000)}"
        )
    )
    terminal_summary = _outcome_summary(receipt)
    local_polarity = (
        TasteOutcomePolarity.SUPPORTS
        if receipt.status == "completed"
        and receipt.objective_score is not None
        and receipt.objective_score.primary_value > 0
        else TasteOutcomePolarity.MIXED
    )
    outcome_id = f"interactive-local-scientific-progress-{turn:03d}"
    credit_id = f"interactive-local-credit-{turn:03d}"
    payload = {
        name: getattr(candidate, name)
        for name in type(candidate).model_fields
        if name != "candidate_sha256"
    }
    payload.update(
        {
            "candidate_id": f"{candidate.candidate_id}-scientific-credit-v2",
            "attribution_producer_id": "interactive-scientific-credit-v2",
            "state_summary": (
                f"Prospectively locked turn {turn}; the research agent complied with "
                f"{action_type} via {model_action}, and the resulting observation was retained."
            ),
            "why_preferred": (
                f"The locked action was executed rather than merely narrated. Its immediate "
                f"observation hash is {observation_sha256}. {successor_summary}"
            ),
            "outcomes": (
                TasteEpisodeOutcome(
                    outcome_id=outcome_id,
                    family=(
                        TasteOutcomeFamily.DESIGN if turn == 1 else TasteOutcomeFamily.ADAPTATION
                    ),
                    summary=(
                        f"Compliant {model_action} produced observation {observation_sha256}. "
                        f"{successor_summary} {terminal_summary}"
                    ),
                    horizon="immediate observation, successor belief update, and terminal score",
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
                    direction=TasteCreditDirection.BENEFICIAL,
                    outcome_ids=(outcome_id,),
                    confounder_ids=("research-agent", "later-trajectory-decisions"),
                    rationale=(
                        "Proposed benefit is limited to producing the retained observation and "
                        "enabling the documented successor update. It does not assign the shared "
                        "terminal score to this turn or claim that later decisions were caused "
                        "by the controller alone."
                    ),
                    confidence=0.5,
                ),
            ),
            "applicability_conditions": (
                "interactive scientific work with an executable action and retained observation",
                "the research agent complies with the prospectively locked high-level action",
                "a successor belief update is visible before terminal scoring",
            ),
            "failure_conditions": (
                "the successor update is unsupported by the immediate observation",
                "the same update would follow under a cheaper or more informative alternative",
                "the research agent does not comply with the locked high-level action",
            ),
            "counterfactual_probe": (
                "Under the same predecision state and remaining budget, would another available "
                "action have produced evidence supporting a stronger successor update?"
            ),
            "confounders": (
                TasteEpisodeConfounder(
                    confounder_id="research-agent",
                    description=(
                        "The research model chose concrete parameters and interpreted the "
                        "observation after receiving high-level Taste guidance."
                    ),
                    resolution="controlled",
                ),
                TasteEpisodeConfounder(
                    confounder_id="later-trajectory-decisions",
                    description=(
                        "Later decisions determine the terminal score, which is retained only as "
                        "context and is not assigned wholesale to this turn."
                    ),
                    resolution="partially-controlled",
                ),
            ),
            "missing_evidence_questions": (
                "Do the retained observation and successor rationale support beneficial "
                "local credit?",
                "Would an available alternative have yielded stronger information at equal cost?",
            ),
        }
    )
    return TasteEpisodeCandidate.create(**payload)


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
) -> tuple[tuple[ResearchAction, ...], str]:
    """Give pre-fit development decisions semantic rather than random tie-breaking."""

    if context.remaining_experiments == 0:
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

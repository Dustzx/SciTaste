"""Scientific study design distinct from available executor capabilities."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scitaste.evaluation.program_control import ExperimentProgramControl
from scitaste.evidence.research_reasoning import (
    REASONING_INSTRUCTION,
    ResearchReasoningFrame,
    grounding_errors,
)
from scitaste.model_nodes.nodes import ModelNode


class DesignModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResearchDesignInput(DesignModel):
    idea_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idea: dict
    capabilities: dict[str, str]
    evidence: dict[str, str]
    objective: str
    scientific_reasoning_required: bool = False
    planning_taste: dict | None = None
    user_intervention: ExperimentProgramControl | None = None
    planning_priority: Literal["scientific-design", "completeness-first"] = "scientific-design"
    workflow_gaps: dict[str, str] = Field(default_factory=dict)
    prior_rejection_reasons: tuple[str, ...] = ()
    protocol_options: dict[str, dict] = Field(default_factory=dict)
    task_options: dict[str, dict] = Field(default_factory=dict)
    workspace_resource_options: dict[str, dict] = Field(default_factory=dict)
    acquisition_options: dict[str, dict] = Field(default_factory=dict)
    required_comparison_roles: tuple[
        Literal["external-method", "mechanism-ablation", "validity-control"], ...
    ] = ()


class StudyHypothesis(DesignModel):
    hypothesis_id: str
    prediction: str = Field(min_length=1)
    falsification: str = Field(min_length=1)


class PlannedComparison(DesignModel):
    comparison_id: str
    role: Literal["external-method", "mechanism-ablation", "validity-control"]
    treatment: str
    comparator: str
    matched_information_and_budget: str
    availability: Literal["available", "requires-integration", "requires-verification"]


class PlannedStudy(DesignModel):
    study_id: str
    question: str = Field(min_length=1)
    hypothesis_ids: tuple[str, ...] = Field(min_length=1)
    comparison_ids: tuple[str, ...] = Field(min_length=1)
    research_paradigm: Literal["training-free", "training-based", "both"]
    task_sampling_and_split: str = Field(min_length=1)
    primary_outcome: str = Field(min_length=1)
    analysis_and_uncertainty: str = Field(min_length=1)
    success_and_null_interpretation: str = Field(min_length=1)
    stopping_rule: str = Field(min_length=1)
    required_models_data_and_compute: str = Field(min_length=1)
    executor_id: str | None
    execution_gaps: tuple[str, ...]
    leakage_and_confounds: tuple[str, ...] = Field(min_length=1)


class DesignExecutionSelection(DesignModel):
    template_id: str
    study_id: str
    manifest_id: str
    lane_id: str
    task_ids: tuple[str, ...] = Field(min_length=1)
    comparisons: dict[str, dict[Literal["treatment", "comparator"], str]] = Field(min_length=1)


class DesignTaskSelection(DesignModel):
    task_option_id: str
    study_id: str
    comparison_id: str
    comparison_arm: Literal["treatment", "comparator"]


class WorkflowValidation(DesignModel):
    purpose: Literal["functional-integration"] = "functional-integration"
    study_id: str = Field(min_length=1)
    completion_observations: tuple[str, ...] = Field(min_length=1, max_length=8)
    reuse_existing_results: Literal[True] = True
    scientific_effectiveness_claimed: Literal[False] = False


class WorkflowCompletionStep(DesignModel):
    kind: Literal["workflow-completion"] = "workflow-completion"
    workflow_gap_id: str = Field(min_length=1)
    implementation_action: str = Field(min_length=1)
    completion_evidence: str = Field(min_length=1)
    positive_scientific_result_required: Literal[False] = False
    execution_authorized: Literal[False] = False
    validation: WorkflowValidation | None = None


class WorkspaceProvisionSelection(DesignModel):
    resource_option_id: str
    study_id: str
    comparison_id: str
    comparison_arm: Literal["treatment", "comparator"]
    asset_targets: tuple[str, ...] = Field(min_length=1)


class AcquisitionSelection(DesignModel):
    option_id: str
    item_ids: tuple[str, ...] = Field(min_length=1, max_length=500)


class PlanningInterventionResponse(DesignModel):
    publication_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    disposition: Literal["addressed", "deferred", "conflict"]
    explanation: str = Field(min_length=1, max_length=2000)


class ResearchDesignProposal(DesignModel):
    idea_sha256: str
    central_question: str
    hypotheses: tuple[StudyHypothesis, ...] = Field(min_length=1, max_length=6)
    comparisons: tuple[PlannedComparison, ...] = Field(min_length=1, max_length=12)
    studies: tuple[PlannedStudy, ...] = Field(min_length=1, max_length=6)
    next_study_id: str
    selection_reason: str
    evidence_ids: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    execution_authorized: Literal[False] = False
    execution_selection: DesignExecutionSelection | None = None
    task_selection: DesignTaskSelection | None = None
    next_work_item: WorkflowCompletionStep | None = None
    workspace_selection: WorkspaceProvisionSelection | None = None
    acquisition_selection: AcquisitionSelection | None = None
    intervention_response: PlanningInterventionResponse | None = None
    scientific_reasoning: ResearchReasoningFrame | None = None


class ResearchDesignNode(ModelNode[ResearchDesignInput, ResearchDesignProposal]):
    node_name = "project-research-design"
    prompt_version = "project-research-design-v9"
    input_model = ResearchDesignInput
    output_model = ResearchDesignProposal
    system_instruction = (
        "Design a scientifically informative research program from the project idea. "
        "user_intervention, when present, is a published user planning constraint. "
        "Explicitly respond with intervention_response bound to its source_publication_sha256. "
        "Explain concretely how the plan addresses the change, or mark deferred/conflict "
        "with the reason and leave all execution/acquisition selections null. Addressed describes "
        "planning only, not execution success. Never enlarge budgets or permissions based on it. "
        "Without a user_intervention, leave intervention_response null. "
        "Do not equate workflow completeness, scientific quality, and effectiveness. "
        "When planning_taste is supplied, consider its validated transfer advice and exact "
        "applicability boundaries; an abstaining or rejected consultation gives no preference. "
        "Do not treat it as raw retrieved authority or override resource and workflow constraints. "
        "Experience abstention is a valid terminal disposition, not proof of a broken pipeline. "
        "Never require a nonzero admission count, positive credit, changed disposition or policy "
        "update to demonstrate workflow completion. Do not relabel observational evidence to "
        "manufacture training signal. Use only supplied workflow gap IDs for next_work_item; "
        "when none are supplied, set next_work_item=null and describe suspected gaps in "
        "unresolved_questions instead. Correct any prior_rejection_reasons. "
        "When planning_priority is completeness-first, select an actual supplied workflow_gap "
        "as next_work_item. Describe concrete implementation and observable completion, not "
        "a favorable mechanism ablation. Keep studies as a deferred scientific agenda; "
        "next_study_id then denotes only a future study, NOT the immediate next action. "
        "Normally leave execution selections null in that mode. Exception: when a bounded "
        "functional run is necessary to close that actual gap, bind next_work_item.validation "
        "to one Native task/workspace study with observable integration outcomes and reuse "
        "existing results. It is not an efficacy study, cannot launch a campaign, does not "
        "authorize execution, and must not require positive scientific results. Reviewer requests "
        "for stronger evidence do not override this priority. Do not rename efficacy "
        "verification as workflow completeness or require positive results before integration. "
        "Define falsifiable hypotheses, actual sampling and split units, comparisons, "
        "outcome measurement, uncertainty, stopping and interpretations of null findings. "
        "Distinguish comparisons to other autonomous research frameworks from within-system "
        "mechanism ablations. Small experimental subject models are not the research agent. "
        "Training-free/training-based describe experiments conducted by the agent, not "
        "necessarily training the agent itself. Do not restrict a general Auto Research idea "
        "to vision or existing hardware. Plan scientifically first; explicitly mark execution "
        "gaps instead of pretending a narrow adapter executes a broad system comparison. "
        "Available adapters are exact limited capabilities, not promises of integration. "
        "Use executor_id=null when none can execute the entire study. A known executor may "
        "still have gaps. Never invent resources, literature verification, observations, "
        "provider calls or completed comparisons. Cite only supplied evidence IDs. "
        "Choose one next study, avoid redundant replications without a statistical purpose, "
        "If protocol_options are provided, optionally select an existing development matrix "
        "using exact template/lane/task/system IDs in execution_selection. "
        "Use compiler_selection.eligible_task_ids: held_out may mean isolation from Taste "
        "training rather than formal-test assignment. Never alter split or isolation flags. "
        "Executor IDs must come from capabilities, never protocol IDs. "
        "Do not reinterpret a mechanism ablation as an external-framework comparison. "
        "Keep broader studies and implementation gaps even when one development "
        "component is selected. "
        "A favorable ablation is never a prerequisite to completing workflow capabilities. "
        "Previous-cycle evidence includes historical observations, not newly admitted Taste. "
        "Use failures, null results, dispositions and unfinished capabilities to choose the "
        "next informative step. Do not repeat completed experiments merely to obtain a "
        "positive score or positive review. A selected best attempt is not a controlled "
        "causal comparison; rejected or abstained experience grants no learned preference. "
        "If the idea changed, discuss applicability rather than assuming direct transfer. "
        "task_options are frozen prepared task/resource envelopes. You may choose exactly "
        "one with task_selection for an implemented study component, using its executor_id "
        "and a separate component study when the broader study has executor_id=null. "
        "All hypothesis_ids/comparison_ids must refer to definitions in this response; "
        "do not use IDs copied from project context without declaring them. "
        "Do not bind task_selection to a broader unimplemented study just because one "
        "component is available. Describe that component as a separate study with the "
        "option's executor_id and retain missing comparison arms as execution gaps. "
        "Use the selected option's executor_id "
        "and exact option ID. This selects a single comparison arm, NOT a whole comparative "
        "study. Keep missing comparator/campaign work explicit. It cannot implement a "
        "different method merely by changing the study description. Never select both "
        "execution_selection and task_selection. No selection is better than falsely "
        "claiming available tasks implement an unrelated scientific contrast. "
        "Alternatively workspace_resource_options permits a NEW Native study from declared "
        "assets without a pre-existing task. Use workspace_selection with resource_option_id, "
        "study_id, comparison_id, comparison_arm and a nonempty subset of asset_targets from "
        "that option's files. Select only assets needed by the study; honor use_constraints. "
        "Do not assume undeclared models/data/GPU or that an available asset proves study quality. "
        "Remote GPU use is possible only if the option explicitly binds remote_workspace; "
        "keep its fixed device/job/time envelope and use the Run Remote tool, never local GPU. "
        "At most one of workspace_selection, task_selection, execution_selection may be set. "
        "In completeness-first mode leave all three null unless the explicit functional "
        "validation exception binds one declared Native task/workspace selection. "
        "If resource acquisition/handoff is the selected workflow gap, acquisition_options "
        "permits acquisition_selection with an exact option_id and nonempty unique item_ids. "
        "Select only necessary declared items with verified license status; never invent "
        "URLs, change constraints, or select execution alongside acquisition. An existing "
        "receipt permits reuse, not automatic study execution or formal task selection. "
        "Otherwise leave acquisition_selection null. "
        "When scientific_reasoning_required and planning_priority=scientific-design, provide "
        "scientific_reasoning with explanation IDs defined in hypotheses. Its evidence anchors "
        "use exact supplied evidence IDs and verbatim quotes. Bind the preferred probe's "
        "intervention to next_study_id and explain the mapping in selection_reason. "
        "No evidence yet means an explicitly provisional frame with no evidence updates. "
        "For completeness-first integration, this frame is optional; do not delay delivery "
        "for a scientific mechanism study. "
        "Keep the complete design concise. Copy idea_sha256 exactly. No execution authority. "
        + REASONING_INSTRUCTION
    )

    def _proposal_rejections(self, proposal, *, input_data, context, policy):
        del context, policy
        reasons = []
        reasoning = proposal.scientific_reasoning
        if (
            input_data.scientific_reasoning_required
            and input_data.planning_priority == "scientific-design"
            and reasoning is None
        ):
            reasons.append(
                "Scientific planning requires competing explanations and outcome branches"
            )
        if reasoning:
            reasons.extend(
                grounding_errors(reasoning, {k: [v] for k, v in input_data.evidence.items()})
            )
            if {h.hypothesis_id for h in reasoning.explanations} - {
                h.hypothesis_id for h in proposal.hypotheses
            }:
                reasons.append("Scientific reasoning must bind declared study hypotheses")
        control = input_data.user_intervention
        response = proposal.intervention_response
        if control is None and response is not None:
            reasons.append("No published intervention to acknowledge")
        if control is not None:
            if response is None or response.publication_sha256 != control.source_publication_sha256:
                reasons.append("Published intervention requires an exact bound response")
            elif response.disposition != "addressed" and any(
                x is not None
                for x in (
                    proposal.task_selection,
                    proposal.workspace_selection,
                    proposal.execution_selection,
                    proposal.acquisition_selection,
                )
            ):
                reasons.append("Deferred/conflicting intervention cannot select execution")
        workspace = proposal.workspace_selection
        if (
            sum(
                x is not None
                for x in (
                    workspace,
                    proposal.task_selection,
                    proposal.execution_selection,
                    proposal.acquisition_selection,
                )
            )
            > 1
        ):
            reasons.append("Select only one execution provisioning route")
        acquisition = proposal.acquisition_selection
        if acquisition is not None:
            option = input_data.acquisition_options.get(acquisition.option_id)
            available = (option or {}).get("items", {})
            if (
                option is None
                or len(set(acquisition.item_ids)) != len(acquisition.item_ids)
                or set(acquisition.item_ids) - available.keys()
                or any(
                    available.get(k, {}).get("license_status") != "verified"
                    for k in acquisition.item_ids
                )
            ):
                reasons.append("Acquisition selection must use declared licensed items")
        if workspace is not None:
            option = input_data.workspace_resource_options.get(workspace.resource_option_id)
            study = next((s for s in proposal.studies if s.study_id == workspace.study_id), None)
            if (
                option is None
                or study is None
                or study.executor_id != "scitaste-native-workspace"
                or workspace.comparison_id not in study.comparison_ids
                or len(set(workspace.asset_targets)) != len(workspace.asset_targets)
                or set(workspace.asset_targets) - set((option or {}).get("files", {}))
            ):
                reasons.append("Workspace selection must bind a Native study and declared assets")
        if proposal.idea_sha256 != input_data.idea_sha256:
            reasons.append("Design targets different idea")
        if input_data.planning_priority == "completeness-first":
            if not input_data.workflow_gaps or proposal.next_work_item is None:
                reasons.append("Completeness-first requires an explicit supplied workflow gap")
            validation = proposal.next_work_item.validation if proposal.next_work_item else None
            selected = proposal.task_selection or workspace
            valid_functional_run = (
                validation is not None
                and selected is not None
                and proposal.execution_selection is None
                and selected.study_id == validation.study_id == proposal.next_study_id
                and any(
                    study.study_id == validation.study_id
                    and study.executor_id == "scitaste-native-workspace"
                    and not study.execution_gaps
                    for study in proposal.studies
                )
                and all(observation.strip() for observation in validation.completion_observations)
            )
            if (
                any(x is not None for x in (proposal.execution_selection, selected))
                and not valid_functional_run
            ):
                reasons.append("Deferred scientific study cannot replace workflow completion")
            if validation is not None and not valid_functional_run:
                reasons.append(
                    "Functional validation requires one available bounded Native selection"
                )
        if proposal.next_work_item is not None:
            if proposal.next_work_item.workflow_gap_id not in input_data.workflow_gaps:
                reasons.append("Next work item references an unknown workflow gap")
        collections = [
            (proposal.hypotheses, "hypothesis_id"),
            (proposal.comparisons, "comparison_id"),
            (proposal.studies, "study_id"),
        ]
        for rows, attr in collections:
            ids = [getattr(row, attr) for row in rows]
            if len(ids) != len(set(ids)) or any(not value.strip() for value in ids):
                reasons.append("Design identifiers must be unique and nonempty")
        hypotheses = {h.hypothesis_id for h in proposal.hypotheses}
        comparisons = {c.comparison_id for c in proposal.comparisons}
        if proposal.next_study_id not in {s.study_id for s in proposal.studies}:
            reasons.append("Next study is absent from design")
        if set(proposal.evidence_ids) - input_data.evidence.keys():
            reasons.append("Unknown design evidence")
        used_comparisons = {key for study in proposal.studies for key in study.comparison_ids}
        covered_roles = {
            c.role for c in proposal.comparisons if c.comparison_id in used_comparisons
        }
        if set(input_data.required_comparison_roles) - covered_roles:
            reasons.append("Design omits required comparison roles; ablations cannot replace them")
        for study in proposal.studies:
            if set(study.hypothesis_ids) - hypotheses or set(study.comparison_ids) - comparisons:
                reasons.append("Study refers to unknown hypothesis or comparison")
            if study.executor_id is not None and study.executor_id not in input_data.capabilities:
                reasons.append("Unknown executor capability")
            if study.executor_id is None and not study.execution_gaps:
                reasons.append("Unavailable executor must have explicit implementation gap")
        selection = proposal.execution_selection
        task_selection = proposal.task_selection
        if task_selection is not None:
            option = input_data.task_options.get(task_selection.task_option_id)
            study = next(
                (s for s in proposal.studies if s.study_id == task_selection.study_id), None
            )
            if (
                option is None
                or study is None
                or study.executor_id != option.get("executor_id")
                or task_selection.comparison_id not in study.comparison_ids
            ):
                reasons.append("Task selection does not bind an available study component")
            if selection is not None:
                reasons.append("Select either a task component or a campaign matrix, not both")
        if selection is not None:
            from scitaste.evaluation.development_selection import development_task_eligible

            option = input_data.protocol_options.get(selection.template_id)
            study = next((s for s in proposal.studies if s.study_id == selection.study_id), None)
            if option is None or study is None:
                reasons.append("Execution selection refers to unknown protocol or study")
            else:
                lane = next(
                    (item for item in option["lanes"] if item["lane_id"] == selection.lane_id), None
                )
                tasks = {t["task_id"]: t for t in option["tasks"]}
                if (
                    lane is None
                    or set(selection.task_ids) - set(lane["task_ids"])
                    or any(
                        not development_task_eligible(tasks[t], study_scope=option["study_scope"])
                        for t in selection.task_ids
                        if t in tasks
                    )
                ):
                    reasons.append("Execution selection includes unknown or non-development tasks")
                if len(selection.task_ids) != len(set(selection.task_ids)):
                    reasons.append("Execution task IDs must be unique")
                if set(selection.comparisons) != set(study.comparison_ids):
                    reasons.append("Selected study comparisons are not fully mapped")
                for pair in selection.comparisons.values():
                    if (
                        set(pair) != {"treatment", "comparator"}
                        or len(set(pair.values())) != 2
                        or lane is None
                        or set(pair.values()) - set(lane["system_ids"])
                    ):
                        reasons.append("Invalid comparison/system selection")
        return reasons

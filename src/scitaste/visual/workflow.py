"""ResearchState-integrated figure workflow."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from scitaste.data.store import TasteLibrary, build_libraries
from scitaste.executor.base import ResearchExecutor
from scitaste.executor.mock import MockExecutor
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.state.research_state import (
    EvidenceGraph,
    EvidenceItem,
    FigureContract,
    FigureState,
    ResearchState,
    ResourceBudget,
    ScientificClaim,
)
from scitaste.state.resources import record_resource_usage
from scitaste.state.transitions import apply_transition
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.retriever import TasteQuery, TasteRetrievalPolicy, TasteRetriever
from scitaste.visual.critic import VisualTasteCritic, blocking_findings
from scitaste.visual.draft import SemanticDraftGenerator
from scitaste.visual.export import export_drawio, export_svg
from scitaste.visual.need import FigureNeedDetector
from scitaste.visual.patcher import ObjectPatcher


class FigureScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    research_direction: str
    target_domain: str
    target_venue: str | None = None
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    claims: list[ScientificClaim] = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    source_text: str = Field(min_length=1)
    figure_role: str = "mechanism"
    contract: FigureContract
    initial_emphasis: dict[str, str] = Field(default_factory=dict)


class FigureWorkflow:
    def __init__(
        self,
        *,
        controller: TasteController | None = None,
        executor: ResearchExecutor | None = None,
        seed: int = 0,
    ) -> None:
        self.controller = controller
        self.executor = executor or MockExecutor(seed=seed)
        self.seed = seed

    def run(
        self,
        scenario: FigureScenario,
        *,
        output_dir: str | Path,
        state_path: str | Path | None = None,
    ) -> dict[str, object]:
        root = Path(output_dir)
        logger = DecisionLogger(root / "decisions.jsonl")
        if logger.path.exists():
            raise FileExistsError(f"refusing to append to existing figure log: {logger.path}")
        store = StateStore(root)
        taste_root = root / "taste_context"
        build_libraries("configs/taste/library_seed_v1.yaml", taste_root)
        retriever = TasteRetriever(TasteLibrary(taste_root / "taste" / "records.jsonl"))
        controller = self.controller or TasteController(
            seed=self.seed,
            mode=TasteMode.AUGMENTED,
            retriever=retriever,
        )
        if state_path is None:
            state = ResearchState(
                project_id=scenario.project_id,
                research_direction=scenario.research_direction,
                target_domain=scenario.target_domain,
                target_venue=scenario.target_venue,
                resource_budget=scenario.resource_budget,
                claims=[item.model_copy(deep=True) for item in scenario.claims],
                evidence_graph=EvidenceGraph(
                    items=[item.model_copy(deep=True) for item in scenario.evidence]
                ),
                current_stage="COMMUNICATION",
            )
        else:
            state = ResearchState.model_validate_json(Path(state_path).read_text(encoding="utf-8"))
            if state.project_id != scenario.project_id:
                raise ValueError("figure scenario belongs to another project")
            if state.current_stage.value != "COMMUNICATION":
                raise ValueError("figure workflow requires a COMMUNICATION state")
            _merge_figure_evidence(state, scenario)
        contract = scenario.contract.model_copy(deep=True)
        need = FigureNeedDetector().assess(scenario.source_text, contract)
        if not need.needed:
            raise ValueError(need.reason)
        references = retriever.retrieve(
            TasteQuery(
                text=f"{scenario.source_text} {contract.purpose}",
                policy=TasteRetrievalPolicy.VISUAL_ROLE,
                stage="COMMUNICATION",
                domain_tags=[scenario.target_domain],
                venue=scenario.target_venue,
                figure_role=scenario.figure_role,
            ),
            limit=3,
        )
        reference_ids = [item.case.case_id for item in references]
        contract.reference_figure_ids = list(
            dict.fromkeys([*contract.reference_figure_ids, *reference_ids])
        )
        state.figure_state = FigureState(
            status="contracted",
            contract=contract,
            retrieved_taste_case_ids=reference_ids,
        )
        state.taste_context_ids = reference_ids
        store.save(state)

        action = ResearchAction(
            action_id="figure-build-editable",
            type=MetaAction.DESIGN_FIGURE,
            description="Build an editable mechanism figure from a claim-linked contract",
            expected_value={"story_potential": 0.9, "claim_relevance": 0.9},
        )
        decision = controller.decide(state=state, candidate_actions=[action])
        result = self.executor.generate_figure(state, decision.selected_action)
        decision.executor_result_id = result.result_id
        decision.actual_outcome = result.model_dump(mode="json")
        logger.append(decision)
        state = apply_transition(state, decision)
        state = record_resource_usage(state, result.cost)

        draft = SemanticDraftGenerator().generate(
            contract, initial_emphasis=scenario.initial_emphasis
        )
        initial_svg = export_svg(contract, draft, root / "figure.initial.svg")
        initial_drawio = export_drawio(contract, draft, root / "figure.initial.drawio")
        critic = VisualTasteCritic()
        initial_report = critic.review(
            contract,
            draft,
            known_claim_ids={item.claim_id for item in state.claims},
        )
        patcher = ObjectPatcher()
        patches = patcher.plan(initial_report, draft)
        patched = patcher.apply(draft, patches)
        final_report = critic.review(
            contract,
            patched,
            known_claim_ids={item.claim_id for item in state.claims},
        )
        if blocking_findings(final_report):
            messages = "; ".join(item.message for item in blocking_findings(final_report))
            raise ValueError(f"figure remains unready after patching: {messages}")
        final_svg = export_svg(contract, patched, root / "figure.svg")
        final_drawio = export_drawio(contract, patched, root / "figure.drawio")
        assert state.figure_state is not None
        state.figure_state.status = "reviewed"
        state.figure_state.semantic_objects = patched
        state.figure_state.initial_critic_report = initial_report
        state.figure_state.final_critic_report = final_report
        state.figure_state.patch_history = patches
        state.figure_state.figure_refs = [str(final_svg), str(final_drawio)]
        state.figure_state.revision = 2
        store.save(state)

        summary: dict[str, object] = {
            "project_id": state.project_id,
            "final_stage": state.current_stage.value,
            "figure_status": state.figure_state.status,
            "figure_id": contract.figure_id,
            "figure_need_reason": need.reason,
            "target_claim_ids": contract.target_claim_ids,
            "retrieved_taste_case_ids": reference_ids,
            "initial_blocking_findings": len(blocking_findings(initial_report)),
            "patch_count": len(patches),
            "patched_object_ids": [item.object_id for item in patches],
            "final_blocking_findings": len(blocking_findings(final_report)),
            "artifacts": [str(initial_svg), str(initial_drawio), str(final_svg), str(final_drawio)],
            "selected_actions": [
                item.selected_action.type.value for item in state.decision_history
            ],
        }
        (root / "figure_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return summary


def load_figure_scenario(path: str | Path) -> FigureScenario:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return FigureScenario.model_validate(data)


def _merge_figure_evidence(state: ResearchState, scenario: FigureScenario) -> None:
    claims = {item.claim_id: index for index, item in enumerate(state.claims)}
    for claim in scenario.claims:
        copied = claim.model_copy(deep=True)
        if claim.claim_id in claims:
            existing = state.claims[claims[claim.claim_id]]
            if existing != copied:
                raise ValueError(f"figure claim conflicts with prior state: {claim.claim_id}")
        else:
            claims[claim.claim_id] = len(state.claims)
            state.claims.append(copied)
    evidence = {item.evidence_id: index for index, item in enumerate(state.evidence_graph.items)}
    for item in scenario.evidence:
        copied = item.model_copy(deep=True)
        if item.evidence_id in evidence:
            existing = state.evidence_graph.items[evidence[item.evidence_id]]
            if existing != copied:
                raise ValueError(f"figure evidence conflicts with prior state: {item.evidence_id}")
        else:
            evidence[item.evidence_id] = len(state.evidence_graph.items)
            state.evidence_graph.items.append(copied)

"""ResearchState-integrated Communication Loop with reviewer-driven evidence."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.data.store import TasteLibrary, build_libraries
from scitaste.evidence.workflow import EvidenceWorkflow, EvidenceWorkflowScenario
from scitaste.executor.base import ExecutionResult, ResearchExecutor
from scitaste.executor.mock import MockExecutor
from scitaste.review.closure import EVIDENCE_ACTIONS, close_satisfied_obligations
from scitaste.review.obligations import create_obligation
from scitaste.review.parser import ReviewFeedback, parse_feedback
from scitaste.review.routing import ReviewActionRouter
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.schema.decisions import ResearchDecision
from scitaste.state.persistence import DecisionLogger, StateStore
from scitaste.state.research_state import (
    EvidenceGraph,
    EvidenceItem,
    NarrativeSpine,
    ParagraphContract,
    ResearchState,
    ResourceBudget,
    ScientificClaim,
    SectionContract,
    WritingState,
)
from scitaste.state.resources import record_resource_usage
from scitaste.state.transitions import apply_transition
from scitaste.taste.controller import TasteController, TasteMode
from scitaste.taste.retriever import TasteRetriever
from scitaste.writing.contracts import retrieve_contract_taste
from scitaste.writing.critics import WritingCriticSuite
from scitaste.writing.drafter import ContractDrafter
from scitaste.writing.narrative import review_narrative


class CommunicationScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    research_direction: str
    target_domain: str
    target_venue: str | None = None
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    claims: list[ScientificClaim] = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(min_length=1)
    narrative: NarrativeSpine
    section_contracts: list[SectionContract] = Field(min_length=1)
    paragraph_contracts: list[ParagraphContract] = Field(min_length=1)
    review_feedback: list[ReviewFeedback] = Field(min_length=1)
    review_resolution: EvidenceWorkflowScenario | None = None

    @model_validator(mode="after")
    def resolution_matches_project(self) -> CommunicationScenario:
        if self.review_resolution and self.review_resolution.project_id != self.project_id:
            raise ValueError("review resolution project_id must match communication project")
        return self


class CommunicationWorkflow:
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

    def run(self, scenario: CommunicationScenario, *, output_dir: str | Path) -> dict[str, object]:
        root = Path(output_dir)
        logger = DecisionLogger(root / "decisions.jsonl")
        if logger.path.exists():
            raise FileExistsError(
                f"refusing to append to existing communication log: {logger.path}"
            )
        store = StateStore(root)
        taste_root = root / "taste_context"
        build_libraries("configs/taste/library_seed_v1.yaml", taste_root)
        retriever = TasteRetriever(TasteLibrary(taste_root / "taste" / "records.jsonl"))
        controller = self.controller or TasteController(
            seed=self.seed,
            mode=TasteMode.AUGMENTED,
            retriever=retriever,
        )
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
        store.save(state)

        def act(actions: list[ResearchAction]) -> tuple[ResearchDecision, ExecutionResult]:
            nonlocal state
            decision = controller.decide(state=state, candidate_actions=actions)
            result = self.executor.execute(state, decision.selected_action)
            decision.executor_result_id = result.result_id
            decision.actual_outcome = result.model_dump(mode="json")
            logger.append(decision)
            state = apply_transition(state, decision)
            state = record_resource_usage(state, result.cost)
            return decision, result

        act(
            [
                ResearchAction(
                    action_id="communication-build-story",
                    type=MetaAction.BUILD_STORY,
                    description="Build and evidence-check the narrative spine",
                    expected_value={"story_potential": 1.0, "claim_relevance": 0.8},
                )
            ]
        )
        narrative_review = review_narrative(scenario.narrative, state)
        if not narrative_review.passes:
            raise ValueError(
                "narrative taste review failed: " + "; ".join(narrative_review.findings)
            )
        state.narrative_spine = scenario.narrative.model_copy(deep=True)
        state.writing_state = WritingState(
            status="contracted",
            section_contracts=[item.model_copy(deep=True) for item in scenario.section_contracts],
            paragraph_contracts=[
                item.model_copy(deep=True) for item in scenario.paragraph_contracts
            ],
        )
        retrieved = retrieve_contract_taste(
            state, state.writing_state.paragraph_contracts, retriever
        )
        state.writing_state.retrieved_taste_case_ids = retrieved
        state.taste_context_ids = list(dict.fromkeys([*state.taste_context_ids, *retrieved]))
        store.save(state)

        act(
            [
                ResearchAction(
                    action_id="communication-write-draft",
                    type=MetaAction.WRITE,
                    description="Draft from section and paragraph contracts",
                    expected_value={"story_potential": 0.9, "venue_fit": 0.7},
                )
            ]
        )
        assert state.writing_state is not None
        drafter = ContractDrafter()
        state.writing_state.section_drafts = drafter.draft(state.writing_state)
        state.writing_state.status = "drafted"
        state.writing_state.revision = 1
        critics = WritingCriticSuite()
        state.writing_state.critic_findings = critics.review(state)
        _require_no_critic_errors(state.writing_state)
        _write_paper(root / "paper.md", state.writing_state.section_drafts)
        state.writing_state.artifact_refs = [str(root / "paper.md")]
        store.save(state)

        act(
            [
                ResearchAction(
                    action_id="communication-review",
                    type=MetaAction.REVIEW,
                    description="Decompose reviewer feedback into research obligations",
                    expected_value={"claim_relevance": 0.8, "review_attack_surface": 0.5},
                )
            ]
        )
        concerns = parse_feedback(scenario.review_feedback)
        state.reviewer_concerns.extend(concerns)
        router = ReviewActionRouter()
        review_actions = [router.route(concern) for concern in concerns]
        state.open_research_obligations.extend(
            create_obligation(concern, action, state)
            for concern, action in zip(concerns, review_actions, strict=True)
        )
        store.save(state)

        selected, _ = act(review_actions)
        selected_obligation = next(
            item
            for item in state.open_research_obligations
            if item.concern_id == selected.selected_action.parameters["concern_id"]
        )
        if selected.selected_action.type.value in EVIDENCE_ACTIONS:
            if scenario.review_resolution is None:
                raise ValueError("evidence-bearing review action requires review_resolution")
            store.save(state)
            EvidenceWorkflow(
                controller=controller,
                executor=self.executor,
                seed=self.seed,
            ).run(
                scenario.review_resolution,
                output_dir=root / "review_evidence",
                state_path=store.latest_path,
            )
            state = StateStore(root / "review_evidence").load()
            closed = close_satisfied_obligations(state)
            if selected_obligation.obligation_id not in {item.obligation_id for item in closed}:
                raise ValueError("new evidence did not close the selected review obligation")
        else:
            selected_obligation.status = "closed"
            selected_obligation.resolution_summary = "Resolved by a communication-only action."
            concern = next(
                item
                for item in state.reviewer_concerns
                if item.concern_id == selected_obligation.concern_id
            )
            concern.status = "closed"
        store.save(state)

        act(
            [
                ResearchAction(
                    action_id="communication-revise-paper",
                    type=MetaAction.WRITE,
                    description="Revise the paper after closing the review obligation",
                    expected_value={"story_potential": 0.8, "claim_relevance": 1.0},
                )
            ]
        )
        assert state.writing_state is not None
        selected_obligation = next(
            item
            for item in state.open_research_obligations
            if item.obligation_id == selected_obligation.obligation_id
        )
        state.writing_state.section_drafts = drafter.revise(
            state.writing_state, selected_obligation
        )
        state.writing_state.revision += 1
        state.writing_state.status = "revised"
        state.writing_state.critic_findings = critics.review(state)
        _require_no_critic_errors(state.writing_state)
        _write_paper(root / "paper.md", state.writing_state.section_drafts)
        store.save(state)

        summary: dict[str, object] = {
            "project_id": state.project_id,
            "final_stage": state.current_stage.value,
            "writing_status": state.writing_state.status,
            "writing_revision": state.writing_state.revision,
            "retrieved_taste_case_ids": state.writing_state.retrieved_taste_case_ids,
            "concern_count": len(state.reviewer_concerns),
            "closed_obligation_ids": [
                item.obligation_id
                for item in state.open_research_obligations
                if item.status == "closed"
            ],
            "selected_actions": [
                decision.selected_action.type.value for decision in state.decision_history
            ],
            "paper": str(root / "paper.md"),
            "decision_log": str(logger.path),
            "evidence_decision_log": str(root / "review_evidence" / "decisions.jsonl")
            if scenario.review_resolution
            else None,
            "latest_state": str(store.latest_path),
        }
        (root / "communication_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return summary


def load_communication_scenario(path: str | Path) -> CommunicationScenario:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return CommunicationScenario.model_validate(data)


def _require_no_critic_errors(writing: WritingState) -> None:
    errors = [item.message for item in writing.critic_findings if item.severity == "error"]
    if errors:
        raise ValueError("writing critic failed: " + "; ".join(errors))


def _write_paper(path: Path, drafts: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "\n\n".join(f"# {name}\n\n{text}" for name, text in drafts.items())
    path.write_text(rendered + "\n", encoding="utf-8")

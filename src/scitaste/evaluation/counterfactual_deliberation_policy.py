"""Outcome-hidden, cross-task deliberation inputs for content-conditioned Taste."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.data.store import TasteLibrary
from scitaste.evaluation.counterfactual_precedents import (
    CounterfactualTastePrecedentManifest,
)
from scitaste.evaluation.counterfactual_taste import (
    CounterfactualActionSetResult,
    CounterfactualResearchAction,
)
from scitaste.evaluation.counterfactual_temporal_precedents import (
    CounterfactualPreDecisionState,
    counterfactual_predecision_state,
    temporal_applicability_mismatches,
)
from scitaste.evaluation.interactive_research import (
    InteractiveResearchPrefix,
    load_interactive_research_prefix,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.taste.deliberation import (
    TasteDecisionFact,
    TasteDeliberationCandidate,
    TasteDeliberationInput,
)
from scitaste.taste.retriever import lexical_similarity

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"

_ACTION_DESCRIPTIONS = {
    CounterfactualResearchAction.PROBE: "Isolate broad variable dependencies.",
    CounterfactualResearchAction.PILOT: "Run a cheap discriminating test of one law family.",
    CounterfactualResearchAction.EXPERIMENT: (
        "Maximize disagreement between currently plausible formulas."
    ),
    CounterfactualResearchAction.ANALYZE: (
        "Compare visible dependencies and units before one diagnostic check."
    ),
    CounterfactualResearchAction.REFINE: "Estimate a supported functional form more precisely.",
    CounterfactualResearchAction.PIVOT: "Test a qualitatively different law family.",
    CounterfactualResearchAction.STOP: "Submit the strongest law supported by visible evidence.",
}


class CounterfactualDeliberationTarget(BaseModel):
    """Objective label kept outside the model-visible deliberation input."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    target_case_id: str
    task_cluster_id: str
    prefix_sha256: str = Field(pattern=_SHA256)
    result_sha256: str = Field(pattern=_SHA256)
    excluded_same_cluster_case_ids: tuple[str, ...] = ()
    eligible_cross_cluster_case_ids: tuple[str, ...] = Field(min_length=2)
    objective_preferred_actions: tuple[str, ...] = Field(min_length=1, max_length=7)
    objective_values: dict[str, float]
    objective_observed: dict[str, bool]
    selector_input_sha256: str = Field(pattern=_SHA256)
    source_outcomes_absent_from_selector_input: Literal[True] = True
    development_only: bool = True
    confirmation_protocol_sha256: str | None = Field(
        default=None,
        pattern=_SHA256,
        exclude_if=lambda value: value is None,
    )
    target_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def target_is_closed(self) -> CounterfactualDeliberationTarget:
        validate_entry_id(self.study_id, field_name="counterfactual deliberation study_id")
        if set(self.objective_values) != set(self.objective_observed):
            raise ValueError("counterfactual target objective maps differ")
        if set(self.objective_preferred_actions) - set(self.objective_values):
            raise ValueError("counterfactual target preferred action lacks an objective")
        if set(self.excluded_same_cluster_case_ids) & set(self.eligible_cross_cluster_case_ids):
            raise ValueError("counterfactual target cluster partitions overlap")
        if self.development_only == (self.confirmation_protocol_sha256 is not None):
            raise ValueError(
                "confirmation targets require a protocol hash; development targets forbid one"
            )
        expected = content_sha256(self.model_dump(mode="json", exclude={"target_sha256"}))
        if self.target_sha256 != expected:
            raise ValueError("counterfactual deliberation target hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualDeliberationTarget:
        payload = {
            "schema_version": "1.0",
            "source_outcomes_absent_from_selector_input": True,
            "development_only": True,
            **values,
        }
        payload.pop("target_sha256", None)
        unsigned = cls.model_construct(target_sha256="0" * 64, **payload)
        return cls(
            **payload,
            target_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"target_sha256"})
            ),
        )


class CounterfactualDeliberationRetrievalRecord(BaseModel):
    """Outcome-hidden record of the deterministic broad-retrieval stage."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    task_cluster_id: str
    retrieval_rule_id: Literal[
        "outcome-hidden-lexical-action-diverse-top-k-v1",
        "hard-safe-then-lexical-action-diverse-top-k-v2",
    ]
    maximum_candidate_cases: int = Field(ge=2, le=20)
    population_scores: dict[str, float] = Field(min_length=2, max_length=20)
    population_preferred_actions: dict[str, str] = Field(min_length=2, max_length=20)
    population_hard_applicability: dict[str, bool] | None = Field(
        default=None,
        min_length=2,
        max_length=20,
        exclude_if=lambda value: value is None,
    )
    selected_case_ids: tuple[str, ...] = Field(min_length=2, max_length=20)
    selector_input_sha256: str = Field(pattern=_SHA256)
    source_outcomes_hidden: Literal[True] = True
    target_outcomes_hidden: Literal[True] = True
    retrieval_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def retrieval_is_closed(self) -> CounterfactualDeliberationRetrievalRecord:
        validate_entry_id(self.study_id, field_name="counterfactual retrieval study_id")
        population = set(self.population_scores)
        if set(self.population_preferred_actions) != population:
            raise ValueError("retrieval score and preferred-action populations differ")
        if (
            self.population_hard_applicability is not None
            and set(self.population_hard_applicability) != population
        ):
            raise ValueError("retrieval hard-applicability population differs")
        uses_hard_rule = self.retrieval_rule_id.startswith("hard-safe-")
        if uses_hard_rule != (self.population_hard_applicability is not None):
            raise ValueError("retrieval rule and hard-applicability evidence differ")
        if set(self.selected_case_ids) - population:
            raise ValueError("retrieval selected an unknown precedent")
        if len(self.selected_case_ids) != min(self.maximum_candidate_cases, len(population)):
            raise ValueError("retrieval selected-case count differs from the frozen top-k rule")
        ranked = _action_diverse_top_k_ids(
            self.population_scores,
            self.population_preferred_actions,
            maximum_candidate_cases=self.maximum_candidate_cases,
            hard_applicability=self.population_hard_applicability,
        )
        if self.selected_case_ids != ranked:
            raise ValueError("retrieval selection differs from outcome-hidden lexical top-k")
        expected = content_sha256(self.model_dump(mode="json", exclude={"retrieval_sha256"}))
        if self.retrieval_sha256 != expected:
            raise ValueError("counterfactual retrieval record hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualDeliberationRetrievalRecord:
        payload = {
            "schema_version": "1.0",
            "source_outcomes_hidden": True,
            "target_outcomes_hidden": True,
            **values,
        }
        payload.setdefault(
            "retrieval_rule_id",
            (
                "outcome-hidden-lexical-action-diverse-top-k-v1"
                if payload.get("population_hard_applicability") is None
                else "hard-safe-then-lexical-action-diverse-top-k-v2"
            ),
        )
        payload.pop("retrieval_sha256", None)
        unsigned = cls.model_construct(retrieval_sha256="0" * 64, **payload)
        return cls(
            **payload,
            retrieval_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"retrieval_sha256"})
            ),
        )


def prepare_counterfactual_deliberation_inputs(
    *,
    project_id: str,
    state_root: str | Path,
    precedent_root: str | Path,
    target_precedent_root: str | Path | None = None,
    output_root: str | Path,
    maximum_selected_cases: int = 3,
    maximum_candidate_cases: int | None = None,
) -> tuple[Path, ...]:
    """Build leave-one-task-cluster-out selector inputs without objective outcomes."""

    validate_project_id(project_id)
    if maximum_candidate_cases is not None and not 2 <= maximum_candidate_cases <= 20:
        raise ValueError("maximum_candidate_cases must be between 2 and 20")
    state_base = Path(state_root).resolve(strict=True)
    precedent_base = Path(precedent_root).resolve(strict=True)
    target_base = Path(output_root).expanduser()
    if target_base.exists() or target_base.is_symlink():
        raise FileExistsError(target_base)
    manifest = CounterfactualTastePrecedentManifest.model_validate_json(
        (precedent_base / "MANIFEST.json").read_bytes(), strict=True
    )
    if manifest.project_id != project_id:
        raise ValueError("counterfactual precedent manifest belongs to another project")
    library_path = precedent_base / "TASTE_LIBRARY.jsonl"
    if hashlib.sha256(library_path.read_bytes()).hexdigest() != manifest.library_sha256:
        raise ValueError("counterfactual precedent library hash differs from its manifest")
    cases = {item.case_id: item for item in TasteLibrary(library_path).all()}
    bindings = {item.case_id: item for item in manifest.bindings}
    if set(cases) != set(bindings):
        raise ValueError("counterfactual precedent library and manifest populations differ")
    target_manifest = manifest
    if target_precedent_root is not None:
        target_precedent_base = Path(target_precedent_root).resolve(strict=True)
        target_manifest = CounterfactualTastePrecedentManifest.model_validate_json(
            (target_precedent_base / "MANIFEST.json").read_bytes(), strict=True
        )
        if target_manifest.project_id != project_id:
            raise ValueError("counterfactual target manifest belongs to another project")
        missing_targets = {
            item.case_id for item in target_manifest.bindings
        } - set(bindings)
        if missing_targets:
            raise ValueError(
                "counterfactual target population is absent from the precedent library: "
                + ", ".join(sorted(missing_targets))
            )

    outputs = []
    target_base.mkdir(parents=True)
    for binding in target_manifest.bindings:
        state_dir = state_base / binding.study_id
        result = CounterfactualActionSetResult.model_validate_json(
            (state_dir / "RESULT.json").read_bytes(), strict=True
        )
        prefix = load_interactive_research_prefix(state_dir / "PREFIX.json")
        if (
            result.result_sha256 != binding.result_sha256
            or prefix.prefix_sha256 != binding.prefix_sha256
        ):
            raise ValueError("counterfactual deliberation state differs from precedent binding")
        excluded = tuple(
            sorted(
                item.case_id
                for item in manifest.bindings
                if item.task_cluster_id == binding.task_cluster_id
            )
        )
        eligible = tuple(
            cases[item.case_id]
            for item in manifest.bindings
            if item.task_cluster_id != binding.task_cluster_id
        )
        if len(eligible) < 2:
            raise ValueError("cross-cluster deliberation requires two or more precedents")
        deliberation_input, population = _deliberation_input(
            project_id=project_id,
            prefix=prefix,
            cases=eligible,
            maximum_selected_cases=maximum_selected_cases,
            maximum_candidate_cases=maximum_candidate_cases,
        )
        serialized_input = deliberation_input.model_dump_json(indent=2) + "\n"
        if "objective_value" in serialized_input or "outcome_summary" in serialized_input:
            raise ValueError("selector input leaked a precedent or target outcome")
        target = CounterfactualDeliberationTarget.create(
            study_id=result.study_id,
            target_case_id=binding.case_id,
            task_cluster_id=binding.task_cluster_id,
            prefix_sha256=result.prefix_sha256,
            result_sha256=result.result_sha256,
            excluded_same_cluster_case_ids=excluded,
            eligible_cross_cluster_case_ids=tuple(
                sorted(item.case_id for item in deliberation_input.candidates)
            ),
            objective_preferred_actions=tuple(
                sorted(item.value for item in result.preferred_actions)
            ),
            objective_values={
                item.action.value: item.objective_value for item in result.outcomes
            },
            objective_observed={
                item.action.value: item.objective_observed for item in result.outcomes
            },
            selector_input_sha256=deliberation_input.fingerprint,
        )
        retrieval = CounterfactualDeliberationRetrievalRecord.create(
            study_id=result.study_id,
            task_cluster_id=binding.task_cluster_id,
            maximum_candidate_cases=(
                len(population)
                if maximum_candidate_cases is None
                else maximum_candidate_cases
            ),
            population_scores={
                item.case_id: item.broad_retrieval_score
                for item in sorted(population, key=lambda item: item.case_id)
            },
            population_preferred_actions={
                item.case_id: item.preferred_action
                for item in sorted(population, key=lambda item: item.case_id)
            },
            population_hard_applicability=(
                {
                    item.case_id: item.hard_applicability_satisfied
                    for item in sorted(population, key=lambda item: item.case_id)
                }
                if all(item.hard_applicability_satisfied is not None for item in population)
                else None
            ),
            selected_case_ids=tuple(item.case_id for item in deliberation_input.candidates),
            selector_input_sha256=deliberation_input.fingerprint,
        )
        destination = target_base / result.study_id
        destination.mkdir()
        _write_new(destination / "INPUT.json", serialized_input.encode())
        _write_new(
            destination / "TARGET.json",
            (target.model_dump_json(indent=2) + "\n").encode(),
        )
        _write_new(
            destination / "RETRIEVAL.json",
            (retrieval.model_dump_json(indent=2) + "\n").encode(),
        )
        outputs.append(destination)
    return tuple(outputs)


def _deliberation_input(
    *,
    project_id: str,
    prefix: InteractiveResearchPrefix,
    cases: tuple[TasteCase, ...],
    maximum_selected_cases: int,
    maximum_candidate_cases: int | None,
) -> tuple[TasteDeliberationInput, tuple[TasteDeliberationCandidate, ...]]:
    latest = prefix.turns[-1].decision.proposal
    facts = [
        TasteDecisionFact(
            fact_id="fact-direction",
            kind="direction",
            text="Choose the next scientific action for hidden-law discovery.",
        ),
        TasteDecisionFact(
            fact_id="fact-domain",
            kind="domain",
            text="The current domain is computational hidden-law discovery.",
        ),
        TasteDecisionFact(
            fact_id="fact-stage",
            kind="stage",
            text=(
                f"interactive-experiment turn={prefix.turn_count}; "
                f"evidence_status={latest.evidence_status}; "
                f"evidence_confidence={latest.evidence_confidence:g}; "
                f"next_experiment_value={latest.next_experiment_value:g}."
            ),
        ),
        TasteDecisionFact(
            fact_id="fact-hypothesis",
            kind="hypothesis",
            text=latest.rationale,
        ),
    ]
    for turn in prefix.turns:
        observation = {
            key: value
            for key, value in turn.observation.items()
            if key not in {"task_id", "environment_sha256"}
        }
        facts.append(
            TasteDecisionFact(
                fact_id=f"fact-observation-{turn.turn:02d}",
                kind="observation",
                text=json.dumps(
                    {
                        "turn": turn.turn,
                        "proposal": turn.decision.proposal.model_dump(mode="json"),
                        "observation": observation,
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
    actions = tuple(
        ResearchAction(
            action_id=action.value,
            type=MetaAction(action.value),
            description=_ACTION_DESCRIPTIONS[action],
        )
        for action in CounterfactualResearchAction
    )
    current_text = " ".join(item.text for item in facts)
    target_observable = counterfactual_predecision_state(prefix)
    available_actions = {item.action_id for item in actions}
    population = tuple(
        _candidate(
            case,
            current_text=current_text,
            target_observable=target_observable,
            available_actions=available_actions,
        )
        for case in sorted(cases, key=lambda item: item.case_id)
    )
    population_by_id = {item.case_id: item for item in population}
    candidate_ids = _action_diverse_top_k_ids(
        {item.case_id: item.broad_retrieval_score for item in population},
        {item.case_id: item.preferred_action for item in population},
        maximum_candidate_cases=(
            len(population) if maximum_candidate_cases is None else maximum_candidate_cases
        ),
        hard_applicability=(
            {
                item.case_id: item.hard_applicability_satisfied
                for item in population
                if item.hard_applicability_satisfied is not None
            }
            if all(item.hard_applicability_satisfied is not None for item in population)
            else None
        ),
    )
    candidates = tuple(population_by_id[item] for item in candidate_ids)
    state_identity = content_sha256(
        {
            "project_id": project_id,
            "prefix_sha256": prefix.prefix_sha256,
            "facts": [item.model_dump(mode="json") for item in facts],
            "candidate_case_ids": [item.case_id for item in candidates],
        }
    )
    deliberation_input = TasteDeliberationInput(
        decision_id=f"counterfactual-taste-{state_identity[:20]}",
        state_snapshot_id=state_identity,
        stage="interactive-experiment",
        current_actions=actions,
        decision_facts=tuple(facts),
        candidates=candidates,
        maximum_selected_cases=min(maximum_selected_cases, len(candidates)),
    )
    return deliberation_input, population


def _action_diverse_top_k_ids(
    scores: dict[str, float],
    preferred_actions: dict[str, str],
    *,
    maximum_candidate_cases: int,
    hard_applicability: dict[str, bool] | None = None,
) -> tuple[str, ...]:
    """Rank by outcome-hidden similarity while preserving available action tension."""

    ranked = sorted(scores, key=lambda case_id: (-scores[case_id], case_id))
    if hard_applicability is not None and set(hard_applicability) != set(scores):
        raise ValueError("hard-applicability population differs from retrieval scores")
    selected: list[str] = []
    covered_actions: set[str] = set()
    groups = (
        (tuple(case_id for case_id in ranked if hard_applicability[case_id]), ranked)
        if hard_applicability is not None
        else (ranked,)
    )
    for group in groups:
        for case_id in group:
            if case_id in selected:
                continue
            action = preferred_actions[case_id]
            if action in covered_actions:
                continue
            selected.append(case_id)
            covered_actions.add(action)
            if len(selected) == maximum_candidate_cases:
                return tuple(selected)
        for case_id in group:
            if case_id not in selected:
                selected.append(case_id)
            if len(selected) == maximum_candidate_cases:
                return tuple(selected)
    return tuple(selected)


def _candidate(
    case: TasteCase,
    *,
    current_text: str,
    target_observable: CounterfactualPreDecisionState,
    available_actions: set[str],
) -> TasteDeliberationCandidate:
    safe_principle = (
        f"Prefer {case.preferred_action} only when the precedent's applicability conditions "
        "match the current visible hypothesis, uncertainty, and resource state; withhold the "
        "precedent whenever a failure condition is triggered."
    )
    safe_rationale = (
        f"The development precedent labels {case.preferred_action} as the locally preferred "
        "action. Raw source outcomes and their magnitudes are intentionally hidden from this "
        "transfer assessment."
    )
    safe_counterfactual = (
        "Would a change in the visible hypothesis, diagnostic evidence, uncertainty, remaining "
        f"budget, or failure conditions make {case.preferred_action} inapplicable?"
    )
    searchable = " ".join(
        filter(
            None,
            (
                case.context_summary,
                case.problem_pattern,
                case.evidence_state,
                safe_principle,
                safe_rationale,
                *case.applicability_conditions,
                *case.failure_conditions,
            ),
        )
    )
    similarity = lexical_similarity(current_text, searchable)
    hard_satisfied, hard_mismatches = _hard_applicability(
        case,
        target_observable=target_observable,
        available_actions=available_actions,
    )
    return TasteDeliberationCandidate(
        case_id=case.case_id,
        case_sha256=content_sha256(case.model_dump(mode="json")),
        taste_grounding_sha256=case.taste_grounding_sha256 or "0" * 64,
        source_identities=tuple(sorted({_source_identity(item) for item in case.provenance})),
        stage=case.stage,
        context_summary=case.context_summary,
        problem_pattern=case.problem_pattern,
        evidence_state=case.evidence_state,
        candidate_actions=tuple(case.candidate_actions),
        preferred_action=case.preferred_action,
        rejected_actions=tuple(case.rejected_actions),
        decision_principle=safe_principle,
        why_preferred=safe_rationale,
        applies_when=tuple(case.applicability_conditions),
        fails_when=tuple(case.failure_conditions),
        counterfactual_probe=safe_counterfactual,
        confidence=case.confidence,
        broad_retrieval_score=round(max(similarity, 0.000001), 6),
        broad_matched_fields=("outcome-hidden-content",),
        hard_applicability_satisfied=hard_satisfied,
        hard_applicability_mismatches=hard_mismatches,
    )


def _hard_applicability(
    case: TasteCase,
    *,
    target_observable: CounterfactualPreDecisionState,
    available_actions: set[str],
) -> tuple[bool | None, tuple[str, ...]]:
    if case.evidence_state is None:
        return None, ()
    try:
        source = CounterfactualPreDecisionState.model_validate_json(
            case.evidence_state,
            strict=True,
        )
    except (ValueError, TypeError):
        return None, ()
    mismatches = temporal_applicability_mismatches(
        source,
        target_observable,
        preferred_action=case.preferred_action,
        available_actions=available_actions,
    )
    return not mismatches, mismatches


def _source_identity(provenance: ProvenanceRecord) -> str:
    return "source-" + content_sha256(
        {
            "source_type": provenance.source_type,
            "locator": provenance.locator,
            "content_hash": provenance.content_hash,
            "version": provenance.version,
        }
    )


def _write_new(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


__all__ = [
    "CounterfactualDeliberationRetrievalRecord",
    "CounterfactualDeliberationTarget",
    "prepare_counterfactual_deliberation_inputs",
]

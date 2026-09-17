#!/usr/bin/env python3
"""Run the real Taste selector on reviewed boundary-pair development cases.

The target outcomes, registered utilities, and preferred actions remain outside
selector and decision prompts. Outcome-grounded Taste cards come only from
source-group-disjoint development precedents. This is a consumed-development
diagnostic and can change the method; it cannot enter the paper result table.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_scitastebench_contrastive_cards import ContrastiveTasteCard
from run_scitastebench_deliberative_selector_development import (
    _load_card_responses,
    _precedent_ids,
    _proposal,
)
from run_scitastebench_natural_development import _call

from scitaste.backends.base import PreferenceRequest, PreferenceResponse
from scitaste.backends.openai_compatible import (
    OpenAICompatibleBackend,
    load_openai_compatible_config,
)
from scitaste.benchmark import (
    BoundaryCounterfactualPair,
    BoundaryPairPackage,
    BoundaryPairState,
)
from scitaste.benchmark.models import BenchmarkCase
from scitaste.benchmark.runner import load_benchmark_suite
from scitaste.model_nodes import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.models import content_sha256
from scitaste.taste.deliberation import (
    TASTE_APPLICABILITY_NODE,
    TasteApplicabilityProposal,
    TasteDecisionFact,
    TasteDeliberationCandidate,
    TasteDeliberationInput,
    TasteDeliberationProposal,
    TasteTransferVerdict,
    merge_taste_applicability_proposals,
    shard_taste_deliberation_input,
    validate_taste_applicability,
)
from scitaste.taste.retriever import LocalTransformerTextEmbedder
from scitaste.taste.semantic import TasteApplicabilityNode

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class BoundaryDecisionConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1)
    evidence_role: Literal["consumed-development-only"]
    boundary_package: FileBinding
    source_suite: FileBinding
    screening_items: FileBinding
    outcome_vault: FileBinding
    card_corpus_summary: FileBinding
    card_response_root: str = Field(min_length=1)
    card_batch_size: int = Field(ge=1, le=20)
    selector_backend: FileBinding
    decision_backend: FileBinding
    embedding_model: str = Field(min_length=1)
    maximum_broad_candidates: int = Field(ge=2, le=20)
    selector_shard_size: int = Field(ge=2, le=8)
    context_token_budget: int = Field(ge=128, le=4_096)
    context_mode: Literal["contrastive-card", "grounded-capsule"] = "contrastive-card"
    frozen_selector_run: str | None = None
    frozen_decision_run: str | None = None
    reused_conditions: tuple[
        Literal["base", "raw_source", "matched_taste", "mismatched_taste"], ...
    ] = ()
    candidate_orders: tuple[Literal["declared", "reversed"], ...]
    conditions: tuple[
        Literal["base", "raw_source", "matched_taste", "mismatched_taste"], ...
    ]
    seed: int
    target_outcomes_visible: Literal[False]
    registered_labels_visible: Literal[False]
    formal_split_opened: Literal[False]
    effectiveness_claim_allowed: Literal[False]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--embedding-device", default=None)
    return parser


def _bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bound input must be a regular file: {path}")
    return path.read_bytes()


def _bound(root: Path, binding: FileBinding) -> Path:
    path = (root / binding.locator).resolve(strict=True)
    path.relative_to(root)
    if hashlib.sha256(_bytes(path)).hexdigest() != binding.sha256:
        raise ValueError(f"bound input hash mismatch: {binding.locator}")
    return path


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
    temporary.replace(path)


def _jsonl(path: Path) -> dict[str, dict[str, JsonValue]]:
    records: dict[str, dict[str, JsonValue]] = {}
    for line in _bytes(path).decode("utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"JSONL record must be an object: {path}")
        records[str(item["intake_candidate_id"])] = item
    return records


def _stage(pair: BoundaryCounterfactualPair) -> str:
    value = pair.decision_context_family.value
    if value == "problem-and-idea-value":
        return "IDEATION"
    if value == "hypothesis-and-falsifiability":
        return "HYPOTHESIS"
    if value == "experiment-design-and-confound-control":
        return "EXPERIMENT"
    if value == "evidence-interpretation-and-contradiction":
        return "ANALYSIS"
    if value == "resource-allocation-pivot-continue-or-stop":
        return "ADAPTATION"
    return "REVIEW"


def _card_text(card: ContrastiveTasteCard) -> str:
    return "\n".join(
        (
            f"Scientific preference: {card.preference}",
            "Applies when: " + "; ".join(card.applies_when),
            "Withhold or reverse when: " + "; ".join(card.reverse_when),
            f"Diagnostic question: {card.diagnostic_question}",
            f"Failure if misapplied: {card.failure_if_misapplied}",
            f"Outcome-grounded rationale: {card.source_outcome_rationale}",
        )
    )


def _raw_source(
    candidate_id: str,
    screens: dict[str, dict[str, JsonValue]],
    outcomes: dict[str, dict[str, JsonValue]],
) -> str:
    source = screens[candidate_id]
    outcome = outcomes[candidate_id]
    return (
        f"Prior source abstract:\n{source['reviewed_abstract']}\n\n"
        f"Prior decision context:\n{source['predecision_review_context']}\n\n"
        "Observed later record:\n"
        + json.dumps(outcome["outcome_payload"], ensure_ascii=False)
    )


def _fit_tokens(value: str, *, budget: int) -> str:
    words = value.split()
    if len(words) >= budget:
        return " ".join(words[:budget])
    filler = "No additional source-grounded information is available.".split()
    while len(words) < budget:
        words.extend(filler[: budget - len(words)])
    return " ".join(words)


def _source_candidate(
    candidate_id: str,
    *,
    source: BenchmarkCase,
    card: ContrastiveTasteCard,
    score: float,
) -> TasteDeliberationCandidate:
    actions = {item.action_id: item for item in source.candidate_actions}
    preferred = actions[source.preferred_action_id].description
    rejected = tuple(
        item.description
        for item in source.candidate_actions
        if item.action_id != source.preferred_action_id
    )
    grounding = {
        "candidate_id": candidate_id,
        "source_sha256": source.source_sha256,
        "card": card.model_dump(mode="json"),
    }
    return TasteDeliberationCandidate(
        case_id=candidate_id,
        case_sha256=content_sha256(source.model_dump(mode="json")),
        taste_grounding_sha256=content_sha256(grounding),
        source_identities=(source.source_group_id,),
        stage=source.stage,
        context_summary=source.decision_context[-8_000:],
        problem_pattern=str(source.decision_context_family),
        evidence_state=(
            f"decision_context_family={source.decision_context_family}; "
            f"taste_judgment_family={source.taste_judgment_family}"
        ),
        candidate_actions=tuple(item.description for item in source.candidate_actions),
        preferred_action=preferred,
        rejected_actions=rejected,
        decision_principle=card.preference,
        why_preferred=card.source_outcome_rationale,
        applies_when=card.applies_when,
        fails_when=card.reverse_when,
        counterfactual_probe=card.diagnostic_question,
        confidence=float(source.expert_distribution[source.preferred_action_id]),
        broad_retrieval_score=max(0.0, score),
        broad_matched_fields=("dense-outcome-grounded-card-retrieval",),
    )


def _document(source: BenchmarkCase, card: ContrastiveTasteCard) -> str:
    return " ".join(
        (
            source.domain,
            source.stage,
            str(source.decision_context_family),
            str(source.taste_judgment_family),
            card.preference,
            *card.applies_when,
            *card.reverse_when,
            card.diagnostic_question,
        )
    )


def _facts(
    pair: BoundaryCounterfactualPair,
    state: BoundaryPairState,
) -> tuple[TasteDecisionFact, ...]:
    return (
        TasteDecisionFact(
            fact_id="fact-direction",
            kind="direction",
            text=pair.changed_fact.question,
        ),
        TasteDecisionFact(fact_id="fact-domain", kind="domain", text=pair.domain),
        TasteDecisionFact(fact_id="fact-stage", kind="stage", text=_stage(pair)),
        TasteDecisionFact(
            fact_id="fact-boundary",
            kind="observation",
            text=(
                f"{pair.changed_fact.question} "
                + (
                    pair.changed_fact.base_value
                    if state.role.value == "base"
                    else pair.changed_fact.twin_value
                )
            ),
            boundary_candidate=True,
        ),
        TasteDecisionFact(
            fact_id="fact-observation",
            kind="observation",
            text=state.decision_context[-10_000:],
        ),
        TasteDecisionFact(
            fact_id="fact-obligation",
            kind="obligation",
            text=state.visible_budget,
        ),
        TasteDecisionFact(
            fact_id="fact-claim",
            kind="claim",
            text="; ".join(pair.invariant_facts)[:10_000],
        ),
    )


def _selector_input(
    pair: BoundaryCounterfactualPair,
    state_name: str,
    *,
    sources: dict[str, BenchmarkCase],
    cards: dict[str, ContrastiveTasteCard],
    embedder: LocalTransformerTextEmbedder,
    maximum_candidates: int,
) -> TasteDeliberationInput:
    state = pair.base if state_name == "base" else pair.twin
    eligible_ids = [
        candidate_id
        for candidate_id, source in sources.items()
        if candidate_id in cards and source.source_group_id != pair.source_group_id
    ]
    documents = tuple(_document(sources[item], cards[item]) for item in eligible_ids)
    query = " ".join(
        (
            pair.domain,
            _stage(pair),
            pair.decision_context_family.value,
            pair.taste_judgment_family.value,
            state.decision_context,
            *(action.description for action in pair.candidate_actions),
        )
    )
    scores = embedder.similarity_scores(query, documents)
    ranked = sorted(
        zip(eligible_ids, scores, strict=True),
        key=lambda item: (-item[1], item[0]),
    )[:maximum_candidates]
    actions = tuple(sorted(pair.candidate_actions, key=lambda item: item.action_id))
    identity = {
        "pair_id": pair.pair_id,
        "state": state_name,
        "actions": [item.action_id for item in actions],
        "candidate_ids": [item[0] for item in ranked],
    }
    return TasteDeliberationInput(
        decision_id=f"taste-{pair.pair_id.removeprefix('boundary-')}-{state_name}",
        state_snapshot_id=content_sha256(identity),
        stage=_stage(pair),
        current_actions=actions,
        decision_facts=_facts(pair, state),
        candidates=tuple(
            _source_candidate(
                candidate_id,
                source=sources[candidate_id],
                card=cards[candidate_id],
                score=score,
            )
            for candidate_id, score in ranked
        ),
        maximum_selected_cases=min(3, len(ranked)),
    )


def _run_selector(
    input_data: TasteDeliberationInput,
    *,
    backend: StructuredOpenAICompatibleBackend,
    root: Path,
    request_prefix: str,
    shard_size: int,
    seed: int,
    resume: bool,
) -> tuple[TasteDeliberationProposal | None, dict[str, JsonValue]]:
    result_path = root / "RESULT.json"
    proposal_path = root / "PROPOSAL.json"
    if resume and result_path.is_file():
        result = json.loads(_bytes(result_path))
        proposal = (
            TasteDeliberationProposal.model_validate_json(_bytes(proposal_path))
            if result["status"] == "accepted"
            else None
        )
        return proposal, result
    _write(root / "INPUT.json", input_data.model_dump(mode="json"))
    result: dict[str, JsonValue] = {
        "status": "invalid",
        "selected_case_ids": [],
        "recommended_action_id": None,
        "input_sha256": input_data.fingerprint,
    }
    try:
        proposals: list[TasteApplicabilityProposal] = []
        shards = shard_taste_deliberation_input(
            input_data,
            maximum_candidates_per_shard=shard_size,
        )
        for index, shard in enumerate(shards, 1):
            shard_root = root / "shards" / f"{index:02d}"
            _write(shard_root / "INPUT.json", shard.model_dump(mode="json"))
            response_path = shard_root / "runtime" / "response.json"
            if resume and response_path.is_file():
                response = json.loads(_bytes(response_path))
                payload = response["output_payload"]
            else:
                payload = _call(
                    backend=backend,
                    request_id=f"{request_prefix}-shard-{index:02d}",
                    node_name=TASTE_APPLICABILITY_NODE,
                    instruction=(
                        TasteApplicabilityNode.system_instruction
                        + f" This request contains exactly {len(shard.candidates)} candidate "
                        "cases. Return exactly one assessment for each case ID."
                    ),
                    payload=shard.model_dump(mode="json"),
                    schema=TasteApplicabilityProposal.model_json_schema(
                        mode="serialization"
                    ),
                    output_dir=shard_root / "runtime",
                    seed=seed + index,
                )
            proposal, _ = _proposal(payload, shard)
            findings = validate_taste_applicability(shard, proposal)
            _write(shard_root / "PROPOSAL.json", proposal.model_dump(mode="json"))
            if findings:
                raise ValueError("; ".join(findings))
            proposals.append(proposal)
        proposal = merge_taste_applicability_proposals(
            input_data,
            shard_inputs=shards,
            shard_proposals=proposals,
        )
        _write(proposal_path, proposal.model_dump(mode="json"))
        result.update(
            {
                "status": "accepted",
                "selected_case_ids": list(proposal.selected_case_ids),
                "recommended_action_id": proposal.recommended_action_id,
                "proposal_sha256": proposal.fingerprint,
            }
        )
    except Exception as exc:
        proposal = None
        result.update({"error_type": type(exc).__name__, "error": str(exc)})
    _write(result_path, result)
    return proposal, result


def _condition_sources(
    input_data: TasteDeliberationInput,
    proposal: TasteDeliberationProposal | None,
) -> tuple[list[str], list[str]]:
    if proposal is None:
        return [], []
    matched = list(proposal.selected_case_ids)
    matched_set = set(matched)
    assessment = {item.case_id: item for item in proposal.assessments}
    rejected = [
        item.case_id
        for item in sorted(
            input_data.candidates,
            key=lambda item: (-item.broad_retrieval_score, item.case_id),
        )
        if item.case_id not in matched_set
        and assessment[item.case_id].verdict is not TasteTransferVerdict.APPLICABLE
    ]
    if len(rejected) < len(matched):
        rejected.extend(
            item.case_id
            for item in sorted(
                input_data.candidates,
                key=lambda item: (-item.broad_retrieval_score, item.case_id),
            )
            if item.case_id not in matched_set and item.case_id not in rejected
        )
    return matched, rejected[: len(matched)]


def _added_context(
    condition: str,
    *,
    matched_ids: list[str],
    mismatched_ids: list[str],
    cards: dict[str, ContrastiveTasteCard],
    screens: dict[str, dict[str, JsonValue]],
    outcomes: dict[str, dict[str, JsonValue]],
    budget: int,
    context_mode: str,
) -> str | None:
    if not matched_ids:
        return None
    if condition == "matched_taste":
        selected_ids = matched_ids
    elif condition == "raw_source":
        values = [_raw_source(item, screens, outcomes) for item in matched_ids]
        return _fit_tokens("\n\n".join(values), budget=budget)
    elif condition == "mismatched_taste":
        if len(mismatched_ids) != len(matched_ids):
            return None
        selected_ids = mismatched_ids
    else:
        return None
    cards_text = "\n\n".join(_card_text(cards[item]) for item in selected_ids)
    if context_mode == "contrastive-card":
        return _fit_tokens(cards_text, budget=budget)
    card_budget = round(budget * 0.625)
    evidence_budget = budget - card_budget
    evidence_text = "\n\n".join(
        _raw_source(item, screens, outcomes) for item in selected_ids
    )
    return (
        _fit_tokens(cards_text, budget=card_budget)
        + " "
        + _fit_tokens(evidence_text, budget=evidence_budget)
    )


def _decision(
    *,
    pair: BoundaryCounterfactualPair,
    state_name: str,
    order: str,
    condition: str,
    added_context: str | None,
    backend: OpenAICompatibleBackend,
    path: Path,
    seed: int,
    resume: bool,
    base_response: PreferenceResponse | None,
    frozen_response: PreferenceResponse | None = None,
) -> PreferenceResponse:
    if frozen_response is not None:
        return frozen_response.model_copy(update={"cached": True})
    if condition != "base" and added_context is None:
        assert base_response is not None
        return base_response.model_copy(update={"cached": True})
    if resume and path.is_file():
        return PreferenceResponse.model_validate_json(_bytes(path))
    state = pair.base if state_name == "base" else pair.twin
    context = state.decision_context
    if added_context is not None:
        context += (
            "\n\nOutcome-grounded Scientific Taste precedents follow. They are fallible "
            "decision experience, not answer keys. Apply them only when their visible "
            "conditions fit this state.\n\n"
            + added_context
        )
    actions = list(pair.candidate_actions)
    if order == "reversed":
        actions.reverse()
    request = PreferenceRequest(
        request_id=f"{pair.pair_id}:{state_name}:{order}:{condition}",
        task=pair.decision_context_family.value,
        stage=_stage(pair),
        decision_context=context,
        candidate_actions=actions,
        seed=seed,
        prompt_version="scitastebench-boundary-decision-development-v1",
    )
    _write(path.parent / "REQUEST.json", request.model_dump(mode="json"))
    response = backend.rank(request)
    _write(path, response.model_dump(mode="json"))
    return response


def _state_regret(pair: BoundaryCounterfactualPair, state_name: str, action_id: str) -> float:
    state = pair.base if state_name == "base" else pair.twin
    return max(state.action_utilities.values()) - state.action_utilities[action_id]


def _analyze(
    pairs: tuple[BoundaryCounterfactualPair, ...],
    records: dict[tuple[str, str, str, str], PreferenceResponse],
    selector_records: dict[tuple[str, str], dict[str, JsonValue]],
    conditions: tuple[str, ...],
    orders: tuple[str, ...],
) -> dict[str, JsonValue]:
    state_names = ("base", "twin")
    metrics: dict[str, dict[str, JsonValue]] = {}
    for condition in conditions:
        correct = 0
        total = 0
        order_consistent = 0
        pair_success = 0
        pair_flip = 0
        pair_regrets: list[float] = []
        for pair in pairs:
            pair_correct = True
            pair_selections: dict[tuple[str, str], str] = {}
            for state_name in state_names:
                expected = (
                    pair.base.preferred_action_id
                    if state_name == "base"
                    else pair.twin.preferred_action_id
                )
                selections = [
                    records[(pair.pair_id, state_name, order, condition)].selected_action_id
                    for order in orders
                ]
                for order, selection in zip(orders, selections, strict=True):
                    pair_selections[(state_name, order)] = selection
                    correct += selection == expected
                    total += 1
                consistent = len(set(selections)) == 1
                order_consistent += consistent
                pair_correct = pair_correct and consistent and selections[0] == expected
            pair_success += pair_correct
            pair_flip += all(
                pair_selections[("base", order)] != pair_selections[("twin", order)]
                for order in orders
            )
            pair_regrets.append(
                sum(
                    _state_regret(
                        pair,
                        state_name,
                        pair_selections[(state_name, order)],
                    )
                    for state_name in state_names
                    for order in orders
                )
                / (len(state_names) * len(orders))
            )
        metrics[condition] = {
            "state_accuracy": correct / total,
            "order_consistency_rate": order_consistent / (len(pairs) * len(state_names)),
            "pair_success_rate": pair_success / len(pairs),
            "pair_flip_rate": pair_flip / len(pairs),
            "mean_budgeted_pair_regret": sum(pair_regrets) / len(pair_regrets),
            "pair_regrets": pair_regrets,
            "input_tokens": sum(
                records[(pair.pair_id, state_name, order, condition)].usage.input_tokens
                for pair in pairs
                for state_name in state_names
                for order in orders
                if not records[(pair.pair_id, state_name, order, condition)].cached
            ),
            "output_tokens": sum(
                records[(pair.pair_id, state_name, order, condition)].usage.output_tokens
                for pair in pairs
                for state_name in state_names
                for order in orders
                if not records[(pair.pair_id, state_name, order, condition)].cached
            ),
        }
    selected = [
        record
        for record in selector_records.values()
        if record["status"] == "accepted" and record["selected_case_ids"]
    ]
    matched = metrics["matched_taste"]
    return {
        "schema_version": "1.0",
        "analysis_scope": "consumed-development-boundary-decision",
        "pair_count": len(pairs),
        "state_count": 2 * len(pairs),
        "decision_call_slots": len(pairs) * 2 * len(orders) * len(conditions),
        "metrics": metrics,
        "selector_valid_state_count": sum(
            record["status"] == "accepted" for record in selector_records.values()
        ),
        "selector_intervention_state_count": len(selected),
        "selector_abstention_state_count": sum(
            record["status"] == "accepted" and not record["selected_case_ids"]
            for record in selector_records.values()
        ),
        "selector_invalid_state_count": sum(
            record["status"] != "accepted" for record in selector_records.values()
        ),
        "representation_gap_pair_success": (
            float(matched["pair_success_rate"])
            - float(metrics["raw_source"]["pair_success_rate"])
        ),
        "specificity_gap_pair_success": (
            float(matched["pair_success_rate"])
            - float(metrics["mismatched_taste"]["pair_success_rate"])
        ),
        "regret_improvement_over_base": (
            float(metrics["base"]["mean_budgeted_pair_regret"])
            - float(matched["mean_budgeted_pair_regret"])
        ),
        "development_gate": {
            "matched_regret_below_base": (
                float(matched["mean_budgeted_pair_regret"])
                < float(metrics["base"]["mean_budgeted_pair_regret"])
            ),
            "matched_regret_below_raw": (
                float(matched["mean_budgeted_pair_regret"])
                < float(metrics["raw_source"]["mean_budgeted_pair_regret"])
            ),
            "matched_regret_below_mismatched": (
                float(matched["mean_budgeted_pair_regret"])
                < float(metrics["mismatched_taste"]["mean_budgeted_pair_regret"])
            ),
            "matched_pair_success_above_base": (
                float(matched["pair_success_rate"])
                > float(metrics["base"]["pair_success_rate"])
            ),
            "selector_validity_at_least_95_percent": (
                sum(record["status"] == "accepted" for record in selector_records.values())
                / len(selector_records)
                >= 0.95
            ),
        },
        "formal_evidence_eligible": False,
        "new_confirmation_authorized": False,
        "claim_boundary": (
            "Consumed development pairs only; results may change the selector but cannot "
            "enter the submission result table."
        ),
    }


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_raw = _bytes(config_path)
    config = BoundaryDecisionConfig.model_validate(yaml.safe_load(config_raw))
    package_path = _bound(root, config.boundary_package)
    source_suite_path = _bound(root, config.source_suite)
    screens_path = _bound(root, config.screening_items)
    outcomes_path = _bound(root, config.outcome_vault)
    _bound(root, config.card_corpus_summary)
    selector_backend_path = _bound(root, config.selector_backend)
    decision_backend_path = _bound(root, config.decision_backend)
    package = BoundaryPairPackage.model_validate_json(_bytes(package_path))
    source_suite = load_benchmark_suite(source_suite_path)
    source_cases = {
        item.case_id.removeprefix("natural-"): item for item in source_suite.cases
    }
    ordered_card_ids = sorted(_precedent_ids(source_suite))
    card_root = (root / config.card_response_root).resolve(strict=True)
    card_root.relative_to(root)
    cards = _load_card_responses(
        ordered_ids=ordered_card_ids,
        response_root=card_root,
        batch_size=config.card_batch_size,
    )
    cards = {key: value for key, value in cards.items() if key in source_cases}
    if len(cards) < config.maximum_broad_candidates + 2:
        raise ValueError("outcome-grounded card corpus is too small for controls")
    source_cases = {key: value for key, value in source_cases.items() if key in cards}
    screens = _jsonl(screens_path)
    outcome_payload = json.loads(_bytes(outcomes_path))
    outcomes = {
        str(item["intake_candidate_id"]): item for item in outcome_payload["records"]
    }
    if not set(cards).issubset(screens) or not set(cards).issubset(outcomes):
        raise ValueError("card sources are missing raw records or outcomes")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema_version": "1.0",
        "run_id": config.run_id,
        "config_sha256": hashlib.sha256(config_raw).hexdigest(),
        "boundary_package_sha256": package.sha256,
        "pair_count": len(package.pairs),
        "state_count": 2 * len(package.pairs),
        "outcome_grounded_card_count": len(cards),
        "target_precedent_overlap_is_excluded_per_state": True,
        "target_outcomes_visible": False,
        "registered_labels_visible": False,
        "conditions": list(config.conditions),
        "candidate_orders": list(config.candidate_orders),
        "context_token_budget": config.context_token_budget,
        "context_mode": config.context_mode,
        "frozen_selector_run": config.frozen_selector_run,
        "frozen_decision_run": config.frozen_decision_run,
        "reused_conditions": list(config.reused_conditions),
        "api_execution_performed": args.allow_api,
        "formal_split_opened": False,
        "effectiveness_claim_allowed": False,
    }
    _write(output / "PLAN.json", plan)
    if not args.allow_api:
        return 0
    selector_config = load_structured_openai_compatible_config(selector_backend_path)
    decision_config = load_openai_compatible_config(decision_backend_path)
    if (selector_config.provider, selector_config.model) != (
        decision_config.provider,
        decision_config.model,
    ):
        raise ValueError("selector and decision backends must use the same provider/model")
    selector_backend = StructuredOpenAICompatibleBackend(selector_config)
    decision_backend = OpenAICompatibleBackend(decision_config)
    frozen_selector_root = (
        (root / config.frozen_selector_run).resolve(strict=True)
        if config.frozen_selector_run is not None
        else None
    )
    frozen_decision_root = (
        (root / config.frozen_decision_run).resolve(strict=True)
        if config.frozen_decision_run is not None
        else None
    )
    if frozen_selector_root is not None:
        frozen_selector_root.relative_to(root)
    if frozen_decision_root is not None:
        frozen_decision_root.relative_to(root)
    if config.reused_conditions and frozen_decision_root is None:
        raise ValueError("reused conditions require a frozen decision run")
    embedder = (
        None
        if frozen_selector_root is not None
        else LocalTransformerTextEmbedder(
            config.embedding_model,
            model_id="qwen3-embedding-0.6b",
            pooling="last-token",
            maximum_tokens=2_048,
            batch_size=4,
            query_instruction=(
                "Retrieve outcome-grounded Scientific Taste precedents whose applicability "
                "and reversal boundaries fit the current research decision."
            ),
            device=args.embedding_device,
        )
    )
    records: dict[tuple[str, str, str, str], PreferenceResponse] = {}
    selector_records: dict[tuple[str, str], dict[str, JsonValue]] = {}
    for pair_index, pair in enumerate(package.pairs, 1):
        for state_index, state_name in enumerate(("base", "twin"), 1):
            state_root = output / "pairs" / f"{pair_index:02d}-{pair.pair_id}" / state_name
            if frozen_selector_root is None:
                assert embedder is not None
                input_data = _selector_input(
                    pair,
                    state_name,
                    sources=source_cases,
                    cards=cards,
                    embedder=embedder,
                    maximum_candidates=config.maximum_broad_candidates,
                )
                proposal, selector_record = _run_selector(
                    input_data,
                    backend=selector_backend,
                    root=state_root / "selector",
                    request_prefix=f"{config.run_id}-{pair_index:02d}-{state_name}",
                    shard_size=config.selector_shard_size,
                    seed=config.seed + pair_index * 100 + state_index * 10,
                    resume=args.resume,
                )
            else:
                prior_selector = (
                    frozen_selector_root
                    / "pairs"
                    / f"{pair_index:02d}-{pair.pair_id}"
                    / state_name
                    / "selector"
                )
                input_data = TasteDeliberationInput.model_validate_json(
                    _bytes(prior_selector / "INPUT.json")
                )
                if any(
                    pair.source_group_id in candidate.source_identities
                    for candidate in input_data.candidates
                ):
                    raise ValueError("frozen selector input overlaps the target source group")
                selector_record = json.loads(_bytes(prior_selector / "RESULT.json"))
                proposal = (
                    TasteDeliberationProposal.model_validate_json(
                        _bytes(prior_selector / "PROPOSAL.json")
                    )
                    if selector_record["status"] == "accepted"
                    else None
                )
            selector_records[(pair.pair_id, state_name)] = selector_record
            matched_ids, mismatched_ids = _condition_sources(input_data, proposal)
            source_record = {
                "matched_ids": matched_ids,
                "mismatched_ids": mismatched_ids,
                "matched_source_groups": [
                    source_cases[item].source_group_id for item in matched_ids
                ],
                "mismatched_source_groups": [
                    source_cases[item].source_group_id for item in mismatched_ids
                ],
            }
            _write(state_root / "CONDITION_SOURCES.json", source_record)
            for order_index, order in enumerate(config.candidate_orders, 1):
                base_response: PreferenceResponse | None = None
                for condition in config.conditions:
                    added = _added_context(
                        condition,
                        matched_ids=matched_ids,
                        mismatched_ids=mismatched_ids,
                        cards=cards,
                        screens=screens,
                        outcomes=outcomes,
                        budget=config.context_token_budget,
                        context_mode=config.context_mode,
                    )
                    frozen_response = None
                    if condition in config.reused_conditions:
                        assert frozen_decision_root is not None
                        prior_response = (
                            frozen_decision_root
                            / "pairs"
                            / f"{pair_index:02d}-{pair.pair_id}"
                            / state_name
                            / order
                            / condition
                            / "RESPONSE.json"
                        )
                        if prior_response.is_file():
                            frozen_response = PreferenceResponse.model_validate_json(
                                _bytes(prior_response)
                            )
                        elif condition != "base" and base_response is not None:
                            frozen_response = base_response
                        else:
                            raise FileNotFoundError(prior_response)
                    response = _decision(
                        pair=pair,
                        state_name=state_name,
                        order=order,
                        condition=condition,
                        added_context=added,
                        backend=decision_backend,
                        path=state_root / order / condition / "RESPONSE.json",
                        seed=config.seed + pair_index * 1_000 + state_index * 100 + order_index,
                        resume=args.resume,
                        base_response=base_response,
                        frozen_response=frozen_response,
                    )
                    if condition == "base":
                        base_response = response
                    records[(pair.pair_id, state_name, order, condition)] = response
    report = _analyze(
        package.pairs,
        records,
        selector_records,
        tuple(config.conditions),
        tuple(config.candidate_orders),
    )
    report["plan_sha256"] = content_sha256(plan)
    _write(output / "REPORT.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

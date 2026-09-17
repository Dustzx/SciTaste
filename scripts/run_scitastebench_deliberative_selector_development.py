#!/usr/bin/env python3
"""Exercise the real SciTaste deliberative selector on consumed natural cases.

This runner is intentionally development-only.  It translates the contrastive
Taste cards already built from development precedents into the same bounded
``TasteDeliberationInput`` used by SciTaste's live controller.  Target outcomes and
proxy-preferred actions stay out of every selector request and are opened only
after both candidate-order arms have terminal receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from build_scitastebench_contrastive_cards import (
    ContrastiveCardBatch,
    ContrastiveTasteCard,
)
from run_scitastebench_natural_development import _call

from scitaste.benchmark.models import BenchmarkCase, BenchmarkSuite
from scitaste.benchmark.runner import load_benchmark_suite
from scitaste.model_nodes.openai_compatible import (
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
    merge_taste_applicability_proposals,
    shard_taste_deliberation_input,
    validate_taste_applicability,
)
from scitaste.taste.retriever import LocalTransformerTextEmbedder
from scitaste.taste.semantic import TasteApplicabilityNode

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _precedent_ids(suite: BenchmarkSuite) -> set[str]:
    result: set[str] = set()
    for case in suite.cases:
        result.update(item.removeprefix("taste-") for item in case.taste_precedent_ids)
        result.update(item.removeprefix("taste-") for item in case.placebo_precedent_ids)
    return result


def _load_card_responses(
    *,
    ordered_ids: list[str],
    response_root: Path,
    batch_size: int,
) -> dict[str, ContrastiveTasteCard]:
    cards: dict[str, ContrastiveTasteCard] = {}
    batches = [
        ordered_ids[index : index + batch_size]
        for index in range(0, len(ordered_ids), batch_size)
    ]
    for ordinal, candidate_batch in enumerate(batches, 1):
        response_path = response_root / f"{ordinal:02d}" / "response.json"
        response = json.loads(response_path.read_text(encoding="utf-8"))
        result = ContrastiveCardBatch.model_validate(response["output_payload"])
        positions = [item.position for item in result.cards]
        if sorted(positions) != list(range(1, len(candidate_batch) + 1)):
            raise ValueError(f"card batch {response_path} has inconsistent positions")
        for card in result.cards:
            cards[candidate_batch[card.position - 1]] = card
    return cards


def _load_cards(args: argparse.Namespace, target_suite: BenchmarkSuite) -> dict[str, Any]:
    desired_ids = _precedent_ids(target_suite)
    reused_suite = load_benchmark_suite(args.reused_card_suite)
    reused_ids = sorted(_precedent_ids(reused_suite))
    reused_cards = _load_card_responses(
        ordered_ids=reused_ids,
        response_root=args.reused_card_responses,
        batch_size=args.reused_card_batch_size,
    )
    cards = {key: value for key, value in reused_cards.items() if key in desired_ids}
    pending_ids = sorted(desired_ids - set(cards))
    new_cards = _load_card_responses(
        ordered_ids=pending_ids,
        response_root=args.new_card_responses,
        batch_size=args.new_card_batch_size,
    )
    overlap = set(cards) & set(new_cards)
    if overlap:
        raise ValueError("reused and new card responses overlap")
    cards.update(new_cards)
    if set(cards) != desired_ids:
        raise ValueError("structured card corpus does not cover the target suite precedents")
    return cards


def _parts(case: BenchmarkCase) -> tuple[str, str, str]:
    marker_review = "\n\nPre-decision review context:\n"
    marker_decision = "\n\nDecision:\n"
    if not case.decision_context.startswith("Article context:\n"):
        raise ValueError(f"case {case.case_id!r} has an unknown decision rendering")
    article_and_rest = case.decision_context.removeprefix("Article context:\n")
    article, review_and_decision = article_and_rest.split(marker_review, 1)
    review, decision = review_and_decision.rsplit(marker_decision, 1)
    return article.strip(), review.strip(), decision.strip()


def _tokens(value: str) -> set[str]:
    return {item.casefold() for item in _WORD.findall(value)}


def _lexical_scores(
    target: BenchmarkCase,
    source_cases: dict[str, BenchmarkCase],
    cards: dict[str, ContrastiveTasteCard],
    *,
    embedding_backend: LocalTransformerTextEmbedder | None,
) -> dict[str, float]:
    _, target_review, target_question = _parts(target)
    query = _tokens(
        " ".join(
            (
                target.domain,
                target.stage,
                str(target.decision_context_family or ""),
                target_question,
                target_review[-4_000:],
                *(item.description for item in target.candidate_actions),
            )
        )
    )
    documents: dict[str, set[str]] = {}
    for candidate_id, card in cards.items():
        source = source_cases[candidate_id]
        _, source_review, source_question = _parts(source)
        documents[candidate_id] = _tokens(
            " ".join(
                (
                    card.preference,
                    *card.applies_when,
                    *card.reverse_when,
                    card.diagnostic_question,
                    source_question,
                    source_review[-2_000:],
                )
            )
        )
    if embedding_backend is not None:
        document_texts = []
        for candidate_id, card in cards.items():
            source = source_cases[candidate_id]
            _, source_review, source_question = _parts(source)
            document_texts.append(
                " ".join(
                    (
                        card.preference,
                        *card.applies_when,
                        *card.reverse_when,
                        card.diagnostic_question,
                        source_question,
                        source_review[-4_000:],
                    )
                )
            )
        query_text = " ".join(
            (
                target.domain,
                target.stage,
                str(target.decision_context_family or ""),
                target_question,
                target_review[-8_000:],
                *(item.description for item in target.candidate_actions),
            )
        )
        scores = embedding_backend.similarity_scores(query_text, tuple(document_texts))
        return {
            candidate_id: score
            for candidate_id, score in zip(cards, scores, strict=True)
        }
    document_count = len(documents)
    frequencies = Counter(token for value in documents.values() for token in value)
    scores: dict[str, float] = {}
    for candidate_id, document in documents.items():
        overlap = query & document
        weighted = math.fsum(
            math.log((document_count + 1) / (frequencies[token] + 1)) + 1.0
            for token in overlap
        )
        normalization = math.sqrt(max(1, len(query)) * max(1, len(document)))
        scores[candidate_id] = weighted / normalization
    return scores


def _candidate(
    candidate_id: str,
    *,
    source: BenchmarkCase,
    card: ContrastiveTasteCard,
    score: float,
) -> TasteDeliberationCandidate:
    _, source_review, source_question = _parts(source)
    action_by_id = {item.action_id: item for item in source.candidate_actions}
    preferred = action_by_id[source.preferred_action_id].description
    rejected = tuple(
        item.description
        for item in source.candidate_actions
        if item.action_id != source.preferred_action_id
    )
    candidate_actions = tuple(item.description for item in source.candidate_actions)
    grounding = {
        "candidate_id": candidate_id,
        "card": card.model_dump(mode="json"),
        "source_sha256": source.source_sha256,
    }
    return TasteDeliberationCandidate(
        case_id=candidate_id,
        case_sha256=content_sha256(
            {
                "source_case_sha256": content_sha256(source.model_dump(mode="json")),
                "card": card.model_dump(mode="json"),
            }
        ),
        taste_grounding_sha256=content_sha256(grounding),
        source_identities=(source.source_group_id,),
        stage=source.stage,
        context_summary=(
            f"Domain: {source.domain}. Decision: {source_question}. "
            f"Visible review context: {source_review[-3_000:]}"
        ),
        problem_pattern=source_question,
        evidence_state=(
            f"decision_context_family={source.decision_context_family}; "
            f"taste_judgment_family={source.taste_judgment_family}"
        ),
        candidate_actions=candidate_actions,
        preferred_action=preferred,
        rejected_actions=rejected,
        decision_principle=card.preference,
        why_preferred=card.source_outcome_rationale,
        applies_when=card.applies_when,
        fails_when=card.reverse_when,
        counterfactual_probe=card.diagnostic_question,
        confidence=source.expert_distribution[source.preferred_action_id],
        broad_retrieval_score=max(0.0, score),
        broad_matched_fields=("outcome-hidden-broad-retrieval",),
    )


def _facts(case: BenchmarkCase) -> tuple[TasteDecisionFact, ...]:
    article, review, question = _parts(case)
    raw = (
        ("direction", question),
        ("domain", case.domain),
        ("stage", case.stage),
        ("observation", article[:9_000]),
        ("obligation", review[-9_000:]),
    )
    return tuple(
        TasteDecisionFact(
            fact_id=f"fact-{index}",
            kind=kind,
            text=text,
        )
        for index, (kind, text) in enumerate(raw, 1)
    )


def _input(
    case: BenchmarkCase,
    *,
    order: str,
    source_cases: dict[str, BenchmarkCase],
    cards: dict[str, ContrastiveTasteCard],
    maximum_candidates: int,
    embedding_backend: LocalTransformerTextEmbedder | None,
) -> TasteDeliberationInput:
    scores = _lexical_scores(
        case,
        source_cases,
        cards,
        embedding_backend=embedding_backend,
    )
    ranked = sorted(scores, key=lambda item: (-scores[item], item))[:maximum_candidates]
    # The selector consumes action identities, not their presentation order.  The
    # evaluated decision backend still receives declared/reversed arms separately.
    actions = tuple(sorted(case.candidate_actions, key=lambda item: item.action_id))
    snapshot = {
        "case_id": case.case_id,
        "source_sha256": case.source_sha256,
        "action_ids": sorted(item.action_id for item in actions),
        "candidate_ids": ranked,
    }
    return TasteDeliberationInput(
        decision_id=f"selector-{case.case_id.removeprefix('natural-')}",
        state_snapshot_id=content_sha256(snapshot),
        stage=case.stage,
        current_actions=actions,
        decision_facts=_facts(case),
        candidates=tuple(
            _candidate(
                candidate_id,
                source=source_cases[candidate_id],
                card=cards[candidate_id],
                score=scores[candidate_id],
            )
            for candidate_id in ranked
        ),
        maximum_selected_cases=min(3, len(ranked)),
    )


def _proposal(
    payload: dict[str, Any], input_data: TasteDeliberationInput
) -> tuple[TasteApplicabilityProposal, int]:
    normalized = dict(payload)
    normalized["decision_id"] = input_data.decision_id
    if normalized.get("type") == "json_object":
        normalized.pop("type")
    verdict_alias_count = 0
    assessments = normalized.get("assessments")
    if isinstance(assessments, list):
        for item in assessments:
            if not isinstance(item, dict):
                continue
            if item.get("verdict") in {"not_applicable", "not-applicable"}:
                item["verdict"] = "inapplicable"
                verdict_alias_count += 1
    return TasteApplicabilityProposal.model_validate(normalized), verdict_alias_count


def _analyze(
    *,
    target_cases: tuple[BenchmarkCase, ...],
    source_cases: dict[str, BenchmarkCase],
    records: dict[tuple[str, str], dict[str, Any]],
    base_reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    case_by_id = {item.case_id: item for item in target_cases}
    orders = ("declared", "reversed")
    terminal = [records[(order, case_id)] for order in orders for case_id in case_by_id]
    accepted = [item for item in terminal if item["status"] == "accepted"]
    recommendations = {
        (order, case_id): records[(order, case_id)].get("recommended_action_id")
        for order in orders
        for case_id in case_by_id
    }
    base_results = {
        (order, item["case_id"]): item
        for order in orders
        for item in base_reports[order]["conditions"]["base"]["results"]
        if item["case_id"] in case_by_id
    }
    final_actions = {
        (order, case_id): (
            recommendations[(order, case_id)]
            or base_results[(order, case_id)]["selected_action_id"]
        )
        for order in orders
        for case_id in case_by_id
    }
    correct_by_order = {
        order: sum(
            final_actions[(order, case_id)] == case.preferred_action_id
            for case_id, case in case_by_id.items()
        )
        / len(case_by_id)
        for order in orders
    }
    order_consistent_correct = sum(
        final_actions[("declared", case_id)]
        == final_actions[("reversed", case_id)]
        == case.preferred_action_id
        for case_id, case in case_by_id.items()
    )
    order_consistent_recommendation = sum(
        final_actions[("declared", case_id)] == final_actions[("reversed", case_id)]
        for case_id in case_by_id
    )
    selected_actions = []
    selected_sources = []
    same_family = 0
    for item in accepted:
        recommendation = item.get("recommended_action_id")
        if recommendation is not None:
            target = case_by_id[item["case_id"]]
            action = next(
                action for action in target.candidate_actions if action.action_id == recommendation
            )
            selected_actions.append(action.type.value)
        for source_id in item.get("selected_case_ids", []):
            selected_sources.append(source_id)
            if (
                source_cases[source_id].taste_judgment_family
                == case_by_id[item["case_id"]].taste_judgment_family
            ):
                same_family += 1
    source_count = len(selected_sources)
    base_order_accuracy = {
        order: sum(
            base_results[(order, case_id)]["correct"] for case_id in case_by_id
        )
        / len(case_by_id)
        for order in orders
    }
    base_order_consistency = sum(
        base_results[("declared", case_id)]["selected_action_id"]
        == base_results[("reversed", case_id)]["selected_action_id"]
        for case_id in case_by_id
    ) / len(case_by_id)
    base_consistent = sum(
        all(
            next(
                item
                for item in base_reports[order]["conditions"]["base"]["results"]
                if item["case_id"] == case_id
            )["correct"]
            for order in orders
        )
        for case_id in case_by_id
    ) / len(case_by_id)
    behavior_changes = {
        order: [
            case_id
            for case_id in case_by_id
            if final_actions[(order, case_id)]
            != base_results[(order, case_id)]["selected_action_id"]
        ]
        for order in orders
    }
    improvements = {
        order: sum(
            final_actions[(order, case_id)] == case_by_id[case_id].preferred_action_id
            and not base_results[(order, case_id)]["correct"]
            for case_id in behavior_changes[order]
        )
        for order in orders
    }
    regressions = {
        order: sum(
            final_actions[(order, case_id)] != case_by_id[case_id].preferred_action_id
            and base_results[(order, case_id)]["correct"]
            for case_id in behavior_changes[order]
        )
        for order in orders
    }
    selector_validity_rate = len(accepted) / len(terminal)
    development_gate = {
        "selector_validity_at_least_95_percent": selector_validity_rate >= 0.95,
        "policy_order_consistency_not_below_base": (
            order_consistent_recommendation / len(case_by_id) >= base_order_consistency
        ),
        "accuracy_exceeds_base_in_both_orders": all(
            correct_by_order[order] > base_order_accuracy[order] for order in orders
        ),
        "order_consistent_accuracy_exceeds_base": (
            order_consistent_correct / len(case_by_id) > base_consistent
        ),
        "more_improvements_than_regressions_in_both_orders": all(
            improvements[order] > regressions[order] for order in orders
        ),
        "multiple_action_types_selected": len(set(selected_actions)) >= 3,
    }
    return {
        "schema_version": "1.0",
        "analysis_scope": "consumed-split-deliberative-selector-development",
        "case_count": len(case_by_id),
        "selector_invocation_count": len(terminal),
        "accepted_invocation_count": len(accepted),
        "invalid_invocation_count": len(terminal) - len(accepted),
        "selector_validity_rate": selector_validity_rate,
        "recommendation_coverage_by_order": {
            order: sum(
                recommendations[(order, case_id)] is not None for case_id in case_by_id
            )
            / len(case_by_id)
            for order in orders
        },
        "taste_override_accuracy_by_order": {
            order: (
                sum(
                    recommendations[(order, case_id)] == case.preferred_action_id
                    for case_id, case in case_by_id.items()
                    if recommendations[(order, case_id)] is not None
                )
                / sum(
                    recommendations[(order, case_id)] is not None
                    for case_id in case_by_id
                )
                if any(
                    recommendations[(order, case_id)] is not None
                    for case_id in case_by_id
                )
                else None
            )
            for order in orders
        },
        "full_policy_accuracy_by_order": correct_by_order,
        "full_policy_order_consistency_rate": (
            order_consistent_recommendation / len(case_by_id)
        ),
        "full_policy_order_consistent_accuracy": order_consistent_correct / len(case_by_id),
        "base_accuracy_by_order": base_order_accuracy,
        "base_order_consistency_rate": base_order_consistency,
        "base_order_consistent_accuracy": base_consistent,
        "behavior_change_count_by_order": {
            order: len(behavior_changes[order]) for order in orders
        },
        "behavior_change_rate_by_order": {
            order: len(behavior_changes[order]) / len(case_by_id) for order in orders
        },
        "improvement_count_by_order": improvements,
        "regression_count_by_order": regressions,
        "action_type_counts": dict(sorted(Counter(selected_actions).items())),
        "selected_precedent_count": source_count,
        "selected_precedent_same_broad_family_rate": (
            same_family / source_count if source_count else None
        ),
        "development_gate": development_gate,
        "fresh_split_candidate_after_specificity_control": all(development_gate.values()),
        "remaining_gate_before_fresh_split": (
            "matched-versus-token-and-source-matched-mismatched applicability control"
        ),
        "new_confirmation_authorized": False,
        "claim_boundary": (
            "Consumed failure cases only. This run can debug the real SciTaste selector but "
            "cannot estimate a revised method effect or enter the submission evidence set."
        ),
    }


def run(args: argparse.Namespace) -> None:
    if args.output.exists() and not args.analyze_existing:
        raise FileExistsError(args.output)
    if not args.output.exists() and args.analyze_existing:
        raise FileNotFoundError(args.output)
    args.output.mkdir(parents=True, exist_ok=args.analyze_existing)
    target_suite = load_benchmark_suite(args.target_suite)
    target_cases = tuple(
        target_suite.cases[: args.maximum_target_cases]
        if args.maximum_target_cases is not None
        else target_suite.cases
    )
    source_suite = load_benchmark_suite(args.source_suite)
    source_cases = {
        item.case_id.removeprefix("natural-"): item for item in source_suite.cases
    }
    cards = _load_cards(args, target_suite)
    if not set(cards).issubset(source_cases):
        raise ValueError("card corpus includes precedents absent from the source suite")
    target_groups = {item.source_group_id for item in target_suite.cases}
    source_groups = {source_cases[item].source_group_id for item in cards}
    if target_groups & source_groups:
        raise ValueError("deliberative selector target and precedent source groups overlap")

    backend = StructuredOpenAICompatibleBackend(
        load_structured_openai_compatible_config(args.backend)
    )
    embedding_backend = None
    if not args.analyze_existing:
        embedding_backend = LocalTransformerTextEmbedder(
            args.embedding_model,
            model_id="qwen3-embedding-0.6b",
            pooling="last-token",
            maximum_tokens=args.embedding_maximum_tokens,
            batch_size=args.embedding_batch_size,
            query_instruction=(
                "Retrieve Scientific Taste precedents whose decision principle, evidence "
                "state, and applicability boundaries fit the current research decision."
            ),
            device=args.embedding_device,
        )
    if args.analyze_existing:
        plan = json.loads((args.output / "PLAN.json").read_text(encoding="utf-8"))
    else:
        plan = {
            "schema_version": "1.0",
            "run_id": args.run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "target_suite": str(args.target_suite),
            "target_suite_sha256": target_suite.sha256,
            "source_suite": str(args.source_suite),
            "source_suite_sha256": source_suite.sha256,
            "target_case_count": len(target_cases),
            "precedent_case_count": len(cards),
            "target_precedent_source_group_overlap_count": 0,
            "candidate_orders": ["declared", "reversed"],
            "maximum_broad_candidates": args.maximum_candidates,
            "maximum_candidates_per_shard": args.shard_size,
            "deterministic_shard_merge": True,
            "broad_retrieval_algorithm": (
                embedding_backend.algorithm_id if embedding_backend is not None else "none"
            ),
            "selector_backend": backend.name,
            "selector_model": backend.model,
            "target_outcomes_visible_to_selector": False,
            "target_proxy_labels_visible_to_selector": False,
            "raw_source_outcomes_visible_to_selector": False,
            "development_only": True,
            "new_confirmation_authorized": False,
        }
        _write_json(args.output / "PLAN.json", plan)

    records: dict[tuple[str, str], dict[str, Any]] = {}
    for order in ("declared", "reversed"):
        for index, case in enumerate(target_cases, 1):
            invocation_root = args.output / order / f"{index:03d}-{case.case_id}"
            if args.analyze_existing:
                record = json.loads(
                    (invocation_root / "RESULT.json").read_text(encoding="utf-8")
                )
                records[(order, case.case_id)] = record
                continue
            input_data = _input(
                case,
                order=order,
                source_cases=source_cases,
                cards=cards,
                maximum_candidates=args.maximum_candidates,
                embedding_backend=embedding_backend,
            )
            _write_json(invocation_root / "INPUT.json", input_data.model_dump(mode="json"))
            shard_inputs = shard_taste_deliberation_input(
                input_data,
                maximum_candidates_per_shard=args.shard_size,
            )
            record: dict[str, Any] = {
                "case_id": case.case_id,
                "candidate_order": order,
                "input_sha256": input_data.fingerprint,
                "status": "invalid",
                "recommended_action_id": None,
                "selected_case_ids": [],
                "shard_count": len(shard_inputs),
                "completed_shard_count": 0,
            }
            try:
                proposals: list[TasteApplicabilityProposal] = []
                verdict_alias_count = 0
                for shard_index, shard_input in enumerate(shard_inputs, 1):
                    shard_root = invocation_root / "shards" / f"{shard_index:02d}"
                    _write_json(shard_root / "INPUT.json", shard_input.model_dump(mode="json"))
                    payload = _call(
                        backend=backend,
                        request_id=(
                            f"{args.run_id}-{order}-{index:03d}-shard-{shard_index:02d}"
                        ),
                        node_name=TASTE_APPLICABILITY_NODE,
                        instruction=(
                            TasteApplicabilityNode.system_instruction
                            + f" This request contains exactly {len(shard_input.candidates)} "
                            "candidate cases. Return exactly one assessment for each candidate "
                            "case ID and no duplicate or additional assessment."
                        ),
                        payload=shard_input.model_dump(mode="json"),
                        schema=TasteApplicabilityProposal.model_json_schema(
                            mode="serialization"
                        ),
                        output_dir=shard_root / "runtime",
                        seed=(
                            args.seed
                            + index
                            + shard_index * 1_000
                        ),
                    )
                    proposal, aliases = _proposal(payload, shard_input)
                    findings = validate_taste_applicability(shard_input, proposal)
                    _write_json(
                        shard_root / "PROPOSAL.json",
                        proposal.model_dump(mode="json"),
                    )
                    if findings:
                        raise ValueError("; ".join(findings))
                    proposals.append(proposal)
                    verdict_alias_count += aliases
                    record["completed_shard_count"] = shard_index
                proposal = merge_taste_applicability_proposals(
                    input_data,
                    shard_inputs=shard_inputs,
                    shard_proposals=proposals,
                )
                _write_json(invocation_root / "PROPOSAL.json", proposal.model_dump(mode="json"))
                record.update(
                    {
                        "status": "accepted",
                        "recommended_action_id": proposal.recommended_action_id,
                        "selected_case_ids": list(proposal.selected_case_ids),
                        "proposal_sha256": proposal.fingerprint,
                        "verdict_alias_normalization_count": verdict_alias_count,
                    }
                )
            except Exception as exc:  # retained development failure, never silently retried
                record["error_type"] = type(exc).__name__
                record["error"] = str(exc)
            _write_json(invocation_root / "RESULT.json", record)
            records[(order, case.case_id)] = record

    base_reports = {
        "declared": json.loads(args.base_declared.read_text(encoding="utf-8")),
        "reversed": json.loads(args.base_reversed.read_text(encoding="utf-8")),
    }
    if any(
        item["suite_sha256"] != target_suite.sha256 for item in base_reports.values()
    ):
        raise ValueError("base reports differ from the deliberative target suite")
    report = _analyze(
        target_cases=target_cases,
        source_cases=source_cases,
        records=records,
        base_reports=base_reports,
    )
    report["plan_sha256"] = content_sha256(plan)
    report["backend_config_sha256"] = _sha(args.backend)
    _write_json(args.output / "REPORT.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    root = Path("outputs/projects/scitaste-self-development/evaluations")
    parser.add_argument("--run-id", default="scitastebench-deliberative-development-v5")
    parser.add_argument(
        "--target-suite",
        type=Path,
        default=root / "scitastebench-natural-contrastive-confirmation-v2/SUITE.yaml",
    )
    parser.add_argument(
        "--source-suite",
        type=Path,
        default=root / "scitastebench-natural-development-v5/SUITE.yaml",
    )
    parser.add_argument(
        "--reused-card-suite",
        type=Path,
        default=root / "scitastebench-natural-development-v5/SUITE.yaml",
    )
    parser.add_argument(
        "--reused-card-responses",
        type=Path,
        default=root / "scitastebench-natural-contrastive-development-v1/card-construction",
    )
    parser.add_argument("--reused-card-batch-size", type=int, default=6)
    parser.add_argument(
        "--new-card-responses",
        type=Path,
        default=(
            root
            / "scitastebench-natural-contrastive-confirmation-v2/card-construction"
        ),
    )
    parser.add_argument("--new-card-batch-size", type=int, default=6)
    parser.add_argument(
        "--base-declared",
        type=Path,
        default=(
            root
            / "scitastebench-natural-contrastive-confirmation-v2/deepseek-declared/"
            "benchmark_report.json"
        ),
    )
    parser.add_argument(
        "--base-reversed",
        type=Path,
        default=(
            root
            / "scitastebench-natural-contrastive-confirmation-v2/deepseek-reversed/"
            "benchmark_report.json"
        ),
    )
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/deepseek_v41flash.scitastebench_live_20260917.yaml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "scitastebench-deliberative-development-v5",
    )
    parser.add_argument("--maximum-candidates", type=int, default=6)
    parser.add_argument("--shard-size", type=int, default=3)
    parser.add_argument(
        "--embedding-model",
        type=Path,
        default=Path("/media/good/dxhismyson/weights/Qwen3-Embedding-0.6B"),
    )
    parser.add_argument("--embedding-device", default=None)
    parser.add_argument("--embedding-maximum-tokens", type=int, default=2_048)
    parser.add_argument("--embedding-batch-size", type=int, default=4)
    parser.add_argument("--maximum-target-cases", type=int, default=None)
    parser.add_argument("--seed", type=int, default=6027)
    parser.add_argument("--analyze-existing", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())

#!/usr/bin/env python3
"""Build a token-matched natural pilot with contrastive Taste cards.

Cards are generated only from a precedent's own pre-decision record and later
outcome.  A held-out target is never shown during card construction.  The
resulting raw, matched-card, and mismatched-card contexts are matched to the
same deterministic lexical-token budget for a direct mechanism comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from scitaste.benchmark.models import (
    BenchmarkCondition,
    BenchmarkSuite,
    ContrastDifference,
    ContrastPrimaryEndpoint,
    MechanismContextBundle,
    ReferenceDomainRelation,
    ReferenceRepresentation,
    ReferenceSourceArtifact,
    ReferenceTreatmentArm,
    ReferenceTreatmentContext,
    RegisteredBenchmarkContrast,
)
from scitaste.benchmark.runner import load_benchmark_suite
from scitaste.evaluation.scitastebench_development_intake import (
    DevelopmentOutcomeVaultRecord,
    DevelopmentScreeningItem,
)
from scitaste.evaluation.scitastebench_development_panel import (
    DevelopmentPanelDecisionRecord,
)
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_TOKENIZER_SPEC = (
    "scitaste-whitespace-tokenizer-v1: split Unicode text on whitespace after "
    "normalizing every run of whitespace to one ASCII space"
)
_TOKENIZER_SHA = hashlib.sha256(_TOKENIZER_SPEC.encode()).hexdigest()
_RENDER_TEMPLATE = (
    "Preference; Applies when; Withhold or reverse when; Diagnostic question; "
    "Failure if misapplied; Source-outcome rationale"
)
_RENDER_TEMPLATE_SHA = hashlib.sha256(_RENDER_TEMPLATE.encode()).hexdigest()


class ContrastiveTasteCard(BaseModel):
    model_config = _CONFIG

    position: int = Field(gt=0, le=12)
    preference: str = Field(min_length=1, max_length=500)
    applies_when: tuple[str, ...] = Field(min_length=2, max_length=3)
    reverse_when: tuple[str, ...] = Field(min_length=2, max_length=3)
    diagnostic_question: str = Field(min_length=1, max_length=350)
    failure_if_misapplied: str = Field(min_length=1, max_length=350)
    source_outcome_rationale: str = Field(min_length=1, max_length=500)


class ContrastiveCardBatch(BaseModel):
    model_config = _CONFIG

    batch_id: str
    cards: tuple[ContrastiveTasteCard, ...] = Field(min_length=1, max_length=12)
    target_records_used: Literal[False] = False
    source_outcomes_used: Literal[True] = True
    human_or_expert_label_claimed: Literal[False] = False


def _read_jsonl(path: Path, model: type[BaseModel]) -> dict[str, BaseModel]:
    rows: dict[str, BaseModel] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = model.model_validate_json(line)
        key = str(item.intake_candidate_id)
        rows[key] = item
    return rows


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _normalize_words(value: str) -> list[str]:
    return value.split()


def _fit_lexical_tokens(value: str, *, budget: int) -> str:
    words = _normalize_words(value)
    if len(words) >= budget:
        return " ".join(words[:budget])
    filler = _normalize_words(
        "Additional source-grounded scope information is unavailable; do not infer it."
    )
    while len(words) < budget:
        words.extend(filler[: budget - len(words)])
    return " ".join(words)


def _render_card(card: ContrastiveTasteCard) -> str:
    applies = "\n".join(f"- {item}" for item in card.applies_when)
    reverse = "\n".join(f"- {item}" for item in card.reverse_when)
    return (
        f"Scientific preference: {card.preference}\n"
        f"Applies when:\n{applies}\n"
        f"Withhold or reverse when:\n{reverse}\n"
        f"Diagnostic question: {card.diagnostic_question}\n"
        f"Failure if misapplied: {card.failure_if_misapplied}\n"
        f"Source-outcome rationale: {card.source_outcome_rationale}"
    )


def _source_context(
    candidate_id: str,
    screens: dict[str, DevelopmentScreeningItem],
    records: dict[str, DevelopmentPanelDecisionRecord],
    outcomes: dict[str, DevelopmentOutcomeVaultRecord],
) -> dict[str, object]:
    screen = screens[candidate_id]
    record = records[candidate_id]
    outcome = outcomes[candidate_id]
    decision = record.final_decision
    if decision is None:
        raise ValueError(f"precedent {candidate_id!r} has no final decision")
    return {
        "article_title": screen.article_title,
        "reviewed_abstract": screen.reviewed_abstract,
        "predecision_review_context": screen.predecision_review_context,
        "atomic_decision_question": decision.atomic_decision_question,
        "decision_context_family": decision.decision_context_family.value,
        "taste_judgment_family": decision.taste_judgment_family.value,
        "observed_later_record": outcome.outcome_payload,
    }


def _raw_context(
    candidate_id: str,
    screens: dict[str, DevelopmentScreeningItem],
    records: dict[str, DevelopmentPanelDecisionRecord],
    outcomes: dict[str, DevelopmentOutcomeVaultRecord],
) -> str:
    source = _source_context(candidate_id, screens, records, outcomes)
    return (
        f"Prior source abstract:\n{source['reviewed_abstract']}\n\n"
        f"Prior decision context:\n{source['predecision_review_context']}\n\n"
        "Observed later record:\n"
        f"{json.dumps(source['observed_later_record'], ensure_ascii=False)}"
    )


def _card_instruction() -> str:
    return (
        "Convert each outcome-grounded scientific precedent into a contrastive Taste card. "
        "The card must explain a preference, observable pre-decision conditions under which "
        "it applies, conditions that require withholding or reversing it, one diagnostic "
        "question answerable before acting, and the failure caused by generic misuse. Preserve "
        "the supplied principle only when the source outcome supports it. Do not mention source "
        "titles, authors, domains, option labels, target records, or publication prestige. Do "
        "not turn stylistic advice into a scientific rule. Return positions in exact order and "
        "only the requested JSON object."
    )


def _call_cards(
    *,
    backend: StructuredOpenAICompatibleBackend,
    batch_id: str,
    items: list[dict[str, object]],
    output_dir: Path,
    seed: int,
) -> ContrastiveCardBatch:
    instruction = _card_instruction()
    payload = {
        "batch_id": batch_id,
        "items": items,
        "target_records_visible": False,
        "source_outcomes_visible": True,
    }
    request = StructuredModelRequest(
        request_id=batch_id,
        node_name="scitastebench-contrastive-card-construction",
        stage="benchmark-development",
        state_snapshot_id=content_sha256(payload),
        expected_backend=backend.name,
        expected_model=backend.model,
        policy_id="contrastive-taste-card-v1",
        policy_fingerprint=_sha_text(instruction),
        system_instruction=instruction,
        input_payload=payload,
        output_schema=ContrastiveCardBatch.model_json_schema(mode="serialization"),
        seed=seed,
        prompt_version="contrastive-taste-card-v1",
    )
    _write_json(output_dir / "request.json", request.model_dump(mode="json"))
    response = backend.complete(request)
    _write_json(output_dir / "response.json", response.model_dump(mode="json"))
    if response.backend != backend.name or response.model != backend.model:
        raise ValueError("contrastive-card provider identity differs")
    if response.tool_calls or not isinstance(response.output_payload, dict):
        raise ValueError("contrastive-card response is not a tool-free object")
    return ContrastiveCardBatch.model_validate(response.output_payload)


def _source_artifact(
    candidate_id: str,
    raw_context: str,
    records: dict[str, DevelopmentPanelDecisionRecord],
) -> ReferenceSourceArtifact:
    return ReferenceSourceArtifact(
        artifact_id=f"natural-precedent-{candidate_id}",
        source_group_id=records[candidate_id].source_group_id,
        source_locator=f"scitastebench-development-intake/{candidate_id}",
        source_content_sha256=_sha_text(raw_context),
    )


def _treatment(
    *,
    arm: ReferenceTreatmentArm,
    representation: ReferenceRepresentation,
    relation: ReferenceDomainRelation,
    rendered: str,
    source: ReferenceSourceArtifact,
    retrieval_sha: str,
    budget: int,
) -> ReferenceTreatmentContext:
    return ReferenceTreatmentContext(
        arm=arm,
        representation=representation,
        domain_relation=relation,
        rendered_context=rendered,
        rendered_context_sha256=_sha_text(rendered),
        sources=(source,),
        tokenizer_id="scitaste-whitespace-tokenizer",
        tokenizer_revision="1.0",
        tokenizer_artifact_sha256=_TOKENIZER_SHA,
        retrieval_query_sha256=retrieval_sha,
        render_template_sha256=_RENDER_TEMPLATE_SHA,
        construction_receipt_sha256=content_sha256(
            {
                "arm": arm.value,
                "rendered_context_sha256": _sha_text(rendered),
                "source": source.model_dump(mode="json"),
            }
        ),
        context_token_budget=budget,
        observed_token_count=len(_normalize_words(rendered)),
        truncation_policy="tail",
        provenance_tier="natural-review-record",
        curation_tier="dual-ai-proxy-development",
        outcome_information_availability="available",
    )


def run(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise FileExistsError(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    suite = load_benchmark_suite(args.suite)
    screens_raw = _read_jsonl(args.screening_items, DevelopmentScreeningItem)
    records_raw = _read_jsonl(args.panel_decisions, DevelopmentPanelDecisionRecord)
    screens = {
        key: DevelopmentScreeningItem.model_validate(value)
        for key, value in screens_raw.items()
    }
    records = {
        key: DevelopmentPanelDecisionRecord.model_validate(value)
        for key, value in records_raw.items()
    }
    vault = json.loads(args.outcome_vault.read_text(encoding="utf-8"))
    outcomes = {
        item["intake_candidate_id"]: DevelopmentOutcomeVaultRecord.model_validate(item)
        for item in vault["records"]
    }

    principles: dict[str, str] = {}
    precedent_ids: set[str] = set()
    for case in suite.cases:
        matched_id = case.taste_precedent_ids[0].removeprefix("taste-")
        mismatched_id = case.placebo_precedent_ids[0].removeprefix("taste-")
        precedent_ids.update((matched_id, mismatched_id))
        for candidate_id, principle in (
            (matched_id, case.taste_principle),
            (mismatched_id, case.placebo_taste_principle),
        ):
            if candidate_id in principles and principles[candidate_id] != principle:
                raise ValueError(f"precedent {candidate_id!r} has inconsistent principles")
            principles[candidate_id] = principle

    backend = StructuredOpenAICompatibleBackend(
        load_structured_openai_compatible_config(args.backend)
    )
    ordered_ids = sorted(precedent_ids)
    cards: dict[str, ContrastiveTasteCard] = {}
    reused_card_count = 0
    if args.reuse_card_suite is not None or args.reuse_card_output is not None:
        if args.reuse_card_suite is None or args.reuse_card_output is None:
            raise ValueError("card reuse requires both its source suite and output directory")
        reused_suite = load_benchmark_suite(args.reuse_card_suite)
        reused_principles: dict[str, str] = {}
        reused_ids: set[str] = set()
        for case in reused_suite.cases:
            for candidate_id, principle in (
                (
                    case.taste_precedent_ids[0].removeprefix("taste-"),
                    case.taste_principle,
                ),
                (
                    case.placebo_precedent_ids[0].removeprefix("taste-"),
                    case.placebo_taste_principle,
                ),
            ):
                reused_ids.add(candidate_id)
                prior = reused_principles.get(candidate_id)
                if prior is not None and prior != principle:
                    raise ValueError(
                        f"reused precedent {candidate_id!r} has inconsistent principles"
                    )
                reused_principles[candidate_id] = principle
        reused_ordered = sorted(reused_ids)
        for ordinal, candidate_batch in enumerate(
            [
                reused_ordered[index : index + args.reuse_card_batch_size]
                for index in range(0, len(reused_ordered), args.reuse_card_batch_size)
            ],
            1,
        ):
            response_path = args.reuse_card_output / f"{ordinal:02d}" / "response.json"
            response = json.loads(response_path.read_text(encoding="utf-8"))
            result = ContrastiveCardBatch.model_validate(response["output_payload"])
            positions = [card.position for card in result.cards]
            if sorted(positions) != list(range(1, len(candidate_batch) + 1)):
                raise ValueError("reused contrastive-card batch positions differ")
            for card in result.cards:
                candidate_id = candidate_batch[card.position - 1]
                if candidate_id not in precedent_ids:
                    continue
                if reused_principles[candidate_id] != principles[candidate_id]:
                    raise ValueError(
                        f"reused precedent {candidate_id!r} changed its grounded principle"
                    )
                cards[candidate_id] = card
                reused_card_count += 1

    pending_ids = [item for item in ordered_ids if item not in cards]
    batches = [
        pending_ids[index : index + args.batch_size]
        for index in range(0, len(pending_ids), args.batch_size)
    ]
    for ordinal, candidate_batch in enumerate(batches, 1):
        batch_id = f"{args.run_id}-cards-{ordinal:02d}"
        items = [
            {
                "position": position,
                "source_record": _source_context(candidate_id, screens, records, outcomes),
                "existing_outcome_grounded_principle": principles[candidate_id],
            }
            for position, candidate_id in enumerate(candidate_batch, 1)
        ]
        result = _call_cards(
            backend=backend,
            batch_id=batch_id,
            items=items,
            output_dir=args.output / "card-construction" / f"{ordinal:02d}",
            seed=args.seed + ordinal,
        )
        if result.batch_id != batch_id or len(result.cards) != len(candidate_batch):
            raise ValueError("contrastive-card batch is incomplete")
        positions = [card.position for card in result.cards]
        if sorted(positions) != list(range(1, len(candidate_batch) + 1)):
            raise ValueError("contrastive-card batch positions differ")
        for card in result.cards:
            cards[candidate_batch[card.position - 1]] = card

    new_cases = []
    for case in suite.cases:
        matched_id = case.taste_precedent_ids[0].removeprefix("taste-")
        mismatched_id = case.placebo_precedent_ids[0].removeprefix("taste-")
        matched_raw = _raw_context(matched_id, screens, records, outcomes)
        mismatched_raw = _raw_context(mismatched_id, screens, records, outcomes)
        rendered_raw = _fit_lexical_tokens(matched_raw, budget=args.token_budget)
        rendered_matched = _fit_lexical_tokens(
            _render_card(cards[matched_id]), budget=args.token_budget
        )
        rendered_mismatched = _fit_lexical_tokens(
            _render_card(cards[mismatched_id]), budget=args.token_budget
        )
        matched_source = _source_artifact(matched_id, matched_raw, records)
        mismatched_source = _source_artifact(mismatched_id, mismatched_raw, records)
        retrieval_sha = content_sha256(
            {
                "held_out_source_group_id": case.source_group_id,
                "decision_context": case.decision_context,
                "policy": "same-family-matched-versus-different-family-mismatched-v1",
            }
        )
        mechanism = MechanismContextBundle(
            bundle_id=f"contrastive-{case.case_id}",
            raw_source_rag=_treatment(
                arm=ReferenceTreatmentArm.RAW_SOURCE_RAG,
                representation=ReferenceRepresentation.RAW_SOURCE,
                relation=ReferenceDomainRelation.MATCHED,
                rendered=rendered_raw,
                source=matched_source,
                retrieval_sha=retrieval_sha,
                budget=args.token_budget,
            ),
            matched_abstracted_taste=_treatment(
                arm=ReferenceTreatmentArm.MATCHED_ABSTRACTED_TASTE,
                representation=ReferenceRepresentation.ABSTRACTED_TASTE,
                relation=ReferenceDomainRelation.MATCHED,
                rendered=rendered_matched,
                source=matched_source,
                retrieval_sha=retrieval_sha,
                budget=args.token_budget,
            ),
            mismatched_taste=_treatment(
                arm=ReferenceTreatmentArm.MISMATCHED_TASTE,
                representation=ReferenceRepresentation.ABSTRACTED_TASTE,
                relation=ReferenceDomainRelation.MISMATCHED,
                rendered=rendered_mismatched,
                source=mismatched_source,
                retrieval_sha=retrieval_sha,
                budget=args.token_budget,
            ),
            held_out_source_group_id=case.source_group_id,
            held_out_source_content_sha256=case.source_sha256,
        )
        new_cases.append(case.model_copy(update={"mechanism_context": mechanism}))

    contrasts = (
        RegisteredBenchmarkContrast(
            contrast_id="contrastive-card-vs-token-matched-raw",
            hypothesis_id="H1-contrastive-abstraction",
            treatment=BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            comparator=BenchmarkCondition.RAW_SOURCE_RAG,
            only_permitted_difference=ContrastDifference.REPRESENTATION,
            primary_endpoint=ContrastPrimaryEndpoint.AI_PANEL_PREFERENCE,
        ),
        RegisteredBenchmarkContrast(
            contrast_id="matched-vs-mismatched-contrastive-card",
            hypothesis_id="H2-contrastive-selectivity",
            treatment=BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            comparator=BenchmarkCondition.MISMATCHED_TASTE,
            only_permitted_difference=ContrastDifference.SOURCE_DOMAIN_RELATION,
            primary_endpoint=ContrastPrimaryEndpoint.AI_PANEL_PREFERENCE,
        ),
    )
    new_suite = BenchmarkSuite(
        suite_id=args.suite_id,
        version="3.0",
        description=(
            "Token-matched contrastive Taste-card study on natural dual-AI-proxy "
            "decisions; not formal effectiveness evidence."
        ),
        evidence_tier=suite.evidence_tier,
        annotation_manifest_sha256=suite.annotation_manifest_sha256,
        reference_treatment_manifest_sha256=content_sha256(
            {
                "run_id": args.run_id,
                "source_suite_sha256": suite.sha256,
                "tokenizer_sha256": _TOKENIZER_SHA,
                "render_template_sha256": _RENDER_TEMPLATE_SHA,
                "token_budget": args.token_budget,
            }
        ),
        registered_contrasts=contrasts,
        conditions=[
            BenchmarkCondition.BASE,
            BenchmarkCondition.RAW_SOURCE_RAG,
            BenchmarkCondition.MATCHED_ABSTRACTED_TASTE,
            BenchmarkCondition.MISMATCHED_TASTE,
        ],
        cases=new_cases,
    )
    suite_path = args.output / "SUITE.yaml"
    suite_path.write_text(
        yaml.safe_dump(
            new_suite.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    summary = {
        "schema_version": "1.0",
        "run_id": args.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "source_suite_sha256": suite.sha256,
        "suite_sha256": new_suite.sha256,
        "case_count": len(new_cases),
        "unique_precedent_count": len(cards),
        "reused_card_count": reused_card_count,
        "new_card_count": len(cards) - reused_card_count,
        "token_budget_per_treatment": args.token_budget,
        "card_backend": backend.name,
        "card_model": backend.model,
        "target_records_used_for_card_construction": False,
        "source_outcomes_used_for_card_construction": True,
        "formal_evidence_eligible": False,
        "not_human_review": True,
        "suite": str(suite_path),
    }
    _write_json(args.output / "SUMMARY.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    root = Path("outputs/projects/scitaste-self-development/evaluations")
    parser.add_argument(
        "--suite", type=Path, default=root / "scitastebench-natural-development-v5/SUITE.yaml"
    )
    parser.add_argument(
        "--screening-items",
        type=Path,
        default=root / "scitastebench-four-layer-development-intake-v1/SCREENING_ITEMS.jsonl",
    )
    parser.add_argument(
        "--outcome-vault",
        type=Path,
        default=root / "scitastebench-four-layer-development-intake-v1/OUTCOME_VAULT.json",
    )
    parser.add_argument(
        "--panel-decisions",
        type=Path,
        default=(
            root
            / "scitastebench-four-layer-development-panel-v3/normalization/FINAL_DECISIONS.jsonl"
        ),
    )
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/zhipu_glm53_flash.scitastebench_live_20260916.yaml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "scitastebench-natural-contrastive-development-v1",
    )
    parser.add_argument("--run-id", default="scitastebench-natural-contrastive-development-v1")
    parser.add_argument("--suite-id", default="scitastebench-natural-contrastive-development-v1")
    parser.add_argument("--reuse-card-suite", type=Path, default=None)
    parser.add_argument("--reuse-card-output", type=Path, default=None)
    parser.add_argument("--reuse-card-batch-size", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--token-budget", type=int, default=256)
    parser.add_argument("--seed", type=int, default=6027)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())

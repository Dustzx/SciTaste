#!/usr/bin/env python3
"""Independently review outcome-hidden SciTasteBench boundary-pair proposals.

The reviewer sees the original pre-decision record, a frozen action menu, and
two randomly ordered states.  It never sees the constructor's preferred
actions, utilities, rationale, state roles, or observed outcome.  The output is
therefore construct evidence from an AI proxy, not an expert or formal label.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.benchmark import BoundaryCounterfactualPair, BoundaryPairPackage
from scitaste.model_nodes import (
    StructuredModelRequest,
    StructuredModelResponse,
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class BoundaryReviewConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    review_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    screening_items: FileBinding
    pair_packages: tuple[FileBinding, ...] = Field(min_length=1)
    pair_selection_policy: Literal["first-package-wins-by-pair-id"]
    reviewer_backend: FileBinding
    reviewer_provider: str = Field(min_length=1)
    reviewer_model: str = Field(min_length=1)
    batch_size: int = Field(ge=1, le=8)
    seed: int
    target_outcomes_visible: Literal[False]
    expected_pair_labels_visible: Literal[False]
    human_review_claim_allowed: Literal[False]
    formal_split_opened: Literal[False]


class Ambiguity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NaturalSourceState(StrEnum):
    STATE_1 = "state_1"
    STATE_2 = "state_2"
    NEITHER = "neither"
    BOTH = "both"
    UNCERTAIN = "uncertain"


class PairReviewProposal(BaseModel):
    model_config = _CONFIG

    pair_id: str = Field(min_length=1)
    construct_valid: bool
    exactly_one_decisive_fact: bool
    shared_context_fact_neutral: bool
    states_internally_noncontradictory: bool
    natural_source_state: NaturalSourceState
    both_action_menu_feasible: bool
    action_meanings_stable_across_states: bool
    twin_changes_only_registered_fact: bool
    labels_uniquely_identifiable: bool
    abstention_explicitly_considered: bool
    utility_components_defensible: bool
    cue_shortcut_resistant: bool
    state_1_selection_id: str | None = Field(default=None, min_length=1)
    state_1_should_abstain: bool = False
    state_2_selection_id: str | None = Field(default=None, min_length=1)
    state_2_should_abstain: bool = False
    ambiguity: Ambiguity
    confidence: float = Field(ge=0, le=1)
    rejection_codes: tuple[str, ...] = ()
    rationale: str = Field(min_length=1, max_length=8_000)

    @model_validator(mode="after")
    def selections_are_atomic(self) -> PairReviewProposal:
        for role, selection, abstains in (
            ("state_1", self.state_1_selection_id, self.state_1_should_abstain),
            ("state_2", self.state_2_selection_id, self.state_2_should_abstain),
        ):
            if abstains == (selection is not None):
                raise ValueError(f"{role} must select one action xor abstain")
        if len(self.rejection_codes) != len(set(self.rejection_codes)):
            raise ValueError("rejection codes must be unique")
        if self.construct_valid and self.rejection_codes:
            raise ValueError("a valid construct cannot carry rejection codes")
        if not self.construct_valid and not self.rejection_codes:
            raise ValueError("an invalid construct requires at least one rejection code")
        return self


class BoundaryReviewBatch(BaseModel):
    model_config = _CONFIG

    reviews: tuple[PairReviewProposal, ...] = Field(min_length=1, max_length=8)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--resume", action="store_true")
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


def _jsonl(path: Path) -> list[dict[str, JsonValue]]:
    records: list[dict[str, JsonValue]] = []
    for line in _bytes(path).decode("utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL record must be an object: {path}")
        records.append(value)
    return records


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
    temporary.replace(path)


def _instruction() -> str:
    return """You independently review proposed scientific-decision boundary pairs.
You see material available before the observed outcome. You do not see the constructor's expected
labels, utilities, rationale, state roles, or later outcome. Treat every supplied pair as a
proposal, not as a correct item.

For each pair:
1. Select exactly one frozen action for each state, or abstain when the evidence cannot support a
   unique action. Judge scientific value, information gain, execution cost, and unsupported-claim
   risk under the visible budget. Do not infer hidden facts.
2. Decide whether exactly one atomic scientific fact differs. Reject compound interventions,
   hidden changes in budget or task, and action descriptions or preconditions that are infeasible in
   either state. Reject when retained shared prose states a base-specific fact that contradicts the
   twin, or a twin-specific fact that contradicts the base.
3. Identify which randomly named state matches the natural value grounded in the original source.
   Use uncertain when the record cannot establish this. The hypothetical state need only be
   coherent; do not claim that it happened.
4. Check that each action has the same meaning in both states, that the preferred label is uniquely
   identifiable from visible evidence, and that abstention was genuinely considered rather than
   forcing a weak action. Treat scalar utilities as invalid unless their registered component
   vectors and aggregation contract make the ordering defensible.
5. Reject items solvable by a shallow word-to-action rule (for example observed/not observed maps
   directly to retain/rephrase) without integrating scientific evidence. A boundary cue can be
   present, but the correct decision must require its interaction with other invariant facts.
6. A construct is valid only when all checks above pass, ambiguity is not high, and the one fact
   produces a defensible action or action/abstention reversal.
7. Use concise rejection codes such as COMPOUND_CHANGE, CONTEXT_CONTRADICTION,
   SOURCE_NOT_GROUNDED, ACTION_INFEASIBLE, ACTION_SEMANTIC_DRIFT, LABEL_AMBIGUOUS,
   UTILITY_UNGROUNDED, CUE_SHORTCUT, NO_DECISION_FLIP, or TASK_DRIFT. Return reviews in input order.

Return one JSON object matching the supplied schema and no prose outside it."""


def _deduplicate_packages(
    package_paths: tuple[Path, ...],
) -> tuple[list[BoundaryCounterfactualPair], dict[str, str], dict[str, int]]:
    pairs: list[BoundaryCounterfactualPair] = []
    sources: dict[str, str] = {}
    duplicates = 0
    per_package: dict[str, int] = {}
    seen: set[str] = set()
    for path in package_paths:
        package = BoundaryPairPackage.model_validate_json(_bytes(path))
        accepted = 0
        for pair in package.pairs:
            if pair.pair_id in seen:
                duplicates += 1
                continue
            seen.add(pair.pair_id)
            pairs.append(pair)
            sources[pair.pair_id] = package.package_id
            accepted += 1
        per_package[package.package_id] = accepted
    return pairs, sources, {**per_package, "duplicate_pair_count": duplicates}


def _state_order(seed: int, pair_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"{seed}:{pair_id}".encode()).digest()
    return ("base", "twin") if digest[0] % 2 == 0 else ("twin", "base")


def _pair_payload(
    pair: BoundaryCounterfactualPair,
    screening: dict[str, JsonValue],
    order: tuple[str, str],
) -> dict[str, JsonValue]:
    states = {"base": pair.base, "twin": pair.twin}
    return {
        "pair_id": pair.pair_id,
        "domain": pair.domain,
        "decision_context_family": pair.decision_context_family.value,
        "taste_judgment_family": pair.taste_judgment_family.value,
        "original_predecision_record": {
            "article_title": screening["article_title"],
            "reviewed_abstract": screening["reviewed_abstract"],
            "predecision_review_context": screening["predecision_review_context"],
        },
        "visible_budget": pair.base.visible_budget,
        "declared_invariant_facts": list(pair.invariant_facts),
        "registered_fact_question": pair.changed_fact.question,
        "frozen_action_menu": [action.model_dump(mode="json") for action in pair.candidate_actions],
        "state_1": states[order[0]].decision_context,
        "state_2": states[order[1]].decision_context,
    }


def _request(
    config: BoundaryReviewConfig,
    *,
    batch_number: int,
    pairs: list[BoundaryCounterfactualPair],
    screening_by_source: dict[str, dict[str, JsonValue]],
    policy_fingerprint: str,
) -> tuple[StructuredModelRequest, dict[str, tuple[str, str]]]:
    orders = {pair.pair_id: _state_order(config.seed, pair.pair_id) for pair in pairs}
    payload = [
        _pair_payload(pair, screening_by_source[pair.source_group_id], orders[pair.pair_id])
        for pair in pairs
    ]
    request = StructuredModelRequest(
        request_id=f"{config.review_id}-batch-{batch_number:02d}",
        node_name="scitastebench-boundary-pair-independent-review",
        stage="EVALUATION",
        state_snapshot_id=f"{config.review_id}-label-hidden",
        expected_backend=config.reviewer_provider,
        expected_model=config.reviewer_model,
        policy_id=config.review_id,
        policy_fingerprint=policy_fingerprint,
        system_instruction=_instruction(),
        input_payload={
            "target_outcomes_visible": False,
            "expected_pair_labels_visible": False,
            "state_names_are_randomized": True,
            "pairs": payload,
        },
        output_schema=BoundaryReviewBatch.model_json_schema(mode="serialization"),
        seed=config.seed + batch_number,
        prompt_version="scitastebench-boundary-independent-review-v1",
    )
    return request, orders


def _validate_review(
    proposal: PairReviewProposal,
    pair: BoundaryCounterfactualPair,
) -> list[str]:
    action_ids = {action.action_id for action in pair.candidate_actions}
    errors: list[str] = []
    for role, selection in (
        ("state_1", proposal.state_1_selection_id),
        ("state_2", proposal.state_2_selection_id),
    ):
        if selection is not None and selection not in action_ids:
            errors.append(f"{role}:selection-outside-frozen-menu:{selection}")
    if proposal.construct_valid:
        if not proposal.exactly_one_decisive_fact:
            errors.append("valid-review-denies-single-decisive-fact")
        if not proposal.shared_context_fact_neutral:
            errors.append("valid-review-shared-context-leaks-boundary-value")
        if not proposal.states_internally_noncontradictory:
            errors.append("valid-review-state-context-is-contradictory")
        if not proposal.both_action_menu_feasible:
            errors.append("valid-review-denies-action-feasibility")
        if not proposal.action_meanings_stable_across_states:
            errors.append("valid-review-denies-action-semantic-stability")
        if not proposal.twin_changes_only_registered_fact:
            errors.append("valid-review-denies-single-fact-intervention")
        if not proposal.labels_uniquely_identifiable:
            errors.append("valid-review-denies-label-identifiability")
        if not proposal.abstention_explicitly_considered:
            errors.append("valid-review-did-not-consider-abstention")
        if not proposal.utility_components_defensible:
            errors.append("valid-review-denies-utility-components")
        if not proposal.cue_shortcut_resistant:
            errors.append("valid-review-allows-cue-shortcut")
        if proposal.natural_source_state in {
            NaturalSourceState.NEITHER,
            NaturalSourceState.BOTH,
            NaturalSourceState.UNCERTAIN,
        }:
            errors.append("valid-review-does-not-ground-natural-state")
        if proposal.ambiguity is Ambiguity.HIGH:
            errors.append("valid-review-has-high-ambiguity")
    return errors


def _normalize_review_payload(
    payload: JsonValue,
    *,
    request_id: str,
) -> tuple[JsonValue, list[dict[str, str]]]:
    """Fail closed on internally inconsistent provider review verdicts."""

    if not isinstance(payload, dict):
        return payload, []
    normalized = json.loads(json.dumps(payload))
    reviews = normalized.get("reviews")
    if not isinstance(reviews, list):
        return normalized, []
    corrections: list[dict[str, str]] = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        if review.get("tambiguity_note") is None and "tambiguity_note" in review:
            review.pop("tambiguity_note")
            corrections.append(
                {
                    "request_id": request_id,
                    "pair_id": str(review.get("pair_id", "")),
                    "field": "tambiguity_note",
                    "observed": "null",
                    "replacement": "removed",
                    "authority": "bounded-null-provider-typo-v1",
                }
            )
        codes = review.get("rejection_codes")
        if not isinstance(codes, list):
            continue
        for state in ("state_1", "state_2"):
            selection_key = f"{state}_selection_id"
            abstain_key = f"{state}_should_abstain"
            if review.get(abstain_key) is not None:
                continue
            selection = review.get(selection_key)
            replacement = selection is None
            review[abstain_key] = replacement
            corrections.append(
                {
                    "request_id": request_id,
                    "pair_id": str(review.get("pair_id", "")),
                    "field": abstain_key,
                    "observed": "null",
                    "replacement": str(replacement).lower(),
                    "authority": "bounded-null-abstention-normalization-v1",
                }
            )
            if selection is None and review.get("construct_valid") is True:
                review["construct_valid"] = False
                if "INCOMPLETE_SELECTION" not in codes:
                    codes.append("INCOMPLETE_SELECTION")
        if review.get("construct_valid") is True and codes:
            review["construct_valid"] = False
            corrections.append(
                {
                    "request_id": request_id,
                    "pair_id": str(review.get("pair_id", "")),
                    "field": "construct_valid",
                    "observed": "true-with-rejection-codes",
                    "replacement": "false",
                    "authority": "fail-closed-review-consistency-v1",
                }
            )
        elif review.get("construct_valid") is False and not codes:
            codes.append("UNSPECIFIED_INVALID_CONSTRUCT")
            corrections.append(
                {
                    "request_id": request_id,
                    "pair_id": str(review.get("pair_id", "")),
                    "field": "rejection_codes",
                    "observed": "empty-for-invalid-construct",
                    "replacement": "UNSPECIFIED_INVALID_CONSTRUCT",
                    "authority": "fail-closed-review-consistency-v1",
                }
            )
    return normalized, corrections


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_raw = _bytes(config_path)
    config = BoundaryReviewConfig.model_validate(yaml.safe_load(config_raw))
    screening_path = _bound(root, config.screening_items)
    package_paths = tuple(_bound(root, item) for item in config.pair_packages)
    backend_path = _bound(root, config.reviewer_backend)
    pairs, package_sources, merge_counts = _deduplicate_packages(package_paths)
    screening_records = _jsonl(screening_path)
    screening_by_source = {str(item["source_group_id"]): item for item in screening_records}
    missing_sources = sorted({pair.source_group_id for pair in pairs} - screening_by_source.keys())
    if missing_sources:
        raise ValueError(
            "pair sources missing from screening projection: " + ", ".join(missing_sources)
        )
    backend_config = load_structured_openai_compatible_config(backend_path)
    if (backend_config.provider, backend_config.model) != (
        config.reviewer_provider,
        config.reviewer_model,
    ):
        raise ValueError("reviewer backend identity differs from frozen config")
    policy_fingerprint = content_sha256(
        {
            "config_sha256": hashlib.sha256(config_raw).hexdigest(),
            "backend_sha256": config.reviewer_backend.sha256,
            "instruction": _instruction(),
        }
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    backend = StructuredOpenAICompatibleBackend(backend_config) if args.allow_api else None
    completed = 0
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    review_records: list[dict[str, JsonValue]] = []
    normalizations: list[dict[str, str]] = []
    for offset in range(0, len(pairs), config.batch_size):
        batch_number = offset // config.batch_size + 1
        batch_pairs = pairs[offset : offset + config.batch_size]
        request, orders = _request(
            config,
            batch_number=batch_number,
            pairs=batch_pairs,
            screening_by_source=screening_by_source,
            policy_fingerprint=policy_fingerprint,
        )
        request_path = output / "requests" / f"{batch_number:02d}.json"
        request_bytes = (request.model_dump_json(indent=2) + "\n").encode()
        forbidden = (b'"preferred_action_id"', b'"action_utilities"', b'"why_decisive"')
        if any(token in request_bytes for token in forbidden):
            raise ValueError("expected pair labels leaked into reviewer request")
        _write(request_path, request_bytes)
        response_path = output / "responses" / f"{batch_number:02d}.json"
        if args.resume and response_path.is_file():
            response = StructuredModelResponse.model_validate_json(_bytes(response_path))
            if response.request_fingerprint != request.fingerprint:
                raise ValueError(f"saved response request drift in batch {batch_number}")
        else:
            if backend is None:
                continue
            response = backend.complete(request)
            _write(response_path, (response.model_dump_json(indent=2) + "\n").encode())
        completed += 1
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        usage["cost_usd"] += response.usage.cost_usd or 0.0
        normalized_payload, corrections = _normalize_review_payload(
            response.output_payload,
            request_id=request.request_id,
        )
        normalizations.extend(corrections)
        proposal_batch = BoundaryReviewBatch.model_validate(normalized_payload)
        expected_ids = [pair.pair_id for pair in batch_pairs]
        observed_ids = [item.pair_id for item in proposal_batch.reviews]
        if observed_ids != expected_ids:
            raise ValueError(f"reviewer changed pair order in batch {batch_number}")
        for pair, proposal in zip(batch_pairs, proposal_batch.reviews, strict=True):
            deterministic_errors = _validate_review(proposal, pair)
            order = orders[pair.pair_id]
            selections = {
                order[0]: {
                    "selection_id": proposal.state_1_selection_id,
                    "should_abstain": proposal.state_1_should_abstain,
                },
                order[1]: {
                    "selection_id": proposal.state_2_selection_id,
                    "should_abstain": proposal.state_2_should_abstain,
                },
            }
            review_records.append(
                {
                    "schema_version": "1.0",
                    "review_id": config.review_id,
                    "reviewer_provider": config.reviewer_provider,
                    "reviewer_model": config.reviewer_model,
                    "authority": "ai-panel-proxy",
                    "pair_id": pair.pair_id,
                    "source_package_id": package_sources[pair.pair_id],
                    "state_order": {"state_1": order[0], "state_2": order[1]},
                    "base_selection_id": selections["base"]["selection_id"],
                    "base_should_abstain": selections["base"]["should_abstain"],
                    "twin_selection_id": selections["twin"]["selection_id"],
                    "twin_should_abstain": selections["twin"]["should_abstain"],
                    "proposal": proposal.model_dump(mode="json"),
                    "deterministic_protocol_errors": deterministic_errors,
                    "protocol_valid": not deterministic_errors,
                    "request_fingerprint": request.fingerprint,
                    "response_sha256": response.raw_response_sha256,
                }
            )
    batch_count = (len(pairs) + config.batch_size - 1) // config.batch_size
    plan = {
        "schema_version": "1.0",
        "review_id": config.review_id,
        "config": {
            "locator": str(config_path.relative_to(root)),
            "sha256": hashlib.sha256(config_raw).hexdigest(),
        },
        "policy_fingerprint": policy_fingerprint,
        "candidate_pair_count": len(pairs),
        "batch_count": batch_count,
        "merge_counts": merge_counts,
        "target_outcomes_visible": False,
        "expected_pair_labels_visible": False,
        "state_order_randomized": True,
        "human_review_claim_allowed": False,
        "formal_split_opened": False,
        "api_execution_performed": backend is not None,
    }
    _write(output / "PLAN.json", (json.dumps(plan, indent=2) + "\n").encode())
    if completed == 0:
        return 0
    if completed != batch_count:
        raise ValueError("cannot compile a partial independent review")
    review_lines = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in review_records)
    _write(output / "REVIEWS.jsonl", review_lines.encode())
    valid = [
        item
        for item in review_records
        if item["protocol_valid"] and item["proposal"]["construct_valid"]
    ]
    rejection_counts = Counter(
        code for item in review_records for code in item["proposal"]["rejection_codes"]
    )
    summary = {
        "schema_version": "1.0",
        "review_id": config.review_id,
        "candidate_pair_count": len(pairs),
        "construct_valid_pair_count": len(valid),
        "invalid_or_protocol_failed_pair_count": len(pairs) - len(valid),
        "protocol_failed_pair_count": sum(not item["protocol_valid"] for item in review_records),
        "ambiguity_counts": dict(Counter(item["proposal"]["ambiguity"] for item in review_records)),
        "rejection_code_counts": dict(rejection_counts),
        "review_records_sha256": hashlib.sha256(review_lines.encode()).hexdigest(),
        "bounded_normalization_count": len(normalizations),
        "bounded_normalizations": normalizations,
        "usage": usage,
        "authority": "ai-panel-proxy",
        "target_outcomes_used": False,
        "expected_pair_labels_used": False,
        "formal_split_opened": False,
        "effectiveness_claim_allowed": False,
    }
    _write(output / "SUMMARY.json", (json.dumps(summary, indent=2) + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

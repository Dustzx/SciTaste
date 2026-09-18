#!/usr/bin/env python3
"""Construct outcome-hidden SciTasteBench development boundary pairs.

This script consumes only the screening projection and caseability decisions.
The outcome vault is intentionally not accepted as an argument.  Model outputs
remain proposals until they satisfy the deterministic single-fact pair schema.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.benchmark import (
    BenchmarkDecisionContextFamily,
    BoundaryCounterfactualPair,
    BoundaryFactChange,
    BoundaryFlipKind,
    BoundaryPairPackage,
    BoundaryPairSplit,
    BoundaryPairState,
    BoundaryStateRole,
    BoundaryUtilityContract,
    BoundaryUtilityVector,
    inspect_boundary_pair_package,
)
from scitaste.model_nodes import (
    StructuredModelRequest,
    StructuredModelResponse,
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.models import content_sha256
from scitaste.schema.actions import ResearchAction
from scitaste.taste.decision_families import ScientificTasteDecisionFamily

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class CandidateSelection(BaseModel):
    model_config = _CONFIG

    intake_candidate_id: str = Field(min_length=1)
    decision_context_family: BenchmarkDecisionContextFamily


class BoundaryConstructionConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    construction_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    evidence_role: Literal["consumed-development-only"]
    screening_items: FileBinding
    caseability_decisions: FileBinding
    constructor_backend: FileBinding
    constructor_provider: str
    constructor_model: str
    batch_size: int = Field(ge=1, le=8)
    seed: int
    standard_visible_budget: str = Field(min_length=1)
    utility_contract: BoundaryUtilityContract | None = None
    selection_mode: Literal["balanced-cohort", "top-up"] = "balanced-cohort"
    selected_candidates: tuple[CandidateSelection, ...] = Field(min_length=1)
    target_pair_count: int = Field(ge=1)
    target_pairs_per_context: int = Field(ge=1)
    target_outcomes_visible_to_constructor: Literal[False]
    formal_split_opened: Literal[False]
    human_label_claim_allowed: Literal[False]
    effectiveness_claim_allowed: Literal[False]

    @model_validator(mode="after")
    def selection_is_closed(self) -> BoundaryConstructionConfig:
        candidate_ids = [item.intake_candidate_id for item in self.selected_candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("selected boundary candidates must be unique")
        if len(candidate_ids) != self.target_pair_count:
            raise ValueError("selected boundary candidate count differs from target")
        counts = Counter(item.decision_context_family for item in self.selected_candidates)
        if self.selection_mode == "balanced-cohort":
            if set(counts) != set(BenchmarkDecisionContextFamily):
                raise ValueError("boundary construction must cover all decision contexts")
            if any(value != self.target_pairs_per_context for value in counts.values()):
                raise ValueError("boundary construction is not balanced by decision context")
        if self.schema_version in {"1.1", "1.2"} and self.utility_contract is None:
            raise ValueError("boundary construction 1.1+ requires a utility contract")
        if self.schema_version == "1.0" and self.utility_contract is not None:
            raise ValueError("legacy boundary construction cannot carry a utility contract")
        return self


class FactProposal(BaseModel):
    model_config = _CONFIG

    fact_id: str = Field(min_length=1, max_length=160)
    question: str = Field(min_length=1, max_length=1_000)
    base_value: str = Field(min_length=1, max_length=4_000)
    twin_value: str = Field(min_length=1, max_length=4_000)
    why_decisive: str = Field(min_length=1, max_length=4_000)


class StatePreferenceProposal(BaseModel):
    model_config = _CONFIG

    preferred_action_id: str | None = Field(default=None, min_length=1, max_length=300)
    should_abstain: bool = False
    action_utilities: dict[str, float]
    utility_components: dict[str, BoundaryUtilityVector] = Field(default_factory=dict)
    utility_rationale: dict[str, str]


class NeutralizedSourceSpan(BaseModel):
    """Exact source prose excluded because it asserts the natural boundary value."""

    model_config = _CONFIG

    source_field: Literal["article_title", "reviewed_abstract", "predecision_review_context"]
    exact_text: str = Field(min_length=12, max_length=4_000)
    asserted_value: Literal["base"] = "base"


class PairProposal(BaseModel):
    model_config = _CONFIG

    intake_candidate_id: str = Field(min_length=1)
    admitted: bool
    rejection_reason: str | None = Field(default=None, max_length=4_000)
    shared_decision_context: str | None = Field(default=None, max_length=30_000)
    candidate_actions: tuple[ResearchAction, ...] = ()
    invariant_facts: tuple[str, ...] = ()
    required_invariant_facts: tuple[str, ...] = ()
    neutralized_source_spans: tuple[NeutralizedSourceSpan, ...] = ()
    boundary_only_insufficient_reason: str | None = Field(
        default=None,
        min_length=30,
        max_length=4_000,
    )
    changed_fact: FactProposal | None = None
    flip_kind: BoundaryFlipKind | None = None
    base: StatePreferenceProposal | None = None
    twin: StatePreferenceProposal | None = None

    @model_validator(mode="after")
    def admission_is_atomic(self) -> PairProposal:
        payload = (
            self.shared_decision_context,
            self.changed_fact,
            self.flip_kind,
            self.base,
            self.twin,
            self.boundary_only_insufficient_reason,
        )
        if self.admitted:
            if self.rejection_reason is not None or not all(item is not None for item in payload):
                raise ValueError("admitted pair proposal requires a complete construction")
            if not 2 <= len(self.candidate_actions) <= 5:
                raise ValueError("admitted pair proposal requires 2--5 actions")
            if len(self.invariant_facts) < 2:
                raise ValueError("admitted pair proposal requires at least two invariant facts")
            span_keys = [
                (item.source_field, item.exact_text) for item in self.neutralized_source_spans
            ]
            if len(span_keys) != len(set(span_keys)):
                raise ValueError("neutralized source spans must be unique")
        elif self.rejection_reason is None:
            raise ValueError("rejected pair proposal requires a reason")
        return self


class BoundaryBatchProposal(BaseModel):
    model_config = _CONFIG

    proposals: tuple[PairProposal, ...] = Field(min_length=1, max_length=8)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    return parser


def _bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bound input must be a regular file: {path}")
    return path.read_bytes()


def _bound(root: Path, binding: FileBinding) -> Path:
    candidate = (root / binding.locator).resolve(strict=True)
    candidate.relative_to(root)
    if hashlib.sha256(_bytes(candidate)).hexdigest() != binding.sha256:
        raise ValueError(f"bound input hash mismatch: {binding.locator}")
    return candidate


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


def _instruction() -> str:
    return """You construct consumed-development examples for a scientific-decision benchmark.
You see only material available before the observed outcome. For each input candidate, either reject
it or construct one boundary-counterfactual pair. A valid pair has a natural base state and a
hypothetical twin. The twin is a construct-validity intervention, never a claim about what happened.

Hard requirements for an admitted pair:
1. Write one shared_decision_context that is faithful to the supplied abstract, review, and atomic
   question but does not state, presuppose, or paraphrase either value of the changed fact. Read the
   completed base and twin contexts back separately; reject the item if any retained sentence
   contradicts either state. Copy every source sentence or clause that had to be excluded for this
   reason verbatim into neutralized_source_spans with its source field. At least one exact source
   span is required; do not invent or paraphrase a span.
2. Register exactly one atomic scientific fact with a base value grounded in the supplied record and
   one hypothetical twin value. Do not change sample size and effect direction together; do not
   smuggle several observations into one fact.
3. Supply 2 or 3 candidate actions at the same abstraction level. Their identifiers, descriptions,
   and feasibility must work unchanged in both states. Therefore do not write action descriptions
   such as 'cite the three observed events' that are impossible in the base state. Prefer semantic
   actions such as 'retain the claim at its current strength' versus 'narrow the claim'. Reject when
   an action description or rationale changes meaning across states or the visible budget cannot
   establish that the action is feasible.
4. The single changed fact must reverse the unique utility-maximizing action, or make exactly one
   state require abstention. Generic 'do more analysis' in both states is invalid.
5. Utilities lie in [-1, 1]. Rationales must cover exactly the frozen action IDs. When a utility
   contract is supplied, score every action separately on evidence_value, expected_information_gain,
   resource_cost, and claim_risk in [0, 1], then compute the scalar exactly from the supplied
   benefit-minus-cost weights. The preferred action must uniquely maximize that scalar; abstain only
   when every action is at or below the contract's commitment threshold.
6. List at least two concrete invariant facts. Do not use author, venue prestige, or the hidden
   later response. Do not infer facts absent from the input. Copy at least two into
   required_invariant_facts because they are jointly necessary for the registered reversal. Every
   required_invariant_facts entry MUST be one exact verbatim substring that appears unchanged both
   in a supplied source field and in shared_decision_context. Repeat the identical string; do not
   summarize, translate, or change punctuation. Use a shorter exact source clause when needed.
7. Prefer decisions in which the changed fact must interact with invariant scientific evidence.
   Reject pairs solvable by a shallow cue rule such as present/absent -> retain/rephrase. Include
   action-to-abstention pairs when the visible evidence does not uniquely justify any action. In
   boundary_only_insufficient_reason, explain why the fact values plus action names and budget do
   not identify either registered label without the required invariant facts. If that explanation
   is not defensible, reject the candidate.
8. Return exactly one proposal per input candidate, in the same order. Reject honestly when no
   defensible single-fact reversal can be formed.

Return one JSON object matching the supplied schema and no prose outside it."""


def _request(
    config: BoundaryConstructionConfig,
    *,
    batch_number: int,
    candidates: list[dict[str, JsonValue]],
    policy_fingerprint: str,
) -> StructuredModelRequest:
    return StructuredModelRequest(
        request_id=f"{config.construction_id}-batch-{batch_number:02d}",
        node_name="scitastebench-boundary-pair-construction",
        stage="EVALUATION",
        state_snapshot_id=f"{config.construction_id}-outcome-hidden",
        expected_backend=config.constructor_provider,
        expected_model=config.constructor_model,
        policy_id=config.construction_id,
        policy_fingerprint=policy_fingerprint,
        system_instruction=_instruction(),
        input_payload={
            "evidence_role": config.evidence_role,
            "standard_visible_budget": config.standard_visible_budget,
            "utility_contract": (
                None
                if config.utility_contract is None
                else config.utility_contract.model_dump(mode="json")
            ),
            "target_outcomes_visible": False,
            "candidates": candidates,
        },
        output_schema=BoundaryBatchProposal.model_json_schema(mode="serialization"),
        seed=config.seed + batch_number,
        prompt_version="scitastebench-boundary-construction-v1",
    )


def _source_license(screening: dict[str, JsonValue]) -> str:
    package_id = str(screening["package_id"])
    if package_id.startswith("f1000"):
        return "CC-BY-item-binding-unresolved-development-only"
    return "ODC-BY-database-only-content-rights-unresolved-development-only"


def _normalize_output_payload(
    payload: JsonValue,
    *,
    request_id: str,
) -> tuple[JsonValue, list[dict[str, str]]]:
    """Normalize bounded provider vocabulary without changing scientific content."""

    if not isinstance(payload, dict):
        return payload, []
    normalized = json.loads(json.dumps(payload))
    proposals = normalized.get("proposals")
    if not isinstance(proposals, list):
        return normalized, []
    aliases = {
        "REPORT": "WRITE",
        "RETAIN_CLAIM": "CITE_EXISTING_EVIDENCE",
    }
    corrections: list[dict[str, str]] = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        for observed_key in tuple(proposal):
            canonical_key = observed_key.strip()
            if (
                canonical_key != observed_key
                and canonical_key in PairProposal.model_fields
                and canonical_key not in proposal
            ):
                proposal[canonical_key] = proposal.pop(observed_key)
                corrections.append(
                    {
                        "request_id": request_id,
                        "intake_candidate_id": str(proposal.get("intake_candidate_id", "")),
                        "action_id": "",
                        "field": observed_key,
                        "observed": observed_key,
                        "replacement": canonical_key,
                        "authority": "bounded-json-key-whitespace-normalization-v1",
                    }
                )
        _remove_null_provider_notes(
            proposal,
            path="proposal",
            request_id=request_id,
            intake_candidate_id=str(proposal.get("intake_candidate_id", "")),
            corrections=corrections,
        )
        if isinstance(proposal.get("shared_decision_context_checked"), bool):
            observed = proposal.pop("shared_decision_context_checked")
            corrections.append(
                {
                    "request_id": request_id,
                    "intake_candidate_id": str(proposal.get("intake_candidate_id", "")),
                    "action_id": "",
                    "field": "shared_decision_context_checked",
                    "observed": str(observed).lower(),
                    "replacement": "removed",
                    "authority": "bounded-nonsemantic-envelope-removal-v1",
                }
            )
        actions = proposal.get("candidate_actions")
        if proposal.get("admitted") is True and (
            not isinstance(actions, list) or not 2 <= len(actions) <= 5
        ):
            observed_count = len(actions) if isinstance(actions, list) else -1
            proposal["admitted"] = False
            proposal["rejection_reason"] = (
                "Provider marked the proposal admitted but emitted an incomplete action menu "
                f"(count={observed_count}); deterministic admission converted it to a rejection."
            )
            corrections.append(
                {
                    "request_id": request_id,
                    "intake_candidate_id": str(proposal.get("intake_candidate_id", "")),
                    "action_id": "",
                    "field": "admitted",
                    "observed": "true-with-incomplete-action-menu",
                    "replacement": "false",
                    "authority": "fail-closed-incomplete-proposal-v1",
                }
            )
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            observed = action.get("type")
            if isinstance(observed, str) and observed in aliases:
                replacement = aliases[observed]
                action["type"] = replacement
                corrections.append(
                    {
                        "request_id": request_id,
                        "intake_candidate_id": str(proposal.get("intake_candidate_id", "")),
                        "action_id": str(action.get("action_id", "")),
                        "field": "candidate_actions.type",
                        "observed": observed,
                        "replacement": replacement,
                        "authority": "bounded-action-vocabulary-alias-v1",
                    }
                )
    return normalized, corrections


def _remove_null_provider_notes(
    value: object,
    *,
    path: str,
    request_id: str,
    intake_candidate_id: str,
    corrections: list[dict[str, str]],
) -> None:
    """Remove only provider-added, null-valued ``*_note`` JSON fields."""

    if isinstance(value, dict):
        for key in tuple(value):
            field_path = f"{path}.{key}"
            if key.endswith("_note") and value[key] is None:
                value.pop(key)
                corrections.append(
                    {
                        "request_id": request_id,
                        "intake_candidate_id": intake_candidate_id,
                        "action_id": "",
                        "field": field_path,
                        "observed": "null",
                        "replacement": "removed",
                        "authority": "bounded-null-provider-note-removal-v1",
                    }
                )
                continue
            _remove_null_provider_notes(
                value[key],
                path=field_path,
                request_id=request_id,
                intake_candidate_id=intake_candidate_id,
                corrections=corrections,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _remove_null_provider_notes(
                item,
                path=f"{path}[{index}]",
                request_id=request_id,
                intake_candidate_id=intake_candidate_id,
                corrections=corrections,
            )


def _compile_pair(
    proposal: PairProposal,
    *,
    screening: dict[str, JsonValue],
    decision: dict[str, JsonValue],
    context_family: BenchmarkDecisionContextFamily,
    config: BoundaryConstructionConfig,
    request: StructuredModelRequest,
    response_sha256: str,
) -> BoundaryCounterfactualPair:
    if not proposal.admitted:
        raise ValueError("cannot compile a rejected boundary proposal")
    assert proposal.shared_decision_context is not None
    assert proposal.changed_fact is not None
    assert proposal.flip_kind is not None
    assert proposal.base is not None
    assert proposal.twin is not None
    pair_suffix = proposal.intake_candidate_id.removeprefix("intake-")
    pair_id = f"boundary-{pair_suffix}"
    fact = BoundaryFactChange(
        **proposal.changed_fact.model_dump(mode="python"),
        base_evidence_refs=(
            f"{config.screening_items.locator}#{proposal.intake_candidate_id}:predecision_review_context",
        ),
        twin_construction_refs=(
            f"{config.construction_id}:{request.request_id}:{proposal.changed_fact.fact_id}",
        ),
    )
    common = {
        "visible_budget": config.standard_visible_budget,
    }
    base_payload = proposal.base.model_dump(mode="python")
    twin_payload = proposal.twin.model_dump(mode="python")
    if config.utility_contract is None:
        base_payload.pop("utility_components", None)
        twin_payload.pop("utility_components", None)
    base = BoundaryPairState(
        role=BoundaryStateRole.BASE,
        decision_context=(
            f"{proposal.shared_decision_context}\n\n"
            f"Registered boundary fact — {fact.question} {fact.base_value}"
        ),
        **common,
        **base_payload,
    )
    twin = BoundaryPairState(
        role=BoundaryStateRole.TWIN,
        decision_context=(
            f"{proposal.shared_decision_context}\n\n"
            f"Registered boundary fact — {fact.question} {fact.twin_value}"
        ),
        **common,
        **twin_payload,
    )
    final = _caseability_decision(decision)
    construction_sha256 = content_sha256(
        {
            "request_fingerprint": request.fingerprint,
            "response_sha256": response_sha256,
            "proposal": proposal.model_dump(mode="json"),
        }
    )
    return BoundaryCounterfactualPair(
        schema_version="1.1" if config.utility_contract is not None else "1.0",
        pair_id=pair_id,
        split=BoundaryPairSplit.DEVELOPMENT,
        source_group_id=str(screening["source_group_id"]),
        domain=str(screening["domain"]),
        decision_context_family=context_family,
        taste_judgment_family=ScientificTasteDecisionFamily(str(final["taste_judgment_family"])),
        source_locator=f"{config.screening_items.locator}#{proposal.intake_candidate_id}",
        source_content_sha256=str(screening["source_projection_sha256"]),
        license_identifier=_source_license(screening),
        public_reconstruction_allowed=False,
        outcome_hidden_during_construction=True,
        candidate_actions=proposal.candidate_actions,
        invariant_facts=proposal.invariant_facts,
        changed_fact=fact,
        flip_kind=proposal.flip_kind,
        utility_contract=config.utility_contract,
        base=base,
        twin=twin,
        judgments=(),
        contamination_probe_refs=(
            f"{config.construction_id}:contamination-probe-pending:{proposal.intake_candidate_id}",
        ),
        construction_manifest_sha256=construction_sha256,
    )


def _caseability_decision(record: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Accept a panel consensus or one outcome-hidden normalized screen decision."""

    value = record.get("final_decision")
    if not isinstance(value, dict):
        value = record.get("decision")
    if not isinstance(value, dict) or value.get("eligible") is not True:
        raise ValueError("caseability decision is missing or ineligible")
    return value


def _caseability_candidate_id(record: dict[str, JsonValue]) -> str:
    value = record.get("intake_candidate_id")
    if isinstance(value, str):
        return value
    decision = record.get("decision")
    if isinstance(decision, dict) and isinstance(decision.get("intake_candidate_id"), str):
        return str(decision["intake_candidate_id"])
    raise ValueError("caseability record lacks an intake candidate identity")


def _recompute_utility_scalars(
    proposal: PairProposal,
    contract: BoundaryUtilityContract | None,
    *,
    request_id: str,
) -> tuple[PairProposal, list[dict[str, str]], str | None]:
    """Derive scalar utilities from registered components and reject label drift."""

    if not proposal.admitted or contract is None:
        return proposal, [], None
    corrections: list[dict[str, str]] = []
    updates: dict[str, StatePreferenceProposal] = {}
    for role in ("base", "twin"):
        state = getattr(proposal, role)
        assert state is not None
        if set(state.utility_components) != set(state.action_utilities):
            return proposal, corrections, f"{role} utility components do not cover the action menu"
        derived = {
            action_id: contract.aggregate(vector)
            for action_id, vector in state.utility_components.items()
        }
        maximum = max(derived.values())
        maximizers = [
            action_id for action_id, value in derived.items() if abs(value - maximum) <= 1e-12
        ]
        should_abstain = maximum <= contract.minimum_action_utility_for_commitment
        if should_abstain != state.should_abstain:
            return proposal, corrections, f"{role} abstention contradicts derived utility"
        if not should_abstain and (
            len(maximizers) != 1 or state.preferred_action_id != maximizers[0]
        ):
            return proposal, corrections, f"{role} preferred action contradicts derived utility"
        for action_id, value in derived.items():
            observed = state.action_utilities[action_id]
            if abs(observed - value) > 1e-12:
                corrections.append(
                    {
                        "request_id": request_id,
                        "intake_candidate_id": proposal.intake_candidate_id,
                        "action_id": action_id,
                        "field": f"{role}.action_utilities",
                        "observed": str(observed),
                        "replacement": str(value),
                        "authority": "registered-utility-contract-recomputation-v1",
                    }
                )
        updates[role] = state.model_copy(update={"action_utilities": derived})
    return proposal.model_copy(update=updates), corrections, None


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _construction_gate_rejection(
    proposal: PairProposal,
    source: dict[str, JsonValue],
) -> str | None:
    """Fail closed when fact neutralization or context interaction is not inspectable."""

    if not proposal.admitted:
        return None
    assert proposal.shared_decision_context is not None
    assert proposal.changed_fact is not None
    if len(proposal.required_invariant_facts) < 2:
        return "fewer than two interacting invariant facts were registered"
    if not set(proposal.required_invariant_facts) <= set(proposal.invariant_facts):
        return "required invariant facts are outside the invariant fact list"
    if not proposal.neutralized_source_spans:
        return "no exact source-span neutralization was registered"
    if proposal.boundary_only_insufficient_reason is None:
        return "boundary-only insufficiency was not explained"
    shared = _normalized_text(proposal.shared_decision_context)
    source_texts = [
        _normalized_text(str(source[field]))
        for field in ("article_title", "reviewed_abstract", "predecision_review_context")
        if isinstance(source.get(field), str)
    ]
    for fact in proposal.required_invariant_facts:
        normalized_fact = _normalized_text(fact)
        if normalized_fact not in shared:
            return "a required invariant fact is not visible verbatim in shared context"
        if not any(normalized_fact in source_text for source_text in source_texts):
            return "a required invariant fact is not grounded verbatim in a source field"
    for span in proposal.neutralized_source_spans:
        source_value = source.get(span.source_field)
        if not isinstance(source_value, str):
            return f"neutralized source field is unavailable: {span.source_field}"
        normalized_span = _normalized_text(span.exact_text)
        if normalized_span not in _normalized_text(source_value):
            return "a neutralized source span is not an exact source substring"
        if normalized_span in shared:
            return "a neutralized source span remains in shared context"
    for value in (
        proposal.changed_fact.base_value,
        proposal.changed_fact.twin_value,
    ):
        normalized_value = _normalized_text(value)
        if len(normalized_value) >= 12 and normalized_value in shared:
            return "shared context repeats a registered boundary value"
    return None


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
    temporary.replace(path)


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_raw = _bytes(config_path)
    config = BoundaryConstructionConfig.model_validate(yaml.safe_load(config_raw))
    screening_path = _bound(root, config.screening_items)
    decisions_path = _bound(root, config.caseability_decisions)
    backend_path = _bound(root, config.constructor_backend)
    screening = {str(item["intake_candidate_id"]): item for item in _jsonl(screening_path)}
    decisions = {_caseability_candidate_id(item): item for item in _jsonl(decisions_path)}
    selected_ids = [item.intake_candidate_id for item in config.selected_candidates]
    missing = sorted(set(selected_ids) - screening.keys() | set(selected_ids) - decisions.keys())
    if missing:
        raise ValueError("selected candidates are missing: " + ", ".join(missing))
    backend_config = load_structured_openai_compatible_config(backend_path)
    if (backend_config.provider, backend_config.model) != (
        config.constructor_provider,
        config.constructor_model,
    ):
        raise ValueError("constructor backend identity differs from frozen config")
    policy_fingerprint = content_sha256(
        {
            "config_sha256": hashlib.sha256(config_raw).hexdigest(),
            "backend_sha256": config.constructor_backend.sha256,
            "instruction": _instruction(),
        }
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    backend = StructuredOpenAICompatibleBackend(backend_config) if args.allow_api else None
    pairs: list[BoundaryCounterfactualPair] = []
    rejections: list[dict[str, str]] = []
    normalizations: list[dict[str, str]] = []
    completed_response_count = 0
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for offset in range(0, len(config.selected_candidates), config.batch_size):
        batch_number = offset // config.batch_size + 1
        selections = config.selected_candidates[offset : offset + config.batch_size]
        candidates: list[dict[str, JsonValue]] = []
        for selection in selections:
            source = screening[selection.intake_candidate_id]
            caseability = decisions[selection.intake_candidate_id]
            final = _caseability_decision(caseability)
            if str(final["decision_context_family"]) != (selection.decision_context_family.value):
                raise ValueError("selected candidate context differs from caseability screen")
            candidates.append(
                {
                    "intake_candidate_id": selection.intake_candidate_id,
                    "domain": str(source["domain"]),
                    "decision_context_family": selection.decision_context_family.value,
                    "taste_judgment_family": str(final["taste_judgment_family"]),
                    "atomic_decision_question": str(final["atomic_decision_question"]),
                    "article_title": str(source["article_title"]),
                    "reviewed_abstract": str(source["reviewed_abstract"]),
                    "predecision_review_context": str(source["predecision_review_context"]),
                }
            )
        request = _request(
            config,
            batch_number=batch_number,
            candidates=candidates,
            policy_fingerprint=policy_fingerprint,
        )
        _write(
            output / "requests" / f"{batch_number:02d}.json",
            (request.model_dump_json(indent=2) + "\n").encode(),
        )
        response_path = output / "responses" / f"{batch_number:02d}.json"
        if args.resume and response_path.is_file():
            response = StructuredModelResponse.model_validate_json(_bytes(response_path))
            if response.request_fingerprint != request.fingerprint:
                raise ValueError(f"saved response request drift in batch {batch_number}")
        else:
            if backend is None:
                continue
            response = backend.complete(request)
            _write(
                response_path,
                (response.model_dump_json(indent=2) + "\n").encode(),
            )
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        usage["cost_usd"] += response.usage.cost_usd or 0.0
        completed_response_count += 1
        normalized_payload, corrections = _normalize_output_payload(
            response.output_payload,
            request_id=request.request_id,
        )
        normalizations.extend(corrections)
        proposal_batch = BoundaryBatchProposal.model_validate(normalized_payload)
        expected_ids = [item.intake_candidate_id for item in selections]
        observed_ids = [item.intake_candidate_id for item in proposal_batch.proposals]
        if observed_ids != expected_ids:
            if not args.allow_partial:
                raise ValueError(f"constructor changed candidate order in batch {batch_number}")
            if len(observed_ids) != len(set(observed_ids)) or not set(observed_ids) <= set(
                expected_ids
            ):
                raise ValueError(f"constructor returned invalid identities in batch {batch_number}")
            retained_order = [item for item in expected_ids if item in set(observed_ids)]
            if observed_ids != retained_order:
                raise ValueError(
                    f"constructor reordered retained candidates in batch {batch_number}"
                )
            for missing_id in [item for item in expected_ids if item not in set(observed_ids)]:
                rejections.append(
                    {
                        "intake_candidate_id": missing_id,
                        "reason": "constructor response omitted candidate; no retry performed",
                    }
                )
        selection_by_id = {item.intake_candidate_id: item for item in selections}
        for proposal in proposal_batch.proposals:
            selection = selection_by_id[proposal.intake_candidate_id]
            if not proposal.admitted:
                rejections.append(
                    {
                        "intake_candidate_id": proposal.intake_candidate_id,
                        "reason": proposal.rejection_reason or "unspecified",
                    }
                )
                continue
            gate_rejection = (
                _construction_gate_rejection(
                    proposal,
                    screening[selection.intake_candidate_id],
                )
                if config.schema_version == "1.2"
                else None
            )
            if gate_rejection is not None:
                rejections.append(
                    {
                        "intake_candidate_id": proposal.intake_candidate_id,
                        "reason": gate_rejection,
                    }
                )
                continue
            proposal, utility_corrections, utility_rejection = _recompute_utility_scalars(
                proposal,
                config.utility_contract,
                request_id=request.request_id,
            )
            normalizations.extend(utility_corrections)
            if utility_rejection is not None:
                rejections.append(
                    {
                        "intake_candidate_id": proposal.intake_candidate_id,
                        "reason": utility_rejection,
                    }
                )
                continue
            pairs.append(
                _compile_pair(
                    proposal,
                    screening=screening[proposal.intake_candidate_id],
                    decision=decisions[proposal.intake_candidate_id],
                    context_family=selection.decision_context_family,
                    config=config,
                    request=request,
                    response_sha256=response.raw_response_sha256,
                )
            )
    plan = {
        "schema_version": "1.0",
        "construction_id": config.construction_id,
        "config": {
            "locator": str(config_path.relative_to(root)),
            "sha256": hashlib.sha256(config_raw).hexdigest(),
        },
        "policy_fingerprint": policy_fingerprint,
        "selected_candidate_count": len(config.selected_candidates),
        "batch_count": (len(config.selected_candidates) + config.batch_size - 1)
        // config.batch_size,
        "target_outcomes_visible": False,
        "formal_split_opened": False,
        "api_execution_performed": backend is not None,
    }
    _write(output / "PLAN.json", (json.dumps(plan, indent=2) + "\n").encode())
    if completed_response_count == 0:
        return 0
    expected_batch_count = (
        len(config.selected_candidates) + config.batch_size - 1
    ) // config.batch_size
    if completed_response_count != expected_batch_count and not args.allow_partial:
        raise ValueError("cannot compile a partial boundary construction package")
    omitted_candidate_count = sum(
        item["reason"].startswith("constructor response omitted candidate")
        for item in rejections
    )
    if not pairs:
        summary = {
            "schema_version": "1.0",
            "construction_id": config.construction_id,
            "selected_candidate_count": len(config.selected_candidates),
            "completed_response_count": completed_response_count,
            "expected_response_count": expected_batch_count,
            "complete": (
                completed_response_count == expected_batch_count
                and omitted_candidate_count == 0
            ),
            "omitted_candidate_count": omitted_candidate_count,
            "admitted_pair_count": 0,
            "rejected_candidate_count": len(rejections),
            "rejections": rejections,
            "bounded_normalization_count": len(normalizations),
            "bounded_normalizations": normalizations,
            "context_counts": {},
            "domain_counts": {},
            "package_sha256": None,
            "readiness": None,
            "usage": usage,
            "target_outcomes_used": False,
            "formal_split_opened": False,
            "effectiveness_claim_allowed": False,
        }
        _write(output / "SUMMARY.json", (json.dumps(summary, indent=2) + "\n").encode())
        return 0
    package = BoundaryPairPackage(
        package_id=config.construction_id,
        release_tier="development",
        pairs=tuple(pairs),
    )
    readiness = inspect_boundary_pair_package(package)
    _write(
        output / "PACKAGE.json",
        (package.model_dump_json(indent=2) + "\n").encode(),
    )
    summary = {
        "schema_version": "1.0",
        "construction_id": config.construction_id,
        "selected_candidate_count": len(config.selected_candidates),
        "completed_response_count": completed_response_count,
        "expected_response_count": expected_batch_count,
        "complete": (
            completed_response_count == expected_batch_count and omitted_candidate_count == 0
        ),
        "omitted_candidate_count": omitted_candidate_count,
        "admitted_pair_count": len(pairs),
        "rejected_candidate_count": len(rejections),
        "rejections": rejections,
        "bounded_normalization_count": len(normalizations),
        "bounded_normalizations": normalizations,
        "context_counts": dict(Counter(pair.decision_context_family.value for pair in pairs)),
        "domain_counts": dict(Counter(pair.domain for pair in pairs)),
        "package_sha256": package.sha256,
        "readiness": readiness.model_dump(mode="json"),
        "usage": usage,
        "target_outcomes_used": False,
        "formal_split_opened": False,
        "effectiveness_claim_allowed": False,
    }
    _write(output / "SUMMARY.json", (json.dumps(summary, indent=2) + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

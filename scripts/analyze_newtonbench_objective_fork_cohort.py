#!/usr/bin/env python3
"""Materialize Scientific Situations from a completed NewtonBench cohort.

This program consumes the already executed, paired-seed objective forks.  A
structured extractor sees only the selector-visible prefix, after which formal
source cases, pre-selection action maps, leave-one-task-cluster-out decisions,
and development-only authorization gates are compiled.  It never opens a
formal hidden split and cannot promote its estimates into paper results.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from scitaste.evaluation.counterfactual_taste import CounterfactualActionSetResult
from scitaste.evaluation.interactive_research import (
    InteractiveResearchPrefix,
    load_interactive_research_prefix,
    load_interactive_research_run_receipt,
)
from scitaste.evaluation.research_action_semantics import (
    ResearchActionSemanticsProfile,
    research_action_instruction,
)
from scitaste.evaluation.scientific_situation_transfer import (
    FormalObjectiveForkSituationCase,
    ObjectiveForkActionDefinition,
    ObjectiveForkConstructionManifest,
    ObjectiveForkExecutionContract,
    ObjectiveForkReplicateOutcome,
    ObjectiveForkScorerContract,
    ObjectiveForkTaskBinding,
    ScientificActionSemanticBinding,
    ScientificSituation,
    ScientificSituationActionMap,
    ScientificSituationAxis,
    ScientificSituationProposal,
    ScientificSituationTransferThresholds,
    select_by_scientific_situation,
    validate_scientific_situation_grounding,
)
from scitaste.model_nodes import (
    StructuredModelRequest,
    StructuredModelResponse,
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class SituationTransferCohortConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0", "1.1"] = "1.0"
    study_id: str
    project_id: str
    cohort_id: str
    cohort_root: str
    cohort_config: FileBinding
    plan: FileBinding
    execution_receipt: FileBinding
    limits: FileBinding
    extractor_backend: FileBinding
    extractor_provider: str
    extractor_model: str
    batch_size: int = Field(ge=1, le=8)
    seed: int = Field(ge=0)
    thresholds: ScientificSituationTransferThresholds
    analysis_mode: Literal["development-transfer-selection", "formal-case-materialization"] = (
        "development-transfer-selection"
    )
    split_assignment: Literal["development", "test"] = "development"
    expected_fork_count: int = Field(default=30, ge=3)
    expected_task_cluster_count: int = Field(default=10, ge=2)
    expected_seed_block_count: int = Field(default=3, ge=2)
    source_evidence_designation: Literal["fresh-development", "formal-confirmation"]
    target_outcomes_visible_to_extractor: Literal[False]
    target_outcomes_used_for_selection: Literal[False]
    formal_hidden_split_opened: bool


class SituationBatchItem(BaseModel):
    model_config = _CONFIG

    study_id: str
    situation: ScientificSituationProposal


class SituationBatch(BaseModel):
    model_config = _CONFIG

    items: tuple[SituationBatchItem, ...] = Field(min_length=1, max_length=8)


def _normalize_batch_anchor_cardinality(
    payload: object,
) -> tuple[object, dict[str, tuple[str, ...]]]:
    """Bound model-produced anchors before strict schema validation.

    The response schema asks for at most six anchors, but some compatible
    providers occasionally return extra exact quotes.  Preserve the anchors
    that cover the most not-yet-covered situation axes, then fill remaining
    slots in response order.  This never fabricates or rewrites evidence.
    """

    normalized = copy.deepcopy(payload)
    findings: dict[str, tuple[str, ...]] = {}
    if not isinstance(normalized, dict) or not isinstance(normalized.get("items"), list):
        return normalized, findings
    for item in normalized["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("situation"), dict):
            continue
        study_id = item.get("study_id")
        anchors = item["situation"].get("anchors")
        if not isinstance(study_id, str) or not isinstance(anchors, list):
            continue
        unique: list[dict[str, object]] = []
        identities: set[tuple[object, object]] = set()
        for anchor in anchors:
            if not isinstance(anchor, dict):
                continue
            identity = (anchor.get("field_id"), anchor.get("quote"))
            if identity in identities:
                continue
            identities.add(identity)
            unique.append(anchor)
        selected = list(unique)
        if len(unique) > 6:
            selected = []
            remaining = list(unique)
            uncovered = {
                "hypothesis_structure",
                "evidence_relation",
                "bottleneck",
                "identifiability",
                "budget_pressure",
                "terminal_readiness",
            }
            while remaining and uncovered and len(selected) < 6:
                best_index = max(
                    range(len(remaining)),
                    key=lambda index: len(
                        set(remaining[index].get("supports_axes", ())) & uncovered
                    ),
                )
                chosen = remaining.pop(best_index)
                selected.append(chosen)
                uncovered -= set(chosen.get("supports_axes", ()))
            selected.extend(remaining[: 6 - len(selected)])
        if selected != anchors:
            item["situation"]["anchors"] = selected
            findings[study_id] = (
                f"model-boundary-anchor-normalization:{len(anchors)}-to-{len(selected)}",
            )
    return normalized, findings


class CohortBinding(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    study_id: str
    task_id: str
    task_cluster_id: str
    prefix_id: str
    decision_axis: Literal["direction", "information", "inference"]
    seed_block_id: str
    result_locator: str
    result_sha256: str = Field(pattern=_SHA256)


class CohortExecutionReceipt(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    cohort_id: str
    bindings: tuple[CohortBinding, ...] = Field(min_length=1)
    formal_hidden_split_opened: bool
    evidence_designation: Literal["fresh-development", "formal-confirmation"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument(
        "--deterministic-extractor",
        action="store_true",
        help=(
            "Materialize a transparent outcome-hidden rule baseline without a model "
            "call. This is a disclosed fallback/sensitivity analysis, not a replacement "
            "for a preregistered model extractor."
        ),
    )
    parser.add_argument("--resume", action="store_true")
    return parser


def _bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bound input must be a regular file: {path}")
    return path.read_bytes()


def _sha256(path: Path) -> str:
    return hashlib.sha256(_bytes(path)).hexdigest()


def _bound(root: Path, binding: FileBinding) -> Path:
    path = (root / binding.locator).resolve(strict=True)
    path.relative_to(root)
    if _sha256(path) != binding.sha256:
        raise ValueError(f"bound input hash mismatch: {binding.locator}")
    return path


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
    temporary.replace(path)


def _visible_fields(prefix: InteractiveResearchPrefix) -> dict[str, str]:
    fields = {
        "trajectory-summary": (
            f"turn_count={prefix.turn_count}; experiment_count={prefix.experiment_count}"
        )
    }
    for turn in prefix.turns:
        proposal = turn.decision.proposal
        fields[f"turn-{turn.turn}-rationale"] = proposal.rationale
        fields[f"turn-{turn.turn}-evidence-state"] = (
            f"evidence_status={proposal.evidence_status}; "
            f"evidence_confidence={proposal.evidence_confidence:g}; "
            f"next_experiment_value={proposal.next_experiment_value:g}"
        )
        observation = {
            key: value
            for key, value in turn.observation.items()
            if key not in {"task_id", "environment_sha256"}
        }
        fields[f"turn-{turn.turn}-observation"] = json.dumps(
            observation,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return fields


def _instruction() -> str:
    axes = ", ".join(item.value for item in ScientificSituationAxis)
    return f"""Abstract each pre-decision scientific situation without recommending an action.
You receive only selector-visible state. Branch outcomes, action utilities, preferred actions,
and later evidence are absent and forbidden.

Classify the six closed fields exactly as defined by the response schema. Evidence anchors must
copy exact substrings from supplied visible_fields. Return 2--6 distinct anchors per item. Every
anchor declares supports_axes, and their union must cover all six axes: {axes}. One exact quote
may ground multiple axes only when its text genuinely supports each one. Lower
abstraction_confidence when evidence is ambiguous; never invent a fact. Return items in the input
order as one schema-valid JSON object and no prose outside it."""


def _deterministic_proposal(
    visible_fields: dict[str, str],
) -> ScientificSituationProposal:
    """Build one auditable outcome-hidden fallback from the latest visible turn."""

    summary = visible_fields["trajectory-summary"]
    turn_match = re.search(r"turn_count=(\d+)", summary)
    if turn_match is None:
        raise ValueError("deterministic situation extractor lacks turn_count")
    turn = int(turn_match.group(1))
    evidence_key = f"turn-{turn}-evidence-state"
    rationale_key = f"turn-{turn}-rationale"
    observation_key = f"turn-{turn}-observation"
    evidence = visible_fields[evidence_key]
    rationale = visible_fields[rationale_key]
    observation = visible_fields[observation_key]
    confidence_match = re.search(r"evidence_confidence=([-+0-9.eE]+)", evidence)
    value_match = re.search(r"next_experiment_value=([-+0-9.eE]+)", evidence)
    confidence = float(confidence_match.group(1)) if confidence_match else 0.0
    next_value = float(value_match.group(1)) if value_match else 1.0
    status_match = re.search(r"evidence_status=([^;]+)", evidence)
    status = status_match.group(1).casefold() if status_match else "unassessed"
    lowered = rationale.casefold()

    if turn == 1:
        hypothesis = "competing-candidates"
        relation = "absent" if confidence == 0 else "underdetermined"
        bottleneck = "variable-discovery"
        identifiability = "low"
        budget = "low"
        readiness = "not-ready"
    elif turn == 2:
        hypothesis = (
            "competing-candidates"
            if any(
                token in lowered
                for token in ("discrimin", "alternative", "versus", "against", "not yet")
            )
            else "single-candidate"
        )
        relation = (
            "conflicted"
            if any(token in lowered for token in ("contradict", "inconsistent", "conflict"))
            else "underdetermined"
        )
        bottleneck = (
            "contradiction-resolution"
            if relation == "conflicted"
            else "functional-form-discrimination"
        )
        identifiability = "medium"
        budget = "medium"
        readiness = "not-ready"
    else:
        hypothesis = "single-candidate"
        if any(token in lowered for token in ("contradict", "inconsistent", "conflict")):
            relation = "conflicted"
            bottleneck = "contradiction-resolution"
        elif confidence >= 0.7 or "supported" in status:
            relation = "consistent"
            bottleneck = "terminal-calibration" if next_value <= 0.7 else "robustness-validation"
        else:
            relation = "underdetermined"
            bottleneck = "functional-form-discrimination"
        identifiability = "high" if relation == "consistent" else "medium"
        budget = "medium"
        readiness = (
            "ready"
            if relation == "consistent" and confidence >= 0.85 and next_value <= 0.5
            else "ambiguous"
        )

    anchors = (
        {
            "field_id": "trajectory-summary",
            "quote": summary,
            "supports_axes": ["budget_pressure", "terminal_readiness"],
        },
        {
            "field_id": evidence_key,
            "quote": evidence,
            "supports_axes": [
                "evidence_relation",
                "identifiability",
                "terminal_readiness",
            ],
        },
        {
            "field_id": rationale_key,
            "quote": rationale[:500],
            "supports_axes": ["hypothesis_structure", "bottleneck"],
        },
        {
            "field_id": observation_key,
            "quote": observation[:500],
            "supports_axes": ["evidence_relation"],
        },
    )
    return ScientificSituationProposal.model_validate(
        {
            "hypothesis_structure": hypothesis,
            "evidence_relation": relation,
            "bottleneck": bottleneck,
            "identifiability": identifiability,
            "budget_pressure": budget,
            "terminal_readiness": readiness,
            "anchors": anchors,
            "decision_basis": (
                "Deterministic outcome-hidden fallback derived from the latest visible "
                f"evidence status ({status}), confidence ({confidence:g}), next-experiment "
                f"value ({next_value:g}), and turn ({turn})."
            ),
            "abstraction_confidence": 0.75,
        }
    )


def _compact_positions(text: str) -> tuple[str, list[int]]:
    compact: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(text):
        if character.isspace():
            continue
        compact.append(character)
        positions.append(index)
    return "".join(compact), positions


def _repair_exact_anchors(
    proposal: ScientificSituationProposal,
    visible_fields: dict[str, str],
) -> tuple[ScientificSituationProposal, tuple[str, ...]]:
    repaired = []
    findings: list[str] = []
    for anchor in proposal.anchors:
        source = visible_fields.get(anchor.field_id)
        if source is None:
            raise ValueError(f"unknown situation anchor field: {anchor.field_id}")
        if anchor.quote in source:
            repaired.append(anchor)
            continue
        compact_source, positions = _compact_positions(source)
        compact_quote, _ = _compact_positions(anchor.quote)
        offset = compact_source.find(compact_quote)
        if offset < 0:
            # A provider may paraphrase one clause while retaining other exact
            # clauses from the same visible field.  Keep only the longest exact
            # sentence/clause fragment; never synthesize or edit evidence text.
            fragments = tuple(
                fragment.strip()
                for fragment in re.split(r"(?<=[.!?;])\s+|\s+(?=However,|But\s)", anchor.quote)
                if len(fragment.strip()) >= 2 and fragment.strip() in source
            )
            if fragments:
                exact_fragment = max(fragments, key=lambda item: (len(item), item))
                repaired.append(anchor.model_copy(update={"quote": exact_fragment}))
                findings.append(f"span-shortened:{anchor.field_id}:{len(repaired) - 1}")
                continue
            # Preserve the proposal so the ordinary grounding validator can report
            # the bad span and the registered model-repair path can correct it.
            repaired.append(anchor)
            continue
        end = offset + len(compact_quote) - 1
        exact = source[positions[offset] : positions[end] + 1]
        repaired.append(anchor.model_copy(update={"quote": exact}))
        findings.append(f"whitespace-normalized:{anchor.field_id}:{len(repaired) - 1}")
    return proposal.model_copy(update={"anchors": tuple(repaired)}), tuple(findings)


def _request(
    config: SituationTransferCohortConfig,
    *,
    batch_number: int,
    records: list[tuple[str, dict[str, str]]],
    policy_fingerprint: str,
) -> StructuredModelRequest:
    request = StructuredModelRequest(
        request_id=f"{config.study_id}-extract-{batch_number:02d}",
        node_name="scientific-situation-extractor",
        stage="EVALUATION",
        state_snapshot_id=f"{config.study_id}-outcome-hidden",
        expected_backend=config.extractor_provider,
        expected_model=config.extractor_model,
        policy_id=config.study_id,
        policy_fingerprint=policy_fingerprint,
        system_instruction=_instruction(),
        input_payload={
            "target_outcomes_visible": False,
            "action_recommendation_requested": False,
            "items": [
                {"study_id": study_id, "visible_fields": fields} for study_id, fields in records
            ],
        },
        output_schema=SituationBatch.model_json_schema(mode="serialization"),
        seed=config.seed + batch_number,
        prompt_version="predecision-scientific-situation-v2-axis-grounded",
    )
    encoded = json.dumps(
        request.input_payload,
        ensure_ascii=False,
        sort_keys=True,
    ).casefold()
    forbidden = ("objective_value", "preferred_actions", "branch outcomes")
    if any(item in encoded for item in forbidden):
        raise ValueError("target outcome leaked into a scientific-situation request")
    return request


def _repair_request(
    config: SituationTransferCohortConfig,
    *,
    batch_number: int,
    item_number: int,
    repair_attempt: int,
    study_id: str,
    visible_fields: dict[str, str],
    proposal: ScientificSituationProposal,
    findings: tuple[str, ...],
    policy_fingerprint: str,
) -> StructuredModelRequest:
    request = _request(
        config,
        batch_number=10_000 + 100 * batch_number + 10 * item_number + repair_attempt,
        records=[(study_id, visible_fields)],
        policy_fingerprint=policy_fingerprint,
    )
    return request.model_copy(
        update={
            "request_id": (
                f"{config.study_id}-repair-{batch_number:02d}-{item_number:02d}-"
                f"{repair_attempt:02d}"
            ),
            "system_instruction": (
                _instruction()
                + "\n\nThe previous outcome-hidden proposal failed deterministic grounding "
                f"validation with: {', '.join(findings)}. Return a corrected proposal. "
                "Do not change a classification merely to satisfy the schema; instead cite an "
                "exact visible span that genuinely supports every missing axis."
            ),
            "input_payload": {
                "target_outcomes_visible": False,
                "action_recommendation_requested": False,
                "validation_findings": list(findings),
                "previous_proposal": proposal.model_dump(mode="json"),
                "items": [{"study_id": study_id, "visible_fields": visible_fields}],
            },
            "seed": config.seed + 10_000 + 100 * batch_number + 10 * item_number + repair_attempt,
            "prompt_version": "predecision-scientific-situation-v2-grounding-repair",
        }
    )


def _load_records(
    root: Path,
    receipt: CohortExecutionReceipt,
) -> tuple[
    dict[
        str,
        list[
            tuple[
                CohortBinding,
                Path,
                InteractiveResearchPrefix,
                CounterfactualActionSetResult,
            ]
        ],
    ],
    dict[str, dict[str, str]],
]:
    grouped: dict[
        str,
        list[tuple[CohortBinding, Path, InteractiveResearchPrefix, CounterfactualActionSetResult]],
    ] = defaultdict(list)
    for binding in receipt.bindings:
        result_path = (root / binding.result_locator).resolve(strict=True)
        result_path.relative_to(root)
        result = CounterfactualActionSetResult.model_validate_json(_bytes(result_path), strict=True)
        if result.result_sha256 != binding.result_sha256:
            raise ValueError(f"objective-fork result drift: {binding.study_id}")
        prefix = load_interactive_research_prefix(result_path.parent / "PREFIX.json")
        if result.prefix_sha256 != prefix.prefix_sha256:
            raise ValueError(f"objective-fork prefix drift: {binding.study_id}")
        grouped[binding.study_id].append((binding, result_path, prefix, result))
    visible: dict[str, dict[str, str]] = {}
    for study_id, rows in grouped.items():
        rows.sort(key=lambda item: item[0].seed_block_id)
        fields = [_visible_fields(item[2]) for item in rows]
        if any(item != fields[0] for item in fields[1:]):
            raise ValueError(f"selector-visible state differs across blocks: {study_id}")
        visible[study_id] = fields[0]
    return dict(grouped), visible


def _action_definitions(actions: tuple[str, ...]) -> tuple[ObjectiveForkActionDefinition, ...]:
    profile = ResearchActionSemanticsProfile.HIDDEN_LAW_DISCOVERY
    return tuple(
        ObjectiveForkActionDefinition.create(
            action_id=action,
            semantic_role=f"hidden-law-{action.casefold()}",
            description=research_action_instruction(profile, action),
            executor_id="scitaste-interactive-research-v1",
            command_template=("force-registered-research-action", action),
        )
        for action in actions
    )


def _replicate_outcome(
    *,
    study_id: str,
    block_id: str,
    action_definition: ObjectiveForkActionDefinition,
    result_path: Path,
    result: CounterfactualActionSetResult,
) -> ObjectiveForkReplicateOutcome:
    outcome = next(
        item for item in result.outcomes if item.action.value == action_definition.action_id
    )
    receipt_path = result_path.parent / outcome.action.value.casefold() / "RECEIPT.json"
    receipt = load_interactive_research_run_receipt(receipt_path)
    observed = outcome.objective_observed
    utility = float(outcome.objective_value) if observed else 0.0
    if observed and utility <= 0.0:
        raise ValueError("observed exp-negative utility must be strictly positive")
    raw_metric = -math.log(utility) if observed else None
    return ObjectiveForkReplicateOutcome.create(
        action_id=action_definition.action_id,
        replicate_id=f"{study_id}-{block_id}-{action_definition.action_id.casefold()}",
        seed_block_id=block_id,
        requested_action_definition_sha256=action_definition.definition_sha256,
        action_compliance="compliant",
        action_trace_sha256=outcome.intervention_sha256,
        executed=receipt.status == "completed",
        objective_observed=observed,
        raw_metric_value=raw_metric,
        utility=utility,
        failure_code=(None if observed else receipt.status),
    )


def _formal_case(
    *,
    root: Path,
    config: SituationTransferCohortConfig,
    plan: dict[str, object],
    limits: dict[str, object],
    backend_timeout: int,
    situation: ScientificSituation,
    rows: list[
        tuple[
            CohortBinding,
            Path,
            InteractiveResearchPrefix,
            CounterfactualActionSetResult,
        ]
    ],
) -> FormalObjectiveForkSituationCase:
    first_binding, first_path, first_prefix, first_result = rows[0]
    actions = tuple(sorted(item.action.value for item in first_result.outcomes))
    definitions = _action_definitions(actions)
    definition_by_action = {item.action_id: item for item in definitions}
    for binding, _, prefix, result in rows:
        if tuple(sorted(item.action.value for item in result.outcomes)) != actions:
            raise ValueError(f"action menu drift across blocks: {binding.study_id}")
        if result.environment_sha256 != first_result.environment_sha256:
            raise ValueError(f"environment drift across blocks: {binding.study_id}")
        if prefix.task_sha256 != first_prefix.task_sha256:
            raise ValueError(f"task drift across blocks: {binding.study_id}")
    parts = first_path.relative_to(root).parts
    slug = parts[parts.index("tasks") + 1]
    task_lock = (root / config.cohort_root / "locks" / f"{slug}.json").resolve(strict=True)
    task_lock.relative_to(root)
    seed_blocks = tuple(sorted(item[0].seed_block_id for item in rows))
    execution = ObjectiveForkExecutionContract.create(
        contract_id=f"{config.cohort_id}-paired-runtime-v1",
        allowed_tools=("newtonbench.run_experiments", "newtonbench.submit_hypothesis"),
        resource_limits={
            key: float(value)
            for key, value in limits.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        },
        maximum_steps=int(limits["max_turns"]),
        timeout_seconds=int(backend_timeout),
        network_access=True,
        seed_block_ids=seed_blocks,
        minimum_action_compliance_rate=1.0,
    )
    scorer = ObjectiveForkScorerContract.create(
        scorer_id="newtonbench-rmsle-v1",
        implementation_sha256=content_sha256(
            {"metric": "rmsle", "transform": "exp-negative", "version": "v1"}
        ),
        metric_name="rmsle",
        metric_direction="lower",
        raw_scale_minimum=0.0,
        raw_scale_maximum=1_000_000.0,
        utility_transform="registered-exp-negative-v1",
        utility_contract_id="newtonbench-exp-negative-rmsle-v1",
        practical_equivalence_tolerance=first_result.practical_equivalence_tolerance,
        intention_to_treat_failure_utility=0.0,
    )
    construction = ObjectiveForkConstructionManifest.create(
        source_collection_id=config.cohort_id,
        source_version=str(plan["benchmark_repository_commit"]),
        construction_protocol_sha256=config.cohort_config.sha256,
        constructor_provider="scitaste-native",
        constructor_model="objective-fork-cohort-v2",
        split_assignment=config.split_assignment,
        contamination_audit_protocol="exact-task-id-exclusion-v1",
        contamination_corpora=("registered-consumed-newtonbench-task-ids",),
        contamination_report_sha256=str(plan["consumed_task_ids_sha256"]),
    )
    replicate_outcomes = tuple(
        _replicate_outcome(
            study_id=first_binding.study_id,
            block_id=binding.seed_block_id,
            action_definition=definition_by_action[action],
            result_path=result_path,
            result=result,
        )
        for binding, result_path, _, result in rows
        for action in actions
    )
    return FormalObjectiveForkSituationCase.create(
        study_id=first_binding.study_id,
        task_cluster_id=first_binding.task_cluster_id,
        situation=situation,
        task_binding=ObjectiveForkTaskBinding(
            task_locator=str(task_lock.relative_to(root)),
            task_sha256=first_prefix.task_sha256,
            environment_sha256=first_result.environment_sha256,
            code_sha256=content_sha256(
                {"benchmark_repository_commit": plan["benchmark_repository_commit"]}
            ),
            prefix_state_sha256=situation.prefix_sha256,
            split_assignment=config.split_assignment,
        ),
        available_actions=actions,
        action_definitions=definitions,
        execution_contract=execution,
        scorer_contract=scorer,
        construction_manifest=construction,
        replicate_outcomes=replicate_outcomes,
    )


def _identity_map(
    *,
    source: FormalObjectiveForkSituationCase,
    target: FormalObjectiveForkSituationCase,
) -> ScientificSituationActionMap:
    source_definitions = {item.action_id: item for item in source.action_definitions}
    target_definitions = {item.action_id: item for item in target.action_definitions}
    if set(source_definitions) != set(target_definitions):
        raise ValueError("identity map requires the same registered menu")
    bindings = tuple(
        ScientificActionSemanticBinding(
            source_action_id=action,
            source_action_definition_sha256=source_definitions[action].definition_sha256,
            target_action=target_definitions[action],
            mapping_rationale=(
                "The source and target use the same frozen hidden-law action profile, "
                "semantic role, executor, and command template."
            ),
            boundary_conditions=(
                "same hidden-law-discovery semantics profile",
                "same decision-axis action menu",
                "same exp-negative RMSLE utility contract",
            ),
            mapping_confidence=1.0,
        )
        for action in target.available_actions
    )
    request_fingerprint = content_sha256(
        {"source": source.study_id, "target": target.study_id, "actions": target.available_actions}
    )
    return ScientificSituationActionMap.create(
        source_study_id=source.study_id,
        bindings=bindings,
        adjudicator_provider="deterministic",
        adjudicator_model="content-bound-identity-map-v1",
        request_fingerprint=request_fingerprint,
        response_sha256=content_sha256([item.model_dump(mode="json") for item in bindings]),
    )


def _static_action(
    target: FormalObjectiveForkSituationCase,
    sources: tuple[FormalObjectiveForkSituationCase, ...],
) -> str:
    values: dict[str, list[float]] = {action: [] for action in target.available_actions}
    for source in sources:
        if (
            source.task_cluster_id == target.task_cluster_id
            or source.available_actions != target.available_actions
        ):
            continue
        for action in target.available_actions:
            values[action].append(source.action_utility_estimates[action])
    means = {key: sum(rows) / len(rows) for key, rows in values.items() if rows}
    return min(means, key=lambda action: (-means[action], action))


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_raw = _bytes(config_path)
    config = SituationTransferCohortConfig.model_validate(yaml.safe_load(config_raw))
    validate_entry_id(config.study_id, field_name="situation-transfer study_id")
    validate_project_id(config.project_id)
    _bound(root, config.cohort_config)
    plan = json.loads(_bytes(_bound(root, config.plan)))
    receipt = CohortExecutionReceipt.model_validate_json(
        _bytes(_bound(root, config.execution_receipt)), strict=True
    )
    limits = json.loads(_bytes(_bound(root, config.limits)))
    backend_path = _bound(root, config.extractor_backend)
    backend_config = load_structured_openai_compatible_config(backend_path)
    if (backend_config.provider, backend_config.model) != (
        config.extractor_provider,
        config.extractor_model,
    ):
        raise ValueError("scientific-situation extractor identity differs")
    if receipt.cohort_id != config.cohort_id:
        raise ValueError("cohort execution receipt identity differs")
    formal = config.analysis_mode == "formal-case-materialization"
    if formal != (config.split_assignment == "test"):
        raise ValueError("situation materialization mode and split assignment differ")
    if formal != config.formal_hidden_split_opened:
        raise ValueError("situation materialization mode and formal-open flag differ")
    if receipt.formal_hidden_split_opened != config.formal_hidden_split_opened:
        raise ValueError("cohort and materialization formal-open flags differ")
    if receipt.evidence_designation != config.source_evidence_designation:
        raise ValueError("cohort and materialization evidence designations differ")
    grouped, visible = _load_records(root, receipt)
    ordered_ids = sorted(grouped)
    observed_cluster_count = len(
        {row[0].task_cluster_id for rows in grouped.values() for row in rows}
    )
    if (
        len(ordered_ids) != config.expected_fork_count
        or observed_cluster_count != config.expected_task_cluster_count
        or any(len(rows) != config.expected_seed_block_count for rows in grouped.values())
    ):
        raise ValueError("objective-fork cohort population differs from the frozen design")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    policy_fingerprint = content_sha256(
        {
            "config_sha256": hashlib.sha256(config_raw).hexdigest(),
            "backend_sha256": config.extractor_backend.sha256,
            "instruction": _instruction(),
        }
    )
    if args.allow_api and args.deterministic_extractor:
        raise ValueError("choose either the registered API extractor or deterministic fallback")
    backend = StructuredOpenAICompatibleBackend(backend_config) if args.allow_api else None
    situations: dict[str, ScientificSituation] = {}
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    batch_count = (len(ordered_ids) + config.batch_size - 1) // config.batch_size
    for offset in range(0, len(ordered_ids), config.batch_size):
        batch_number = offset // config.batch_size + 1
        ids = ordered_ids[offset : offset + config.batch_size]
        request = _request(
            config,
            batch_number=batch_number,
            records=[(study_id, visible[study_id]) for study_id in ids],
            policy_fingerprint=policy_fingerprint,
        )
        request_path = output / "requests" / f"{batch_number:02d}.json"
        _write(request_path, (request.model_dump_json(indent=2) + "\n").encode())
        if args.deterministic_extractor:
            for study_id in ids:
                proposal = _deterministic_proposal(visible[study_id])
                situation = ScientificSituation.create(
                    study_id=study_id,
                    task_cluster_id=grouped[study_id][0][0].task_cluster_id,
                    prefix_sha256=content_sha256(visible[study_id]),
                    **proposal.model_dump(mode="python"),
                    anchor_normalization_repairs=(),
                    extractor_provider="deterministic",
                    extractor_model="outcome-hidden-situation-rule-v1",
                    request_fingerprint=request.fingerprint,
                    response_sha256=content_sha256(proposal.model_dump(mode="json")),
                )
                grounding = validate_scientific_situation_grounding(
                    situation,
                    visible_fields=visible[study_id],
                    require_all_axes=True,
                )
                if grounding:
                    raise ValueError(
                        f"deterministic situation grounding failed for {study_id}: {grounding}"
                    )
                situations[study_id] = situation
            continue
        response_path = output / "responses" / f"{batch_number:02d}.json"
        if args.resume and response_path.is_file():
            response = StructuredModelResponse.model_validate_json(_bytes(response_path))
            if response.request_fingerprint != request.fingerprint:
                raise ValueError(f"saved extractor response drift: batch {batch_number}")
        else:
            if backend is None:
                continue
            response = backend.complete(request)
            _write(response_path, (response.model_dump_json(indent=2) + "\n").encode())
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        usage["cost_usd"] += response.usage.cost_usd or 0.0
        normalized_payload, batch_normalizations = _normalize_batch_anchor_cardinality(
            response.output_payload
        )
        parsed = SituationBatch.model_validate(normalized_payload)
        if [item.study_id for item in parsed.items] != ids:
            raise ValueError(f"extractor item order drift: batch {batch_number}")
        for item_number, item in enumerate(parsed.items, 1):
            proposal = item.situation
            normalization_repairs = batch_normalizations.get(item.study_id, ())
            active_request = request
            active_response = response
            situation = None
            for repair_attempt in range(0, 3):
                proposal, repairs = _repair_exact_anchors(proposal, visible[item.study_id])
                task_cluster_id = grouped[item.study_id][0][0].task_cluster_id
                candidate = ScientificSituation.create(
                    study_id=item.study_id,
                    task_cluster_id=task_cluster_id,
                    prefix_sha256=content_sha256(visible[item.study_id]),
                    **proposal.model_dump(mode="python"),
                    anchor_normalization_repairs=normalization_repairs + repairs,
                    extractor_provider=active_response.backend,
                    extractor_model=active_response.model,
                    request_fingerprint=active_request.fingerprint,
                    response_sha256=active_response.raw_response_sha256,
                )
                grounding = validate_scientific_situation_grounding(
                    candidate,
                    visible_fields=visible[item.study_id],
                    require_all_axes=True,
                )
                if not grounding:
                    situation = candidate
                    break
                if repair_attempt == 2 or backend is None:
                    raise ValueError(
                        f"formal situation grounding failed for {item.study_id}: {grounding}"
                    )
                repair_number = repair_attempt + 1
                active_request = _repair_request(
                    config,
                    batch_number=batch_number,
                    item_number=item_number,
                    repair_attempt=repair_number,
                    study_id=item.study_id,
                    visible_fields=visible[item.study_id],
                    proposal=proposal,
                    findings=grounding,
                    policy_fingerprint=policy_fingerprint,
                )
                repair_request_path = (
                    output
                    / "repair_requests"
                    / f"{batch_number:02d}-{item_number:02d}-{repair_number:02d}.json"
                )
                _write(
                    repair_request_path,
                    (active_request.model_dump_json(indent=2) + "\n").encode(),
                )
                repair_response_path = (
                    output
                    / "repair_responses"
                    / f"{batch_number:02d}-{item_number:02d}-{repair_number:02d}.json"
                )
                if args.resume and repair_response_path.is_file():
                    active_response = StructuredModelResponse.model_validate_json(
                        _bytes(repair_response_path)
                    )
                    if active_response.request_fingerprint != active_request.fingerprint:
                        raise ValueError("saved grounding-repair response drift")
                else:
                    active_response = backend.complete(active_request)
                    _write(
                        repair_response_path,
                        (active_response.model_dump_json(indent=2) + "\n").encode(),
                    )
                usage["input_tokens"] += active_response.usage.input_tokens
                usage["output_tokens"] += active_response.usage.output_tokens
                usage["cost_usd"] += active_response.usage.cost_usd or 0.0
                normalized_repair, repair_normalizations = _normalize_batch_anchor_cardinality(
                    active_response.output_payload
                )
                repaired = SituationBatch.model_validate(normalized_repair)
                if len(repaired.items) != 1 or repaired.items[0].study_id != item.study_id:
                    raise ValueError("grounding repair changed item identity")
                normalization_repairs += repair_normalizations.get(item.study_id, ())
                proposal = repaired.items[0].situation
            assert situation is not None
            situations[item.study_id] = situation

    plan_record = {
        "schema_version": "1.0",
        "study_id": config.study_id,
        "cohort_id": config.cohort_id,
        "fork_count": len(ordered_ids),
        "task_cluster_count": config.expected_task_cluster_count,
        "paired_seed_block_count": config.expected_seed_block_count,
        "branch_trajectory_count": sum(
            len(row[3].outcomes) for rows in grouped.values() for row in rows
        ),
        "extractor_batch_count": batch_count,
        "extractor_mode": (
            "deterministic-outcome-hidden-fallback-v1"
            if args.deterministic_extractor
            else "registered-structured-model"
        ),
        "policy_fingerprint": policy_fingerprint,
        "target_outcomes_visible_to_extractor": False,
        "target_outcomes_used_for_selection": False,
        "formal_hidden_split_opened": config.formal_hidden_split_opened,
        "split_assignment": config.split_assignment,
        "evidence_designation": config.source_evidence_designation,
    }
    _write(output / "PLAN.json", (json.dumps(plan_record, indent=2) + "\n").encode())
    if len(situations) != len(ordered_ids):
        if backend is None:
            print(json.dumps(plan_record, indent=2))
            return 0
        raise ValueError("cannot compile a partial situation-transfer population")

    cases = tuple(
        _formal_case(
            root=root,
            config=config,
            plan=plan,
            limits=limits,
            backend_timeout=backend_config.timeout_seconds,
            situation=situations[study_id],
            rows=grouped[study_id],
        )
        for study_id in ordered_ids
    )
    if formal:
        situation_lines = "".join(situations[item].model_dump_json() + "\n" for item in ordered_ids)
        case_lines = "".join(item.model_dump_json() + "\n" for item in cases)
        _write(output / "SITUATIONS.jsonl", situation_lines.encode())
        _write(output / "FORMAL_TEST_CASES.jsonl", case_lines.encode())
        report = {
            "schema_version": "1.0",
            "study_id": config.study_id,
            "method": "outcome-hidden-scientific-situation-materialization-v1",
            "population_count": len(cases),
            "task_cluster_count": len({item.task_cluster_id for item in cases}),
            "paired_seed_block_count": config.expected_seed_block_count,
            "branch_trajectory_count": sum(len(item.replicate_outcomes) for item in cases),
            "target_outcomes_visible_to_extractor": False,
            "target_outcomes_used_for_selection": False,
            "formal_hidden_split_opened": True,
            "split_assignment": "test",
            "source_evidence_designation": config.source_evidence_designation,
            "extractor_mode": plan_record["extractor_mode"],
            "formal_case_materialization_complete": True,
            "effect_claim_authorized": False,
            "usage": usage,
            "situations_sha256": hashlib.sha256(situation_lines.encode()).hexdigest(),
            "formal_test_cases_sha256": hashlib.sha256(case_lines.encode()).hexdigest(),
        }
        report["report_sha256"] = content_sha256(report)
        _write(output / "REPORT.json", (json.dumps(report, indent=2) + "\n").encode())
        print(json.dumps(report, indent=2))
        return 0

    decisions = []
    maps = []
    result_rows = []
    for target in cases:
        target_maps = tuple(
            _identity_map(source=source, target=target)
            for source in cases
            if source.task_cluster_id != target.task_cluster_id
            and source.available_actions == target.available_actions
        )
        maps.extend(target_maps)
        decision = select_by_scientific_situation(
            target=target.situation,
            sources=cases,
            available_actions=set(target.available_actions),
            thresholds=config.thresholds,
            action_maps=target_maps,
        )
        decisions.append(decision)
        best_utility = max(target.action_utility_estimates.values())
        preferred = tuple(
            sorted(
                action
                for action, utility in target.action_utility_estimates.items()
                if best_utility - utility <= target.scorer_contract.practical_equivalence_tolerance
            )
        )
        selected_utility = (
            None
            if decision.selected_action is None
            else target.action_utility_estimates[decision.selected_action]
        )
        static_action = _static_action(target, cases)
        static_utility = target.action_utility_estimates[static_action]
        result_rows.append(
            {
                "study_id": target.study_id,
                "task_cluster_id": target.task_cluster_id,
                "available_actions": list(target.available_actions),
                "selected_action": decision.selected_action,
                "abstained": decision.abstained,
                "abstention_reasons": list(decision.abstention_reasons),
                "coverage": 0 if decision.abstained else 1,
                "selected_utility": selected_utility,
                "selected_regret": (
                    None if selected_utility is None else best_utility - selected_utility
                ),
                "selected_preferred": decision.selected_action in preferred,
                "static_action": static_action,
                "static_utility": static_utility,
                "static_regret": best_utility - static_utility,
                "static_preferred": static_action in preferred,
                "preferred_actions": list(preferred),
                "best_utility": best_utility,
                "decision_sha256": decision.decision_sha256,
            }
        )

    situation_lines = "".join(situations[item].model_dump_json() + "\n" for item in ordered_ids)
    case_lines = "".join(item.model_dump_json() + "\n" for item in cases)
    map_lines = "".join(item.model_dump_json() + "\n" for item in maps)
    decision_lines = "".join(item.model_dump_json() + "\n" for item in decisions)
    result_lines = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in result_rows
    )
    for name, content in (
        ("SITUATIONS.jsonl", situation_lines),
        ("FORMAL_DEVELOPMENT_CASES.jsonl", case_lines),
        ("ACTION_MAPS.jsonl", map_lines),
        ("DECISIONS.jsonl", decision_lines),
        ("RESULTS.jsonl", result_lines),
    ):
        _write(output / name, content.encode())

    selected = [item for item in result_rows if not item["abstained"]]
    selector_regret = (
        sum(float(item["selected_regret"]) for item in selected) / len(selected)
        if selected
        else None
    )
    static_matched_regret = (
        sum(float(item["static_regret"]) for item in selected) / len(selected) if selected else None
    )
    selector_precision = (
        sum(bool(item["selected_preferred"]) for item in selected) / len(selected)
        if selected
        else None
    )
    static_matched_precision = (
        sum(bool(item["static_preferred"]) for item in selected) / len(selected)
        if selected
        else None
    )
    selected_actions = {str(item["selected_action"]) for item in selected}
    gates = {
        "nontrivial_coverage": len(selected) / len(result_rows) >= 0.25,
        "action_diversity": len(selected_actions) >= 2,
        "lower_regret_than_static_on_interventions": (
            selector_regret is not None
            and static_matched_regret is not None
            and selector_regret < static_matched_regret
        ),
        "higher_precision_than_static_on_interventions": (
            selector_precision is not None
            and static_matched_precision is not None
            and selector_precision > static_matched_precision
        ),
    }
    report = {
        "schema_version": "1.0",
        "study_id": config.study_id,
        "method": "typed-objective-fork-transfer-formal-schema-v3",
        "population_count": len(result_rows),
        "task_cluster_count": len({item["task_cluster_id"] for item in result_rows}),
        "paired_seed_block_count": 3,
        "branch_trajectory_count": 270,
        "selected_count": len(selected),
        "abstained_count": len(result_rows) - len(selected),
        "coverage": len(selected) / len(result_rows),
        "selected_actions": sorted(selected_actions),
        "selector_precision": selector_precision,
        "matched_static_precision": static_matched_precision,
        "selector_mean_regret": selector_regret,
        "matched_static_mean_regret": static_matched_regret,
        "all_case_static_mean_regret": sum(float(item["static_regret"]) for item in result_rows)
        / len(result_rows),
        "authorization_gates": gates,
        "fresh_confirmation_authorized": all(gates.values()),
        "thresholds": config.thresholds.model_dump(mode="json"),
        "usage": usage,
        "situations_sha256": hashlib.sha256(situation_lines.encode()).hexdigest(),
        "formal_development_cases_sha256": hashlib.sha256(case_lines.encode()).hexdigest(),
        "action_maps_sha256": hashlib.sha256(map_lines.encode()).hexdigest(),
        "decisions_sha256": hashlib.sha256(decision_lines.encode()).hexdigest(),
        "results_sha256": hashlib.sha256(result_lines.encode()).hexdigest(),
        "source_evidence_designation": "fresh-development",
        "formal_evidence_eligible": False,
        "formal_hidden_split_opened": False,
        "development_outcomes_must_not_be_reported_as_confirmation": True,
    }
    report["report_sha256"] = content_sha256(report)
    _write(output / "REPORT.json", (json.dumps(report, indent=2) + "\n").encode())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

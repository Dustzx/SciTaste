#!/usr/bin/env python3
"""Run model-synthesized Scientific Taste transfer on consumed objective forks."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from scitaste.evaluation.counterfactual_taste import CounterfactualActionSetResult
from scitaste.evaluation.scientific_situation_transfer import (
    ObjectiveForkSituationCase,
    ScientificSituation,
    ScientificSituationModelTransferProposal,
    admit_scientific_situation_model_proposal,
    normalize_objective_fork_utilities,
    scientific_situation_candidate_precedents,
    scientific_situation_similarity,
)
from scitaste.model_nodes import (
    StructuredModelRequest,
    StructuredModelResponse,
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_ACTION_DESCRIPTIONS = {
    "PROBE": "Isolate broad variable dependencies.",
    "PILOT": "Run a cheap discriminating test of one law family.",
    "EXPERIMENT": "Maximize disagreement between currently plausible formulas.",
    "ANALYZE": "Compare visible dependencies and units before one diagnostic check.",
    "REFINE": "Estimate a supported functional form more precisely.",
    "PIVOT": "Test a qualitatively different law family.",
    "STOP": "Submit the strongest law supported by visible evidence.",
}


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class ModelTransferConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    project_id: str
    population_lock: FileBinding
    state_root: str
    situations: FileBinding
    selector_backend: FileBinding
    selector_provider: str
    selector_model: str
    batch_size: int = Field(ge=1, le=6)
    maximum_precedents: int = Field(ge=2, le=12)
    seed: int
    minimum_confidence: float = Field(ge=0.0, le=1.0)
    minimum_action_margin: float = Field(ge=0.0, le=1.0)
    minimum_used_task_clusters: int = Field(ge=2, le=6)
    minimum_used_precedent_similarity: float = Field(ge=0.0, le=1.0)
    source_evidence_designation: Literal["consumed-development"]
    target_outcomes_visible_to_selector: Literal[False]
    formal_split_opened: Literal[False]


class PopulationBinding(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    study_id: str
    task_id: str
    result_sha256: str = Field(pattern=_SHA256)


class PopulationLock(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    project_id: str
    bindings: tuple[PopulationBinding, ...] = Field(min_length=4)


class ModelTransferBatchItem(BaseModel):
    model_config = _CONFIG

    proposal: ScientificSituationModelTransferProposal


class ModelTransferBatch(BaseModel):
    model_config = _CONFIG

    items: tuple[ModelTransferBatchItem, ...] = Field(min_length=1, max_length=6)


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


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
    temporary.replace(path)


def _jsonl(path: Path) -> list[dict[str, JsonValue]]:
    rows = []
    for line in _bytes(path).decode().splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row must be an object: {path}")
            rows.append(value)
    return rows


def _instruction() -> str:
    return """Estimate which scientific action has the highest expected value in each target
situation by transferring only from the supplied objective-fork precedents. Each precedent was
executed from a shared prefix and its utility vector is scorer owned and normalized within that
source state. The target action outcomes are hidden.

Do not copy the most frequent action and do not use task names as evidence. Compare the target and
source epistemic states: hypothesis structure, evidence relation, bottleneck, identifiability,
budget pressure, readiness, and quoted decision-time evidence. Source utilities are supervision,
not target labels. Cite the precedent IDs that materially support the estimate, using at least two
different source tasks when selecting an action. Score every available action from 0 to 1. Select
the unique highest-score action only when its advantage transfers across sources; otherwise
abstain. Confidence describes transfer reliability, not fluency. Return items in input order as one
JSON object matching the supplied schema and no prose outside it."""


def _situation_view(situation: ScientificSituation) -> dict[str, JsonValue]:
    return {
        "hypothesis_structure": situation.hypothesis_structure.value,
        "evidence_relation": situation.evidence_relation.value,
        "bottleneck": situation.bottleneck.value,
        "identifiability": situation.identifiability.value,
        "budget_pressure": situation.budget_pressure.value,
        "terminal_readiness": situation.terminal_readiness.value,
        "evidence_anchors": [item.model_dump(mode="json") for item in situation.anchors],
        "decision_basis": situation.decision_basis,
        "abstraction_confidence": situation.abstraction_confidence,
    }


def _request(
    config: ModelTransferConfig,
    *,
    batch_number: int,
    targets: list[ObjectiveForkSituationCase],
    population: tuple[ObjectiveForkSituationCase, ...],
    policy_fingerprint: str,
) -> tuple[
    StructuredModelRequest,
    dict[str, tuple[ObjectiveForkSituationCase, ...]],
]:
    candidates = {
        target.study_id: scientific_situation_candidate_precedents(
            target=target.situation,
            sources=population,
            maximum_precedents=config.maximum_precedents,
        )
        for target in targets
    }
    items = []
    for target in targets:
        precedents = []
        for source in candidates[target.study_id]:
            precedents.append(
                {
                    "precedent_id": source.study_id,
                    "source_task_id": "source-task-"
                    + content_sha256(source.task_cluster_id)[:10],
                    "situation_similarity": scientific_situation_similarity(
                        source.situation,
                        target.situation,
                    ),
                    "situation": _situation_view(source.situation),
                    "objective_fork_normalized_utilities": (
                        source.normalized_action_utilities
                    ),
                }
            )
        items.append(
            {
                "target_study_id": target.study_id,
                "target_situation": _situation_view(target.situation),
                "available_actions": _ACTION_DESCRIPTIONS,
                "candidate_precedents": precedents,
                "target_action_outcomes_visible": False,
            }
        )
    request = StructuredModelRequest(
        request_id=f"{config.study_id}-batch-{batch_number:02d}",
        node_name="scientific-situation-model-transfer",
        stage="EVALUATION",
        state_snapshot_id=f"{config.study_id}-target-outcomes-hidden",
        expected_backend=config.selector_provider,
        expected_model=config.selector_model,
        policy_id=config.study_id,
        policy_fingerprint=policy_fingerprint,
        system_instruction=_instruction(),
        input_payload={
            "source_utilities_are_visible_supervision": True,
            "target_action_outcomes_visible": False,
            "items": items,
        },
        output_schema=ModelTransferBatch.model_json_schema(mode="serialization"),
        seed=config.seed + batch_number,
        prompt_version="scientific-situation-model-transfer-v1",
    )
    return request, candidates


def _load_population(
    *,
    lock: PopulationLock,
    situations_path: Path,
    state_root: Path,
) -> tuple[
    tuple[ObjectiveForkSituationCase, ...],
    dict[str, CounterfactualActionSetResult],
]:
    situations = {
        item.study_id: item
        for item in (
            ScientificSituation.model_validate(row)
            for row in _jsonl(situations_path)
        )
    }
    if set(situations) != {item.study_id for item in lock.bindings}:
        raise ValueError("scientific situations and population lock differ")
    cases = []
    results = {}
    for binding in lock.bindings:
        result = CounterfactualActionSetResult.model_validate_json(
            _bytes(state_root / binding.study_id / "RESULT.json"),
            strict=True,
        )
        if result.result_sha256 != binding.result_sha256:
            raise ValueError(f"result differs from population lock: {binding.study_id}")
        values = {item.action.value: item.objective_value for item in result.outcomes}
        observed = {item.action.value: item.objective_observed for item in result.outcomes}
        normalized = normalize_objective_fork_utilities(values, observed)
        cases.append(
            ObjectiveForkSituationCase(
                study_id=binding.study_id,
                task_cluster_id=binding.task_id,
                situation=situations[binding.study_id],
                observed_actions=tuple(sorted(normalized)),
                normalized_action_utilities=normalized,
                result_sha256=result.result_sha256,
            )
        )
        results[binding.study_id] = result
    return tuple(cases), results


def _static_action(
    target: ObjectiveForkSituationCase,
    population: tuple[ObjectiveForkSituationCase, ...],
    actions: set[str],
) -> str:
    values: dict[str, list[float]] = {action: [] for action in actions}
    for source in population:
        if source.task_cluster_id == target.task_cluster_id:
            continue
        for action, value in source.normalized_action_utilities.items():
            values[action].append(value)
    means = {
        action: sum(observed) / len(observed)
        for action, observed in values.items()
        if observed
    }
    return min(means, key=lambda action: (-means[action], action))


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_raw = _bytes(config_path)
    config = ModelTransferConfig.model_validate(yaml.safe_load(config_raw))
    lock_path = _bound(root, config.population_lock)
    situations_path = _bound(root, config.situations)
    backend_path = _bound(root, config.selector_backend)
    state_root = (root / config.state_root).resolve(strict=True)
    state_root.relative_to(root)
    lock = PopulationLock.model_validate_json(_bytes(lock_path), strict=True)
    if lock.project_id != config.project_id:
        raise ValueError("model-transfer population belongs to another project")
    population, results = _load_population(
        lock=lock,
        situations_path=situations_path,
        state_root=state_root,
    )
    backend_config = load_structured_openai_compatible_config(backend_path)
    if (backend_config.provider, backend_config.model) != (
        config.selector_provider,
        config.selector_model,
    ):
        raise ValueError("model-transfer backend identity differs from config")
    policy_fingerprint = content_sha256(
        {
            "config_sha256": hashlib.sha256(config_raw).hexdigest(),
            "backend_sha256": config.selector_backend.sha256,
            "instruction": _instruction(),
        }
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    backend = StructuredOpenAICompatibleBackend(backend_config) if args.allow_api else None
    decisions = []
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    completed = 0
    for offset in range(0, len(population), config.batch_size):
        batch_number = offset // config.batch_size + 1
        targets = list(population[offset : offset + config.batch_size])
        request, candidates = _request(
            config,
            batch_number=batch_number,
            targets=targets,
            population=population,
            policy_fingerprint=policy_fingerprint,
        )
        request_path = output / "requests" / f"{batch_number:02d}.json"
        _write(request_path, (request.model_dump_json(indent=2) + "\n").encode())
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
        parsed = ModelTransferBatch.model_validate(response.output_payload)
        expected_ids = [item.study_id for item in targets]
        observed_ids = [item.proposal.target_study_id for item in parsed.items]
        if observed_ids != expected_ids:
            raise ValueError(f"model transfer changed target order in batch {batch_number}")
        for item, target in zip(parsed.items, targets, strict=True):
            decisions.append(
                admit_scientific_situation_model_proposal(
                    target=target.situation,
                    candidates=candidates[target.study_id],
                    proposal=item.proposal,
                    available_actions=set(_ACTION_DESCRIPTIONS),
                    request_fingerprint=request.fingerprint,
                    response_sha256=response.raw_response_sha256,
                    minimum_confidence=config.minimum_confidence,
                    minimum_action_margin=config.minimum_action_margin,
                    minimum_used_task_clusters=config.minimum_used_task_clusters,
                    minimum_used_precedent_similarity=(
                        config.minimum_used_precedent_similarity
                    ),
                )
            )

    batch_count = (len(population) + config.batch_size - 1) // config.batch_size
    _write(
        output / "PLAN.json",
        (
            json.dumps(
                {
                    "schema_version": "1.0",
                    "study_id": config.study_id,
                    "population_count": len(population),
                    "batch_count": batch_count,
                    "target_outcomes_visible_to_selector": False,
                    "source_evidence_designation": "consumed-development",
                    "formal_split_opened": False,
                    "policy_fingerprint": policy_fingerprint,
                },
                indent=2,
            )
            + "\n"
        ).encode(),
    )
    if completed == 0:
        return 0
    if completed != batch_count or len(decisions) != len(population):
        raise ValueError("cannot compile partial scientific-situation model transfer")

    case_by_id = {item.study_id: item for item in population}
    rows: list[dict[str, JsonValue]] = []
    for decision in decisions:
        target = case_by_id[decision.target_study_id]
        result = results[target.study_id]
        utilities = target.normalized_action_utilities
        preferred = {item.value for item in result.preferred_actions}
        static_action = _static_action(target, population, set(_ACTION_DESCRIPTIONS))
        static_utility = utilities.get(static_action, 0.0)
        selected_utility = (
            None
            if decision.selected_action is None
            else utilities.get(decision.selected_action, 0.0)
        )
        rows.append(
            {
                "study_id": target.study_id,
                "task_cluster_id": target.task_cluster_id,
                "selected_action": decision.selected_action,
                "abstained": decision.abstained,
                "abstention_reasons": list(decision.abstention_reasons),
                "selected_normalized_utility": selected_utility,
                "selected_normalized_regret": (
                    None if selected_utility is None else 1.0 - selected_utility
                ),
                "selected_action_objectively_preferred": (
                    None
                    if decision.selected_action is None
                    else decision.selected_action in preferred
                    and decision.selected_action in utilities
                ),
                "static_action": static_action,
                "static_normalized_regret": 1.0 - static_utility,
                "static_action_objectively_preferred": static_action in preferred
                and static_action in utilities,
                "objective_preferred_actions": sorted(preferred),
                "decision_sha256": decision.decision_sha256,
            }
        )
    decision_lines = "".join(
        item.model_dump_json() + "\n"
        for item in sorted(decisions, key=lambda row: row.target_study_id)
    )
    result_lines = "".join(
        json.dumps(item, ensure_ascii=False) + "\n"
        for item in sorted(rows, key=lambda row: row["study_id"])
    )
    _write(output / "DECISIONS.jsonl", decision_lines.encode())
    _write(output / "RESULTS.jsonl", result_lines.encode())

    selected = [item for item in rows if not item["abstained"]]
    selector_regrets = [float(item["selected_normalized_regret"]) for item in selected]
    static_regrets = [float(item["static_normalized_regret"]) for item in selected]
    selector_hits = [bool(item["selected_action_objectively_preferred"]) for item in selected]
    static_hits = [bool(item["static_action_objectively_preferred"]) for item in selected]
    selected_actions = {str(item["selected_action"]) for item in selected}
    selector_mean = sum(selector_regrets) / len(selector_regrets) if selector_regrets else None
    static_mean = sum(static_regrets) / len(static_regrets) if static_regrets else None
    selector_precision = sum(selector_hits) / len(selector_hits) if selector_hits else None
    static_precision = sum(static_hits) / len(static_hits) if static_hits else None
    gates = {
        "nontrivial_coverage": len(selected) / len(rows) >= 0.25,
        "action_diversity": len(selected_actions) >= 2,
        "lower_regret_than_static_on_interventions": (
            selector_mean is not None and static_mean is not None and selector_mean < static_mean
        ),
        "higher_precision_than_static_on_interventions": (
            selector_precision is not None
            and static_precision is not None
            and selector_precision > static_precision
        ),
    }
    report = {
        "schema_version": "1.0",
        "study_id": config.study_id,
        "method": "model-synthesized-scientific-situation-transfer-v1",
        "population_count": len(rows),
        "task_cluster_count": len({item["task_cluster_id"] for item in rows}),
        "selected_count": len(selected),
        "abstained_count": len(rows) - len(selected),
        "coverage": len(selected) / len(rows),
        "selected_actions": sorted(selected_actions),
        "selector_precision": selector_precision,
        "matched_static_precision": static_precision,
        "selector_mean_normalized_regret": selector_mean,
        "matched_static_mean_normalized_regret": static_mean,
        "authorization_gates": gates,
        "fresh_confirmation_authorized": all(gates.values()),
        "usage": usage,
        "decisions_sha256": hashlib.sha256(decision_lines.encode()).hexdigest(),
        "results_sha256": hashlib.sha256(result_lines.encode()).hexdigest(),
        "source_evidence_designation": "consumed-development",
        "formal_evidence_eligible": False,
        "formal_split_opened": False,
    }
    _write(output / "REPORT.json", (json.dumps(report, indent=2) + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

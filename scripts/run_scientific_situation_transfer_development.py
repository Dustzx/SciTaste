#!/usr/bin/env python3
"""Develop typed Scientific Taste transfer on consumed objective action forks.

The extractor sees decision-time fields only.  Selection then uses cross-task,
scorer-owned utilities from shared-prefix action branches.  The resulting report
is development evidence and can never be promoted to a formal confirmation.
"""

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
from scitaste.evaluation.interactive_research import (
    InteractiveResearchPrefix,
    load_interactive_research_prefix,
)
from scitaste.evaluation.scientific_situation_transfer import (
    ObjectiveForkSituationCase,
    ScientificSituation,
    ScientificSituationProposal,
    ScientificSituationTransferThresholds,
    normalize_objective_fork_utilities,
    select_by_scientific_situation,
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


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)


class ScientificSituationTransferDevelopmentConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    population_lock: FileBinding
    state_root: str = Field(min_length=1)
    extractor_backend: FileBinding
    extractor_provider: str = Field(min_length=1)
    extractor_model: str = Field(min_length=1)
    batch_size: int = Field(ge=1, le=8)
    seed: int
    thresholds: ScientificSituationTransferThresholds
    source_evidence_designation: Literal["consumed-development"]
    target_outcomes_visible_to_extractor: Literal[False]
    target_outcomes_used_for_selection: Literal[False]
    formal_split_opened: Literal[False]


class PopulationBinding(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    study_id: str
    task_id: str
    prefix_sha256: str = Field(pattern=_SHA256)
    result_sha256: str = Field(pattern=_SHA256)


class PopulationLock(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    project_id: str
    bindings: tuple[PopulationBinding, ...] = Field(min_length=4)


class SituationBatchItem(BaseModel):
    model_config = _CONFIG

    study_id: str
    situation: ScientificSituationProposal


class SituationBatch(BaseModel):
    model_config = _CONFIG

    items: tuple[SituationBatchItem, ...] = Field(min_length=1, max_length=8)


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


def _instruction() -> str:
    return """Abstract the scientific situation at a research decision point.
You receive only information visible before the next action. You never receive branch outcomes,
action utilities, preferred actions, or later evidence. Do not recommend an action.

For each item, classify:
- hypothesis_structure: none, single-candidate, or competing-candidates;
- evidence_relation: absent, consistent, conflicted, or underdetermined;
- bottleneck: variable-discovery, functional-form-discrimination, parameter-estimation,
  contradiction-resolution, robustness-validation, or terminal-calibration;
- identifiability: whether the visible evidence can distinguish the relevant explanations;
- budget_pressure from the visible phase and work already consumed;
- terminal_readiness: not-ready, ambiguous, or ready.

Ground every abstraction in 2--6 short exact quotes. Each anchor must use one supplied field_id and
copy a substring verbatim from that field's text. Prefer anchors from different turns or field
types. Treat numerical observations as evidence only when their interpretation is stated in a
visible rationale. If the record is ambiguous, lower abstraction_confidence rather than inventing
facts. Return items in input order as one JSON object matching the supplied schema, with no prose
outside it."""


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


def _request(
    config: ScientificSituationTransferDevelopmentConfig,
    *,
    batch_number: int,
    records: list[tuple[PopulationBinding, InteractiveResearchPrefix]],
    policy_fingerprint: str,
) -> tuple[StructuredModelRequest, dict[str, dict[str, str]]]:
    visible = {
        binding.study_id: _visible_fields(prefix) for binding, prefix in records
    }
    request = StructuredModelRequest(
        request_id=f"{config.study_id}-extract-{batch_number:02d}",
        node_name="scientific-situation-extractor",
        stage="EVALUATION",
        state_snapshot_id=f"{config.study_id}-predecision-only",
        expected_backend=config.extractor_provider,
        expected_model=config.extractor_model,
        policy_id=config.study_id,
        policy_fingerprint=policy_fingerprint,
        system_instruction=_instruction(),
        input_payload={
            "target_outcomes_visible": False,
            "action_recommendation_requested": False,
            "items": [
                {
                    "study_id": binding.study_id,
                    "visible_fields": visible[binding.study_id],
                }
                for binding, _ in records
            ],
        },
        output_schema=SituationBatch.model_json_schema(mode="serialization"),
        seed=config.seed + batch_number,
        prompt_version="predecision-scientific-situation-v1",
    )
    encoded = request.model_dump_json().casefold()
    forbidden = (
        "objective_value",
        "preferred_actions",
        "normalized_action_utilities",
        "counterfactual outcome",
    )
    if any(item in encoded for item in forbidden):
        raise ValueError("target outcome or action label leaked into situation request")
    return request, visible


def _compact_text_with_positions(text: str) -> tuple[str, list[int]]:
    compact: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(text):
        if character.isspace():
            continue
        compact.append(character)
        positions.append(index)
    return "".join(compact), positions


def _exact_anchors(
    proposal: ScientificSituationProposal,
    visible_fields: dict[str, str],
) -> tuple[ScientificSituationProposal, tuple[str, ...]]:
    exact = []
    repairs: list[str] = []
    for anchor in proposal.anchors:
        try:
            source = visible_fields[anchor.field_id]
        except KeyError as exc:
            raise ValueError(f"unknown situation evidence field: {anchor.field_id}") from exc
        if anchor.quote in source:
            exact.append(anchor)
            continue
        compact_source, source_positions = _compact_text_with_positions(source)
        compact_quote, _ = _compact_text_with_positions(anchor.quote)
        offset = compact_source.find(compact_quote)
        if offset < 0:
            raise ValueError(
                f"situation anchor is not an exact quote from {anchor.field_id}: {anchor.quote!r}"
            )
        end = offset + len(compact_quote) - 1
        exact_quote = source[source_positions[offset] : source_positions[end] + 1]
        exact.append(anchor.model_copy(update={"quote": exact_quote}))
        repairs.append(f"whitespace-normalized:{anchor.field_id}:{len(exact) - 1}")
    return proposal.model_copy(update={"anchors": tuple(exact)}), tuple(repairs)


def _load_population(
    *,
    state_root: Path,
    lock: PopulationLock,
) -> list[tuple[PopulationBinding, InteractiveResearchPrefix, CounterfactualActionSetResult]]:
    records = []
    seen: set[str] = set()
    for binding in lock.bindings:
        if binding.study_id in seen:
            raise ValueError(f"duplicate population study ID: {binding.study_id}")
        seen.add(binding.study_id)
        state_dir = state_root / binding.study_id
        prefix = load_interactive_research_prefix(state_dir / "PREFIX.json")
        result = CounterfactualActionSetResult.model_validate_json(
            _bytes(state_dir / "RESULT.json"),
            strict=True,
        )
        if prefix.prefix_sha256 != binding.prefix_sha256:
            raise ValueError(f"prefix hash differs from population lock: {binding.study_id}")
        if result.result_sha256 != binding.result_sha256:
            raise ValueError(f"result hash differs from population lock: {binding.study_id}")
        if result.study_id != binding.study_id:
            raise ValueError(f"result study ID differs from population lock: {binding.study_id}")
        records.append((binding, prefix, result))
    return records


def _static_action(
    target: ScientificSituation,
    sources: tuple[ObjectiveForkSituationCase, ...],
    available_actions: set[str],
) -> str:
    values: dict[str, list[float]] = {action: [] for action in available_actions}
    for source in sources:
        if source.task_cluster_id == target.task_cluster_id:
            continue
        for action, value in source.normalized_action_utilities.items():
            if action in values:
                values[action].append(value)
    means = {
        action: sum(action_values) / len(action_values)
        for action, action_values in values.items()
        if action_values
    }
    if not means:
        raise ValueError("static comparator has no cross-task utility observations")
    return min(means, key=lambda action: (-means[action], action))


def _evaluated_utility(action: str, utilities: dict[str, float]) -> tuple[float, bool]:
    if action not in utilities:
        return 0.0, False
    return utilities[action], True


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_raw = _bytes(config_path)
    config = ScientificSituationTransferDevelopmentConfig.model_validate(
        yaml.safe_load(config_raw)
    )
    lock_path = _bound(root, config.population_lock)
    backend_path = _bound(root, config.extractor_backend)
    state_root = (root / config.state_root).resolve(strict=True)
    state_root.relative_to(root)
    lock = PopulationLock.model_validate_json(_bytes(lock_path), strict=True)
    if lock.project_id != config.project_id:
        raise ValueError("scientific-situation population lock belongs to another project")
    population = _load_population(state_root=state_root, lock=lock)
    backend_config = load_structured_openai_compatible_config(backend_path)
    if (backend_config.provider, backend_config.model) != (
        config.extractor_provider,
        config.extractor_model,
    ):
        raise ValueError("scientific-situation extractor identity differs from config")
    policy_fingerprint = content_sha256(
        {
            "config_sha256": hashlib.sha256(config_raw).hexdigest(),
            "backend_sha256": config.extractor_backend.sha256,
            "instruction": _instruction(),
        }
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    backend = StructuredOpenAICompatibleBackend(backend_config) if args.allow_api else None
    situations: list[ScientificSituation] = []
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    completed = 0
    for offset in range(0, len(population), config.batch_size):
        batch_number = offset // config.batch_size + 1
        batch = population[offset : offset + config.batch_size]
        request, visible = _request(
            config,
            batch_number=batch_number,
            records=[(binding, prefix) for binding, prefix, _ in batch],
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
        parsed = SituationBatch.model_validate(response.output_payload)
        expected_ids = [binding.study_id for binding, _, _ in batch]
        if [item.study_id for item in parsed.items] != expected_ids:
            raise ValueError(f"situation extractor changed item order in batch {batch_number}")
        for item, (binding, prefix, _) in zip(parsed.items, batch, strict=True):
            proposal, anchor_repairs = _exact_anchors(
                item.situation,
                visible[binding.study_id],
            )
            situations.append(
                ScientificSituation.create(
                    study_id=binding.study_id,
                    task_cluster_id=binding.task_id,
                    prefix_sha256=prefix.prefix_sha256,
                    **proposal.model_dump(mode="python"),
                    anchor_normalization_repairs=anchor_repairs,
                    extractor_provider=response.backend,
                    extractor_model=response.model,
                    request_fingerprint=request.fingerprint,
                    response_sha256=response.raw_response_sha256,
                )
            )

    batch_count = (len(population) + config.batch_size - 1) // config.batch_size
    plan = {
        "schema_version": "1.0",
        "study_id": config.study_id,
        "population_count": len(population),
        "batch_count": batch_count,
        "target_outcomes_visible_to_extractor": False,
        "target_outcomes_used_for_selection": False,
        "source_evidence_designation": "consumed-development",
        "formal_split_opened": False,
        "policy_fingerprint": policy_fingerprint,
    }
    _write(output / "PLAN.json", (json.dumps(plan, indent=2) + "\n").encode())
    if completed == 0:
        return 0
    if completed != batch_count:
        raise ValueError("cannot compile a partial scientific-situation extraction")
    if len(situations) != len(population):
        raise ValueError("scientific-situation population is incomplete")

    situation_by_id = {item.study_id: item for item in situations}
    cases: list[ObjectiveForkSituationCase] = []
    results: dict[str, CounterfactualActionSetResult] = {}
    target_utilities: dict[str, dict[str, float]] = {}
    for binding, _, result in population:
        values = {item.action.value: item.objective_value for item in result.outcomes}
        observed = {item.action.value: item.objective_observed for item in result.outcomes}
        normalized = normalize_objective_fork_utilities(values, observed)
        cases.append(
            ObjectiveForkSituationCase(
                study_id=binding.study_id,
                task_cluster_id=binding.task_id,
                situation=situation_by_id[binding.study_id],
                observed_actions=tuple(sorted(normalized)),
                normalized_action_utilities=normalized,
                result_sha256=result.result_sha256,
            )
        )
        results[binding.study_id] = result
        target_utilities[binding.study_id] = normalized
    source_cases = tuple(cases)

    rows: list[dict[str, JsonValue]] = []
    decisions = []
    for case in source_cases:
        result = results[case.study_id]
        available = {item.action.value for item in result.outcomes}
        decision = select_by_scientific_situation(
            target=case.situation,
            sources=source_cases,
            available_actions=available,
            thresholds=config.thresholds,
        )
        decisions.append(decision)
        static_action = _static_action(case.situation, source_cases, available)
        utilities = target_utilities[case.study_id]
        preferred = {item.value for item in result.preferred_actions}
        static_utility, static_observed = _evaluated_utility(static_action, utilities)
        selected_utility = None
        selected_observed = None
        selected_regret = None
        selected_hit = None
        if decision.selected_action is not None:
            selected_utility, selected_observed = _evaluated_utility(
                decision.selected_action,
                utilities,
            )
            selected_regret = 1.0 - selected_utility
            selected_hit = decision.selected_action in preferred and selected_observed
        rows.append(
            {
                "study_id": case.study_id,
                "task_cluster_id": case.task_cluster_id,
                "situation_sha256": case.situation.situation_sha256,
                "selected_action": decision.selected_action,
                "abstained": decision.abstained,
                "abstention_reasons": list(decision.abstention_reasons),
                "selected_objective_observed": selected_observed,
                "selected_normalized_utility": selected_utility,
                "selected_normalized_regret": selected_regret,
                "selected_action_objectively_preferred": selected_hit,
                "static_action": static_action,
                "static_objective_observed": static_observed,
                "static_normalized_utility": static_utility,
                "static_normalized_regret": 1.0 - static_utility,
                "static_action_objectively_preferred": static_action in preferred
                and static_observed,
                "objective_preferred_actions": sorted(preferred),
                "target_result_sha256": result.result_sha256,
                "decision_sha256": decision.decision_sha256,
            }
        )

    situation_lines = "".join(
        item.model_dump_json() + "\n" for item in sorted(situations, key=lambda row: row.study_id)
    )
    decision_lines = "".join(
        item.model_dump_json() + "\n"
        for item in sorted(decisions, key=lambda row: row.target_study_id)
    )
    result_lines = "".join(
        json.dumps(item, ensure_ascii=False) + "\n"
        for item in sorted(rows, key=lambda row: row["study_id"])
    )
    _write(output / "SITUATIONS.jsonl", situation_lines.encode())
    _write(output / "DECISIONS.jsonl", decision_lines.encode())
    _write(output / "RESULTS.jsonl", result_lines.encode())

    selected = [item for item in rows if not item["abstained"]]
    selected_regrets = [float(item["selected_normalized_regret"]) for item in selected]
    matched_static_regrets = [float(item["static_normalized_regret"]) for item in selected]
    selected_hits = [bool(item["selected_action_objectively_preferred"]) for item in selected]
    static_hits = [bool(item["static_action_objectively_preferred"]) for item in selected]
    selected_actions = {str(item["selected_action"]) for item in selected}
    coverage = len(selected) / len(rows)
    selector_mean_regret = (
        sum(selected_regrets) / len(selected_regrets) if selected_regrets else None
    )
    matched_static_mean_regret = (
        sum(matched_static_regrets) / len(matched_static_regrets)
        if matched_static_regrets
        else None
    )
    selector_precision = sum(selected_hits) / len(selected_hits) if selected_hits else None
    matched_static_precision = sum(static_hits) / len(static_hits) if static_hits else None
    authorization_gates = {
        "nontrivial_coverage": coverage >= 0.25,
        "action_diversity": len(selected_actions) >= 2,
        "lower_regret_than_static_on_interventions": (
            selector_mean_regret is not None
            and matched_static_mean_regret is not None
            and selector_mean_regret < matched_static_mean_regret
        ),
        "higher_precision_than_static_on_interventions": (
            selector_precision is not None
            and matched_static_precision is not None
            and selector_precision > matched_static_precision
        ),
    }
    report = {
        "schema_version": "1.0",
        "study_id": config.study_id,
        "method": "typed-scientific-situation-objective-fork-transfer-v1",
        "population_count": len(rows),
        "task_cluster_count": len({item["task_cluster_id"] for item in rows}),
        "selected_count": len(selected),
        "abstained_count": len(rows) - len(selected),
        "coverage": coverage,
        "selected_action_count": len(selected_actions),
        "selected_actions": sorted(selected_actions),
        "selector_precision": selector_precision,
        "matched_static_precision": matched_static_precision,
        "selector_mean_normalized_regret": selector_mean_regret,
        "matched_static_mean_normalized_regret": matched_static_mean_regret,
        "authorization_gates": authorization_gates,
        "fresh_confirmation_authorized": all(authorization_gates.values()),
        "thresholds": config.thresholds.model_dump(mode="json"),
        "usage": usage,
        "situations_sha256": hashlib.sha256(situation_lines.encode()).hexdigest(),
        "decisions_sha256": hashlib.sha256(decision_lines.encode()).hexdigest(),
        "results_sha256": hashlib.sha256(result_lines.encode()).hexdigest(),
        "source_evidence_designation": "consumed-development",
        "formal_evidence_eligible": False,
        "formal_split_opened": False,
        "development_outcomes_must_not_be_reported_as_confirmation": True,
    }
    _write(output / "REPORT.json", (json.dumps(report, indent=2) + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

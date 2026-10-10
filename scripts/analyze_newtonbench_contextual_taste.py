#!/usr/bin/env python3
"""Fit and falsify contextual Scientific Taste on the consumed dev cohort.

The extractor sees only the pre-decision trajectory.  Objective branch values
are joined afterwards.  Every target is evaluated by leave-one-task-cluster-out
prediction; the ridge penalty is selected by a nested task-cluster split.  The
script may authorize construction of a fresh confirmation split, but it never
opens one and its outputs are never formal paper evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from scitaste.evaluation.contextual_taste import (
    ActionAffordanceProfile,
    ContextualTasteActionScore,
    ContextualTasteDecision,
    ContextualTasteModel,
    DecisionGeometryDimension,
    ScientificDecisionGeometry,
    ScientificDecisionGeometryProposal,
    validate_decision_geometry_grounding,
)
from scitaste.evaluation.interactive_research import (
    InteractiveResearchPrefix,
    load_interactive_research_prefix,
)
from scitaste.evaluation.scientific_situation_transfer import (
    FormalObjectiveForkSituationCase,
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


class AffordanceValues(BaseModel):
    model_config = _CONFIG

    evidence_acquisition: float = Field(ge=0.0, le=1.0)
    hypothesis_revision: float = Field(ge=0.0, le=1.0)
    evidence_synthesis: float = Field(ge=0.0, le=1.0)
    candidate_refinement: float = Field(ge=0.0, le=1.0)
    termination: float = Field(ge=0.0, le=1.0)
    intervention_scope: float = Field(ge=0.0, le=1.0)


class ContextualTasteDevelopmentConfig(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    study_id: str
    project_id: str
    cohort_id: str
    cohort_receipt: FileBinding
    formal_development_cases: FileBinding
    extractor_backend: FileBinding
    extractor_provider: str
    extractor_model: str
    batch_size: int = Field(ge=1, le=8)
    seed: int = Field(ge=0)
    ridge_alpha_grid: tuple[float, ...] = Field(min_length=2, max_length=10)
    confidence_level: float = Field(gt=0.5, lt=1.0)
    minimum_geometry_confidence: float = Field(ge=0.0, le=1.0)
    minimum_predicted_advantage: float = Field(ge=0.0, le=1.0)
    decision_equivalence_tolerance: float = Field(gt=0.0, le=1.0)
    minimum_authorization_coverage: float = Field(gt=0.0, le=1.0)
    maximum_authorized_mean_regret: float = Field(ge=0.0, le=1.0)
    maximum_authorized_single_regret: float = Field(ge=0.0, le=1.0)
    action_affordances: dict[str, AffordanceValues] = Field(min_length=2)
    source_evidence_designation: Literal["fresh-development"]
    target_outcomes_visible_to_extractor: Literal[False]
    target_outcomes_used_for_selection: Literal[False]
    formal_hidden_split_opened: Literal[False]


class GeometryBatchItem(BaseModel):
    model_config = _CONFIG

    study_id: str
    geometry: ScientificDecisionGeometryProposal


class GeometryBatch(BaseModel):
    model_config = _CONFIG

    items: tuple[GeometryBatchItem, ...] = Field(min_length=1, max_length=8)


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
    dimensions = ", ".join(item.value for item in DecisionGeometryDimension)
    return f"""Estimate a continuous scientific decision geometry from pre-decision evidence.
You receive only selector-visible trajectory fields. Branch outcomes, target utilities, preferred
actions, and later evidence are absent and forbidden. Do not recommend or rank an action.

All eight values lie in [0,1]. evidence_strength is the degree of empirical support already
obtained; residual_uncertainty is uncertainty that still matters to the scientific claim;
expected_information_gain is the marginal value of gathering new evidence;
contradiction_pressure is unresolved conflict among evidence or hypotheses;
hypothesis_concentration is how strongly belief has concentrated on one concrete candidate;
repairability is the extent to which local refinement can plausibly fix the current candidate;
terminal_readiness is readiness to commit or stop; budget_pressure is pressure from the consumed
versus remaining resource envelope. These are semantic judgments, not probabilities.

Every evidence anchor must copy an exact substring from visible_fields. Return 2--8 distinct
anchors per item. The union of supports_dimensions must cover all eight dimensions:
{dimensions}. Lower abstraction_confidence when the evidence is ambiguous. Preserve item order
and return one schema-valid JSON object with no prose outside it."""


def _request(
    config: ContextualTasteDevelopmentConfig,
    *,
    batch_number: int,
    records: list[tuple[str, dict[str, str]]],
    policy_fingerprint: str,
) -> StructuredModelRequest:
    request = StructuredModelRequest(
        request_id=f"{config.study_id}-extract-{batch_number:02d}",
        node_name="scientific-decision-geometry-extractor",
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
        output_schema=GeometryBatch.model_json_schema(mode="serialization"),
        seed=config.seed + batch_number,
        prompt_version="scientific-decision-geometry-v1",
    )
    encoded = json.dumps(request.input_payload, sort_keys=True).casefold()
    forbidden = ("objective_value", "preferred_actions", "selected_regret", "branch outcomes")
    if any(item in encoded for item in forbidden):
        raise ValueError("target outcome leaked into a decision-geometry request")
    return request


def _repair_request(
    config: ContextualTasteDevelopmentConfig,
    *,
    batch_number: int,
    item_number: int,
    repair_attempt: int,
    study_id: str,
    visible_fields: dict[str, str],
    proposal: ScientificDecisionGeometryProposal,
    findings: tuple[str, ...],
    policy_fingerprint: str,
) -> StructuredModelRequest:
    ordinal = 10_000 + 100 * batch_number + 10 * item_number + repair_attempt
    request = _request(
        config,
        batch_number=ordinal,
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
                + "\n\nThe previous outcome-hidden proposal failed deterministic exact-span "
                f"grounding with: {', '.join(findings)}. Correct the anchors without "
                "consulting or inferring any branch outcome. Do not change a numerical "
                "judgment merely to satisfy the schema; cite exact visible text that "
                "genuinely supports each missing dimension."
            ),
            "input_payload": {
                "target_outcomes_visible": False,
                "action_recommendation_requested": False,
                "validation_findings": list(findings),
                "previous_proposal": proposal.model_dump(mode="json"),
                "items": [{"study_id": study_id, "visible_fields": visible_fields}],
            },
            "seed": config.seed + ordinal,
            "prompt_version": "scientific-decision-geometry-v1-grounding-repair",
        }
    )


def _compact_positions(text: str) -> tuple[str, list[int]]:
    compact: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(text):
        if not character.isspace():
            compact.append(character)
            positions.append(index)
    return "".join(compact), positions


def _repair_exact_anchors(
    proposal: ScientificDecisionGeometryProposal,
    visible_fields: dict[str, str],
) -> ScientificDecisionGeometryProposal:
    repaired = []
    for anchor in proposal.anchors:
        source = visible_fields.get(anchor.field_id)
        if source is None:
            repaired.append(anchor)
            continue
        if anchor.quote in source:
            repaired.append(anchor)
            continue
        compact_source, positions = _compact_positions(source)
        compact_quote, _ = _compact_positions(anchor.quote)
        offset = compact_source.find(compact_quote)
        if offset < 0:
            repaired.append(anchor)
            continue
        end = offset + len(compact_quote) - 1
        repaired.append(
            anchor.model_copy(update={"quote": source[positions[offset] : positions[end] + 1]})
        )
    return proposal.model_copy(update={"anchors": tuple(repaired)})


def _load_visible_states(
    root: Path,
    receipt_path: Path,
) -> dict[str, dict[str, str]]:
    receipt = json.loads(_bytes(receipt_path))
    if receipt.get("formal_hidden_split_opened") is not False:
        raise ValueError("development receipt must keep the hidden split closed")
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for binding in receipt["bindings"]:
        result_path = (root / binding["result_locator"]).resolve(strict=True)
        result_path.relative_to(root)
        result_payload = json.loads(_bytes(result_path))
        if result_payload.get("result_sha256") != binding["result_sha256"]:
            raise ValueError(f"objective-fork result drift: {binding['study_id']}")
        prefix = load_interactive_research_prefix(result_path.parent / "PREFIX.json")
        grouped[binding["study_id"]].append(_visible_fields(prefix))
    visible: dict[str, dict[str, str]] = {}
    for study_id, rows in grouped.items():
        if any(item != rows[0] for item in rows[1:]):
            raise ValueError(f"selector-visible state differs across seed blocks: {study_id}")
        visible[study_id] = rows[0]
    return visible


def _load_cases(path: Path) -> tuple[FormalObjectiveForkSituationCase, ...]:
    cases = tuple(
        FormalObjectiveForkSituationCase.model_validate_json(line, strict=True)
        for line in _bytes(path).decode().splitlines()
        if line.strip()
    )
    if len(cases) != 30 or len({item.task_cluster_id for item in cases}) != 10:
        raise ValueError("contextual Taste development requires 30 forks from 10 clusters")
    return tuple(sorted(cases, key=lambda item: item.study_id))


def _profiles(
    config: ContextualTasteDevelopmentConfig,
    cases: tuple[FormalObjectiveForkSituationCase, ...],
) -> dict[str, ActionAffordanceProfile]:
    definitions: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        for definition in case.action_definitions:
            definitions[definition.action_id].add(definition.definition_sha256)
    if set(definitions) != set(config.action_affordances):
        raise ValueError("registered action affordances do not cover the development menus")
    if any(len(items) != 1 for items in definitions.values()):
        raise ValueError("one action ID has multiple executable definitions")
    return {
        action_id: ActionAffordanceProfile.create(
            action_id=action_id,
            action_definition_sha256=next(iter(definitions[action_id])),
            **values.model_dump(mode="python"),
            construction_rationale=(
                "Outcome-blind hidden-law action ontology registered before contextual "
                "advantage fitting."
            ),
        )
        for action_id, values in sorted(config.action_affordances.items())
    }


def _fit_model(
    *,
    cases: tuple[FormalObjectiveForkSituationCase, ...],
    geometries: dict[str, ScientificDecisionGeometry],
    profiles: dict[str, ActionAffordanceProfile],
    alpha: float,
) -> ContextualTasteModel:
    try:
        import numpy as np
        from sklearn.linear_model import Ridge
    except ImportError as error:  # pragma: no cover - exercised by study environment
        raise RuntimeError("contextual Taste fitting requires the 'study' extra") from error

    states = np.asarray(
        [geometries[item.study_id].feature_vector() for item in cases],
        dtype=float,
    )
    means = states.mean(axis=0)
    scales = states.std(axis=0)
    scales[scales < 1e-8] = 1.0
    design: list[list[float]] = []
    targets: list[float] = []
    for case, state in zip(cases, states, strict=True):
        standardized = np.concatenate(([1.0], (state - means) / scales))
        case_mean = statistics.fmean(case.action_utility_estimates.values())
        for action_id in case.available_actions:
            design.append(
                np.kron(
                    np.asarray(profiles[action_id].feature_vector(), dtype=float),
                    standardized,
                ).tolist()
            )
            targets.append(case.action_utility_estimates[action_id] - case_mean)
    fitted = Ridge(alpha=alpha, fit_intercept=False).fit(
        np.asarray(design, dtype=float),
        np.asarray(targets, dtype=float),
    )
    return ContextualTasteModel.create(
        state_means=tuple(float(item) for item in means),
        state_scales=tuple(float(item) for item in scales),
        coefficients=tuple(float(item) for item in fitted.coef_),
        ridge_alpha=alpha,
        source_case_ids=tuple(sorted(item.study_id for item in cases)),
        source_task_cluster_ids=tuple(sorted({item.task_cluster_id for item in cases})),
    )


def _choose_action(
    model: ContextualTasteModel,
    case: FormalObjectiveForkSituationCase,
    geometry: ScientificDecisionGeometry,
    profiles: dict[str, ActionAffordanceProfile],
) -> tuple[str, dict[str, float]]:
    scores = {
        action_id: model.score(geometry, profiles[action_id])
        for action_id in case.available_actions
    }
    action = min(scores, key=lambda item: (-scores[item], item))
    return action, scores


def _static_action(
    target: FormalObjectiveForkSituationCase,
    sources: tuple[FormalObjectiveForkSituationCase, ...],
) -> str:
    values: dict[str, list[float]] = {action: [] for action in target.available_actions}
    for source in sources:
        if source.task_cluster_id == target.task_cluster_id:
            continue
        if source.available_actions != target.available_actions:
            continue
        for action in target.available_actions:
            values[action].append(source.action_utility_estimates[action])
    means = {action: statistics.fmean(rows) for action, rows in values.items() if rows}
    return min(means, key=lambda item: (-means[item], item))


def _nested_alpha(
    *,
    sources: tuple[FormalObjectiveForkSituationCase, ...],
    geometries: dict[str, ScientificDecisionGeometry],
    profiles: dict[str, ActionAffordanceProfile],
    grid: tuple[float, ...],
) -> tuple[float, dict[str, float]]:
    losses = {alpha: [] for alpha in grid}
    for cluster_id in sorted({item.task_cluster_id for item in sources}):
        training = tuple(item for item in sources if item.task_cluster_id != cluster_id)
        validation = tuple(item for item in sources if item.task_cluster_id == cluster_id)
        for alpha in grid:
            model = _fit_model(
                cases=training,
                geometries=geometries,
                profiles=profiles,
                alpha=alpha,
            )
            for case in validation:
                action, _ = _choose_action(
                    model,
                    case,
                    geometries[case.study_id],
                    profiles,
                )
                losses[alpha].append(
                    max(case.action_utility_estimates.values())
                    - case.action_utility_estimates[action]
                )
    means = {alpha: statistics.fmean(items) for alpha, items in losses.items()}
    selected = min(grid, key=lambda alpha: (means[alpha], -alpha))
    return selected, {str(alpha): means[alpha] for alpha in grid}


def _jackknife_standard_error(values: list[float]) -> float:
    """Delete-one-cluster jackknife standard error, not an IID seed error."""

    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    return math.sqrt((len(values) - 1) / len(values) * sum((x - mean) ** 2 for x in values))


def _decision(
    *,
    config: ContextualTasteDevelopmentConfig,
    target: FormalObjectiveForkSituationCase,
    sources: tuple[FormalObjectiveForkSituationCase, ...],
    geometries: dict[str, ScientificDecisionGeometry],
    profiles: dict[str, ActionAffordanceProfile],
) -> tuple[
    ContextualTasteDecision,
    ContextualTasteModel,
    tuple[ContextualTasteModel, ...],
    dict[str, float],
]:
    alpha, inner_losses = _nested_alpha(
        sources=sources,
        geometries=geometries,
        profiles=profiles,
        grid=config.ridge_alpha_grid,
    )
    model = _fit_model(cases=sources, geometries=geometries, profiles=profiles, alpha=alpha)
    geometry = geometries[target.study_id]
    proposed, scores = _choose_action(model, target, geometry, profiles)
    base_action = _static_action(target, sources)
    jackknife_models = tuple(
        _fit_model(
            cases=tuple(item for item in sources if item.task_cluster_id != cluster_id),
            geometries=geometries,
            profiles=profiles,
            alpha=alpha,
        )
        for cluster_id in sorted({item.task_cluster_id for item in sources})
    )
    member_scores = [
        {
            action_id: item.score(geometry, profiles[action_id])
            for action_id in target.available_actions
        }
        for item in jackknife_models
    ]
    score_rows = tuple(
        ContextualTasteActionScore(
            action_id=action_id,
            mean_advantage_score=scores[action_id],
            jackknife_standard_error=_jackknife_standard_error(
                [item[action_id] for item in member_scores]
            ),
        )
        for action_id in sorted(target.available_actions)
    )
    advantages = [item[proposed] - item[base_action] for item in member_scores]
    mean_advantage = statistics.fmean(advantages)
    advantage_se = _jackknife_standard_error(advantages)
    lower_bound = mean_advantage - NormalDist().inv_cdf(config.confidence_level) * advantage_se
    reasons: list[str] = []
    if geometry.abstraction_confidence < config.minimum_geometry_confidence:
        reasons.append("low-geometry-confidence")
    if proposed == base_action:
        reasons.append("no-residual-action-change")
    if mean_advantage < config.minimum_predicted_advantage:
        reasons.append("insufficient-predicted-advantage")
    if lower_bound <= 0.0:
        reasons.append("nonpositive-cluster-jackknife-lower-bound")
    return (
        ContextualTasteDecision.create(
            target_study_id=target.study_id,
            target_geometry_sha256=geometry.geometry_sha256,
            base_action_id=base_action,
            action_scores=score_rows,
            proposed_action_id=proposed,
            selected_action_id=None if reasons else proposed,
            abstained=bool(reasons),
            abstention_reasons=tuple(reasons),
            predicted_advantage_over_base=mean_advantage,
            advantage_standard_error=advantage_se,
            advantage_lower_confidence_bound=lower_bound,
            confidence_level=config.confidence_level,
            fitted_model_sha256=model.model_sha256,
            jackknife_model_sha256s=tuple(sorted(item.model_sha256 for item in jackknife_models)),
        ),
        model,
        jackknife_models,
        inner_losses,
    )


def main() -> int:
    args = _parser().parse_args()
    root = args.repository_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    config_path.relative_to(root)
    config_raw = _bytes(config_path)
    config = ContextualTasteDevelopmentConfig.model_validate(yaml.safe_load(config_raw))
    validate_entry_id(config.study_id, field_name="contextual Taste study_id")
    validate_project_id(config.project_id)
    receipt_path = _bound(root, config.cohort_receipt)
    cases_path = _bound(root, config.formal_development_cases)
    backend_path = _bound(root, config.extractor_backend)
    backend_config = load_structured_openai_compatible_config(backend_path)
    if (backend_config.provider, backend_config.model) != (
        config.extractor_provider,
        config.extractor_model,
    ):
        raise ValueError("decision-geometry extractor identity differs")
    cases = _load_cases(cases_path)
    visible = _load_visible_states(root, receipt_path)
    if set(visible) != {item.study_id for item in cases}:
        raise ValueError("decision-geometry state and formal case populations differ")
    profiles = _profiles(config, cases)

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    policy_fingerprint = content_sha256(
        {
            "config_sha256": hashlib.sha256(config_raw).hexdigest(),
            "backend_sha256": config.extractor_backend.sha256,
            "instruction": _instruction(),
        }
    )
    backend = StructuredOpenAICompatibleBackend(backend_config) if args.allow_api else None
    ordered_ids = [item.study_id for item in cases]
    geometries: dict[str, ScientificDecisionGeometry] = {}
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
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
        response_path = output / "responses" / f"{batch_number:02d}.json"
        if args.resume and response_path.is_file():
            response = StructuredModelResponse.model_validate_json(_bytes(response_path))
            if response.request_fingerprint != request.fingerprint:
                raise ValueError(f"saved geometry response drift: batch {batch_number}")
        else:
            if backend is None:
                continue
            response = backend.complete(request)
            _write(response_path, (response.model_dump_json(indent=2) + "\n").encode())
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        usage["cost_usd"] += response.usage.cost_usd or 0.0
        parsed = GeometryBatch.model_validate(response.output_payload)
        if [item.study_id for item in parsed.items] != ids:
            raise ValueError(f"geometry extractor item order drift: batch {batch_number}")
        for item_number, item in enumerate(parsed.items, 1):
            proposal = item.geometry
            active_request = request
            active_response = response
            case = next(row for row in cases if row.study_id == item.study_id)
            geometry = None
            for repair_attempt in range(0, 3):
                proposal = _repair_exact_anchors(proposal, visible[item.study_id])
                candidate = ScientificDecisionGeometry.create(
                    study_id=item.study_id,
                    task_cluster_id=case.task_cluster_id,
                    prefix_sha256=case.situation.prefix_sha256,
                    **proposal.model_dump(mode="python"),
                    extractor_provider=active_response.backend,
                    extractor_model=active_response.model,
                    request_fingerprint=active_request.fingerprint,
                    response_sha256=active_response.raw_response_sha256,
                )
                findings = validate_decision_geometry_grounding(
                    candidate,
                    visible_fields=visible[item.study_id],
                )
                if not findings:
                    geometry = candidate
                    break
                if repair_attempt == 2 or backend is None:
                    raise ValueError(
                        f"decision geometry grounding failed for {item.study_id}: {findings}"
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
                    findings=findings,
                    policy_fingerprint=policy_fingerprint,
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
                        raise ValueError("saved geometry repair response drift")
                else:
                    active_response = backend.complete(active_request)
                    _write(
                        repair_response_path,
                        (active_response.model_dump_json(indent=2) + "\n").encode(),
                    )
                usage["input_tokens"] += active_response.usage.input_tokens
                usage["output_tokens"] += active_response.usage.output_tokens
                usage["cost_usd"] += active_response.usage.cost_usd or 0.0
                repaired_payload = dict(active_response.output_payload)
                repaired_items = list(repaired_payload.get("items", []))
                if len(repaired_items) == 1 and isinstance(repaired_items[0], dict):
                    repaired_item = dict(repaired_items[0])
                    repaired_item["geometry"] = {
                        **proposal.model_dump(mode="json"),
                        **dict(repaired_item.get("geometry", {})),
                    }
                    anchors_by_span: dict[tuple[str, str], dict[str, object]] = {}
                    for raw_anchor in repaired_item["geometry"].get("anchors", []):
                        anchor = dict(raw_anchor)
                        identity = (str(anchor["field_id"]), str(anchor["quote"]))
                        if identity not in anchors_by_span:
                            anchors_by_span[identity] = anchor
                            continue
                        dimensions = {
                            *anchors_by_span[identity].get("supports_dimensions", []),
                            *anchor.get("supports_dimensions", []),
                        }
                        anchors_by_span[identity]["supports_dimensions"] = sorted(dimensions)
                    repaired_item["geometry"]["anchors"] = list(anchors_by_span.values())
                    repaired_payload["items"] = [repaired_item]
                repaired = GeometryBatch.model_validate(repaired_payload)
                if len(repaired.items) != 1 or repaired.items[0].study_id != item.study_id:
                    raise ValueError("geometry grounding repair changed item identity")
                proposal = repaired.items[0].geometry
            assert geometry is not None
            geometries[item.study_id] = geometry

    plan = {
        "schema_version": "1.0",
        "study_id": config.study_id,
        "cohort_id": config.cohort_id,
        "population_count": len(cases),
        "task_cluster_count": len({item.task_cluster_id for item in cases}),
        "policy_fingerprint": policy_fingerprint,
        "estimator": "nested-loto-ridge-action-contrast-v1",
        "uncertainty": "delete-one-source-task-cluster-jackknife",
        "target_outcomes_visible_to_extractor": False,
        "target_outcomes_used_for_selection": False,
        "formal_hidden_split_opened": False,
        "evidence_designation": "fresh-development",
    }
    _write(output / "PLAN.json", (json.dumps(plan, indent=2) + "\n").encode())
    if len(geometries) != len(cases):
        if backend is None:
            print(json.dumps(plan, indent=2))
            return 0
        raise ValueError("cannot fit contextual Taste from a partial geometry population")

    decisions = []
    fitted_models = []
    jackknife_models: dict[str, ContextualTasteModel] = {}
    tuning_rows = []
    result_rows = []
    for target in cases:
        sources = tuple(item for item in cases if item.task_cluster_id != target.task_cluster_id)
        decision, model, members, inner_losses = _decision(
            config=config,
            target=target,
            sources=sources,
            geometries=geometries,
            profiles=profiles,
        )
        decisions.append(decision)
        fitted_models.append(model)
        jackknife_models.update({item.model_sha256: item for item in members})
        tuning_rows.append(
            {
                "target_study_id": target.study_id,
                "selected_alpha": model.ridge_alpha,
                "inner_loto_mean_regret_by_alpha": inner_losses,
            }
        )
        best_utility = max(target.action_utility_estimates.values())
        selected_utility = (
            None
            if decision.selected_action_id is None
            else target.action_utility_estimates[decision.selected_action_id]
        )
        base_utility = target.action_utility_estimates[decision.base_action_id]
        tolerance = config.decision_equivalence_tolerance
        result_rows.append(
            {
                "study_id": target.study_id,
                "task_cluster_id": target.task_cluster_id,
                "selected_action": decision.selected_action_id,
                "proposed_action": decision.proposed_action_id,
                "base_action": decision.base_action_id,
                "abstained": decision.abstained,
                "abstention_reasons": list(decision.abstention_reasons),
                "predicted_advantage_over_base": decision.predicted_advantage_over_base,
                "advantage_lower_confidence_bound": decision.advantage_lower_confidence_bound,
                "selected_utility": selected_utility,
                "base_utility": base_utility,
                "best_utility": best_utility,
                "selected_regret": (
                    None if selected_utility is None else best_utility - selected_utility
                ),
                "base_regret": best_utility - base_utility,
                "selected_preferred": (
                    False
                    if selected_utility is None
                    else best_utility - selected_utility <= tolerance
                ),
                "base_preferred": best_utility - base_utility <= tolerance,
                "decision_sha256": decision.decision_sha256,
            }
        )

    geometry_lines = "".join(geometries[item].model_dump_json() + "\n" for item in ordered_ids)
    profile_lines = "".join(item.model_dump_json() + "\n" for item in profiles.values())
    model_lines = "".join(item.model_dump_json() + "\n" for item in fitted_models)
    jackknife_lines = "".join(
        item.model_dump_json() + "\n" for _, item in sorted(jackknife_models.items())
    )
    decision_lines = "".join(item.model_dump_json() + "\n" for item in decisions)
    tuning_lines = "".join(json.dumps(item, sort_keys=True) + "\n" for item in tuning_rows)
    result_lines = "".join(json.dumps(item, sort_keys=True) + "\n" for item in result_rows)
    for name, content in (
        ("GEOMETRIES.jsonl", geometry_lines),
        ("ACTION_AFFORDANCES.jsonl", profile_lines),
        ("FITTED_MODELS.jsonl", model_lines),
        ("JACKKNIFE_MODELS.jsonl", jackknife_lines),
        ("DECISIONS.jsonl", decision_lines),
        ("TUNING.jsonl", tuning_lines),
        ("RESULTS.jsonl", result_lines),
    ):
        _write(output / name, content.encode())

    selected = [item for item in result_rows if not item["abstained"]]
    selected_regrets = [float(item["selected_regret"]) for item in selected]
    base_regrets = [float(item["base_regret"]) for item in selected]
    selector_precision = (
        statistics.fmean(bool(item["selected_preferred"]) for item in selected)
        if selected
        else None
    )
    base_precision = (
        statistics.fmean(bool(item["base_preferred"]) for item in selected) if selected else None
    )
    selected_actions = {str(item["selected_action"]) for item in selected}
    coverage = len(selected) / len(result_rows)
    selector_regret = statistics.fmean(selected_regrets) if selected_regrets else None
    base_regret = statistics.fmean(base_regrets) if base_regrets else None
    gates = {
        "nontrivial_coverage": coverage >= config.minimum_authorization_coverage,
        "action_diversity": len(selected_actions) >= 2,
        "lower_regret_than_static_on_interventions": (
            selector_regret is not None
            and base_regret is not None
            and selector_regret < base_regret
        ),
        "higher_decision_precision_than_static": (
            selector_precision is not None
            and base_precision is not None
            and selector_precision > base_precision
        ),
        "bounded_mean_regret": (
            selector_regret is not None and selector_regret <= config.maximum_authorized_mean_regret
        ),
        "bounded_single_decision_regret": (
            bool(selected_regrets)
            and max(selected_regrets) <= config.maximum_authorized_single_regret
        ),
    }
    report = {
        **plan,
        "method": "contextual-outcome-grounded-residual-taste-v1",
        "selected_count": len(selected),
        "abstained_count": len(result_rows) - len(selected),
        "coverage": coverage,
        "selected_actions": sorted(selected_actions),
        "selector_mean_regret": selector_regret,
        "matched_static_mean_regret": base_regret,
        "selector_decision_precision": selector_precision,
        "matched_static_decision_precision": base_precision,
        "decision_equivalence_tolerance": config.decision_equivalence_tolerance,
        "maximum_selected_regret": max(selected_regrets) if selected_regrets else None,
        "all_case_static_mean_regret": statistics.fmean(
            float(item["base_regret"]) for item in result_rows
        ),
        "selected_alpha_counts": {
            str(alpha): sum(item.ridge_alpha == alpha for item in fitted_models)
            for alpha in config.ridge_alpha_grid
        },
        "authorization_gates": gates,
        "fresh_confirmation_authorized": all(gates.values()),
        "usage": usage,
        "geometries_sha256": hashlib.sha256(geometry_lines.encode()).hexdigest(),
        "action_affordances_sha256": hashlib.sha256(profile_lines.encode()).hexdigest(),
        "fitted_models_sha256": hashlib.sha256(model_lines.encode()).hexdigest(),
        "decisions_sha256": hashlib.sha256(decision_lines.encode()).hexdigest(),
        "results_sha256": hashlib.sha256(result_lines.encode()).hexdigest(),
        "formal_evidence_eligible": False,
        "development_outcomes_must_not_be_reported_as_confirmation": True,
    }
    report["report_sha256"] = content_sha256(report)
    _write(output / "REPORT.json", (json.dumps(report, indent=2) + "\n").encode())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

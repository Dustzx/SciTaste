"""Prospective confirmation for the content-conditioned Scientific Taste selector."""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.data.store import TasteLibrary
from scitaste.evaluation.counterfactual_confirmation import (
    _exact_two_sided_sign_test,
    _exhaustive_cluster_bootstrap,
)
from scitaste.evaluation.counterfactual_deliberation_policy import (
    CounterfactualDeliberationRetrievalRecord,
    CounterfactualDeliberationTarget,
    _deliberation_input,
    _write_new,
)
from scitaste.evaluation.counterfactual_precedents import (
    CounterfactualTastePrecedentManifest,
)
from scitaste.evaluation.counterfactual_taste import (
    CounterfactualActionSetResult,
    CounterfactualResearchAction,
)
from scitaste.evaluation.interactive_research import load_interactive_research_prefix
from scitaste.model_nodes.runtime import RuntimeLedgerEntry, RuntimeOutcome
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.taste.deliberation import TasteDeliberationInput
from scitaste.taste.semantic import taste_deliberation_from_ledger

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"
_SHA1 = r"^[0-9a-f]{40}$"
_STATIC_ACTIONS = (
    CounterfactualResearchAction.EXPERIMENT,
    CounterfactualResearchAction.PROBE,
    CounterfactualResearchAction.STOP,
)


class CounterfactualDeliberationConfirmationStudy(BaseModel):
    """One prospectively declared target state."""

    model_config = _CONFIG

    study_id: str
    task_id: str
    task_config: str
    task_config_sha256: str = Field(pattern=_SHA256)
    prefix_turn_count: int = Field(ge=1)

    @model_validator(mode="after")
    def study_is_canonical(self) -> CounterfactualDeliberationConfirmationStudy:
        validate_entry_id(self.study_id, field_name="confirmation study_id")
        return self


class CounterfactualDeliberationSelectorLock(BaseModel):
    model_config = _CONFIG

    profile_set: str
    profile_set_sha256: str = Field(pattern=_SHA256)
    profile_id: str
    backend_config: str
    backend_config_sha256: str = Field(pattern=_SHA256)
    maximum_candidate_cases: Literal[3] = 3
    maximum_selected_cases: Literal[3] = 3
    selection_rule: Literal["direct-deliberated-action-v1"] = "direct-deliberated-action-v1"


class CounterfactualDeliberationEndpointLock(BaseModel):
    model_config = _CONFIG

    primary_metric: Literal["exp-neg-rmsle"] = "exp-neg-rmsle"
    source_metric: Literal["rmsle"] = "rmsle"
    metric_transform: Literal["exp-negative"] = "exp-negative"
    direction: Literal["higher"] = "higher"
    failure_value: Literal[0] = 0
    practical_equivalence_tolerance: Literal[0.001] = 0.001


class CounterfactualDeliberationSuccessLock(BaseModel):
    model_config = _CONFIG

    expected_state_count: int = Field(ge=4)
    expected_task_cluster_count: int = Field(ge=2)
    minimum_objective_observation_rate: float = Field(ge=0.0, le=1.0)
    minimum_selected_action_types: int = Field(ge=2, le=7)
    maximum_selected_action_share: float = Field(gt=0.0, le=1.0)
    minimum_mean_margin_over_strongest_static: float = Field(ge=0.0)
    require_positive_task_cluster_interval_lower_bound: bool
    require_failure_noninferiority: bool


class CounterfactualDeliberationResourceLock(BaseModel):
    model_config = _CONFIG

    maximum_source_trajectories: int = Field(ge=1)
    maximum_branch_trajectories: int = Field(ge=1)
    maximum_selector_invocations: int = Field(ge=1)
    gpu_hours: Literal[0] = 0


class CounterfactualDeliberationExecutionLock(BaseModel):
    """Provider and research-loop identities frozen before target outcomes exist."""

    model_config = _CONFIG

    limits: str
    limits_sha256: str = Field(pattern=_SHA256)
    research_agent_config: str
    research_agent_config_sha256: str = Field(pattern=_SHA256)
    terminal_judge_config: str
    terminal_judge_config_sha256: str = Field(pattern=_SHA256)
    research_agent_policy_id: str
    research_agent_prompt_version: str
    terminal_judge_prompt_version: str
    research_agent_seeds: dict[str, int]
    terminal_judge_seeds: dict[str, int]


class CounterfactualDeliberationConfirmationProtocol(BaseModel):
    """Complete pre-outcome lock for one selector confirmation."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    protocol_id: str
    project_id: str
    target_venue: str
    frozen_implementation_commit: str = Field(pattern=_SHA1)
    benchmark_name: Literal["NewtonBench"] = "NewtonBench"
    benchmark_repository_commit: str = Field(pattern=_SHA1)
    benchmark_checkout: str
    source_precedent_root: str
    source_manifest_sha256: str = Field(pattern=_SHA256)
    source_library_sha256: str = Field(pattern=_SHA256)
    development_report: str
    development_report_sha256: str = Field(pattern=_SHA256)
    studies: tuple[CounterfactualDeliberationConfirmationStudy, ...] = Field(min_length=4)
    forced_actions: tuple[CounterfactualResearchAction, ...] = Field(min_length=7, max_length=7)
    selector: CounterfactualDeliberationSelectorLock
    execution: CounterfactualDeliberationExecutionLock
    endpoint: CounterfactualDeliberationEndpointLock
    success: CounterfactualDeliberationSuccessLock
    resources: CounterfactualDeliberationResourceLock
    evidence_scope: Literal["mechanism-confirmation-only"] = "mechanism-confirmation-only"

    @model_validator(mode="after")
    def protocol_is_closed(self) -> CounterfactualDeliberationConfirmationProtocol:
        validate_entry_id(self.protocol_id, field_name="confirmation protocol_id")
        validate_project_id(self.project_id)
        study_ids = [item.study_id for item in self.studies]
        if len(study_ids) != len(set(study_ids)):
            raise ValueError("confirmation study IDs must be unique")
        task_turns: dict[str, set[int]] = defaultdict(set)
        for study in self.studies:
            task_turns[study.task_id].add(study.prefix_turn_count)
        if len(task_turns) != self.success.expected_task_cluster_count:
            raise ValueError("confirmation task count differs from the frozen success rule")
        if len(self.studies) != self.success.expected_state_count:
            raise ValueError("confirmation state count differs from the frozen success rule")
        expected_turns = set(
            range(1, self.success.expected_state_count // len(task_turns) + 1)
        )
        if any(turns != expected_turns for turns in task_turns.values()):
            raise ValueError("confirmation tasks must share the same consecutive prefix phases")
        if set(self.forced_actions) != set(CounterfactualResearchAction):
            raise ValueError("confirmation must declare the complete research-action space")
        if self.resources.maximum_branch_trajectories != len(self.studies) * len(
            self.forced_actions
        ):
            raise ValueError("confirmation branch ceiling differs from the frozen population")
        task_ids = {item.task_id for item in self.studies}
        if set(self.execution.research_agent_seeds) != task_ids:
            raise ValueError("research-agent seeds must cover every and only confirmation task")
        if set(self.execution.terminal_judge_seeds) != task_ids:
            raise ValueError("terminal-judge seeds must cover every and only confirmation task")
        return self


class CounterfactualDeliberationConfirmationBinding(BaseModel):
    model_config = _CONFIG

    study_id: str
    task_id: str
    prefix_turn_count: int = Field(ge=1)
    result_sha256: str = Field(pattern=_SHA256)
    prefix_sha256: str = Field(pattern=_SHA256)
    selector_input_sha256: str = Field(pattern=_SHA256)
    target_sha256: str = Field(pattern=_SHA256)
    retrieval_sha256: str = Field(pattern=_SHA256)


class CounterfactualDeliberationPopulationLock(BaseModel):
    """Hash every target and selector input before selector execution."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    protocol_id: str
    protocol_sha256: str = Field(pattern=_SHA256)
    project_id: str
    source_manifest_sha256: str = Field(pattern=_SHA256)
    source_library_sha256: str = Field(pattern=_SHA256)
    development_report_sha256: str = Field(pattern=_SHA256)
    bindings: tuple[CounterfactualDeliberationConfirmationBinding, ...] = Field(
        min_length=4
    )
    target_outcomes_absent_from_selector_inputs: Literal[True] = True
    source_outcomes_absent_from_selector_inputs: Literal[True] = True
    policy_update_from_confirmation_forbidden: Literal[True] = True
    population_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def population_is_closed(self) -> CounterfactualDeliberationPopulationLock:
        if len({item.study_id for item in self.bindings}) != len(self.bindings):
            raise ValueError("confirmation population repeats a study")
        expected = content_sha256(self.model_dump(mode="json", exclude={"population_sha256"}))
        if self.population_sha256 != expected:
            raise ValueError("confirmation population hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualDeliberationPopulationLock:
        payload = {
            "schema_version": "1.0",
            "target_outcomes_absent_from_selector_inputs": True,
            "source_outcomes_absent_from_selector_inputs": True,
            "policy_update_from_confirmation_forbidden": True,
            **values,
        }
        payload.pop("population_sha256", None)
        unsigned = cls.model_construct(population_sha256="0" * 64, **payload)
        return cls(
            **payload,
            population_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"population_sha256"})
            ),
        )


class CounterfactualDeliberationConfirmationContrast(BaseModel):
    model_config = _CONFIG

    baseline_action: CounterfactualResearchAction
    selector_mean: float = Field(allow_inf_nan=False)
    baseline_mean: float = Field(allow_inf_nan=False)
    paired_mean_difference: float = Field(allow_inf_nan=False)
    task_cluster_mean_differences: dict[str, float]
    exhaustive_task_cluster_bootstrap_95_interval: tuple[float, float]
    bootstrap_enumeration_count: int = Field(ge=1)
    practical_wins: int = Field(ge=0)
    practical_losses: int = Field(ge=0)
    practical_ties: int = Field(ge=0)
    exact_two_sided_sign_p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    selector_failure_rate: float = Field(ge=0.0, le=1.0)
    baseline_failure_rate: float = Field(ge=0.0, le=1.0)


class CounterfactualDeliberationConfirmationState(BaseModel):
    model_config = _CONFIG

    study_id: str
    task_id: str
    prefix_turn_count: int = Field(ge=1)
    accepted_invocation_id: str
    selected_action: CounterfactualResearchAction
    selected_value: float = Field(allow_inf_nan=False)
    selected_objective_observed: bool
    objective_preferred_actions: tuple[CounterfactualResearchAction, ...]
    oracle_value: float = Field(allow_inf_nan=False)
    regret: float = Field(ge=0.0, allow_inf_nan=False)
    static_values: dict[CounterfactualResearchAction, float]
    static_objective_observed: dict[CounterfactualResearchAction, bool]


class CounterfactualDeliberationConfirmationReport(BaseModel):
    """Outcome-opened report under the prospectively frozen selector contract."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    report_id: str
    project_id: str
    protocol_sha256: str = Field(pattern=_SHA256)
    population_sha256: str = Field(pattern=_SHA256)
    source_library_sha256: str = Field(pattern=_SHA256)
    development_report_sha256: str = Field(pattern=_SHA256)
    state_count: int = Field(ge=1)
    task_cluster_count: int = Field(ge=1)
    accepted_state_count: int = Field(ge=0)
    objective_observation_rate: float = Field(ge=0.0, le=1.0)
    selected_action_counts: dict[CounterfactualResearchAction, int]
    distinct_selected_action_count: int = Field(ge=0)
    maximum_selected_action_share: float = Field(ge=0.0, le=1.0)
    mean_selector_value: float = Field(allow_inf_nan=False)
    mean_oracle_regret: float = Field(ge=0.0, allow_inf_nan=False)
    strongest_static_action: CounterfactualResearchAction
    contrasts: tuple[CounterfactualDeliberationConfirmationContrast, ...] = Field(
        min_length=3, max_length=3
    )
    complete_coverage_gate: bool
    objective_observation_gate: bool
    action_diversity_gate: bool
    action_concentration_gate: bool
    mean_utility_margin_gate: bool
    clustered_uncertainty_gate: bool
    failure_noninferiority_gate: bool
    confirmation_supported: bool
    verdict: Literal["supported", "not-supported", "inadmissible"]
    verdict_reasons: tuple[str, ...] = Field(min_length=1)
    mechanism_effect_claim_allowed: bool
    full_scitaste_claim_allowed: Literal[False] = False
    venue_ready: Literal[False] = False
    policy_update_from_confirmation_forbidden: Literal[True] = True
    states: tuple[CounterfactualDeliberationConfirmationState, ...]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    known_api_cost_usd: float = Field(ge=0.0)
    report_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def report_is_closed(self) -> CounterfactualDeliberationConfirmationReport:
        validate_entry_id(self.report_id, field_name="confirmation report_id")
        if self.state_count != len(self.states):
            raise ValueError("confirmation report state count mismatch")
        expected_supported = all(
            (
                self.complete_coverage_gate,
                self.objective_observation_gate,
                self.action_diversity_gate,
                self.action_concentration_gate,
                self.mean_utility_margin_gate,
                self.clustered_uncertainty_gate,
                self.failure_noninferiority_gate,
            )
        )
        if self.confirmation_supported != expected_supported:
            raise ValueError("confirmation verdict differs from its frozen gates")
        if self.mechanism_effect_claim_allowed != self.confirmation_supported:
            raise ValueError("mechanism claim authorization differs from confirmation verdict")
        expected = content_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))
        if self.report_sha256 != expected:
            raise ValueError("confirmation report hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualDeliberationConfirmationReport:
        payload = {
            "schema_version": "1.0",
            "full_scitaste_claim_allowed": False,
            "venue_ready": False,
            "policy_update_from_confirmation_forbidden": True,
            **values,
        }
        payload.pop("report_sha256", None)
        unsigned = cls.model_construct(report_sha256="0" * 64, **payload)
        return cls(
            **payload,
            report_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"report_sha256"})
            ),
        )


def load_counterfactual_deliberation_confirmation_protocol(
    path: str | Path,
) -> tuple[CounterfactualDeliberationConfirmationProtocol, str]:
    source = Path(path).resolve(strict=True)
    protocol_sha256 = _sha256(source)
    protocol = CounterfactualDeliberationConfirmationProtocol.model_validate_json(
        source.read_bytes(), strict=True
    )
    _verify_file(protocol.source_precedent_root + "/MANIFEST.json", protocol.source_manifest_sha256)
    _verify_file(
        protocol.source_precedent_root + "/TASTE_LIBRARY.jsonl",
        protocol.source_library_sha256,
    )
    _verify_file(protocol.development_report, protocol.development_report_sha256)
    _verify_file(protocol.selector.profile_set, protocol.selector.profile_set_sha256)
    _verify_file(protocol.selector.backend_config, protocol.selector.backend_config_sha256)
    _verify_file(protocol.execution.limits, protocol.execution.limits_sha256)
    _verify_file(
        protocol.execution.research_agent_config,
        protocol.execution.research_agent_config_sha256,
    )
    _verify_file(
        protocol.execution.terminal_judge_config,
        protocol.execution.terminal_judge_config_sha256,
    )
    for study in protocol.studies:
        _verify_file(study.task_config, study.task_config_sha256)
    return protocol, protocol_sha256


def prepare_counterfactual_deliberation_confirmation(
    *,
    protocol_path: str | Path,
    state_root: str | Path,
    output_root: str | Path,
) -> CounterfactualDeliberationPopulationLock:
    """Compile sealed confirmation inputs from exactly the predeclared action branches."""

    protocol, protocol_sha256 = load_counterfactual_deliberation_confirmation_protocol(
        protocol_path
    )
    state_base = Path(state_root).resolve(strict=True)
    destination = Path(output_root).expanduser()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    source_root = Path(protocol.source_precedent_root).resolve(strict=True)
    manifest = CounterfactualTastePrecedentManifest.model_validate_json(
        (source_root / "MANIFEST.json").read_bytes(), strict=True
    )
    cases = {item.case_id: item for item in TasteLibrary(source_root / "TASTE_LIBRARY.jsonl").all()}
    if set(cases) != {item.case_id for item in manifest.bindings}:
        raise ValueError("confirmation source manifest and Taste library differ")
    source_result_hashes = {item.result_sha256 for item in manifest.bindings}
    source_task_ids = {item.task_cluster_id for item in manifest.bindings}

    destination.mkdir(parents=True)
    bindings: list[CounterfactualDeliberationConfirmationBinding] = []
    seen_results: set[str] = set()
    seen_prefixes: set[str] = set()
    for study in protocol.studies:
        root = state_base / study.study_id
        result = CounterfactualActionSetResult.model_validate_json(
            (root / "RESULT.json").read_bytes(), strict=True
        )
        prefix = load_interactive_research_prefix(root / "PREFIX.json")
        if result.study_id != study.study_id or result.task_id != study.task_id:
            raise ValueError("confirmation result differs from its frozen study identity")
        if (
            prefix.turn_count != study.prefix_turn_count
            or result.prefix_sha256 != prefix.prefix_sha256
        ):
            raise ValueError("confirmation prefix differs from its frozen study phase")
        if result.result_sha256 in source_result_hashes or result.task_id in source_task_ids:
            raise ValueError("confirmation population overlaps the development source library")
        if result.result_sha256 in seen_results or prefix.prefix_sha256 in seen_prefixes:
            raise ValueError("confirmation population repeats a result or prefix")
        seen_results.add(result.result_sha256)
        seen_prefixes.add(prefix.prefix_sha256)
        if {item.action for item in result.outcomes} != set(protocol.forced_actions):
            raise ValueError("confirmation state lacks the frozen action space")
        endpoint = protocol.endpoint
        if (
            result.primary_metric != endpoint.primary_metric
            or result.source_metric != endpoint.source_metric
            or result.metric_transform != endpoint.metric_transform
            or result.metric_direction != endpoint.direction
            or result.failure_value != endpoint.failure_value
            or result.practical_equivalence_tolerance
            != endpoint.practical_equivalence_tolerance
        ):
            raise ValueError("confirmation outcome contract differs from the protocol")

        deliberation_input, population = _deliberation_input(
            project_id=protocol.project_id,
            prefix=prefix,
            cases=tuple(cases.values()),
            maximum_selected_cases=protocol.selector.maximum_selected_cases,
            maximum_candidate_cases=protocol.selector.maximum_candidate_cases,
        )
        encoded_input = deliberation_input.model_dump_json(indent=2) + "\n"
        if "objective_value" in encoded_input or "outcome_summary" in encoded_input:
            raise ValueError("confirmation selector input contains an outcome")
        target = CounterfactualDeliberationTarget.create(
            study_id=result.study_id,
            target_case_id=(
                "confirmation-target-"
                + content_sha256(
                    {"protocol_sha256": protocol_sha256, "prefix_sha256": prefix.prefix_sha256}
                )[:20]
            ),
            task_cluster_id=result.task_id,
            prefix_sha256=result.prefix_sha256,
            result_sha256=result.result_sha256,
            excluded_same_cluster_case_ids=(),
            eligible_cross_cluster_case_ids=tuple(
                sorted(item.case_id for item in deliberation_input.candidates)
            ),
            objective_preferred_actions=tuple(
                sorted(item.value for item in result.preferred_actions)
            ),
            objective_values={item.action.value: item.objective_value for item in result.outcomes},
            objective_observed={
                item.action.value: item.objective_observed for item in result.outcomes
            },
            selector_input_sha256=deliberation_input.fingerprint,
            development_only=False,
            confirmation_protocol_sha256=protocol_sha256,
        )
        retrieval = CounterfactualDeliberationRetrievalRecord.create(
            study_id=result.study_id,
            task_cluster_id=result.task_id,
            maximum_candidate_cases=protocol.selector.maximum_candidate_cases,
            population_scores={
                item.case_id: item.broad_retrieval_score
                for item in sorted(population, key=lambda item: item.case_id)
            },
            population_preferred_actions={
                item.case_id: item.preferred_action
                for item in sorted(population, key=lambda item: item.case_id)
            },
            population_hard_applicability={
                item.case_id: bool(item.hard_applicability_satisfied)
                for item in sorted(population, key=lambda item: item.case_id)
            },
            selected_case_ids=tuple(item.case_id for item in deliberation_input.candidates),
            selector_input_sha256=deliberation_input.fingerprint,
        )
        target_root = destination / study.study_id
        target_root.mkdir()
        _write_new(target_root / "INPUT.json", encoded_input.encode())
        _write_new(target_root / "TARGET.json", (target.model_dump_json(indent=2) + "\n").encode())
        _write_new(
            target_root / "RETRIEVAL.json",
            (retrieval.model_dump_json(indent=2) + "\n").encode(),
        )
        bindings.append(
            CounterfactualDeliberationConfirmationBinding(
                study_id=study.study_id,
                task_id=study.task_id,
                prefix_turn_count=study.prefix_turn_count,
                result_sha256=result.result_sha256,
                prefix_sha256=prefix.prefix_sha256,
                selector_input_sha256=deliberation_input.fingerprint,
                target_sha256=target.target_sha256,
                retrieval_sha256=retrieval.retrieval_sha256,
            )
        )
    lock = CounterfactualDeliberationPopulationLock.create(
        protocol_id=protocol.protocol_id,
        protocol_sha256=protocol_sha256,
        project_id=protocol.project_id,
        source_manifest_sha256=protocol.source_manifest_sha256,
        source_library_sha256=protocol.source_library_sha256,
        development_report_sha256=protocol.development_report_sha256,
        bindings=tuple(bindings),
    )
    _write_new(
        destination / "POPULATION_LOCK.json",
        (lock.model_dump_json(indent=2) + "\n").encode(),
    )
    return lock


def analyze_counterfactual_deliberation_confirmation(
    *,
    protocol_path: str | Path,
    input_root: str | Path,
    ledger_root: str | Path,
    evidence_root: str | Path,
) -> CounterfactualDeliberationConfirmationReport:
    """Open target outcomes only after accepted selector decisions cover the population."""

    protocol, protocol_sha256 = load_counterfactual_deliberation_confirmation_protocol(
        protocol_path
    )
    input_base = Path(input_root).resolve(strict=True)
    lock = CounterfactualDeliberationPopulationLock.model_validate_json(
        (input_base / "POPULATION_LOCK.json").read_bytes(), strict=True
    )
    if lock.protocol_sha256 != protocol_sha256:
        raise ValueError("confirmation population targets another protocol")
    accepted: dict[str, tuple[str, str]] = {}
    input_tokens = 0
    output_tokens = 0
    known_cost = 0.0
    for path in sorted(Path(ledger_root).resolve(strict=True).glob("*.json")):
        entry = RuntimeLedgerEntry.model_validate_json(path.read_bytes(), strict=True)
        input_tokens += entry.usage.input_tokens
        output_tokens += entry.usage.output_tokens
        if entry.usage.cost_usd is not None:
            known_cost += entry.usage.cost_usd
        if entry.outcome is not RuntimeOutcome.ACCEPTED:
            continue
        verified = taste_deliberation_from_ledger(path, evidence_root=evidence_root)
        recommendation = verified.proposal.recommended_action_id
        if recommendation is None:
            raise ValueError("confirmation selector abstained despite an accepted proposal")
        if verified.input.fingerprint in accepted:
            raise ValueError("confirmation contains multiple accepted decisions for one state")
        accepted[verified.input.fingerprint] = (verified.invocation_id, recommendation)

    states: list[CounterfactualDeliberationConfirmationState] = []
    branch_observed = 0
    branch_count = 0
    for binding in lock.bindings:
        root = input_base / binding.study_id
        input_data = TasteDeliberationInput.model_validate_json(
            (root / "INPUT.json").read_bytes(), strict=True
        )
        target = CounterfactualDeliberationTarget.model_validate_json(
            (root / "TARGET.json").read_bytes(), strict=True
        )
        retrieval = CounterfactualDeliberationRetrievalRecord.model_validate_json(
            (root / "RETRIEVAL.json").read_bytes(), strict=True
        )
        if (
            input_data.fingerprint != binding.selector_input_sha256
            or target.target_sha256 != binding.target_sha256
            or retrieval.retrieval_sha256 != binding.retrieval_sha256
            or target.confirmation_protocol_sha256 != protocol_sha256
        ):
            raise ValueError("confirmation input differs from the frozen population")
        try:
            invocation_id, selected_name = accepted[input_data.fingerprint]
        except KeyError as exc:
            raise ValueError(f"no accepted confirmation decision for {binding.study_id}") from exc
        selected_action = CounterfactualResearchAction(selected_name)
        objective_values = {
            CounterfactualResearchAction(key): value
            for key, value in target.objective_values.items()
        }
        objective_observed = {
            CounterfactualResearchAction(key): value
            for key, value in target.objective_observed.items()
        }
        branch_observed += sum(objective_observed.values())
        branch_count += len(objective_observed)
        oracle_value = max(objective_values.values())
        states.append(
            CounterfactualDeliberationConfirmationState(
                study_id=binding.study_id,
                task_id=binding.task_id,
                prefix_turn_count=binding.prefix_turn_count,
                accepted_invocation_id=invocation_id,
                selected_action=selected_action,
                selected_value=objective_values[selected_action],
                selected_objective_observed=objective_observed[selected_action],
                objective_preferred_actions=tuple(
                    CounterfactualResearchAction(item)
                    for item in target.objective_preferred_actions
                ),
                oracle_value=oracle_value,
                regret=max(0.0, oracle_value - objective_values[selected_action]),
                static_values={item: objective_values[item] for item in _STATIC_ACTIONS},
                static_objective_observed={
                    item: objective_observed[item] for item in _STATIC_ACTIONS
                },
            )
        )
    states.sort(key=lambda item: (item.task_id, item.prefix_turn_count))
    static_means = {
        action: math.fsum(item.static_values[action] for item in states) / len(states)
        for action in _STATIC_ACTIONS
    }
    strongest = max(_STATIC_ACTIONS, key=lambda action: (static_means[action], action.value))
    contrasts = tuple(
        _confirmation_contrast(states, action, protocol.endpoint.practical_equivalence_tolerance)
        for action in _STATIC_ACTIONS
    )
    strongest_contrast = next(item for item in contrasts if item.baseline_action is strongest)
    counts = Counter(item.selected_action for item in states)
    state_count = len(states)
    observation_rate = branch_observed / branch_count
    complete_gate = len(accepted) == state_count == protocol.success.expected_state_count
    observation_gate = observation_rate >= protocol.success.minimum_objective_observation_rate
    diversity_gate = len(counts) >= protocol.success.minimum_selected_action_types
    concentration_gate = (
        max(counts.values()) / state_count <= protocol.success.maximum_selected_action_share
    )
    margin_gate = (
        strongest_contrast.paired_mean_difference
        >= protocol.success.minimum_mean_margin_over_strongest_static
    )
    uncertainty_gate = (
        not protocol.success.require_positive_task_cluster_interval_lower_bound
        or strongest_contrast.exhaustive_task_cluster_bootstrap_95_interval[0] > 0.0
    )
    failure_gate = (
        not protocol.success.require_failure_noninferiority
        or strongest_contrast.selector_failure_rate
        <= strongest_contrast.baseline_failure_rate
    )
    supported = all(
        (
            complete_gate,
            observation_gate,
            diversity_gate,
            concentration_gate,
            margin_gate,
            uncertainty_gate,
            failure_gate,
        )
    )
    if not complete_gate or not observation_gate:
        verdict: Literal["supported", "not-supported", "inadmissible"] = "inadmissible"
    elif supported:
        verdict = "supported"
    else:
        verdict = "not-supported"
    reasons = tuple(
        name
        for name, passed in (
            ("incomplete-selector-coverage", complete_gate),
            ("objective-observation-below-threshold", observation_gate),
            ("selected-action-diversity-below-threshold", diversity_gate),
            ("selected-action-concentration-above-threshold", concentration_gate),
            ("mean-margin-over-strongest-static-below-threshold", margin_gate),
            ("task-cluster-interval-includes-nonpositive-effects", uncertainty_gate),
            ("selector-failure-rate-exceeds-strongest-static", failure_gate),
        )
        if not passed
    ) or ("all-frozen-confirmation-gates-passed",)
    return CounterfactualDeliberationConfirmationReport.create(
        report_id=f"{protocol.protocol_id}-report",
        project_id=protocol.project_id,
        protocol_sha256=protocol_sha256,
        population_sha256=lock.population_sha256,
        source_library_sha256=lock.source_library_sha256,
        development_report_sha256=lock.development_report_sha256,
        state_count=state_count,
        task_cluster_count=len({item.task_id for item in states}),
        accepted_state_count=len(accepted),
        objective_observation_rate=observation_rate,
        selected_action_counts=dict(sorted(counts.items(), key=lambda item: item[0].value)),
        distinct_selected_action_count=len(counts),
        maximum_selected_action_share=max(counts.values()) / state_count,
        mean_selector_value=math.fsum(item.selected_value for item in states) / state_count,
        mean_oracle_regret=math.fsum(item.regret for item in states) / state_count,
        strongest_static_action=strongest,
        contrasts=contrasts,
        complete_coverage_gate=complete_gate,
        objective_observation_gate=observation_gate,
        action_diversity_gate=diversity_gate,
        action_concentration_gate=concentration_gate,
        mean_utility_margin_gate=margin_gate,
        clustered_uncertainty_gate=uncertainty_gate,
        failure_noninferiority_gate=failure_gate,
        confirmation_supported=supported,
        verdict=verdict,
        verdict_reasons=reasons,
        mechanism_effect_claim_allowed=supported,
        states=tuple(states),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        known_api_cost_usd=known_cost,
    )


def save_counterfactual_deliberation_confirmation_report(
    report: CounterfactualDeliberationConfirmationReport,
    path: str | Path,
) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_new(target, (report.model_dump_json(indent=2) + "\n").encode())
    return target


def _confirmation_contrast(
    states: list[CounterfactualDeliberationConfirmationState],
    baseline: CounterfactualResearchAction,
    tolerance: float,
) -> CounterfactualDeliberationConfirmationContrast:
    effects = [item.selected_value - item.static_values[baseline] for item in states]
    clustered: dict[str, list[float]] = defaultdict(list)
    for state, effect in zip(states, effects, strict=True):
        clustered[state.task_id].append(effect)
    cluster_means = {
        task: math.fsum(values) / len(values) for task, values in sorted(clustered.items())
    }
    interval, samples = _exhaustive_cluster_bootstrap(tuple(cluster_means.values()))
    wins = sum(item > tolerance for item in effects)
    losses = sum(item < -tolerance for item in effects)
    return CounterfactualDeliberationConfirmationContrast(
        baseline_action=baseline,
        selector_mean=math.fsum(item.selected_value for item in states) / len(states),
        baseline_mean=math.fsum(item.static_values[baseline] for item in states) / len(states),
        paired_mean_difference=math.fsum(effects) / len(effects),
        task_cluster_mean_differences=cluster_means,
        exhaustive_task_cluster_bootstrap_95_interval=interval,
        bootstrap_enumeration_count=samples,
        practical_wins=wins,
        practical_losses=losses,
        practical_ties=len(effects) - wins - losses,
        exact_two_sided_sign_p_value=_exact_two_sided_sign_test(wins, losses),
        selector_failure_rate=sum(not item.selected_objective_observed for item in states)
        / len(states),
        baseline_failure_rate=sum(
            not item.static_objective_observed[baseline] for item in states
        )
        / len(states),
    )


def _verify_file(path: str | Path, expected_sha256: str) -> None:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"confirmation dependency is not a regular file: {source}")
    if _sha256(source) != expected_sha256:
        raise ValueError(f"confirmation dependency hash differs: {source}")


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "CounterfactualDeliberationConfirmationProtocol",
    "CounterfactualDeliberationConfirmationReport",
    "CounterfactualDeliberationPopulationLock",
    "analyze_counterfactual_deliberation_confirmation",
    "load_counterfactual_deliberation_confirmation_protocol",
    "prepare_counterfactual_deliberation_confirmation",
    "save_counterfactual_deliberation_confirmation_report",
]

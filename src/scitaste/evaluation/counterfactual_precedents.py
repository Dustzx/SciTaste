"""Compile objective counterfactual branches into development-only Taste precedents."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.data.models import ProvenanceRecord, TasteCase
from scitaste.data.store import TasteLibrary
from scitaste.evaluation.counterfactual_abstraction import (
    build_counterfactual_taste_abstraction_input,
    resource_aware_preferred_outcome,
)
from scitaste.evaluation.counterfactual_taste import CounterfactualActionSetResult
from scitaste.evaluation.interactive_research import load_interactive_research_prefix
from scitaste.model_nodes.models import NodeResult, NodeResultStatus
from scitaste.model_nodes.runtime import (
    RuntimeBackendMode,
    RuntimeLedgerEntry,
    RuntimeOutcome,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id
from scitaste.taste.semantic import (
    is_verified_model_generation_entry,
    load_verified_taste_abstraction_ledger,
)
from scitaste.taste.semantic_models import (
    GROUNDED_TASTE_ABSTRACTION_NODE,
    GroundedTasteCaseAbstraction,
    TasteAbstractionInput,
)

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"


class CounterfactualTastePrecedentBinding(BaseModel):
    """Exact objective and model-ledger provenance for one reusable precedent."""

    model_config = _CONFIG

    case_id: str
    study_id: str
    task_cluster_id: str
    prefix_turn_count: int = Field(ge=1)
    evidence_status: str
    result_sha256: str = Field(pattern=_SHA256)
    prefix_sha256: str = Field(pattern=_SHA256)
    source_projection_sha256: str = Field(pattern=_SHA256)
    ledger_locator: str
    ledger_sha256: str = Field(pattern=_SHA256)
    ledger_entry_sha256: str = Field(pattern=_SHA256)
    generation_ledger_locator: str
    generation_ledger_sha256: str = Field(pattern=_SHA256)
    objective_preferred_actions: tuple[str, ...] = Field(min_length=1, max_length=7)
    resource_aware_preferred_action: str
    taste_case_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def binding_is_closed(self) -> CounterfactualTastePrecedentBinding:
        validate_entry_id(self.case_id, field_name="counterfactual Taste case_id")
        validate_entry_id(self.study_id, field_name="counterfactual Taste study_id")
        if self.objective_preferred_actions != tuple(sorted(set(self.objective_preferred_actions))):
            raise ValueError("counterfactual preferred actions must be sorted and unique")
        if self.resource_aware_preferred_action not in self.objective_preferred_actions:
            raise ValueError("resource-aware action is absent from the objective preferred set")
        return self


class CounterfactualTastePrecedentManifest(BaseModel):
    """Development corpus contract; never evidence of policy effectiveness."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    manifest_id: str
    project_id: str
    source_run_id: str
    bindings: tuple[CounterfactualTastePrecedentBinding, ...] = Field(min_length=2)
    action_vocabulary: tuple[str, ...] = Field(min_length=2, max_length=7)
    training_population_sha256: str = Field(pattern=_SHA256)
    library_sha256: str = Field(pattern=_SHA256)
    development_only: Literal[True] = True
    source_outcomes_hidden_at_selection: Literal[True] = True
    same_task_cluster_exclusion_required: Literal[True] = True
    confirmation_population_reuse_prohibited: Literal[True] = True
    effectiveness_claim_allowed: Literal[False] = False
    manifest_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def manifest_is_closed(self) -> CounterfactualTastePrecedentManifest:
        validate_entry_id(self.manifest_id, field_name="counterfactual Taste manifest_id")
        validate_project_id(self.project_id)
        validate_entry_id(self.source_run_id, field_name="counterfactual Taste source_run_id")
        if self.bindings != tuple(sorted(self.bindings, key=lambda item: item.case_id)):
            raise ValueError("counterfactual Taste bindings must be case ordered")
        if len({item.case_id for item in self.bindings}) != len(self.bindings):
            raise ValueError("counterfactual Taste manifest repeats a case")
        if self.action_vocabulary != tuple(sorted(set(self.action_vocabulary))):
            raise ValueError("counterfactual Taste action vocabulary must be canonical")
        expected_population = content_sha256(
            tuple(item.model_dump(mode="json") for item in self.bindings)
        )
        if self.training_population_sha256 != expected_population:
            raise ValueError("counterfactual Taste population hash mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("counterfactual Taste manifest hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualTastePrecedentManifest:
        payload = {
            "schema_version": "1.0",
            "development_only": True,
            "source_outcomes_hidden_at_selection": True,
            "same_task_cluster_exclusion_required": True,
            "confirmation_population_reuse_prohibited": True,
            "effectiveness_claim_allowed": False,
            **values,
        }
        payload.pop("manifest_sha256", None)
        bindings = tuple(sorted(payload["bindings"], key=lambda item: item.case_id))  # type: ignore[arg-type]
        payload["bindings"] = bindings
        payload["training_population_sha256"] = content_sha256(
            tuple(item.model_dump(mode="json") for item in bindings)
        )
        unsigned = cls.model_construct(manifest_sha256="0" * 64, **payload)
        return cls(
            **payload,
            manifest_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"manifest_sha256"})
            ),
        )


def compile_counterfactual_taste_precedents(
    *,
    manifest_id: str,
    project_id: str,
    source_run_id: str,
    state_root: str | Path,
    abstraction_input_root: str | Path,
    ledger_root: str | Path,
    evidence_root: str | Path,
    output_root: str | Path,
) -> CounterfactualTastePrecedentManifest:
    """Verify and atomically publish objective-labelled grounded Taste cases."""

    state_base = Path(state_root).resolve(strict=True)
    input_base = Path(abstraction_input_root).resolve(strict=True)
    ledger_base = Path(ledger_root).resolve(strict=True)
    evidence_base = Path(evidence_root).resolve(strict=True)
    target = Path(output_root).expanduser()
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    accepted = _accepted_ledgers_by_case(ledger_base)
    prepared = sorted(input_base.glob("*/INPUT.json"))
    if len(prepared) < 2:
        raise ValueError("counterfactual precedent compilation requires at least two states")

    cases: list[TasteCase] = []
    pending: list[dict[str, object]] = []
    seen_cases: set[str] = set()
    action_vocabulary: set[str] = set()
    for input_path in prepared:
        expected_input = TasteAbstractionInput.model_validate_json(
            input_path.read_bytes(), strict=True
        )
        if expected_input.case_id in seen_cases:
            raise ValueError("counterfactual abstraction inputs repeat a case")
        seen_cases.add(expected_input.case_id)
        ledger_path = accepted.get(expected_input.case_id)
        if ledger_path is None:
            raise ValueError(f"missing accepted grounded ledger for {expected_input.case_id}")
        study_id = input_path.parent.name
        state_dir = state_base / study_id
        result = CounterfactualActionSetResult.model_validate_json(
            (state_dir / "RESULT.json").read_bytes(), strict=True
        )
        prefix = load_interactive_research_prefix(state_dir / "PREFIX.json")
        rebuilt_input = build_counterfactual_taste_abstraction_input(result, prefix)
        if rebuilt_input != expected_input:
            raise ValueError("prepared abstraction input differs from objective state bytes")

        (
            ledger,
            abstraction,
            ledger_locator,
            ledger_sha256,
            generation_ledger_locator,
            generation_ledger_sha256,
        ) = _grounded_abstraction_from_verified_ledger(
            ledger_path,
            ledger_root=ledger_base,
            evidence_root=evidence_base,
        )
        ledger_input = TasteAbstractionInput.model_validate_json(
            json.dumps(ledger.intent.node_input, ensure_ascii=False, allow_nan=False),
            strict=True,
        )
        if ledger_input != expected_input:
            raise ValueError("accepted ledger input differs from the objective source projection")
        objective_choice = resource_aware_preferred_outcome(result).action.value
        if abstraction.preferred_action != objective_choice:
            raise ValueError("grounded abstraction changed the objective preferred action")
        case = _taste_case(
            abstraction=abstraction,
            result=result,
            prefix_turn_count=prefix.turn_count,
            evidence_status=prefix.turns[-1].decision.proposal.evidence_status,
            ledger=ledger,
            ledger_locator=ledger_locator,
            ledger_sha256=ledger_sha256,
            generation_ledger_locator=generation_ledger_locator,
            generation_ledger_sha256=generation_ledger_sha256,
        )
        cases.append(case)
        action_vocabulary.update(item.action.value for item in result.outcomes)
        pending.append(
            {
                "case": case,
                "result": result,
                "prefix_turn_count": prefix.turn_count,
                "evidence_status": prefix.turns[-1].decision.proposal.evidence_status,
                "source_projection_sha256": expected_input.source_projection_sha256,
                "ledger_locator": ledger_locator,
                "ledger_sha256": ledger_sha256,
                "ledger_entry_sha256": ledger.entry_sha256,
                "generation_ledger_locator": generation_ledger_locator,
                "generation_ledger_sha256": generation_ledger_sha256,
            }
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        library_path = staging / "TASTE_LIBRARY.jsonl"
        library = TasteLibrary(library_path)
        for case in sorted(cases, key=lambda item: item.case_id):
            library.add(case)
        library_sha256 = hashlib.sha256(library_path.read_bytes()).hexdigest()
        bindings = tuple(
            CounterfactualTastePrecedentBinding(
                case_id=item["case"].case_id,  # type: ignore[union-attr]
                study_id=item["result"].study_id,  # type: ignore[union-attr]
                task_cluster_id=item["result"].task_id,  # type: ignore[union-attr]
                prefix_turn_count=item["prefix_turn_count"],
                evidence_status=item["evidence_status"],
                result_sha256=item["result"].result_sha256,  # type: ignore[union-attr]
                prefix_sha256=item["result"].prefix_sha256,  # type: ignore[union-attr]
                source_projection_sha256=item["source_projection_sha256"],
                ledger_locator=item["ledger_locator"],
                ledger_sha256=item["ledger_sha256"],
                ledger_entry_sha256=item["ledger_entry_sha256"],
                generation_ledger_locator=item["generation_ledger_locator"],
                generation_ledger_sha256=item["generation_ledger_sha256"],
                objective_preferred_actions=tuple(
                    sorted(action.value for action in item["result"].preferred_actions)  # type: ignore[union-attr]
                ),
                resource_aware_preferred_action=item["case"].preferred_action,  # type: ignore[union-attr]
                taste_case_sha256=content_sha256(
                    item["case"].model_dump(mode="json")  # type: ignore[union-attr]
                ),
            )
            for item in pending
        )
        manifest = CounterfactualTastePrecedentManifest.create(
            manifest_id=manifest_id,
            project_id=project_id,
            source_run_id=source_run_id,
            bindings=bindings,
            action_vocabulary=tuple(sorted(action_vocabulary)),
            library_sha256=library_sha256,
        )
        _write_new(
            staging / "MANIFEST.json",
            (manifest.model_dump_json(indent=2) + "\n").encode(),
        )
        staging.replace(target)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _accepted_ledgers_by_case(ledger_root: Path) -> dict[str, Path]:
    accepted: dict[str, Path] = {}
    for path in sorted(ledger_root.glob("*.json")):
        entry = RuntimeLedgerEntry.model_validate_json(path.read_bytes(), strict=True)
        if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
            continue
        proposal = entry.result.get("proposal")
        case_id = proposal.get("case_id") if isinstance(proposal, dict) else None
        if not isinstance(case_id, str):
            continue
        if case_id in accepted:
            raise ValueError(f"multiple accepted ledgers exist for {case_id}")
        accepted[case_id] = path
    return accepted


def _grounded_abstraction_from_verified_ledger(
    ledger_path: Path,
    *,
    ledger_root: Path,
    evidence_root: Path,
) -> tuple[RuntimeLedgerEntry, GroundedTasteCaseAbstraction, str, str, str, str]:
    entry, resolved, raw = load_verified_taste_abstraction_ledger(
        ledger_path,
        evidence_root=evidence_root,
    )
    if (
        entry.intent.node_name != GROUNDED_TASTE_ABSTRACTION_NODE
        or entry.outcome is not RuntimeOutcome.ACCEPTED
        or entry.result is None
    ):
        raise ValueError("counterfactual precedent ledger is not an accepted grounded result")
    generation_entry = entry
    generation_resolved = resolved
    generation_raw = raw
    if entry.intent.backend_mode is RuntimeBackendMode.REPLAY:
        source_invocation = entry.intent.replay_source_invocation_id
        if not source_invocation:
            raise ValueError("accepted replay lacks its live generation identity")
        matches = tuple(ledger_root.glob(f"*__{source_invocation}.json"))
        if len(matches) != 1:
            raise ValueError("accepted replay generation source is missing or ambiguous")
        generation_entry, generation_resolved, generation_raw = (
            load_verified_taste_abstraction_ledger(
                matches[0],
                evidence_root=evidence_root,
            )
        )
        source_response = (
            generation_entry.result.get("response") if generation_entry.result else None
        )
        replay_response = entry.result.get("response")
        source_raw_response = (
            source_response.get("raw_response_sha256")
            if isinstance(source_response, dict)
            else None
        )
        replay_raw_response = (
            replay_response.get("raw_response_sha256")
            if isinstance(replay_response, dict)
            else None
        )
        if (
            entry.recording_sha256 != generation_entry.recording_sha256
            or entry.request_fingerprint != generation_entry.request_fingerprint
            or replay_raw_response != source_raw_response
            or entry.input_tokens != generation_entry.input_tokens
            or entry.output_tokens != generation_entry.output_tokens
            or entry.intent.node_input != generation_entry.intent.node_input
        ):
            raise ValueError("accepted replay differs from its recorded model generation")
    if not is_verified_model_generation_entry(generation_entry):
        raise ValueError("counterfactual precedent lacks verified live or local generation")
    result = NodeResult[GroundedTasteCaseAbstraction].model_validate_json(
        json.dumps(entry.result, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("counterfactual precedent accepted ledger has no grounded proposal")
    return (
        entry,
        result.proposal,
        resolved.relative_to(evidence_root).as_posix(),
        hashlib.sha256(raw).hexdigest(),
        generation_resolved.relative_to(evidence_root).as_posix(),
        hashlib.sha256(generation_raw).hexdigest(),
    )


def _taste_case(
    *,
    abstraction: GroundedTasteCaseAbstraction,
    result: CounterfactualActionSetResult,
    prefix_turn_count: int,
    evidence_status: str,
    ledger: RuntimeLedgerEntry,
    ledger_locator: str,
    ledger_sha256: str,
    generation_ledger_locator: str,
    generation_ledger_sha256: str,
) -> TasteCase:
    grounding_sha256 = content_sha256(
        {
            "grounding": [item.model_dump(mode="json") for item in abstraction.grounding],
            "transfer_boundary": abstraction.transfer_boundary.model_dump(mode="json"),
        }
    )
    return TasteCase(
        case_id=abstraction.case_id,
        stage="interactive-experiment",
        context_summary=abstraction.context_summary,
        problem_pattern=abstraction.problem_pattern,
        evidence_state=abstraction.evidence_state,
        reviewer_context=None,
        candidate_actions=list(abstraction.candidate_actions),
        preferred_action=abstraction.preferred_action,
        rejected_actions=list(abstraction.rejected_actions),
        decision_principle=abstraction.decision_principle,
        why_preferred=abstraction.why_preferred,
        applicability_conditions=list(abstraction.transfer_boundary.applies_when),
        failure_conditions=list(abstraction.transfer_boundary.fails_when),
        counterfactual_probe=abstraction.transfer_boundary.counterfactual_probe,
        taste_grounding_sha256=grounding_sha256,
        outcome_summary=abstraction.outcome_summary,
        provenance=[
            ProvenanceRecord(
                source_type="objective-counterfactual-development",
                locator=ledger_locator,
                title=result.study_id,
                content_hash=ledger_sha256,
                accessed_at=ledger.completed_at,
                access_scope="development-only-grounded-counterfactual-precedent",
                derivation_method=(
                    "Objective action label with model-assisted grounded transfer abstraction."
                ),
                redistributable=False,
                personal_data_removed=True,
                metadata={
                    "result_sha256": result.result_sha256,
                    "prefix_sha256": result.prefix_sha256,
                    "task_cluster_id": result.task_id,
                    "prefix_turn_count": prefix_turn_count,
                    "evidence_status": evidence_status,
                    "ledger_entry_sha256": ledger.entry_sha256,
                    "generation_ledger_locator": generation_ledger_locator,
                    "generation_ledger_sha256": generation_ledger_sha256,
                    "grounding_contract": "objective-counterfactual-grounded-v1",
                    "selection_must_hide_outcomes": True,
                    "same_task_cluster_exclusion_required": True,
                },
            )
        ],
        confidence=abstraction.confidence,
        domain_tags=[
            "hidden-law-discovery",
            "scientific-experimentation",
            evidence_status,
            f"turn-{prefix_turn_count}",
        ],
        label_basis="objective-counterfactual-development",
        extractor_version="scitaste-grounded-counterfactual-v1",
        human_verified=False,
        retrieval_eligible=True,
        outcome_horizon="terminal-hidden-objective",
        source_action_id=abstraction.preferred_action,
    )


def _write_new(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


__all__ = [
    "CounterfactualTastePrecedentBinding",
    "CounterfactualTastePrecedentManifest",
    "compile_counterfactual_taste_precedents",
]

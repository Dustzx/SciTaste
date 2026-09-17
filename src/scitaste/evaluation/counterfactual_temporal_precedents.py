"""Derive decision-time-only Taste precedents from objective development labels.

The objective label is preserved as supervision, but every selector-visible
description and transfer boundary is rebuilt from the prefix that existed before
the labelled action was chosen.  Terminal metrics remain in the immutable source
artifacts and are never copied into the derived library.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.data.models import TasteCase
from scitaste.data.store import TasteLibrary
from scitaste.evaluation.counterfactual_precedents import (
    CounterfactualTastePrecedentManifest,
)
from scitaste.evaluation.interactive_research import (
    InteractiveResearchPrefix,
    load_interactive_research_prefix,
)
from scitaste.project.models import content_sha256, validate_entry_id, validate_project_id

_CONFIG = ConfigDict(
    extra="forbid",
    frozen=True,
    str_strip_whitespace=True,
    revalidate_instances="always",
)
_SHA256 = r"^[0-9a-f]{64}$"
TEMPORAL_SAFE_PRECEDENT_CONTRACT = "counterfactual-predecision-observables-v1"
_FORBIDDEN_SELECTOR_MARKERS = (
    "additional_experiments",
    "additional_tokens",
    "counterfactual outcome",
    "frozen practical-equivalence",
    "objective_observed",
    "objective_value",
    "status agent_failure",
)


class CounterfactualPreDecisionState(BaseModel):
    """Typed state that was observable before a counterfactual branch began."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    contract_id: Literal["counterfactual-predecision-observables-v1"] = (
        TEMPORAL_SAFE_PRECEDENT_CONTRACT
    )
    stage: Literal["interactive-experiment"] = "interactive-experiment"
    turn_count: int = Field(ge=1, le=49)
    trajectory_phase: Literal["early", "middle", "late"]
    evidence_status: Literal[
        "unassessed",
        "no-candidate",
        "candidate-untested",
        "candidate-supported",
        "candidate-conflicted",
    ]
    evidence_confidence_band: Literal["low", "medium", "high"]
    next_experiment_value_band: Literal["low", "medium", "high"]
    observed_experiment_count_band: Literal["one-to-three", "four-to-eight", "nine-plus"]
    diagnostic_rationale: str = Field(min_length=1, max_length=8_000)
    diagnostic_rationale_sha256: str = Field(pattern=_SHA256)
    hard_predicates: tuple[str, str]
    soft_descriptors: tuple[str, ...] = Field(min_length=4, max_length=8)
    state_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def state_is_closed(self) -> CounterfactualPreDecisionState:
        if self.diagnostic_rationale_sha256 != hashlib.sha256(
            self.diagnostic_rationale.encode()
        ).hexdigest():
            raise ValueError("pre-decision diagnostic-rationale hash mismatch")
        expected_hard = (
            f"stage={self.stage}",
            f"evidence_status={self.evidence_status}",
        )
        if self.hard_predicates != expected_hard:
            raise ValueError("pre-decision hard predicates differ from typed state")
        expected = content_sha256(self.model_dump(mode="json", exclude={"state_sha256"}))
        if self.state_sha256 != expected:
            raise ValueError("pre-decision observable-state hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualPreDecisionState:
        payload = {
            "schema_version": "1.0",
            "contract_id": TEMPORAL_SAFE_PRECEDENT_CONTRACT,
            "stage": "interactive-experiment",
            **values,
        }
        payload.pop("state_sha256", None)
        unsigned = cls.model_construct(state_sha256="0" * 64, **payload)
        return cls(
            **payload,
            state_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"state_sha256"})
            ),
        )


class CounterfactualTemporalSafeCaseAudit(BaseModel):
    model_config = _CONFIG

    case_id: str
    study_id: str
    source_case_sha256: str = Field(pattern=_SHA256)
    safe_case_sha256: str = Field(pattern=_SHA256)
    prefix_sha256: str = Field(pattern=_SHA256)
    observable_state: CounterfactualPreDecisionState
    selector_visible_sha256: str = Field(pattern=_SHA256)
    preferred_action_preserved: Literal[True] = True
    terminal_metrics_absent_from_selector_fields: Literal[True] = True

    @model_validator(mode="after")
    def identities_are_valid(self) -> CounterfactualTemporalSafeCaseAudit:
        validate_entry_id(self.case_id, field_name="temporal-safe case_id")
        validate_entry_id(self.study_id, field_name="temporal-safe study_id")
        return self


class CounterfactualTemporalSafePrecedentAudit(BaseModel):
    """Immutable derivation receipt for a decision-time-only precedent library."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    audit_id: str
    project_id: str
    source_manifest_sha256: str = Field(pattern=_SHA256)
    source_library_sha256: str = Field(pattern=_SHA256)
    output_manifest_sha256: str = Field(pattern=_SHA256)
    output_library_sha256: str = Field(pattern=_SHA256)
    cases: tuple[CounterfactualTemporalSafeCaseAudit, ...] = Field(min_length=2)
    selector_visible_contract: Literal["counterfactual-predecision-observables-v1"] = (
        TEMPORAL_SAFE_PRECEDENT_CONTRACT
    )
    objective_labels_preserved: Literal[True] = True
    terminal_metrics_quarantined: Literal[True] = True
    development_only: Literal[True] = True
    formal_confirmation_reuse_prohibited: Literal[True] = True
    audit_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def audit_is_closed(self) -> CounterfactualTemporalSafePrecedentAudit:
        validate_entry_id(self.audit_id, field_name="temporal-safe audit_id")
        validate_project_id(self.project_id)
        if self.cases != tuple(sorted(self.cases, key=lambda item: item.case_id)):
            raise ValueError("temporal-safe case audits must be case ordered")
        expected = content_sha256(self.model_dump(mode="json", exclude={"audit_sha256"}))
        if self.audit_sha256 != expected:
            raise ValueError("temporal-safe precedent audit hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualTemporalSafePrecedentAudit:
        payload = {
            "schema_version": "1.0",
            "selector_visible_contract": TEMPORAL_SAFE_PRECEDENT_CONTRACT,
            "objective_labels_preserved": True,
            "terminal_metrics_quarantined": True,
            "development_only": True,
            "formal_confirmation_reuse_prohibited": True,
            **values,
        }
        payload.pop("audit_sha256", None)
        unsigned = cls.model_construct(audit_sha256="0" * 64, **payload)
        return cls(
            **payload,
            audit_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"audit_sha256"})
            ),
        )


class CounterfactualTemporalSafeMergeSource(BaseModel):
    """Content identities of one temporal-safe library entering a merge."""

    model_config = _CONFIG

    audit_id: str
    audit_sha256: str = Field(pattern=_SHA256)
    manifest_id: str
    manifest_sha256: str = Field(pattern=_SHA256)
    library_sha256: str = Field(pattern=_SHA256)
    case_ids: tuple[str, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def source_is_canonical(self) -> CounterfactualTemporalSafeMergeSource:
        validate_entry_id(self.audit_id, field_name="temporal-safe merge source audit_id")
        validate_entry_id(self.manifest_id, field_name="temporal-safe merge source manifest_id")
        if self.case_ids != tuple(sorted(set(self.case_ids))):
            raise ValueError("temporal-safe merge source case IDs must be sorted and unique")
        return self


class CounterfactualTemporalSafeMergeReceipt(BaseModel):
    """Receipt for combining development precedents without changing target labels."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    merge_id: str
    project_id: str
    sources: tuple[CounterfactualTemporalSafeMergeSource, ...] = Field(min_length=2)
    output_manifest_id: str
    output_manifest_sha256: str = Field(pattern=_SHA256)
    output_library_sha256: str = Field(pattern=_SHA256)
    case_count: int = Field(ge=4)
    selector_visible_contract: Literal["counterfactual-predecision-observables-v1"] = (
        TEMPORAL_SAFE_PRECEDENT_CONTRACT
    )
    objective_labels_preserved: Literal[True] = True
    terminal_metrics_quarantined: Literal[True] = True
    development_only: Literal[True] = True
    target_population_unchanged_by_merge: Literal[True] = True
    formal_confirmation_reuse_prohibited: Literal[True] = True
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_closed(self) -> CounterfactualTemporalSafeMergeReceipt:
        validate_entry_id(self.merge_id, field_name="temporal-safe merge_id")
        validate_project_id(self.project_id)
        validate_entry_id(
            self.output_manifest_id,
            field_name="temporal-safe merge output_manifest_id",
        )
        if self.sources != tuple(sorted(self.sources, key=lambda item: item.manifest_id)):
            raise ValueError("temporal-safe merge sources must be manifest ordered")
        if len({item.manifest_id for item in self.sources}) != len(self.sources):
            raise ValueError("temporal-safe merge repeats a source manifest")
        if self.case_count != sum(len(item.case_ids) for item in self.sources):
            raise ValueError("temporal-safe merge case count differs from its sources")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("temporal-safe merge receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> CounterfactualTemporalSafeMergeReceipt:
        payload = {
            "schema_version": "1.0",
            "selector_visible_contract": TEMPORAL_SAFE_PRECEDENT_CONTRACT,
            "objective_labels_preserved": True,
            "terminal_metrics_quarantined": True,
            "development_only": True,
            "target_population_unchanged_by_merge": True,
            "formal_confirmation_reuse_prohibited": True,
            **values,
        }
        payload.pop("receipt_sha256", None)
        payload["sources"] = tuple(
            sorted(payload["sources"], key=lambda item: item.manifest_id)  # type: ignore[arg-type]
        )
        unsigned = cls.model_construct(receipt_sha256="0" * 64, **payload)
        return cls(
            **payload,
            receipt_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


def derive_temporal_safe_counterfactual_precedents(
    *,
    audit_id: str,
    manifest_id: str,
    precedent_root: str | Path,
    state_root: str | Path,
    output_root: str | Path,
) -> CounterfactualTemporalSafePrecedentAudit:
    """Publish a new library whose transfer fields use only prefix observables."""

    source_root = Path(precedent_root).resolve(strict=True)
    state_base = Path(state_root).resolve(strict=True)
    target = Path(output_root).expanduser()
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    source_manifest_path = source_root / "MANIFEST.json"
    source_library_path = source_root / "TASTE_LIBRARY.jsonl"
    source_manifest = CounterfactualTastePrecedentManifest.model_validate_json(
        source_manifest_path.read_bytes(), strict=True
    )
    source_library_sha256 = hashlib.sha256(source_library_path.read_bytes()).hexdigest()
    if source_library_sha256 != source_manifest.library_sha256:
        raise ValueError("source counterfactual precedent library hash mismatch")
    source_cases = {item.case_id: item for item in TasteLibrary(source_library_path).all()}
    if set(source_cases) != {item.case_id for item in source_manifest.bindings}:
        raise ValueError("source counterfactual precedent population differs")

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        safe_cases: list[TasteCase] = []
        case_audits: list[CounterfactualTemporalSafeCaseAudit] = []
        safe_bindings = []
        for binding in source_manifest.bindings:
            source_case = source_cases[binding.case_id]
            source_case_sha256 = content_sha256(source_case.model_dump(mode="json"))
            if source_case_sha256 != binding.taste_case_sha256:
                raise ValueError("source counterfactual precedent case hash mismatch")
            prefix = load_interactive_research_prefix(
                state_base / binding.study_id / "PREFIX.json"
            )
            if prefix.prefix_sha256 != binding.prefix_sha256:
                raise ValueError("temporal-safe source prefix hash mismatch")
            observable = counterfactual_predecision_state(prefix)
            safe_case = _temporal_safe_case(
                source_case,
                observable=observable,
                action_vocabulary=source_manifest.action_vocabulary,
                source_manifest_sha256=source_manifest.manifest_sha256,
            )
            safe_case_sha256 = content_sha256(safe_case.model_dump(mode="json"))
            selector_visible = _selector_visible_projection(safe_case)
            _reject_terminal_markers(selector_visible)
            safe_cases.append(safe_case)
            safe_bindings.append(
                binding.model_copy(update={"taste_case_sha256": safe_case_sha256})
            )
            case_audits.append(
                CounterfactualTemporalSafeCaseAudit(
                    case_id=binding.case_id,
                    study_id=binding.study_id,
                    source_case_sha256=source_case_sha256,
                    safe_case_sha256=safe_case_sha256,
                    prefix_sha256=prefix.prefix_sha256,
                    observable_state=observable,
                    selector_visible_sha256=content_sha256(selector_visible),
                )
            )

        library_path = staging / "TASTE_LIBRARY.jsonl"
        library = TasteLibrary(library_path)
        for case in sorted(safe_cases, key=lambda item: item.case_id):
            library.add(case)
        output_library_sha256 = hashlib.sha256(library_path.read_bytes()).hexdigest()
        output_manifest = CounterfactualTastePrecedentManifest.create(
            manifest_id=manifest_id,
            project_id=source_manifest.project_id,
            source_run_id=source_manifest.source_run_id,
            bindings=tuple(safe_bindings),
            action_vocabulary=source_manifest.action_vocabulary,
            library_sha256=output_library_sha256,
        )
        manifest_bytes = (output_manifest.model_dump_json(indent=2) + "\n").encode()
        _write_new(staging / "MANIFEST.json", manifest_bytes)
        audit = CounterfactualTemporalSafePrecedentAudit.create(
            audit_id=audit_id,
            project_id=source_manifest.project_id,
            source_manifest_sha256=source_manifest.manifest_sha256,
            source_library_sha256=source_library_sha256,
            output_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            output_library_sha256=output_library_sha256,
            cases=tuple(sorted(case_audits, key=lambda item: item.case_id)),
        )
        _write_new(
            staging / "TEMPORAL_SAFETY.json",
            (audit.model_dump_json(indent=2) + "\n").encode(),
        )
        staging.replace(target)
        return audit
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def merge_temporal_safe_counterfactual_precedents(
    *,
    merge_id: str,
    manifest_id: str,
    precedent_roots: tuple[str | Path, ...],
    output_root: str | Path,
) -> CounterfactualTemporalSafeMergeReceipt:
    """Merge verified temporal-safe development libraries into one source pool.

    This operation changes only the available precedent population. Callers must
    separately bind a frozen target manifest when preparing an evaluation so that
    adding precedents cannot silently add or remove evaluated states.
    """

    if len(precedent_roots) < 2:
        raise ValueError("temporal-safe merge requires at least two source roots")
    target = Path(output_root).expanduser()
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)

    project_id: str | None = None
    action_vocabulary: tuple[str, ...] | None = None
    all_bindings = []
    all_cases: dict[str, TasteCase] = {}
    sources: list[CounterfactualTemporalSafeMergeSource] = []
    for raw_root in precedent_roots:
        unresolved = Path(raw_root).expanduser()
        if unresolved.is_symlink() or not unresolved.is_dir():
            raise ValueError(f"temporal-safe source root must be a regular directory: {raw_root}")
        root = unresolved.resolve(strict=True)
        manifest_bytes = (root / "MANIFEST.json").read_bytes()
        library_bytes = (root / "TASTE_LIBRARY.jsonl").read_bytes()
        audit_bytes = (root / "TEMPORAL_SAFETY.json").read_bytes()
        manifest = CounterfactualTastePrecedentManifest.model_validate_json(
            manifest_bytes, strict=True
        )
        audit = CounterfactualTemporalSafePrecedentAudit.model_validate_json(
            audit_bytes, strict=True
        )
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        library_sha256 = hashlib.sha256(library_bytes).hexdigest()
        audit_sha256 = hashlib.sha256(audit_bytes).hexdigest()
        if (
            audit.project_id != manifest.project_id
            or audit.output_manifest_sha256 != manifest_sha256
            or audit.output_library_sha256 != library_sha256
            or manifest.library_sha256 != library_sha256
        ):
            raise ValueError("temporal-safe source hashes differ from its audit")
        if project_id is None:
            project_id = manifest.project_id
            action_vocabulary = manifest.action_vocabulary
        elif (
            manifest.project_id != project_id
            or manifest.action_vocabulary != action_vocabulary
        ):
            raise ValueError("temporal-safe sources differ in project or action vocabulary")
        cases = {item.case_id: item for item in TasteLibrary(root / "TASTE_LIBRARY.jsonl").all()}
        binding_ids = {item.case_id for item in manifest.bindings}
        audit_ids = {item.case_id for item in audit.cases}
        if set(cases) != binding_ids or binding_ids != audit_ids:
            raise ValueError("temporal-safe source populations differ across artifacts")
        duplicates = set(all_cases) & set(cases)
        if duplicates:
            raise ValueError(
                "temporal-safe merge repeats case IDs: " + ", ".join(sorted(duplicates))
            )
        for binding in manifest.bindings:
            if content_sha256(cases[binding.case_id].model_dump(mode="json")) != (
                binding.taste_case_sha256
            ):
                raise ValueError("temporal-safe source case hash differs from its binding")
        all_cases.update(cases)
        all_bindings.extend(manifest.bindings)
        sources.append(
            CounterfactualTemporalSafeMergeSource(
                audit_id=audit.audit_id,
                audit_sha256=audit_sha256,
                manifest_id=manifest.manifest_id,
                manifest_sha256=manifest_sha256,
                library_sha256=library_sha256,
                case_ids=tuple(sorted(cases)),
            )
        )

    assert project_id is not None
    assert action_vocabulary is not None
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        library_path = staging / "TASTE_LIBRARY.jsonl"
        library = TasteLibrary(library_path)
        for case in sorted(all_cases.values(), key=lambda item: item.case_id):
            library.add(case)
        output_library_sha256 = hashlib.sha256(library_path.read_bytes()).hexdigest()
        output_manifest = CounterfactualTastePrecedentManifest.create(
            manifest_id=manifest_id,
            project_id=project_id,
            source_run_id=merge_id,
            bindings=tuple(all_bindings),
            action_vocabulary=action_vocabulary,
            library_sha256=output_library_sha256,
        )
        manifest_bytes = (output_manifest.model_dump_json(indent=2) + "\n").encode()
        _write_new(staging / "MANIFEST.json", manifest_bytes)
        receipt = CounterfactualTemporalSafeMergeReceipt.create(
            merge_id=merge_id,
            project_id=project_id,
            sources=tuple(sources),
            output_manifest_id=manifest_id,
            output_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            output_library_sha256=output_library_sha256,
            case_count=len(all_cases),
        )
        _write_new(
            staging / "TEMPORAL_SAFE_MERGE.json",
            (receipt.model_dump_json(indent=2) + "\n").encode(),
        )
        staging.replace(target)
        return receipt
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def counterfactual_predecision_state(
    prefix: InteractiveResearchPrefix,
) -> CounterfactualPreDecisionState:
    latest = prefix.turns[-1].decision.proposal
    phase = "early" if prefix.turn_count <= 1 else ("late" if prefix.turn_count >= 3 else "middle")
    confidence_band = _unit_interval_band(latest.evidence_confidence)
    next_value_band = _unit_interval_band(latest.next_experiment_value)
    experiment_band = (
        "one-to-three"
        if prefix.experiment_count <= 3
        else ("four-to-eight" if prefix.experiment_count <= 8 else "nine-plus")
    )
    rationale = latest.rationale.strip()
    return CounterfactualPreDecisionState.create(
        turn_count=prefix.turn_count,
        trajectory_phase=phase,
        evidence_status=latest.evidence_status,
        evidence_confidence_band=confidence_band,
        next_experiment_value_band=next_value_band,
        observed_experiment_count_band=experiment_band,
        diagnostic_rationale=rationale,
        diagnostic_rationale_sha256=hashlib.sha256(rationale.encode()).hexdigest(),
        hard_predicates=(
            "stage=interactive-experiment",
            f"evidence_status={latest.evidence_status}",
        ),
        soft_descriptors=(
            f"trajectory_phase={phase}",
            f"evidence_confidence_band={confidence_band}",
            f"next_experiment_value_band={next_value_band}",
            f"observed_experiment_count_band={experiment_band}",
        ),
    )


def temporal_applicability_mismatches(
    source: CounterfactualPreDecisionState,
    target: CounterfactualPreDecisionState,
    *,
    preferred_action: str,
    available_actions: set[str],
) -> tuple[str, ...]:
    """Evaluate non-negotiable transfer predicates without model judgment."""

    mismatches: list[str] = []
    if source.stage != target.stage:
        mismatches.append(f"stage:{source.stage}!={target.stage}")
    if source.evidence_status != target.evidence_status:
        mismatches.append(
            f"evidence_status:{source.evidence_status}!={target.evidence_status}"
        )
    if preferred_action not in available_actions:
        mismatches.append(f"preferred_action_unavailable:{preferred_action}")
    return tuple(mismatches)


def _temporal_safe_case(
    source: TasteCase,
    *,
    observable: CounterfactualPreDecisionState,
    action_vocabulary: tuple[str, ...],
    source_manifest_sha256: str,
) -> TasteCase:
    rationale_excerpt = observable.diagnostic_rationale[:1_500]
    applicability = [
        f"decision-time stage equals {observable.stage}",
        f"decision-time evidence_status equals {observable.evidence_status}",
        (
            "the visible diagnostic rationale addresses the same unresolved scientific "
            f"dependency: {rationale_excerpt}"
        ),
        *[f"soft state descriptor is {item}" for item in observable.soft_descriptors],
    ]
    failure = [
        (
            "decision-time stage or evidence_status differs from the typed hard predicates "
            f"{', '.join(observable.hard_predicates)}"
        ),
        f"the preferred action {source.preferred_action} is unavailable in the current action set",
        "the visible diagnostic rationale concerns a different scientific dependency",
    ]
    provenance = [
        item.model_copy(
            update={
                "metadata": {
                    **item.metadata,
                    "selector_visible_contract": TEMPORAL_SAFE_PRECEDENT_CONTRACT,
                    "source_case_sha256": content_sha256(source.model_dump(mode="json")),
                    "source_manifest_sha256": source_manifest_sha256,
                    "predecision_observable_state_sha256": observable.state_sha256,
                    "terminal_metrics_quarantined": True,
                }
            }
        )
        for item in source.provenance
    ]
    return TasteCase(
        case_id=source.case_id,
        stage=observable.stage,
        context_summary=(
            f"At turn {observable.turn_count} ({observable.trajectory_phase}) of interactive "
            f"hidden-law discovery, evidence_status={observable.evidence_status}, "
            f"evidence_confidence_band={observable.evidence_confidence_band}, and "
            f"next_experiment_value_band={observable.next_experiment_value_band}. The visible "
            f"diagnostic rationale is: {rationale_excerpt}"
        ),
        problem_pattern=(
            "Choose the next scientific action from decision-time observations while requiring "
            "an exact stage and evidence-status match and treating diagnostic content as a soft "
            "transfer judgment."
        ),
        evidence_state=observable.model_dump_json(),
        reviewer_context=None,
        candidate_actions=list(action_vocabulary),
        preferred_action=source.preferred_action,
        rejected_actions=[
            action for action in action_vocabulary if action != source.preferred_action
        ],
        decision_principle=(
            f"Consider {source.preferred_action} only after deterministic hard-predicate checks "
            "pass; then assess whether the visible hypothesis and diagnostic rationale match."
        ),
        why_preferred=(
            f"The development supervision label for this pre-decision state identifies "
            f"{source.preferred_action}. Terminal metrics and resource measurements are omitted "
            "from every selector-visible field."
        ),
        applicability_conditions=applicability,
        failure_conditions=failure,
        counterfactual_probe=(
            "If evidence status or the unresolved scientific dependency changed while the action "
            f"menu stayed fixed, would {source.preferred_action} still be defensible?"
        ),
        taste_grounding_sha256=content_sha256(
            {
                "source_taste_grounding_sha256": source.taste_grounding_sha256,
                "observable_state_sha256": observable.state_sha256,
                "contract": TEMPORAL_SAFE_PRECEDENT_CONTRACT,
            }
        ),
        outcome_summary=None,
        provenance=provenance,
        confidence=0.5,
        domain_tags=list(source.domain_tags),
        label_basis="objective-counterfactual-development-temporal-safe",
        extractor_version="scitaste-counterfactual-predecision-v1",
        human_verified=False,
        retrieval_eligible=True,
        outcome_horizon=source.outcome_horizon,
        source_action_id=source.source_action_id,
    )


def _selector_visible_projection(case: TasteCase) -> dict[str, object]:
    return {
        "context_summary": case.context_summary,
        "problem_pattern": case.problem_pattern,
        "evidence_state": case.evidence_state,
        "candidate_actions": case.candidate_actions,
        "preferred_action": case.preferred_action,
        "rejected_actions": case.rejected_actions,
        "decision_principle": case.decision_principle,
        "why_preferred": case.why_preferred,
        "applicability_conditions": case.applicability_conditions,
        "failure_conditions": case.failure_conditions,
        "counterfactual_probe": case.counterfactual_probe,
    }


def _reject_terminal_markers(selector_visible: dict[str, object]) -> None:
    text = json.dumps(selector_visible, ensure_ascii=False, allow_nan=False).casefold()
    found = [marker for marker in _FORBIDDEN_SELECTOR_MARKERS if marker in text]
    if found:
        raise ValueError(
            "temporal-safe selector fields contain terminal markers: " + ", ".join(found)
        )


def _unit_interval_band(value: float) -> Literal["low", "medium", "high"]:
    if value < 1.0 / 3.0:
        return "low"
    if value < 2.0 / 3.0:
        return "medium"
    return "high"


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
    "TEMPORAL_SAFE_PRECEDENT_CONTRACT",
    "CounterfactualPreDecisionState",
    "CounterfactualTemporalSafeCaseAudit",
    "CounterfactualTemporalSafeMergeReceipt",
    "CounterfactualTemporalSafeMergeSource",
    "CounterfactualTemporalSafePrecedentAudit",
    "counterfactual_predecision_state",
    "derive_temporal_safe_counterfactual_precedents",
    "merge_temporal_safe_counterfactual_precedents",
    "temporal_applicability_mismatches",
]

"""Compile objective scientific-situation transfer into the canonical Taste packet.

The evaluator estimates which action has transferable objective value.  This
module is the policy boundary: it requires explicit source-to-target action
semantics and fact-grounded applicability before the estimate can influence the
research controller.  A missing or inconsistent binding produces a zero-effect
abstaining packet rather than an ungrounded recommendation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.scientific_situation_transfer import (
    ScientificSituation,
    ScientificSituationSourceCase,
    ScientificSituationTransferDecision,
    scientific_situation_similarity,
)
from scitaste.project.models import validate_entry_id
from scitaste.taste.deliberation import (
    TasteBoundarySupport,
    TasteCaseTransferAssessment,
    TasteControlPacket,
    TasteCounterfactualStatus,
    TasteDeliberationInput,
    TasteDeliberationProposal,
    TasteDeliberationRole,
    TasteTransferVerdict,
    build_taste_control_packet,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[A-Za-z0-9]+(?:[A-Za-z0-9._:-]*[A-Za-z0-9])?$"


class ScientificActionSemanticBinding(BaseModel):
    """One explicit mapping from a source action to the frozen target menu."""

    model_config = _CONFIG

    source_action_id: str = Field(min_length=1)
    target_action_id: str = Field(pattern=_ID)
    relation: Literal["aligned", "opposed"]


class ScientificSituationPrecedentBinding(BaseModel):
    """Fact and action binding required before one objective fork can intervene."""

    model_config = _CONFIG

    source_study_id: str
    target_taste_case_id: str = Field(pattern=_ID)
    applicability_supports: tuple[TasteBoundarySupport, ...] = Field(
        min_length=2,
        max_length=20,
    )
    action_semantics: tuple[ScientificActionSemanticBinding, ...] = Field(min_length=2)
    role: TasteDeliberationRole = TasteDeliberationRole.SUPPORT
    counterfactual_status: TasteCounterfactualStatus = TasteCounterfactualStatus.NOT_TRIGGERED
    relevance_confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    rationale: str = Field(min_length=1, max_length=8_000)

    @model_validator(mode="after")
    def identities_are_unique(self) -> ScientificSituationPrecedentBinding:
        validate_entry_id(
            self.source_study_id,
            field_name="scientific-situation precedent source_study_id",
        )
        source_ids = [item.source_action_id for item in self.action_semantics]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source action-semantic bindings must be unique")
        target_ids = [item.target_action_id for item in self.action_semantics]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("target action-semantic bindings must be one-to-one")
        if not any(item.relation == "aligned" for item in self.action_semantics):
            raise ValueError("a precedent binding must align at least one target action")
        return self


class ScientificSituationControlCompilation(BaseModel):
    """Closed bridge result preserving both the transfer and packet identities."""

    model_config = _CONFIG

    transfer_decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal: TasteDeliberationProposal
    packet: TasteControlPacket
    compilation_findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def findings_force_abstention(self) -> ScientificSituationControlCompilation:
        if bool(self.compilation_findings) != self.packet.abstained:
            raise ValueError("control-compilation findings must correspond to packet abstention")
        return self


def compile_scientific_situation_control_packet(
    *,
    target: ScientificSituation,
    sources: tuple[ScientificSituationSourceCase, ...],
    decision: ScientificSituationTransferDecision,
    input_data: TasteDeliberationInput,
    bindings: tuple[ScientificSituationPrecedentBinding, ...],
) -> ScientificSituationControlCompilation:
    """Compile one transfer decision into the controller's sole treatment type."""

    if decision.target_study_id != target.study_id:
        raise ValueError("transfer decision and target study IDs differ")
    if decision.target_situation_sha256 != target.situation_sha256:
        raise ValueError("transfer decision and target situation hashes differ")
    source_by_id = {item.study_id: item for item in sources}
    if len(source_by_id) != len(sources):
        raise ValueError("scientific-situation source study IDs must be unique")
    binding_by_case = {item.target_taste_case_id: item for item in bindings}
    if len(binding_by_case) != len(bindings):
        raise ValueError("scientific-situation bindings must target unique Taste cases")
    candidate_by_id = {item.case_id: item for item in input_data.candidates}
    action_ids = {item.action_id for item in input_data.current_actions}
    estimate_ids = {item.action_id for item in decision.estimates}
    findings: list[str] = []
    if estimate_ids and estimate_ids != action_ids:
        findings.append("transfer-action-menu-drift")

    best = decision.estimates[0] if decision.estimates else None
    contributing = set(best.contributing_case_ids) if best is not None else set()
    eligible_bindings: list[ScientificSituationPrecedentBinding] = []
    for binding in bindings:
        source = source_by_id.get(binding.source_study_id)
        candidate = candidate_by_id.get(binding.target_taste_case_id)
        if source is None:
            findings.append(f"unknown-source:{binding.source_study_id}")
            continue
        if candidate is None:
            findings.append(f"unknown-target-case:{binding.target_taste_case_id}")
            continue
        source_actions = {item.source_action_id for item in binding.action_semantics}
        target_actions = {item.target_action_id for item in binding.action_semantics}
        # The current estimator operates on the shared MetaAction ontology.  We
        # still record the mapping explicitly, but reject semantic remapping until
        # it is applied before value estimation rather than after selection.
        if any(item.source_action_id != item.target_action_id for item in binding.action_semantics):
            findings.append(f"post-selection-action-remap:{binding.source_study_id}")
            continue
        if source_actions != action_ids or target_actions != action_ids:
            findings.append(f"incomplete-action-semantics:{binding.source_study_id}")
            continue
        aligned = {
            item.target_action_id for item in binding.action_semantics if item.relation == "aligned"
        }
        opposed = {
            item.target_action_id for item in binding.action_semantics if item.relation == "opposed"
        }
        if aligned & opposed or aligned | opposed != action_ids:
            findings.append(f"non-partitioning-action-semantics:{binding.source_study_id}")
            continue
        if decision.selected_action is not None and decision.selected_action not in aligned:
            findings.append(f"selected-action-not-aligned:{binding.source_study_id}")
            continue
        if binding.source_study_id not in contributing:
            continue
        if source.task_cluster_id == target.task_cluster_id:
            findings.append(f"same-task-precedent:{binding.source_study_id}")
            continue
        eligible_bindings.append(binding)

    if decision.abstained:
        findings.extend(decision.abstention_reasons)
    elif not eligible_bindings:
        findings.append("no-grounded-contributing-precedent")
    elif (
        len({source_by_id[item.source_study_id].task_cluster_id for item in eligible_bindings}) < 2
    ):
        findings.append("insufficient-grounded-source-task-diversity")

    ranked_bindings = sorted(
        eligible_bindings,
        key=lambda item: (
            -scientific_situation_similarity(
                source_by_id[item.source_study_id].situation,
                target,
            ),
            -item.relevance_confidence,
            item.source_study_id,
        ),
    )[: input_data.maximum_selected_cases]
    selected_case_ids = (
        tuple(item.target_taste_case_id for item in ranked_bindings) if not findings else ()
    )
    selected = set(selected_case_ids)
    assessments: list[TasteCaseTransferAssessment] = []
    for candidate in input_data.candidates:
        binding = binding_by_case.get(candidate.case_id)
        if binding is None or candidate.case_id not in selected:
            assessments.append(
                TasteCaseTransferAssessment(
                    case_id=candidate.case_id,
                    verdict=TasteTransferVerdict.UNCERTAIN,
                    role=TasteDeliberationRole.BOUNDARY,
                    counterfactual_status=TasteCounterfactualStatus.UNKNOWN,
                    relevance_confidence=0.0,
                    rationale="Not admitted by the objective-transfer evidence gate.",
                )
            )
            continue
        aligned = tuple(
            sorted(
                item.target_action_id
                for item in binding.action_semantics
                if item.relation == "aligned"
            )
        )
        opposed = tuple(
            sorted(
                item.target_action_id
                for item in binding.action_semantics
                if item.relation == "opposed"
            )
        )
        assessments.append(
            TasteCaseTransferAssessment(
                case_id=candidate.case_id,
                verdict=TasteTransferVerdict.APPLICABLE,
                applicability_supports=binding.applicability_supports,
                aligned_current_action_ids=aligned,
                opposed_current_action_ids=opposed,
                role=binding.role,
                counterfactual_status=binding.counterfactual_status,
                relevance_confidence=binding.relevance_confidence,
                rationale=binding.rationale,
            )
        )
    unique_findings = tuple(sorted(set(findings)))
    proposal = TasteDeliberationProposal(
        decision_id=input_data.decision_id,
        assessments=tuple(assessments),
        selected_case_ids=selected_case_ids,
        recommended_action_id=(None if unique_findings else decision.selected_action),
        selection_rationale=(
            "Objective transfer abstained: " + ", ".join(unique_findings)
            if unique_findings
            else (
                "Objective scientific-situation transfer admitted grounded, cross-task "
                f"precedents under decision {decision.decision_sha256}."
            )
        ),
    )
    packet = build_taste_control_packet(input_data, proposal)
    return ScientificSituationControlCompilation(
        transfer_decision_sha256=decision.decision_sha256,
        proposal=proposal,
        packet=packet,
        compilation_findings=unique_findings,
    )


__all__ = [
    "ScientificActionSemanticBinding",
    "ScientificSituationControlCompilation",
    "ScientificSituationPrecedentBinding",
    "compile_scientific_situation_control_packet",
]

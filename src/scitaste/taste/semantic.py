"""Proposal-only model node for source-grounded Taste abstraction."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.model_nodes.nodes import ModelNode
from scitaste.model_nodes.runtime import (
    ModelNodeRegistration,
    ModelNodeRuntime,
    RuntimeBackendMode,
    RuntimeLedgerEntry,
    RuntimeOutcome,
)
from scitaste.project import ProjectRuntime
from scitaste.taste.deliberation import (
    TASTE_DELIBERATION_NODE,
    TasteDeliberationInput,
    TasteDeliberationProposal,
    VerifiedTasteDeliberation,
    validate_taste_deliberation,
)
from scitaste.taste.reference_mining import (
    REFERENCE_MINING_NODE,
    ReferenceMiningNeed,
    ReferenceMiningProposal,
    VerifiedReferenceMining,
    validate_reference_mining_proposal,
)
from scitaste.taste.reference_quality import (
    REFERENCE_QUALITY_NODE,
    ReferenceQualityInput,
    ReferenceQualityProposal,
    VerifiedReferenceQuality,
    validate_reference_quality,
)
from scitaste.taste.semantic_models import (
    GROUNDED_TASTE_ABSTRACTION_NODE,
    TASTE_ABSTRACTION_NODE,
    GroundedTasteCaseAbstraction,
    TasteAbstractionInput,
    TasteCaseAbstraction,
    validate_grounded_abstraction_against_projection,
)


class TasteAbstractionNode(ModelNode[TasteAbstractionInput, TasteCaseAbstraction]):
    """Abstract one decision precedent without granting corpus-admission authority."""

    node_name = TASTE_ABSTRACTION_NODE
    prompt_version = "taste-abstraction-v1"
    system_instruction = (
        "Extract one transferable scientific decision precedent from only the supplied source "
        "projection. Separate context, evidence state, alternatives, selected action, decision "
        "principle, rationale, and outcome. Preserve the controller-issued case identity and "
        "explicitly reject every non-selected candidate. If outcome information is withheld, "
        "return no outcome summary. Do not use or infer an experimental relation label, held-out "
        "task content, facts outside the source, citations, scores of a target system, or claims "
        "about SciTaste. This output is an untrusted proposal for independent human review: do "
        "not admit it to a library, retrieve it, call tools, execute actions, or train a model."
    )
    input_model = TasteAbstractionInput
    output_model = TasteCaseAbstraction

    def _proposal_rejections(
        self,
        proposal: TasteCaseAbstraction,
        *,
        input_data: TasteAbstractionInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        return _common_proposal_rejections(proposal, input_data=input_data, context=context)


class GroundedTasteAbstractionNode(ModelNode[TasteAbstractionInput, GroundedTasteCaseAbstraction]):
    """Distill a source-traceable principle with explicit transfer limits."""

    node_name = GROUNDED_TASTE_ABSTRACTION_NODE
    prompt_version = "grounded-taste-abstraction-v2"
    system_instruction = (
        "Distill one transferable scientific decision precedent from only the supplied canonical "
        "source projection. Return a closed decision with alternatives, selected action, "
        "rationale, and outcome only when available. Ground context, evidence, alternatives, "
        "choice, principle, and any outcome with exact, byte-for-byte verbatim excerpts and their "
        "projection-field names. Never cite request identity, controller context, metadata, or a "
        "field outside source_projection. A context grounding may use only a problem_context or "
        "source_metadata field; evidence_state only evidence or limitation; alternatives only "
        "alternative; choice only scientific_action; outcome only outcome. Do not add a second "
        "support to a target when its semantic role is incompatible. Preserve Unicode punctuation "
        "exactly in every verbatim_evidence string. The decision "
        "principle must contrastively synthesize at least two semantic source roles, including a "
        "scientific action and evidential, justificatory, limitation, or outcome support. State at "
        "least two applicability conditions, two failure conditions, a counterfactual probe that "
        "would change the action, and the source-specific details deliberately discarded during "
        "transfer. Preserve controller-issued identities internally but never expose source, "
        "candidate, relation, condition, or held-out-task identity in the abstraction. Do not use "
        "outside facts, admit memory, call tools, execute actions, or claim that SciTaste works. "
        "This is an untrusted proposal for independent review; a reviewer may be AI and must never "
        "be represented as human."
    )
    input_model = TasteAbstractionInput
    output_model = GroundedTasteCaseAbstraction

    def _normalize_proposal(
        self,
        proposal: GroundedTasteCaseAbstraction,
        *,
        input_data: TasteAbstractionInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> GroundedTasteCaseAbstraction:
        """Undo only redundant JSON quote escaping when it yields an exact source span."""

        del context, policy
        return _normalize_grounding_quote_escapes(proposal, input_data)

    def _proposal_rejections(
        self,
        proposal: GroundedTasteCaseAbstraction,
        *,
        input_data: TasteAbstractionInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        reasons = _common_proposal_rejections(
            proposal,
            input_data=input_data,
            context=context,
        )
        reasons.extend(validate_grounded_abstraction_against_projection(proposal, input_data))
        return sorted(set(reasons))


class TasteDeliberationNode(ModelNode[TasteDeliberationInput, TasteDeliberationProposal]):
    """Assess transfer before selecting a diverse set of decision precedents."""

    node_name = TASTE_DELIBERATION_NODE
    prompt_version = "taste-deliberation-v1"
    system_instruction = (
        "Select Scientific Taste precedents for the current research decision, not passages that "
        "merely share vocabulary. Assess every supplied case exactly once. Cite exact current "
        "decision-fact IDs for each satisfied applicability or triggered failure condition; never "
        "invent a condition, fact, case, or action. A selected case must satisfy at least two of "
        "its stated applicability conditions, trigger none of its stated failure conditions, and "
        "align to a current action. Preserve decision tension: when the applicable pool supports "
        "different actions, select source-disjoint precedents covering more than one action; when "
        "an applicable challenge or boundary case is available, do not return only supportive "
        "precedents. Source outcomes, held-out task content, relation labels, and external facts "
        "are unavailable and must not be inferred. The output is a proposal only: do not execute "
        "an action, admit memory, call tools, or claim effectiveness."
    )
    input_model = TasteDeliberationInput
    output_model = TasteDeliberationProposal

    def _proposal_rejections(
        self,
        proposal: TasteDeliberationProposal,
        *,
        input_data: TasteDeliberationInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        reasons = list(validate_taste_deliberation(input_data, proposal))
        if context.stage != input_data.stage:
            reasons.append("Taste deliberation context stage differs from the closed input")
        if context.state_snapshot_id != input_data.state_snapshot_id:
            reasons.append("Taste deliberation context state differs from the closed input")
        if context.candidate_actions != list(input_data.current_actions):
            reasons.append("Taste deliberation context actions differ from the closed input")
        if context.claim_ids or context.evidence_ids or context.section_ids or context.metadata:
            reasons.append("Taste deliberation context contains information outside the input")
        return sorted(set(reasons))


class ReferenceQualityNode(ModelNode[ReferenceQualityInput, ReferenceQualityProposal]):
    """Screen whether a prestige-blind source can teach transferable judgment."""

    node_name = REFERENCE_QUALITY_NODE
    prompt_version = "reference-quality-v1"
    system_instruction = (
        "Judge whether the supplied source projection can teach transferable scientific "
        "decision quality. Assess exactly five dimensions: evidential rigor, decision "
        "traceability, visible alternatives, visible failure boundaries, and transfer "
        "potential. Ground every assessment in exact verbatim excerpts and field names. "
        "Qualify only when every dimension is strong. Author identity, venue, citations, "
        "experimental relation labels, and downstream task outcomes are hidden; do not infer "
        "or reward prestige. A successful reported outcome alone is not evidence of decision "
        "quality. This is an untrusted proposal only: do not admit a source, abstract Taste, "
        "call tools, execute actions, or make effectiveness claims."
    )
    input_model = ReferenceQualityInput
    output_model = ReferenceQualityProposal

    def _proposal_rejections(
        self,
        proposal: ReferenceQualityProposal,
        *,
        input_data: ReferenceQualityInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        reasons = list(validate_reference_quality(input_data, proposal))
        if context.stage != input_data.decision_stage:
            reasons.append("reference-quality context stage differs from the closed input")
        if context.state_snapshot_id != input_data.source_projection_sha256:
            reasons.append("reference-quality context projection differs from the closed input")
        if context.evidence_ids != [input_data.source_id]:
            reasons.append("reference-quality context source differs from the closed input")
        if (
            context.claim_ids
            or context.section_ids
            or context.candidate_actions
            or context.metadata
        ):
            reasons.append("reference-quality context contains information outside the input")
        return sorted(set(reasons))


class ReferenceMiningNode(ModelNode[ReferenceMiningNeed, ReferenceMiningProposal]):
    """Propose contrastive search queries without executing search or judging quality."""

    node_name = REFERENCE_MINING_NODE
    prompt_version = "reference-mining-v2"
    system_instruction = (
        "Plan a bounded metadata search for references that may inform the supplied scientific "
        "decision. Cover exactly the declared query families and all required decision patterns, "
        "evidence roles, and domain facets. Search deliberately for alternatives, negative or "
        "null results, failure boundaries, replications, reappraisals, and cross-domain transfer, "
        "not only supportive or lexically similar work. Make every query_text a concise, directly "
        "executable bibliographic query within max_query_terms, containing at least the declared "
        "minimum number of metadata_relevance_anchor_terms; do not write narrative search "
        "instructions. Do not rank by venue, author, citation "
        "count, or reported success. The source body is unavailable. Every result remains an "
        "unqualified candidate. This proposal cannot call search tools, download or read content, "
        "qualify a reference, authorize resources, or execute a research action."
    )
    input_model = ReferenceMiningNeed
    output_model = ReferenceMiningProposal

    def _proposal_rejections(
        self,
        proposal: ReferenceMiningProposal,
        *,
        input_data: ReferenceMiningNeed,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        reasons = list(validate_reference_mining_proposal(input_data, proposal))
        if context.stage != input_data.stage.value:
            reasons.append("reference-mining context stage differs from the closed need")
        if context.state_snapshot_id != input_data.need_sha256:
            reasons.append("reference-mining context differs from the closed need")
        if context.evidence_ids != sorted(input_data.evidence_gap_ids):
            reasons.append("reference-mining context evidence gaps differ from the closed need")
        if (
            context.claim_ids
            or context.section_ids
            or context.candidate_actions
            or context.metadata
        ):
            reasons.append("reference-mining context contains information outside the need")
        return sorted(set(reasons))


def taste_node_types() -> dict[str, ModelNodeRegistration]:
    """Return the Scientific Taste extension understood by the durable runtime."""

    from scitaste.taste.ai_attribution import ai_attribution_node_types
    from scitaste.taste.family_review import family_review_node_types

    registrations = {
        REFERENCE_MINING_NODE: ModelNodeRegistration(
            ReferenceMiningNode,
            ReferenceMiningNeed,
            ReferenceMiningProposal,
        ),
        REFERENCE_QUALITY_NODE: ModelNodeRegistration(
            ReferenceQualityNode,
            ReferenceQualityInput,
            ReferenceQualityProposal,
        ),
        TASTE_ABSTRACTION_NODE: ModelNodeRegistration(
            TasteAbstractionNode,
            TasteAbstractionInput,
            TasteCaseAbstraction,
        ),
        GROUNDED_TASTE_ABSTRACTION_NODE: ModelNodeRegistration(
            GroundedTasteAbstractionNode,
            TasteAbstractionInput,
            GroundedTasteCaseAbstraction,
        ),
        TASTE_DELIBERATION_NODE: ModelNodeRegistration(
            TasteDeliberationNode,
            TasteDeliberationInput,
            TasteDeliberationProposal,
        ),
    }
    registrations.update(ai_attribution_node_types())
    registrations.update(family_review_node_types())
    return registrations


def is_verified_model_generation_entry(entry: RuntimeLedgerEntry) -> bool:
    """Accept actual remote or local generation, never fixtures or replay."""

    if entry.intent.backend_mode is RuntimeBackendMode.LIVE:
        return entry.intent.profile.live_execution_permitted
    if entry.intent.backend_mode is RuntimeBackendMode.LOCAL:
        return entry.intent.profile.local_execution_permitted
    return False


def taste_deliberation_from_ledger(
    ledger_entry: str | Path,
    *,
    evidence_root: str | Path,
) -> VerifiedTasteDeliberation:
    """Compile one accepted live selector proposal from its verified project ledger."""

    from scitaste.model_nodes.models import NodeResult, NodeResultStatus

    entry, resolved, raw = load_verified_taste_abstraction_ledger(
        ledger_entry,
        evidence_root=evidence_root,
    )
    if entry.intent.node_name != TASTE_DELIBERATION_NODE:
        raise ValueError("ledger entry is not a Taste deliberation invocation")
    if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
        raise ValueError("Taste deliberation ledger entry is not accepted")
    if not is_verified_model_generation_entry(entry):
        raise ValueError("decision-aware Taste selection requires a verified model invocation")
    input_data = TasteDeliberationInput.model_validate_json(
        json.dumps(entry.intent.node_input, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    result = NodeResult[TasteDeliberationProposal].model_validate_json(
        json.dumps(entry.result, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("Taste deliberation ledger result has no accepted proposal")
    return VerifiedTasteDeliberation(
        invocation_id=entry.intent.invocation_id,
        backend=result.response.backend,
        model=result.response.model,
        ledger_locator=resolved.relative_to(Path(evidence_root).resolve(strict=True)).as_posix(),
        ledger_sha256=hashlib.sha256(raw).hexdigest(),
        input=input_data,
        proposal=result.proposal,
    )


def reference_mining_from_ledger(
    ledger_entry: str | Path,
    *,
    evidence_root: str | Path,
) -> VerifiedReferenceMining:
    """Compile one accepted live query plan from its verified project ledger."""

    from scitaste.model_nodes.models import NodeResult, NodeResultStatus

    entry, resolved, raw = load_verified_taste_abstraction_ledger(
        ledger_entry,
        evidence_root=evidence_root,
    )
    if entry.intent.node_name != REFERENCE_MINING_NODE:
        raise ValueError("ledger entry is not a reference-mining invocation")
    if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
        raise ValueError("reference-mining ledger entry is not accepted")
    if not is_verified_model_generation_entry(entry):
        raise ValueError("reference mining requires a verified model query proposal")
    input_data = ReferenceMiningNeed.model_validate_json(
        json.dumps(entry.intent.node_input, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    result = NodeResult[ReferenceMiningProposal].model_validate_json(
        json.dumps(entry.result, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("reference-mining ledger result has no accepted proposal")
    return VerifiedReferenceMining(
        invocation_id=entry.intent.invocation_id,
        backend=result.response.backend,
        model=result.response.model,
        ledger_locator=resolved.relative_to(Path(evidence_root).resolve(strict=True)).as_posix(),
        ledger_sha256=hashlib.sha256(raw).hexdigest(),
        input=input_data,
        proposal=result.proposal,
    )


def reference_quality_from_ledger(
    ledger_entry: str | Path,
    *,
    evidence_root: str | Path,
) -> VerifiedReferenceQuality:
    """Compile an accepted live, prestige-blind quality proposal from its ledger."""

    from scitaste.model_nodes.models import NodeResult, NodeResultStatus

    entry, resolved, raw = load_verified_taste_abstraction_ledger(
        ledger_entry,
        evidence_root=evidence_root,
    )
    if entry.intent.node_name != REFERENCE_QUALITY_NODE:
        raise ValueError("ledger entry is not a reference-quality invocation")
    if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
        raise ValueError("reference-quality ledger entry is not accepted")
    if not is_verified_model_generation_entry(entry):
        raise ValueError("reference-quality screening requires a verified model invocation")
    input_data = ReferenceQualityInput.model_validate_json(
        json.dumps(entry.intent.node_input, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    result = NodeResult[ReferenceQualityProposal].model_validate_json(
        json.dumps(entry.result, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("reference-quality ledger result has no accepted proposal")
    return VerifiedReferenceQuality(
        invocation_id=entry.intent.invocation_id,
        backend=result.response.backend,
        model=result.response.model,
        ledger_locator=resolved.relative_to(Path(evidence_root).resolve(strict=True)).as_posix(),
        ledger_sha256=hashlib.sha256(raw).hexdigest(),
        input=input_data,
        proposal=result.proposal,
    )


def taste_abstraction_candidate_from_ledger(
    ledger_entry: str | Path,
    *,
    evidence_root: str | Path,
    author_id: str,
    derivation_method: str,
) -> Any:
    """Compile one accepted ledger proposal into an untrusted review candidate."""

    from scitaste.evaluation.taste_corpus_curation import (
        TasteAbstractionCandidate,
        TasteAbstractionOrigin,
    )
    from scitaste.evaluation.taste_corpus_pair import TasteCorpusFileBinding
    from scitaste.model_nodes.models import NodeResult, NodeResultStatus

    entry, resolved, raw = load_verified_taste_abstraction_ledger(
        ledger_entry,
        evidence_root=evidence_root,
    )
    if entry.intent.node_name not in {
        TASTE_ABSTRACTION_NODE,
        GROUNDED_TASTE_ABSTRACTION_NODE,
    }:
        raise ValueError("ledger entry is not a Taste abstraction invocation")
    if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
        raise ValueError("Taste abstraction ledger entry is not accepted")
    if not is_verified_model_generation_entry(entry):
        raise ValueError("model-assisted Taste abstraction requires a verified model invocation")
    node_input = TasteAbstractionInput.model_validate_json(
        json.dumps(entry.intent.node_input, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    output_type = (
        GroundedTasteCaseAbstraction
        if entry.intent.node_name == GROUNDED_TASTE_ABSTRACTION_NODE
        else TasteCaseAbstraction
    )
    result_type = NodeResult[output_type]
    result = result_type.model_validate_json(
        json.dumps(entry.result, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("Taste abstraction ledger result has no accepted proposal")
    return TasteAbstractionCandidate(
        candidate_id=node_input.candidate_id,
        source_id=node_input.source_id,
        author_id=author_id,
        origin=TasteAbstractionOrigin.MODEL_ASSISTED,
        derivation_method=derivation_method,
        abstraction=result.proposal,
        model_trace=TasteCorpusFileBinding(
            path=resolved.relative_to(Path(evidence_root).resolve(strict=True)).as_posix(),
            sha256=hashlib.sha256(raw).hexdigest(),
        ),
    )


def _common_proposal_rejections(
    proposal: TasteCaseAbstraction,
    *,
    input_data: TasteAbstractionInput,
    context: NodeContext,
) -> list[str]:
    reasons: list[str] = []
    if proposal.case_id != input_data.case_id:
        reasons.append("Taste abstraction changed the controller-issued case identity")
    if input_data.outcome_information_availability == "withheld":
        if proposal.outcome_summary is not None:
            reasons.append("Taste abstraction invented a withheld outcome")
    elif proposal.outcome_summary is None:
        reasons.append("Taste abstraction omitted an available source outcome")
    if (
        context.stage != input_data.stage
        or context.state_snapshot_id != input_data.source_projection_sha256
        or context.evidence_ids != [input_data.source_id]
    ):
        reasons.append("Taste abstraction context differs from its source projection")
    if context.claim_ids or context.section_ids or context.candidate_actions:
        reasons.append("Taste abstraction context contains out-of-scope research state")
    internal_ids = {input_data.source_id, input_data.candidate_id}
    visible = [
        proposal.context_summary,
        proposal.problem_pattern or "",
        proposal.evidence_state or "",
        proposal.reviewer_context or "",
        *proposal.candidate_actions,
        proposal.decision_principle,
        proposal.why_preferred,
        proposal.outcome_summary or "",
    ]
    if isinstance(proposal, GroundedTasteCaseAbstraction):
        visible.extend(proposal.transfer_boundary.applies_when)
        visible.extend(proposal.transfer_boundary.fails_when)
        visible.extend(proposal.transfer_boundary.deliberately_discarded_details)
        visible.append(proposal.transfer_boundary.counterfactual_probe)
    if any(identifier in text for identifier in internal_ids for text in visible):
        reasons.append("Taste abstraction leaked internal source or candidate identity")
    return sorted(set(reasons))


def _normalize_grounding_quote_escapes(
    proposal: GroundedTasteCaseAbstraction,
    input_data: TasteAbstractionInput,
) -> GroundedTasteCaseAbstraction:
    try:
        projection = json.loads(input_data.source_projection)
    except json.JSONDecodeError:
        return proposal
    fields = projection.get("fields") if isinstance(projection, dict) else None
    if not isinstance(fields, dict):
        return proposal
    visible: dict[str, str] = {}
    for name, record in fields.items():
        if not isinstance(name, str) or not isinstance(record, dict) or "value" not in record:
            continue
        value = record["value"]
        visible[name] = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        )
    changed = False
    grounding = []
    for claim in proposal.grounding:
        supports = []
        for support in claim.supports:
            evidence = support.verbatim_evidence
            source = visible.get(support.projection_field)
            normalized = evidence.replace('\\"', '"')
            if source is not None and evidence not in source and normalized in source:
                support = support.model_copy(update={"verbatim_evidence": normalized})
                changed = True
            supports.append(support)
        grounding.append(claim.model_copy(update={"supports": tuple(supports)}))
    return proposal.model_copy(update={"grounding": tuple(grounding)}) if changed else proposal


def load_verified_taste_abstraction_ledger(
    ledger_entry: str | Path,
    *,
    evidence_root: str | Path,
) -> tuple[RuntimeLedgerEntry, Path, bytes]:
    """Load one entry only after verifying its canonical project-owned ledger chain."""

    root = Path(evidence_root).resolve(strict=True)
    requested = Path(ledger_entry)
    candidate_path = requested if requested.is_absolute() else root / requested
    if candidate_path.is_symlink():
        raise ValueError("Taste abstraction ledger entry must not be a symlink")
    resolved = candidate_path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Taste abstraction ledger entry escapes the evidence root") from exc
    if not resolved.is_file() or not 1 <= resolved.stat().st_size <= 64 * 1_048_576:
        raise ValueError("Taste abstraction ledger entry must be a bounded regular file")
    raw = resolved.read_bytes()
    entry = RuntimeLedgerEntry.model_validate_json(raw, strict=True)
    expected = Path(
        "projects",
        entry.intent.project_id,
        "runs",
        entry.intent.run_id,
        "model_nodes",
        "ledger",
        f"{entry.index:08d}__{entry.intent.invocation_id}.json",
    )
    if relative != expected:
        raise ValueError("Taste abstraction trace is not its canonical project-owned ledger entry")
    from scitaste.model_nodes.registry import first_party_node_types

    verified = ModelNodeRuntime(
        ProjectRuntime(root),
        node_types=first_party_node_types(),
    ).entry(
        project_id=entry.intent.project_id,
        run_id=entry.intent.run_id,
        invocation_id=entry.intent.invocation_id,
    )
    if verified != entry:
        raise ValueError("Taste abstraction ledger entry differs from the verified chain")
    return entry, resolved, raw


def save_taste_abstraction_candidate(candidate: Any, path: str | Path) -> Path:
    """Atomically create one candidate file without replacing prior evidence."""

    from scitaste.evaluation.taste_corpus_curation import TasteAbstractionCandidate

    validated = TasteAbstractionCandidate.model_validate(candidate, strict=True)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    payload = (
        json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return output


__all__ = [
    "GROUNDED_TASTE_ABSTRACTION_NODE",
    "REFERENCE_MINING_NODE",
    "REFERENCE_QUALITY_NODE",
    "TASTE_ABSTRACTION_NODE",
    "TASTE_DELIBERATION_NODE",
    "GroundedTasteAbstractionNode",
    "GroundedTasteCaseAbstraction",
    "ReferenceMiningNeed",
    "ReferenceMiningNode",
    "ReferenceMiningProposal",
    "ReferenceQualityInput",
    "ReferenceQualityNode",
    "ReferenceQualityProposal",
    "TasteAbstractionInput",
    "TasteAbstractionNode",
    "TasteCaseAbstraction",
    "TasteDeliberationInput",
    "TasteDeliberationNode",
    "TasteDeliberationProposal",
    "VerifiedReferenceQuality",
    "is_verified_model_generation_entry",
    "load_verified_taste_abstraction_ledger",
    "reference_mining_from_ledger",
    "reference_quality_from_ledger",
    "save_taste_abstraction_candidate",
    "taste_abstraction_candidate_from_ledger",
    "taste_deliberation_from_ledger",
    "taste_node_types",
]

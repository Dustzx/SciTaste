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
from scitaste.taste.semantic_models import (
    TASTE_ABSTRACTION_NODE,
    TasteAbstractionInput,
    TasteCaseAbstraction,
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
        internal_ids = {
            input_data.source_id,
            input_data.candidate_id,
        }
        visible = (
            proposal.context_summary,
            proposal.problem_pattern or "",
            proposal.evidence_state or "",
            proposal.reviewer_context or "",
            *proposal.candidate_actions,
            proposal.decision_principle,
            proposal.why_preferred,
            proposal.outcome_summary or "",
        )
        if any(identifier in text for identifier in internal_ids for text in visible):
            reasons.append("Taste abstraction leaked internal source or candidate identity")
        return sorted(set(reasons))


def taste_node_types() -> dict[str, ModelNodeRegistration]:
    """Return the Scientific Taste extension understood by the durable runtime."""

    return {
        TASTE_ABSTRACTION_NODE: ModelNodeRegistration(
            TasteAbstractionNode,
            TasteAbstractionInput,
            TasteCaseAbstraction,
        )
    }


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
    if entry.intent.node_name != TASTE_ABSTRACTION_NODE:
        raise ValueError("ledger entry is not a Taste abstraction invocation")
    if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
        raise ValueError("Taste abstraction ledger entry is not accepted")
    if (
        entry.intent.backend_mode is not RuntimeBackendMode.LIVE
        or not entry.intent.profile.live_execution_permitted
    ):
        raise ValueError("model-assisted Taste abstraction requires a verified live invocation")
    node_input = TasteAbstractionInput.model_validate_json(
        json.dumps(entry.intent.node_input, ensure_ascii=False, allow_nan=False),
        strict=True,
    )
    result_type = NodeResult[TasteCaseAbstraction]
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
    "TASTE_ABSTRACTION_NODE",
    "TasteAbstractionInput",
    "TasteAbstractionNode",
    "TasteCaseAbstraction",
    "load_verified_taste_abstraction_ledger",
    "save_taste_abstraction_candidate",
    "taste_abstraction_candidate_from_ledger",
    "taste_node_types",
]

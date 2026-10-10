"""Bounded, evidence-grounded scientific reasoning, not a scientific truth oracle."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReasoningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvidenceAnchor(ReasoningModel):
    source_id: str = Field(min_length=1)
    quote: str = Field(min_length=8, max_length=2000)


class CompetingExplanation(ReasoningModel):
    hypothesis_id: str = Field(min_length=1)
    mechanism: str = Field(min_length=1, max_length=2000)
    falsification: str = Field(min_length=1, max_length=2000)
    applicability_boundary: str = Field(min_length=1, max_length=2000)


class ProbePrediction(ReasoningModel):
    hypothesis_id: str = Field(min_length=1)
    observable_prediction: str = Field(min_length=1, max_length=2000)


class OutcomeBranch(ReasoningModel):
    kind: Literal["diagnostic", "inconclusive"]
    observed_pattern: str = Field(min_length=1, max_length=2000)
    interpretation: str = Field(min_length=1, max_length=2000)
    next_question: str = Field(min_length=1, max_length=2000)
    next_action: Literal["continue", "discriminate", "reformulate", "expand", "stop"]
    action_rationale: str = Field(min_length=1, max_length=2000)


class DiscriminatingProbe(ReasoningModel):
    probe_id: str = Field(min_length=1)
    intervention: str = Field(min_length=1, max_length=2000)
    predictions: tuple[ProbePrediction, ...] = Field(min_length=2, max_length=6)
    controls_and_confounders: str = Field(min_length=1, max_length=2000)
    # Units remain separate; no addition of dollars, hours and experiment counts.
    cost_and_feasibility: str = Field(min_length=1, max_length=2000)
    decision_relevance: str = Field(min_length=1, max_length=2000)
    branches: tuple[OutcomeBranch, ...] = Field(min_length=2, max_length=4)


class HypothesisUpdate(ReasoningModel):
    hypothesis_id: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    disposition: Literal["strengthen", "weaken", "unresolved", "retire"]
    reasoning: str = Field(min_length=1, max_length=2000)
    remaining_uncertainty: str = Field(min_length=1, max_length=2000)


class ResearchReasoningFrame(ReasoningModel):
    schema_version: Literal["1.0"] = "1.0"
    question: str = Field(min_length=1, max_length=2000)
    explanatory_gap: str = Field(min_length=1, max_length=2000)
    scientific_importance: str = Field(min_length=1, max_length=2000)
    evidence: tuple[EvidenceAnchor, ...] = Field(default=(), max_length=12)
    explanations: tuple[CompetingExplanation, ...] = Field(min_length=2, max_length=6)
    probes: tuple[DiscriminatingProbe, ...] = Field(min_length=1, max_length=4)
    preferred_probe_id: str
    selection_reason: str = Field(min_length=1, max_length=3000)
    stopping_condition: str = Field(min_length=1, max_length=2000)
    # Conditional lookahead, never a claim to know an optimal path to a positive result.
    horizon: int = Field(default=2, ge=1, le=3)
    updates: tuple[HypothesisUpdate, ...] = Field(default=(), max_length=12)
    retired_hypothesis_ids: tuple[str, ...] = ()
    archived_evidence_ids: tuple[str, ...] = Field(default=(), max_length=12)
    revision_reason: str = Field(min_length=1, max_length=2000)
    taste_transfer: str = Field(min_length=1, max_length=2000)
    authority: Literal["model-proposed-reasoning"] = "model-proposed-reasoning"

    @model_validator(mode="after")
    def references_are_connected(self):
        if len(self.model_dump_json().encode()) > 24000:
            raise ValueError("Active scientific reasoning must stay within 24 KB")

        def unique(values):
            if len(values) != len(set(values)):
                raise ValueError("Reasoning identifiers must be unique")
            return set(values)

        hypotheses = unique([h.hypothesis_id for h in self.explanations])
        retired = unique(list(self.retired_hypothesis_ids))
        if hypotheses & retired:
            raise ValueError("Retired explanations cannot remain active")
        sources = {e.source_id for e in self.evidence}
        if sources & set(self.archived_evidence_ids):
            raise ValueError("Archived evidence cannot also be in the active frame")
        probes = unique([p.probe_id for p in self.probes])
        if self.preferred_probe_id not in probes:
            raise ValueError("Preferred probe must be declared")
        for probe in self.probes:
            predicted = unique([p.hypothesis_id for p in probe.predictions])
            if predicted - hypotheses:
                raise ValueError("Probe references an unknown explanation")
            if len({p.observable_prediction.casefold() for p in probe.predictions}) < 2:
                raise ValueError("Probe needs different observable predictions")
            if {branch.kind for branch in probe.branches} != {"diagnostic", "inconclusive"}:
                raise ValueError("Probe needs diagnostic and inconclusive continuations")
        unique([u.hypothesis_id for u in self.updates])
        for update in self.updates:
            if update.hypothesis_id not in hypotheses | retired:
                raise ValueError("Update references an unknown explanation")
            if set(update.evidence_ids) - sources:
                raise ValueError("Updates need quoted evidence anchors")
            if (update.disposition == "retire") != (update.hypothesis_id in retired):
                raise ValueError("Retirement needs an explicit matching update")
        if retired - {u.hypothesis_id for u in self.updates}:
            raise ValueError("Retirement cannot silently discard evidence or hypotheses")
        return self


REASONING_INSTRUCTION = (
    "Scientific reasoning: identify an important explanatory gap, not just a score target. "
    "Maintain 2-6 competing mechanisms with falsification and transfer boundaries. "
    "Propose 1-4 discriminating probes with different observable predictions, controls, "
    "cost/feasibility and conditional diagnostic AND inconclusive next steps. Explain why "
    "the preferred probe changes a consequential decision better than alternatives; look "
    "ahead at most three steps, do not claim a known shortest path or calibrated information "
    "gain. Cheap is not always informative. Negative results and justified stopping are valid. "
    "Use Taste to notice gaps, generate alternatives and design probes as well as rank actions; "
    "state applicability and uncertainty, never treat literature prestige as evidence. "
    "Quote supplied evidence exactly. Observation, interpretation and future prediction remain "
    "distinct. A tool failure is not a falsified scientific hypothesis. Preserve previous "
    "hypothesis identities; changed mechanisms receive new IDs and explicit evidence-bound "
    "retirement of old IDs. Unexpected positives, nulls and boundary cases may generate new "
    "questions, not only contradictions. Never silently remove an alternative or source. "
    "To keep the active frame bounded, archived_evidence_ids may explicitly reference old "
    "anchors omitted from this frame; explain why in revision_reason. Full past frames remain "
    "in the trajectory. Archival is not rejection of inconvenient evidence. "
    "A reasoning frame is model-proposed, not verified support, a confidence estimate, "
    "execution permission or admitted Taste."
)


def grounding_errors(frame, sources, previous=None):
    """Check observable provenance only; semantic validity still needs actual experiments."""
    errors = []
    for anchor in frame.evidence:
        if anchor.source_id not in sources or not any(
            anchor.quote in value for value in sources.get(anchor.source_id, ())
        ):
            errors.append(f"Reasoning evidence quote absent: {anchor.source_id}")
    if previous:
        old = {h.hypothesis_id: h for h in previous.explanations}
        new = {h.hypothesis_id: h for h in frame.explanations}
        missing = old.keys() - new.keys() - set(frame.retired_hypothesis_ids)
        if missing:
            errors.append("Reasoning silently drops competing explanations")
        if set(frame.retired_hypothesis_ids) - old.keys():
            errors.append("Reasoning retires an unknown previous explanation")
        if any(old[k] != new[k] for k in old.keys() & new.keys()):
            errors.append("Changed explanation requires a new identity")
        previous_sources = {(e.source_id, e.quote) for e in previous.evidence}
        current_sources = {(e.source_id, e.quote) for e in frame.evidence}
        archived = set(frame.archived_evidence_ids)
        if archived - {e.source_id for e in previous.evidence}:
            errors.append("Cannot archive an unknown previous source")
        if not {p for p in previous_sources if p[0] not in archived} <= current_sources:
            errors.append("Reasoning cannot silently discard prior evidence anchors")
    elif frame.retired_hypothesis_ids:
        errors.append("Retirement requires previous reasoning context")
    if previous is None and frame.archived_evidence_ids:
        errors.append("Evidence archival requires previous reasoning context")
    return errors


class ResearchReasoningUpdateRejected(ValueError):
    """An uncommitted model update needs correction, not weakened evidence rules."""


def validate_action_probe_references(state, proposals):
    """Reject unexecuted action metadata while a bounded model correction is possible.

    Operational actions may omit a probe. Claimed scientific probes must exist
    in the admitted prospective frame; this does not authorize tool execution.
    """
    frame = state.executor_context.get("research_reasoning", {}).get("frame")
    known = {probe["probe_id"] for probe in frame["probes"]} if frame else set()
    for proposal in proposals:
        probe = proposal.scientific_probe_id
        if probe is not None and probe not in known:
            raise ResearchReasoningUpdateRejected(
                f"Action references unknown scientific probe {probe!r}; "
                "declare it in the grounded active frame, or omit the optional "
                "probe identity for a purely operational action."
            )


def apply_research_reasoning(state, history, frame):
    """Persist grounded reasoning atomically before action selection; never relabel evidence."""
    if frame is None:
        return state
    previous_record = state.executor_context.get("research_reasoning")
    previous = (
        ResearchReasoningFrame.model_validate(previous_record["frame"]) if previous_record else None
    )
    if previous == frame:
        return state
    sources, bindings = {}, {}
    failed = (
        set(previous_record.get("non_scientific_failure_ids", [])) if previous_record else set()
    )
    # Previously grounded anchors survive bounded prompt/history projections and new runs.
    if previous:
        for anchor in previous.evidence:
            sources.setdefault(anchor.source_id, []).append(anchor.quote)
        bindings.update(previous_record.get("source_bindings", {}))
    for row in history:
        result = row["result"]
        key = result["result_id"]
        digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        if key in bindings and bindings[key] != digest:
            raise ValueError("Scientific reasoning source identity was reused")
        bindings[key] = digest
        sources[key] = [v for v in result.get("observations", []) if isinstance(v, str)]
        if isinstance(result.get("error"), str):
            sources[key].append(result["error"])
        if result["status"] != "SUCCEEDED":
            failed.add(key)
    errors = grounding_errors(frame, sources, previous)
    for update in frame.updates:
        if update.disposition != "unresolved" and set(update.evidence_ids) & failed:
            errors.append("Execution failure cannot establish scientific support or refutation")
    if previous is None and frame.updates and not frame.evidence:
        errors.append("Evidence updates require observed evidence")
    if errors:
        raise ResearchReasoningUpdateRejected("; ".join(errors))
    updated = state.model_copy(deep=True)
    updated.executor_context["research_reasoning"] = {
        "frame": frame.model_dump(mode="json"),
        "source_bindings": {e.source_id: bindings[e.source_id] for e in frame.evidence},
        "non_scientific_failure_ids": sorted(failed & {e.source_id for e in frame.evidence}),
        "scientific_quality_established": False,
        "execution_authorized": False,
    }
    updated.revision += 1
    return updated


def seed_research_reasoning(state, instructions, design_sha256):
    """Carry a bound plan into execution; resuming never overwrites evolved reasoning."""
    if state.executor_context.get("research_reasoning") or not instructions.get(
        "scientific_reasoning"
    ):
        return state
    frame = ResearchReasoningFrame.model_validate(instructions["scientific_reasoning"])
    payload = frame.model_dump(mode="json")
    # Planning evidence IDs are local aliases, not Native execution result IDs.
    mapping = {e.source_id: f"design:{design_sha256}:{e.source_id}" for e in frame.evidence}
    for anchor in payload["evidence"]:
        anchor["source_id"] = mapping[anchor["source_id"]]
    for update in payload["updates"]:
        update["evidence_ids"] = [mapping[k] for k in update["evidence_ids"]]
    frame = ResearchReasoningFrame.model_validate(payload)
    updated = state.model_copy(deep=True)
    updated.executor_context["research_reasoning"] = {
        "frame": frame.model_dump(mode="json"),
        "source_bindings": {e.source_id: design_sha256 for e in frame.evidence},
        "source_scope": "quoted planning context bound to immutable design, not new experiments",
        "non_scientific_failure_ids": [],
        "scientific_quality_established": False,
        "execution_authorized": False,
    }
    updated.revision += 1
    return updated

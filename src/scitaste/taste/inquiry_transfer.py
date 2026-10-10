"""Source-linked inquiry transfer without relaxing method-applicability gates.

An unknown premise can motivate a discriminating experiment; it cannot justify
copying a source method. This optional protocol shares the existing proposal call
and reasoning frame. It does not authorize execution or certify causal support.
"""

import copy
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evidence.research_reasoning import EvidenceAnchor, ResearchReasoningFrame

INQUIRY_CONTEXT = "reviewed-inquiry-v1"


def inquiry_retrieval_query(state):
    """Use the evolving question/gap, not only the initial project topic.

    These are provisional model descriptions, not verified transfer premises.
    Whole fields only: scientific context cannot silently truncate a condition.
    """
    frame = (state.executor_context.get("research_reasoning") or {}).get("frame") or {}
    parts = [state.research_direction]
    for key in ("question", "explanatory_gap"):
        value = frame.get(key)
        if isinstance(value, str) and value and len("\n".join([*parts, value]).encode()) <= 12000:
            parts.append(value)
    return "\n".join(parts)


class PremiseAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["applicability", "failure"]
    condition: str = Field(min_length=1, max_length=4000)
    status: Literal["observed", "contradicted", "unknown"]
    evidence: tuple[EvidenceAnchor, ...] = Field(default=(), max_length=4)
    interpretation: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def evidence_is_not_assumed(self):
        if (self.status == "unknown") == bool(self.evidence):
            raise ValueError("Unknown premises have no supporting evidence; judgments need anchors")
        return self


class InquiryTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["reviewed-inquiry-v1"] = INQUIRY_CONTEXT
    case_id: str = Field(min_length=1)
    complete_case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    premises: tuple[PremiseAssessment, ...] = Field(min_length=4, max_length=40)
    question: str = Field(min_length=1, max_length=2000)
    probe_id: str = Field(min_length=1)
    tested_conditions: tuple[str, ...] = Field(min_length=1, max_length=40)
    # Eligibility is a necessary condition, NOT an admitted recommendation.
    recipe_eligible: bool = False
    execution_authorized: Literal[False] = False
    authority: Literal["model-proposed-inquiry"] = "model-proposed-inquiry"

    @model_validator(mode="after")
    def bounded_active_transfer(self):
        if len(self.model_dump_json().encode()) > 16000:
            raise ValueError("Active inquiry transfer must stay within 16 KB")
        return self


def validate_inquiry_transfer(
    proposal: InquiryTransfer,
    *,
    context: dict,
    frame: ResearchReasoningFrame,
    sources: dict[str, tuple[str, ...]],
    failed_source_ids: frozenset[str] = frozenset(),
) -> InquiryTransfer:
    """Validate closed source scope and quotes, not the model's semantic judgment."""
    if context.get("version") not in {"reviewed-conditional-v1", INQUIRY_CONTEXT} or (
        context.get("execution_authorized") is not False
        or context.get("applicability_established") is not False
    ):
        raise ValueError("Inquiry requires a non-authoritative reviewed source context")
    cases = [case for case in context["cases"] if case["case_id"] == proposal.case_id]
    if len(cases) != 1 or cases[0]["complete_case_sha256"] != proposal.complete_case_sha256:
        raise ValueError("Inquiry must bind one exact visible source case")
    case = cases[0]
    expected = {
        (kind, text)
        for kind, key in (
            ("applicability", "applicability_conditions"),
            ("failure", "failure_conditions"),
        )
        for text in case[key]
    }
    assessed = [(item.kind, item.condition) for item in proposal.premises]
    if len(assessed) != len(set(assessed)) or set(assessed) != expected:
        raise ValueError("Inquiry must assess every exact source premise without cherry-picking")
    for item in proposal.premises:
        for anchor in item.evidence:
            if anchor.source_id in failed_source_ids:
                raise ValueError("Tool failure cannot establish a transfer premise")
            if not any(anchor.quote in text for text in sources.get(anchor.source_id, ())):
                raise ValueError("Inquiry judgment quote is absent from current evidence")
    unresolved = {
        item.condition
        for item in proposal.premises
        if (item.kind == "applicability" and item.status != "observed")
        or (item.kind == "failure" and item.status != "contradicted")
    }
    if len(set(proposal.tested_conditions)) != len(proposal.tested_conditions):
        raise ValueError("Inquiry tested conditions must be unique")
    if not set(proposal.tested_conditions) <= {text for _, text in expected}:
        raise ValueError("Inquiry probe must name visible source conditions")
    if unresolved and not set(proposal.tested_conditions) & unresolved:
        raise ValueError("Inquiry must address a blocking or unknown transfer premise")
    if proposal.recipe_eligible and unresolved:
        raise ValueError("Unknown or adverse premises cannot establish recipe eligibility")
    if proposal.probe_id not in {probe.probe_id for probe in frame.probes}:
        raise ValueError("Inquiry must bind a declared discriminating probe")
    if proposal.question != frame.question:
        raise ValueError("Inquiry must describe the active scientific question")
    return proposal


def inquiry_context(context: dict, *, max_bytes: int = 12000) -> dict:
    """Opt-in projection; legacy context and source cases remain byte-for-byte intact."""
    if context.get("version") != "reviewed-conditional-v1":
        raise ValueError("Inquiry requires the reviewed conditional-source projection")
    if (
        context.get("execution_authorized") is not False
        or context.get("applicability_established") is not False
    ):
        raise ValueError("Inquiry cannot inherit claimed applicability or execution authority")
    value = {
        **copy.deepcopy(context),
        "version": INQUIRY_CONTEXT,
        "inquiry_protocol": (
            "Distinguish a useful question from eligibility to apply a source recipe. "
            "Assess every visible applicability/failure premise as observed, contradicted "
            "or unknown. Only exact current observations may support judgments; literature "
            "results and source prestige are not current-task evidence. An unknown or adverse "
            "premise may motivate a declared discriminating probe with competing predictions, "
            "not a recipe recommendation. Bind the source case and an existing scientific "
            "reasoning probe; test a blocking premise. Compare its decision relevance and "
            "cost with alternatives in the existing reasoning frame. Recipe eligibility "
            "requires all applicability premises observed and all failure premises "
            "contradicted, and still needs the separate action-applicability gate. Abstain "
            "if no consequential probe follows. Keep the active transfer within 16 KB. "
            "Never manufacture evidence to avoid abstention."
        ),
    }
    # Drop complete candidate cases only; never truncate a transfer premise.
    # Case omission is visible and does not imply that a source was inapplicable.
    while len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) > max_bytes:
        if not value["cases"]:
            raise ValueError("Inquiry context budget cannot preserve its interpretation boundary")
        removed = value["cases"].pop()
        value.setdefault("omitted_case_ids", []).append(removed["case_id"])
        value["omitted_case_count"] = value.get("omitted_case_count", 0) + 1
    return value


def validate_workspace_inquiry(proposal, *, context, state, history, reasoning=None):
    """Bind an optional proposal to committed observations, never arbitrary text.

    The existing reasoning admission must validate a newly proposed frame first.
    Prior bound anchors survive context compaction, while failed/pending tools
    remain inadmissible as evidence that a scientific transfer premise holds.
    """
    record = state.executor_context.get("research_reasoning") or {}
    previous = ResearchReasoningFrame.model_validate(record["frame"]) if record else None
    frame = reasoning if reasoning is not None else previous
    if frame is None:
        raise ValueError("Inquiry requires an active scientific reasoning frame")
    sources = {}
    bindings = dict(record.get("source_bindings", {}))
    failed = set(record.get("non_scientific_failure_ids", ()))
    if previous:
        for anchor in previous.evidence:
            sources.setdefault(anchor.source_id, []).append(anchor.quote)
    for row in history:
        result = row["result"]
        identity = result["result_id"]
        digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        if identity in bindings and bindings[identity] != digest:
            raise ValueError("Scientific inquiry source identity was reused")
        bindings[identity] = digest
        if result["status"] != "SUCCEEDED":
            failed.add(identity)
        sources[identity] = tuple(
            observation
            for observation in result.get("observations", ())
            if isinstance(observation, str)
        )
    return validate_inquiry_transfer(
        proposal,
        context=context,
        frame=frame,
        sources=sources,
        failed_source_ids=frozenset(failed),
    )

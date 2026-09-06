"""Bounded semantic proposals for native Discovery hypothesis formation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from pydantic import JsonValue

from scitaste.discovery.semantic_models import (
    DEFAULT_PROBE_TYPES,
    DISCOVERY_HYPOTHESIS_NODE,
    DiscoveryHypothesisInput,
    DiscoveryHypothesisProposal,
    DiscoveryIntuitionProposal,
    DiscoverySemanticReference,
)
from scitaste.model_nodes.backends import StructuredModelBackend
from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.model_nodes.nodes import ModelNode
from scitaste.model_nodes.profiles import ModelNodeProfile, validate_profile_binding
from scitaste.model_nodes.runtime import (
    ModelNodeRegistration,
    RuntimeBackendMode,
    RuntimeInvocationReceipt,
    RuntimeOutcome,
)


class DiscoveryHypothesisNode(
    ModelNode[DiscoveryHypothesisInput, DiscoveryHypothesisProposal]
):
    """Propose grounded semantics while leaving all actions to SciTaste policy."""

    node_name = DISCOVERY_HYPOTHESIS_NODE
    prompt_version = "discovery-hypothesis-v1"
    system_instruction = (
        "Synthesize one research intuition and one falsifiable working hypothesis from only "
        "the supplied literature findings. Cite only supplied source identifiers and choose "
        "only permitted probe types. Include plausible alternatives and the main uncertainty. "
        "Return data only: do not select or execute actions, call tools, change state, assign "
        "budgets, claim experimental support, or invent evidence identifiers."
    )
    input_model = DiscoveryHypothesisInput
    output_model = DiscoveryHypothesisProposal

    def _proposal_rejections(
        self,
        proposal: DiscoveryHypothesisProposal,
        *,
        input_data: DiscoveryHypothesisInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        reasons: list[str] = []
        supplied_sources = set(input_data.source_ids)
        cited_sources = set(proposal.intuition.supporting_source_ids)
        if cited_sources - supplied_sources:
            reasons.append("intuition references a source outside the supplied landscape")
        if set(context.evidence_ids) != supplied_sources:
            reasons.append("node context source scope differs from the supplied landscape")
        if set(proposal.hypothesis.proposed_probe_types) - set(input_data.permitted_probe_types):
            reasons.append("hypothesis proposes a probe type outside the deterministic allowlist")
        predictions = [
            item.strip().casefold()
            for item in proposal.hypothesis.falsifiable_predictions
        ]
        if len(predictions) != len(set(predictions)):
            reasons.append("falsifiable predictions must be distinct")
        if any(len(item) > 4_000 for item in proposal.hypothesis.falsifiable_predictions):
            reasons.append("falsifiable prediction exceeds the semantic content limit")
        if len(proposal.hypothesis.falsifiable_predictions) > 8:
            reasons.append("hypothesis exceeds the falsifiable prediction count limit")
        if len(proposal.hypothesis.proposed_probe_types) > 5:
            reasons.append("hypothesis exceeds the probe type count limit")
        return reasons


def discovery_node_types() -> dict[str, ModelNodeRegistration]:
    """Return a fresh extension catalog for runtime construction and verification."""

    return {
        DISCOVERY_HYPOTHESIS_NODE: ModelNodeRegistration(
            DiscoveryHypothesisNode,
            DiscoveryHypothesisInput,
            DiscoveryHypothesisProposal,
        )
    }


@dataclass(frozen=True)
class DiscoverySemanticBinding:
    """Explicit backend and policy authority supplied by an application boundary."""

    backend: StructuredModelBackend | None
    profile: ModelNodeProfile
    policy: NodePolicy
    backend_mode: RuntimeBackendMode
    allow_live: bool = False
    request_id: str | None = None
    replay_source_invocation_id: str | None = None

    def __post_init__(self) -> None:
        validate_profile_binding(
            self.profile,
            self.policy,
            node_name=DISCOVERY_HYPOTHESIS_NODE,
        )
        if (
            self.policy.allowed_action_types
            or self.policy.allowed_tool_names
            or self.profile.admission.allowed_tool_names
            or self.profile.admission.max_tool_call_proposals
        ):
            raise ValueError("discovery semantics cannot receive action or tool authority")
        if self.backend_mode is RuntimeBackendMode.REPLAY:
            if self.backend is not None or self.replay_source_invocation_id is None:
                raise ValueError("semantic replay requires only a replay source invocation")
        elif self.backend is None:
            raise ValueError("scripted/live semantic generation requires a backend")
        if self.backend is not None and (self.backend.name, self.backend.model) != (
            self.policy.expected_backend,
            self.policy.expected_model,
        ):
            raise ValueError("semantic backend identity differs from its deterministic policy")
        if self.allow_live != (self.backend_mode is RuntimeBackendMode.LIVE):
            raise ValueError("semantic live authorization must match backend mode exactly")

    @property
    def fingerprint(self) -> str:
        raw_backend_config = (
            getattr(self.backend, "config", None) if self.backend is not None else None
        )
        backend_config = (
            raw_backend_config.model_dump(mode="json")
            if hasattr(raw_backend_config, "model_dump")
            else None
        )
        backend_identity = (
            None
            if self.backend is None
            else {"provider": self.backend.name, "model": self.backend.model}
        )
        payload = {
            "schema_version": "1.0",
            "node_name": DISCOVERY_HYPOTHESIS_NODE,
            "backend": backend_identity,
            "backend_config": backend_config,
            "profile": self.profile.model_dump(mode="json"),
            "policy": self.policy.model_dump(mode="json"),
            "backend_mode": self.backend_mode.value,
            "allow_live": self.allow_live,
            "request_id": self.request_id,
            "replay_source_invocation_id": self.replay_source_invocation_id,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


def semantic_reference_from_receipt(
    receipt: RuntimeInvocationReceipt,
    proposal: DiscoveryHypothesisProposal,
) -> DiscoverySemanticReference:
    if receipt.outcome is not RuntimeOutcome.ACCEPTED:
        raise ValueError("only an accepted semantic proposal can enter discovery state")
    if receipt.request_fingerprint is None or receipt.telemetry.cost_usd is None:
        raise ValueError("accepted semantic proposal lacks auditable identity or cost")
    payload: dict[str, JsonValue] = proposal.model_dump(mode="json")
    return DiscoverySemanticReference(
        invocation_id=receipt.invocation_id,
        ledger_entry_sha256=receipt.entry_sha256,
        request_fingerprint=receipt.request_fingerprint,
        proposal_sha256=_canonical_sha256(payload),
        recording_locator=receipt.recording_locator,
        input_tokens=receipt.telemetry.input_tokens,
        output_tokens=receipt.telemetry.output_tokens,
        cost_usd=receipt.telemetry.cost_usd,
        recovered_without_provider=receipt.recovered_without_provider,
    )


def semantic_proposal_from_receipt(
    receipt: RuntimeInvocationReceipt,
) -> DiscoveryHypothesisProposal:
    if receipt.outcome is not RuntimeOutcome.ACCEPTED or receipt.result is None:
        blockers = "; ".join(receipt.blockers) or receipt.outcome.value
        raise ValueError(f"discovery semantic proposal was not accepted: {blockers}")
    proposal = receipt.result.get("proposal")
    if not isinstance(proposal, dict):
        raise ValueError("accepted discovery semantic receipt has no typed proposal")
    return DiscoveryHypothesisProposal.model_validate_json(
        json.dumps(proposal, ensure_ascii=False, allow_nan=False),
        strict=True,
    )


def _canonical_sha256(payload: dict[str, JsonValue]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


__all__ = [
    "DEFAULT_PROBE_TYPES",
    "DISCOVERY_HYPOTHESIS_NODE",
    "DiscoveryHypothesisInput",
    "DiscoveryHypothesisNode",
    "DiscoveryHypothesisProposal",
    "DiscoveryIntuitionProposal",
    "DiscoverySemanticBinding",
    "DiscoverySemanticReference",
    "discovery_node_types",
    "semantic_proposal_from_receipt",
    "semantic_reference_from_receipt",
]

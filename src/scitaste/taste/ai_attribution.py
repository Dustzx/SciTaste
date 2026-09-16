"""Model-node bridge for evidence-bound, disclosed AI Taste attribution review."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.backends.local_transformers import LocalTransformersConfig
from scitaste.model_nodes.facade import ImmutableStateProjection
from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResult, NodeResultStatus
from scitaste.model_nodes.nodes import ModelNode
from scitaste.model_nodes.openai_compatible import StructuredOpenAICompatibleConfig
from scitaste.model_nodes.profiles import ModelNodeProfile, validate_profile_binding
from scitaste.model_nodes.runtime import (
    ModelNodeRegistration,
    ModelNodeRuntime,
    ModelNodeTrigger,
    RuntimeBackendMode,
    RuntimeOutcome,
)
from scitaste.model_nodes.runtime_config import (
    LiveRuntimeBackend,
    LocalRuntimeBackend,
    ModelNodeRuntimeConfig,
)
from scitaste.project import ProjectRuntime
from scitaste.project.idea_revision import ProjectIdeaRevisionBinding
from scitaste.project.models import content_sha256, validate_relative_locator
from scitaste.taste.episode_learning import (
    AITasteEpisodeAttributionReview,
    AITasteReviewArtifactBinding,
    AITasteReviewArtifactRole,
    AITasteReviewExecutionReceipt,
    AITasteReviewFirewallReport,
    AITasteReviewNormalizationReport,
    AITasteReviewPanelContract,
    TasteAttributionReviewRole,
    TasteAttributionReviewVerdict,
)
from scitaste.taste.episodes import (
    TasteCreditAssignment,
    TasteEpisodeAlternative,
    TasteEpisodeCandidate,
    TasteEpisodeConfounder,
    TasteEpisodeEvidenceRole,
    TasteEpisodeOutcome,
    inspect_taste_episode_candidate,
)

if TYPE_CHECKING:
    from scitaste.evaluation.evidence_review import EvidenceReviewInspection

AI_TASTE_ATTRIBUTION_REVIEW_NODE = "taste-episode-attribution-review"
_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_EVIDENCE_FILE_BYTES = 256 * 1024
_MAX_VISIBLE_EVIDENCE_BYTES = 768 * 1024
_ARTIFACT_FILENAMES = {
    AITasteReviewArtifactRole.REVIEW_PACKET: "REVIEW_PACKET.json",
    AITasteReviewArtifactRole.INPUT_PROJECTION: "INPUT_PROJECTION.json",
    AITasteReviewArtifactRole.RUBRIC: "RUBRIC.json",
    AITasteReviewArtifactRole.SYSTEM_PROMPT: "SYSTEM_PROMPT.txt",
    AITasteReviewArtifactRole.USER_PROMPT: "USER_PROMPT.json",
    AITasteReviewArtifactRole.RAW_RESPONSE: "RAW_RESPONSE.json",
    AITasteReviewArtifactRole.NORMALIZATION_REPORT: "NORMALIZATION_REPORT.json",
    AITasteReviewArtifactRole.EXECUTION_RECEIPT: "EXECUTION_RECEIPT.json",
    AITasteReviewArtifactRole.FIREWALL_REPORT: "FIREWALL_REPORT.json",
    AITasteReviewArtifactRole.SAMPLING_CONFIG: "SAMPLING_CONFIG.json",
}
_RUBRIC = {
    "schema_version": "1.0",
    "dimensions": (
        "decision_trace_supported",
        "outcome_trace_supported",
        "alternatives_supported",
        "credit_assignment_supported",
        "transfer_scope_supported",
        "reversal_probe_supported",
    ),
    "acceptance_rule": (
        "Accept only when every dimension is supported, one available action is preferred, "
        "and at least one attributable credit is supported."
    ),
    "reviewer_kind": "ai",
    "human_validity_claim_allowed": False,
}


class AITasteReviewSamplingConfig(BaseModel):
    """Provider-independent sampling intent shared by the review panel."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    seed: int = Field(ge=0)
    temperature: Literal[0] = 0
    response_format: Literal["json-object"] = "json-object"
    independent_context: Literal[True] = True


class AITasteReviewEvidenceProjection(BaseModel):
    """Exact UTF-8 evidence made visible to one isolated reviewer."""

    model_config = _CONFIG

    evidence_id: str
    role: TasteEpisodeEvidenceRole
    source_sha256: str = Field(pattern=_SHA256)
    content: str = Field(min_length=1, max_length=_MAX_EVIDENCE_FILE_BYTES)


class AITasteAttributionReviewInput(BaseModel):
    """Condition- and claim-blinded projection shared byte-for-byte across reviewers."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str
    candidate_sha256: str = Field(pattern=_SHA256)
    idea_revision_binding_sha256: str = Field(pattern=_SHA256)
    stage: str
    state_summary: str
    alternatives: tuple[TasteEpisodeAlternative, ...] = Field(min_length=2, max_length=30)
    selected_action_id: str
    decision_principle: str
    why_preferred: str
    outcomes: tuple[TasteEpisodeOutcome, ...] = Field(min_length=1, max_length=100)
    credit_assignments: tuple[TasteCreditAssignment, ...] = Field(min_length=1, max_length=100)
    applicability_conditions: tuple[str, ...] = Field(min_length=1, max_length=30)
    failure_conditions: tuple[str, ...] = Field(min_length=1, max_length=30)
    counterfactual_probe: str
    confounders: tuple[TasteEpisodeConfounder, ...] = Field(default=(), max_length=100)
    missing_evidence_questions: tuple[str, ...] = Field(default=(), max_length=30)
    evidence: tuple[AITasteReviewEvidenceProjection, ...] = Field(min_length=2, max_length=200)
    sampling: AITasteReviewSamplingConfig
    review_packet_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def packet_is_closed(self) -> AITasteAttributionReviewInput:
        if self.selected_action_id not in {item.action_id for item in self.alternatives}:
            raise ValueError("AI Taste review selected action is outside alternatives")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("AI Taste review evidence IDs must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"review_packet_sha256"}))
        if self.review_packet_sha256 != expected:
            raise ValueError("AI Taste review packet hash differs")
        return self

    @classmethod
    def create(cls, **values: object) -> AITasteAttributionReviewInput:
        payload = {"schema_version": "1.0", **values}
        payload.pop("review_packet_sha256", None)
        unsigned = cls.model_construct(review_packet_sha256="0" * 64, **payload)
        return cls(
            **payload,
            review_packet_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"review_packet_sha256"})
            ),
        )


class AITasteAttributionReviewProposal(BaseModel):
    """Untrusted scientific-credit judgment returned by one model."""

    model_config = _CONFIG

    review_packet_sha256: str = Field(pattern=_SHA256)
    verdict: TasteAttributionReviewVerdict
    # Keep both keys required in the provider-facing JSON Schema. Their values
    # may still be null/empty for a rejection, while the validator below
    # requires a concrete preference and credit assignment for acceptance.
    # Defaults made these fields disappear from ``required`` even though an
    # accepted response cannot be valid without them.
    preferred_action_id: str | None = Field(max_length=300)
    supported_credit_ids: tuple[str, ...] = Field(max_length=100)
    decision_trace_supported: bool
    outcome_trace_supported: bool
    alternatives_supported: bool
    credit_assignment_supported: bool
    transfer_scope_supported: bool
    reversal_probe_supported: bool
    attribution_confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def verdict_matches_dimensions(self) -> AITasteAttributionReviewProposal:
        dimensions = (
            self.decision_trace_supported,
            self.outcome_trace_supported,
            self.alternatives_supported,
            self.credit_assignment_supported,
            self.transfer_scope_supported,
            self.reversal_probe_supported,
        )
        if self.verdict is TasteAttributionReviewVerdict.ACCEPT:
            if not all(dimensions):
                raise ValueError("accepted AI Taste attribution requires every dimension")
            if self.preferred_action_id is None or not self.supported_credit_ids:
                raise ValueError("accepted AI Taste attribution requires preference and credit")
        elif all(dimensions):
            raise ValueError("rejected AI Taste attribution must identify a failed dimension")
        return self


class AITasteAttributionReviewMaterial(BaseModel):
    """Verified project projection from which one or more runtime configs are built."""

    model_config = _CONFIG

    project_id: str
    project_revision: int = Field(ge=0)
    node_input: AITasteAttributionReviewInput


class AITasteAttributionReviewNode(
    ModelNode[AITasteAttributionReviewInput, AITasteAttributionReviewProposal]
):
    """Review one frozen outcome attribution without seeing experiment-arm identity."""

    node_name = AI_TASTE_ATTRIBUTION_REVIEW_NODE
    prompt_version = "taste-episode-attribution-review-v1"
    system_instruction = (
        "Act as an isolated AI scientific-outcome attribution reviewer. Judge only the supplied "
        "decision-time state, alternatives, selected action, delayed outcomes, causal-credit "
        "proposal, transfer limits, counterfactual, and exact evidence. Do not infer an experiment "
        "condition, paper claim, author intent, prestige, another review, or information outside "
        "the packet. Accept only when every rubric dimension is supported; otherwise reject and "
        "mark at least one unsupported dimension. A successful outcome does not by itself prove "
        "good judgment. Select only an available action and only supplied credit IDs. This is AI "
        "review, not human or expert validation, and it cannot execute actions or update policy."
    )
    input_model = AITasteAttributionReviewInput
    output_model = AITasteAttributionReviewProposal

    def _proposal_rejections(
        self,
        proposal: AITasteAttributionReviewProposal,
        *,
        input_data: AITasteAttributionReviewInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> list[str]:
        del policy
        reasons: list[str] = []
        if proposal.review_packet_sha256 != input_data.review_packet_sha256:
            reasons.append("AI Taste attribution proposal targets another review packet")
        if proposal.preferred_action_id is not None and proposal.preferred_action_id not in {
            item.action_id for item in input_data.alternatives
        }:
            reasons.append("AI Taste attribution preferred an unavailable action")
        if set(proposal.supported_credit_ids) - {
            item.credit_id for item in input_data.credit_assignments
        }:
            reasons.append("AI Taste attribution cites an unavailable credit")
        if context.state_snapshot_id != input_data.review_packet_sha256:
            reasons.append("AI Taste attribution context targets another packet")
        if context.stage != "TASTE_ATTRIBUTION_REVIEW":
            reasons.append("AI Taste attribution context uses another lifecycle stage")
        if context.claim_ids or context.section_ids or context.candidate_actions:
            reasons.append("AI Taste attribution context exposes out-of-scope state")
        if context.evidence_ids != sorted(item.evidence_id for item in input_data.evidence):
            reasons.append("AI Taste attribution context evidence differs from the packet")
        return sorted(set(reasons))


def ai_attribution_node_types() -> dict[str, ModelNodeRegistration]:
    """Return the runtime registration for the AI attribution bridge."""

    return {
        AI_TASTE_ATTRIBUTION_REVIEW_NODE: ModelNodeRegistration(
            AITasteAttributionReviewNode,
            AITasteAttributionReviewInput,
            AITasteAttributionReviewProposal,
        )
    }


def build_ai_taste_attribution_review_material(
    runtime: ProjectRuntime,
    candidate: TasteEpisodeCandidate,
    *,
    evidence_root: str | Path,
    current_idea_revision: ProjectIdeaRevisionBinding,
    seed: int,
) -> AITasteAttributionReviewMaterial:
    """Build one shared, evidence-bearing review packet without invoking a model."""

    inspection = inspect_taste_episode_candidate(
        candidate,
        evidence_root=evidence_root,
        current_idea_revision=current_idea_revision,
    )
    if not inspection.ready_for_independent_review:
        codes = ", ".join(item.code for item in inspection.findings)
        raise ValueError(f"Taste episode is not ready for AI attribution review: {codes}")
    root = Path(evidence_root).resolve(strict=True)
    visible: list[AITasteReviewEvidenceProjection] = []
    visible_bytes = 0
    for binding in candidate.evidence:
        if binding.role is TasteEpisodeEvidenceRole.REVIEW:
            raise ValueError("AI Taste review input cannot contain another review")
        path = _bound_regular_file(root, binding.locator)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != binding.sha256:
            raise ValueError(f"Taste review evidence hash differs: {binding.locator}")
        if not 1 <= len(raw) <= _MAX_EVIDENCE_FILE_BYTES:
            raise ValueError(f"Taste review evidence exceeds the per-file limit: {binding.locator}")
        visible_bytes += len(raw)
        if visible_bytes > _MAX_VISIBLE_EVIDENCE_BYTES:
            raise ValueError("Taste review evidence exceeds the panel packet byte limit")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                "AI Taste review evidence must be an explicit UTF-8 projection"
            ) from exc
        visible.append(
            AITasteReviewEvidenceProjection(
                evidence_id=binding.evidence_id,
                role=binding.role,
                source_sha256=binding.sha256,
                content=content,
            )
        )
    snapshot = runtime.open(candidate.project_id)
    return AITasteAttributionReviewMaterial(
        project_id=candidate.project_id,
        project_revision=snapshot.revision,
        node_input=AITasteAttributionReviewInput.create(
            candidate_id=candidate.candidate_id,
            candidate_sha256=candidate.candidate_sha256,
            idea_revision_binding_sha256=candidate.idea_revision.binding_sha256,
            stage=candidate.stage,
            state_summary=candidate.state_summary,
            alternatives=candidate.alternatives,
            selected_action_id=candidate.selected_action_id,
            decision_principle=candidate.decision_principle,
            why_preferred=candidate.why_preferred,
            outcomes=candidate.outcomes,
            credit_assignments=candidate.credit_assignments,
            applicability_conditions=candidate.applicability_conditions,
            failure_conditions=candidate.failure_conditions,
            counterfactual_probe=candidate.counterfactual_probe,
            confounders=candidate.confounders,
            missing_evidence_questions=candidate.missing_evidence_questions,
            evidence=tuple(visible),
            sampling=AITasteReviewSamplingConfig(seed=seed),
        ),
    )


def build_ai_taste_attribution_runtime_config(
    material: AITasteAttributionReviewMaterial,
    *,
    profile: ModelNodeProfile,
    backend_config: StructuredOpenAICompatibleConfig | LocalTransformersConfig,
) -> ModelNodeRuntimeConfig:
    """Bind one panel member to a live or local model without embedding a credential."""

    if AI_TASTE_ATTRIBUTION_REVIEW_NODE not in profile.allowed_node_names:
        raise ValueError("selected model profile does not permit AI Taste attribution review")
    if isinstance(backend_config, StructuredOpenAICompatibleConfig):
        backend_identity = (backend_config.provider, backend_config.model)
        backend = LiveRuntimeBackend(config=backend_config)
    else:
        backend_identity = (backend_config.provider, backend_config.model_identity)
        backend = LocalRuntimeBackend(config=backend_config)
    if backend_identity != (profile.provider, profile.model):
        raise ValueError("AI Taste review backend identity differs from its profile")
    if backend_config.max_output_tokens < profile.generation.max_output_tokens:
        raise ValueError("AI Taste review backend output ceiling is below its profile")
    policy = NodePolicy(
        policy_id=f"{profile.profile_id}-policy-v1",
        enabled=True,
        allowed_node_names=[AI_TASTE_ATTRIBUTION_REVIEW_NODE],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_tool_names=[],
        allowed_action_types=[],
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    validate_profile_binding(
        profile,
        policy,
        node_name=AI_TASTE_ATTRIBUTION_REVIEW_NODE,
    )
    review_input = material.node_input
    return ModelNodeRuntimeConfig(
        node_name=AI_TASTE_ATTRIBUTION_REVIEW_NODE,
        node_input=review_input.model_dump(mode="json"),
        state_projection=ImmutableStateProjection(
            project_id=material.project_id,
            state_snapshot_id=review_input.review_packet_sha256,
            state_revision=material.project_revision,
            stage="TASTE_ATTRIBUTION_REVIEW",
            evidence_ids=tuple(sorted(item.evidence_id for item in review_input.evidence)),
            metadata={
                "candidate_sha256": review_input.candidate_sha256,
                "review_packet_sha256": review_input.review_packet_sha256,
                "condition_identity_exposed": False,
                "paper_claims_exposed": False,
            },
        ),
        trigger=ModelNodeTrigger(
            trigger_id=f"attribution-{review_input.candidate_id}",
            reason="Independent AI review of one frozen Taste outcome-attribution candidate.",
        ),
        policy=policy,
        backend=backend,
        seed=review_input.sampling.seed,
    )


def materialize_ai_taste_attribution_review(
    runtime: ProjectRuntime,
    candidate: TasteEpisodeCandidate,
    *,
    project_id: str,
    run_id: str,
    invocation_id: str,
    review_id: str,
    reviewer_id: str,
    role: TasteAttributionReviewRole,
    panel_contract: AITasteReviewPanelContract,
    evidence_root: str | Path,
    output_directory: str,
    producer_model_id: str | None = None,
    producer_run_id: str | None = None,
) -> tuple[AITasteEpisodeAttributionReview, Path]:
    """Convert one accepted real model-node ledger entry into ten bound artifacts."""

    if project_id != candidate.project_id:
        raise ValueError("AI Taste review project differs from the candidate")
    root = Path(evidence_root).resolve(strict=True)
    validate_relative_locator(output_directory, field_name="AI Taste review output directory")
    target = root / PurePosixPath(output_directory)
    target_parent = target.parent.resolve()
    target_parent.relative_to(root)
    target_parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    from scitaste.model_nodes.registry import first_party_node_types

    entry = ModelNodeRuntime(
        runtime,
        node_types=first_party_node_types(),
    ).entry(project_id=project_id, run_id=run_id, invocation_id=invocation_id)
    if entry.outcome is not RuntimeOutcome.ACCEPTED or entry.result is None:
        raise ValueError("AI Taste attribution import requires an accepted runtime entry")
    if entry.intent.backend_mode not in {RuntimeBackendMode.LIVE, RuntimeBackendMode.LOCAL}:
        raise ValueError("AI Taste attribution review requires an actual model generation")
    if entry.intent.node_name != AI_TASTE_ATTRIBUTION_REVIEW_NODE:
        raise ValueError("runtime entry is not an AI Taste attribution review")
    result = NodeResult[AITasteAttributionReviewProposal].model_validate(entry.result)
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("runtime entry has no accepted AI Taste attribution proposal")
    review_input = AITasteAttributionReviewInput.model_validate(entry.intent.node_input)
    if (
        review_input.candidate_id != candidate.candidate_id
        or review_input.candidate_sha256 != candidate.candidate_sha256
        or review_input.idea_revision_binding_sha256 != candidate.idea_revision.binding_sha256
    ):
        raise ValueError("AI Taste attribution runtime input binds another candidate")
    if result.proposal.review_packet_sha256 != review_input.review_packet_sha256:
        raise ValueError("AI Taste attribution proposal binds another review packet")
    if result.response.raw_response is None:
        raise ValueError("AI Taste attribution response did not retain its raw provider body")
    if result.response.usage.cost_usd is None:
        raise ValueError("AI Taste attribution response has no auditable API cost")

    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target_parent))
    try:
        artifact_bytes = _render_review_artifacts(review_input, result)
        for artifact_role, raw in artifact_bytes.items():
            _write_new(temporary / _ARTIFACT_FILENAMES[artifact_role], raw)
        artifact_hashes = {
            artifact_role: hashlib.sha256(raw).hexdigest()
            for artifact_role, raw in artifact_bytes.items()
        }
        prompt_sha256 = content_sha256(
            {
                artifact_role.value: artifact_hashes[artifact_role]
                for artifact_role in (
                    AITasteReviewArtifactRole.SYSTEM_PROMPT,
                    AITasteReviewArtifactRole.USER_PROMPT,
                )
            }
        )
        proposal_sha256 = content_sha256(result.proposal.model_dump(mode="json"))
        receipt = AITasteReviewExecutionReceipt.create(
            provider_id=result.response.backend,
            model_id=result.response.model,
            model_revision=result.response.model,
            run_id=entry.intent.invocation_id,
            prompt_sha256=prompt_sha256,
            input_projection_sha256=artifact_hashes[AITasteReviewArtifactRole.INPUT_PROJECTION],
            raw_response_sha256=artifact_hashes[AITasteReviewArtifactRole.RAW_RESPONSE],
            input_tokens=result.response.usage.input_tokens,
            output_tokens=result.response.usage.output_tokens,
            cost_usd=result.response.usage.cost_usd,
        )
        normalization = AITasteReviewNormalizationReport.create(
            run_id=entry.intent.invocation_id,
            candidate_sha256=candidate.candidate_sha256,
            raw_response_sha256=artifact_hashes[AITasteReviewArtifactRole.RAW_RESPONSE],
            normalized_response_sha256=proposal_sha256,
            schema_valid=True,
            fuzzy_repair_applied=False,
        )
        firewall = AITasteReviewFirewallReport.create(
            review_packet_sha256=artifact_hashes[AITasteReviewArtifactRole.REVIEW_PACKET],
            input_projection_sha256=artifact_hashes[AITasteReviewArtifactRole.INPUT_PROJECTION],
            condition_identity_exposed=False,
            paper_claims_exposed=False,
            out_of_window_outcomes_exposed=False,
            other_review_exposed=False,
            producer_response_exposed=False,
        )
        generated = {
            AITasteReviewArtifactRole.EXECUTION_RECEIPT: _json_bytes(
                receipt.model_dump(mode="json")
            ),
            AITasteReviewArtifactRole.NORMALIZATION_REPORT: _json_bytes(
                normalization.model_dump(mode="json")
            ),
            AITasteReviewArtifactRole.FIREWALL_REPORT: _json_bytes(
                firewall.model_dump(mode="json")
            ),
        }
        for artifact_role, raw in generated.items():
            _write_new(temporary / _ARTIFACT_FILENAMES[artifact_role], raw)
            artifact_hashes[artifact_role] = hashlib.sha256(raw).hexdigest()
        artifacts = tuple(
            AITasteReviewArtifactBinding(
                role=artifact_role,
                locator=(
                    PurePosixPath(output_directory) / _ARTIFACT_FILENAMES[artifact_role]
                ).as_posix(),
                sha256=artifact_hashes[artifact_role],
            )
            for artifact_role in AITasteReviewArtifactRole
        )
        proposal = result.proposal
        review = AITasteEpisodeAttributionReview(
            review_id=review_id,
            candidate_id=candidate.candidate_id,
            candidate_sha256=candidate.candidate_sha256,
            idea_revision_binding_sha256=candidate.idea_revision.binding_sha256,
            reviewer_id=reviewer_id,
            role=role,
            verdict=proposal.verdict,
            preferred_action_id=proposal.preferred_action_id,
            supported_credit_ids=proposal.supported_credit_ids,
            decision_trace_supported=proposal.decision_trace_supported,
            outcome_trace_supported=proposal.outcome_trace_supported,
            alternatives_supported=proposal.alternatives_supported,
            credit_assignment_supported=proposal.credit_assignment_supported,
            transfer_scope_supported=proposal.transfer_scope_supported,
            reversal_probe_supported=proposal.reversal_probe_supported,
            attribution_confidence=proposal.attribution_confidence,
            rationale=proposal.rationale,
            reviewed_at=entry.completed_at.astimezone(UTC),
            model_id=result.response.model,
            model_revision=result.response.model,
            provider_id=result.response.backend,
            prompt_sha256=prompt_sha256,
            normalized_response_sha256=proposal_sha256,
            run_id=entry.intent.invocation_id,
            producer_model_id=producer_model_id,
            producer_run_id=producer_run_id,
            panel_contract_sha256=panel_contract.contract_sha256,
            artifacts=artifacts,
        )
        _write_new(temporary / "REVIEW.json", _json_bytes(review.model_dump(mode="json")))
        os.replace(temporary, target)
        _fsync_directory(target_parent)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return review, target / "REVIEW.json"


def ai_review_authority_sha256(
    inspection: EvidenceReviewInspection,
    *,
    panel_contract: AITasteReviewPanelContract,
    workspace_root: str | Path,
) -> str:
    """Resolve panel authority from the central review package without a human gate."""

    package = inspection.package
    if package.ai_review_contract is None or package.ai_review_contract_sha256 is None:
        raise ValueError("evidence review package has no AI review authority")
    root = Path(workspace_root).resolve(strict=True)
    bound = _bound_regular_file(root, package.ai_review_contract.path)
    if hashlib.sha256(bound.read_bytes()).hexdigest() != package.ai_review_contract.file_sha256:
        raise ValueError("evidence review package AI contract file hash differs")
    if package.ai_review_contract_sha256 != panel_contract.contract_sha256:
        raise ValueError("evidence review package binds another AI panel contract")
    return package.ai_review_contract_sha256


def save_runtime_config(config: ModelNodeRuntimeConfig, path: str | Path) -> Path:
    """Persist a no-secret runtime config without replacing prior evidence."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_bytes(config.model_dump(mode="json", exclude_computed_fields=True))
    _write_new(target, payload)
    _fsync_directory(target.parent)
    return target


def save_ai_reviewed_episode_json(value: BaseModel, path: str | Path) -> Path:
    """Persist an admitted episode or other typed panel result immutably."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_new(target, _json_bytes(value.model_dump(mode="json")))
    _fsync_directory(target.parent)
    return target


def _render_review_artifacts(
    review_input: AITasteAttributionReviewInput,
    result: NodeResult[AITasteAttributionReviewProposal],
) -> dict[AITasteReviewArtifactRole, bytes]:
    input_projection = _json_bytes(review_input.model_dump(mode="json"))
    review_packet = _json_bytes(
        {
            "schema_version": "1.0",
            "input": review_input.model_dump(mode="json"),
            "rubric": _RUBRIC,
        }
    )
    user_prompt = _json_bytes(
        {
            "response_contract": (
                "Return exactly one JSON object that validates against output_schema."
            ),
            "input": review_input.model_dump(mode="json"),
            "output_schema": result.request.output_schema,
        }
    )
    return {
        AITasteReviewArtifactRole.REVIEW_PACKET: review_packet,
        AITasteReviewArtifactRole.INPUT_PROJECTION: input_projection,
        AITasteReviewArtifactRole.RUBRIC: _json_bytes(_RUBRIC),
        AITasteReviewArtifactRole.SYSTEM_PROMPT: (
            result.request.system_instruction + "\n"
        ).encode(),
        AITasteReviewArtifactRole.USER_PROMPT: user_prompt,
        AITasteReviewArtifactRole.RAW_RESPONSE: result.response.raw_response.encode(),
        AITasteReviewArtifactRole.SAMPLING_CONFIG: _json_bytes(
            review_input.sampling.model_dump(mode="json")
        ),
    }


def _bound_regular_file(root: Path, locator: str) -> Path:
    validate_relative_locator(locator, field_name="AI Taste review evidence")
    path = root / PurePosixPath(locator)
    if path.is_symlink():
        raise ValueError("AI Taste review evidence cannot be a symlink")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("AI Taste review evidence escapes its root") from exc
    if not resolved.is_file():
        raise ValueError("AI Taste review evidence must be a regular file")
    return resolved


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _write_new(path: Path, raw: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "AI_TASTE_ATTRIBUTION_REVIEW_NODE",
    "AITasteAttributionReviewInput",
    "AITasteAttributionReviewMaterial",
    "AITasteAttributionReviewNode",
    "AITasteAttributionReviewProposal",
    "AITasteReviewEvidenceProjection",
    "AITasteReviewSamplingConfig",
    "ai_attribution_node_types",
    "ai_review_authority_sha256",
    "build_ai_taste_attribution_review_material",
    "build_ai_taste_attribution_runtime_config",
    "materialize_ai_taste_attribution_review",
    "save_ai_reviewed_episode_json",
    "save_runtime_config",
]

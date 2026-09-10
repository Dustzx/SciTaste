"""Deterministic conversion of proposal-only model critique into a review report."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from scitaste.model_nodes.facade import ImmutableStateProjection
from scitaste.model_nodes.models import NodePolicy
from scitaste.model_nodes.openai_compatible import StructuredOpenAICompatibleConfig
from scitaste.model_nodes.profiles import ModelNodeProfile, validate_profile_binding
from scitaste.model_nodes.runtime import ModelNodeTrigger
from scitaste.model_nodes.runtime_config import LiveRuntimeBackend, ModelNodeRuntimeConfig
from scitaste.model_nodes.schemas import VenuePaperReviewInput, VenuePaperReviewProposal
from scitaste.project import ProjectRuntime
from scitaste.project.models import validate_relative_locator
from scitaste.review.parser import ReviewFeedback
from scitaste.review.routing import ReviewActionRouter
from scitaste.review.venue import (
    ReviewerIdentity,
    VenueCriterionAssessment,
    VenueReviewPacket,
    VenueReviewReport,
    load_venue_review_packet,
)
from scitaste.writing.argument import load_paper_argument_contract


class VenuePaperReviewMaterial(BaseModel):
    """Verified project projection used to construct a model-node runtime config."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    project_revision: int = Field(ge=0)
    review_id: str
    paper_locator: str
    node_input: VenuePaperReviewInput
    claim_ids: tuple[str, ...]
    section_ids: tuple[str, ...]


def build_venue_paper_review_material(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    review_id: str,
    paper_label: str = "source-markdown",
    permitted_evidence_types: tuple[str, ...] = (),
) -> VenuePaperReviewMaterial:
    """Read one exact registered text artifact; never invoke a model."""

    packet = load_venue_review_packet(runtime, project_id, review_id)
    snapshot = runtime.open(project_id)
    entry = next(
        (item for item in snapshot.papers if item.directory_name == packet.paper_directory),
        None,
    )
    if entry is None:
        raise ValueError("review packet paper is no longer registered")
    locator = entry.manifest.files.get(paper_label)
    if locator is None:
        raise ValueError(f"paper has no registered text artifact {paper_label!r}")
    paper_root = runtime.projects_root / project_id / "papers" / packet.paper_directory
    text_path = _contained_file(paper_root, locator)
    observed = hashlib.sha256(text_path.read_bytes()).hexdigest()
    expected = packet.paper_artifact_sha256.get(paper_label)
    if observed != expected:
        raise ValueError("registered model-review paper artifact differs from its packet")
    paper_bytes = text_path.read_bytes()
    try:
        paper_text = paper_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("model-review paper artifact must be UTF-8 text") from exc

    section_ids: tuple[str, ...] = ()
    contract_locator = entry.manifest.files.get("paper-argument-contract")
    if contract_locator is not None:
        contract = load_paper_argument_contract(_contained_file(paper_root, contract_locator))
        section_ids = tuple(sorted(item.section_id for item in contract.sections))
    node_input = VenuePaperReviewInput(
        packet_sha256=packet.packet_sha256,
        paper_text=paper_text,
        paper_text_sha256=observed,
        venue_id=packet.venue_id,
        registered_claim_ids=packet.registered_claim_ids,
        permitted_evidence_types=tuple(sorted(set(permitted_evidence_types))),
    )
    return VenuePaperReviewMaterial(
        project_id=project_id,
        project_revision=snapshot.revision,
        review_id=review_id,
        paper_locator=f"papers/{packet.paper_directory}/{locator}",
        node_input=node_input,
        claim_ids=packet.registered_claim_ids,
        section_ids=section_ids,
    )


def build_internal_model_review_report(
    packet: VenueReviewPacket,
    proposal: VenuePaperReviewProposal,
    *,
    report_id: str,
    reviewer_id: str,
    provider: str,
    model: str,
) -> VenueReviewReport:
    """Bind model content to deterministic identity and hashes, never expert status."""

    if proposal.packet_sha256 != packet.packet_sha256:
        raise ValueError("model review proposal targets a different review packet")
    concerns = tuple(
        ReviewFeedback.model_validate(
            item.model_dump(mode="python", exclude={"proposed_action_type"})
        )
        for item in proposal.concerns
    )
    return VenueReviewReport.create(
        report_id=report_id,
        packet_sha256=packet.packet_sha256,
        review_scope=packet.review_scope,
        reviewer=ReviewerIdentity(
            reviewer_id=reviewer_id,
            reviewer_kind="internal_model",
            independent=False,
            conflict_status="unverified",
            provider=provider,
            model_name=model,
        ),
        summary=proposal.summary,
        strengths=proposal.strengths,
        weaknesses=proposal.weaknesses,
        criteria=tuple(
            VenueCriterionAssessment(
                criterion=item.criterion,
                assessment=item.assessment,
                rationale=item.rationale,
            )
            for item in proposal.criteria
        ),
        initial_recommendation=proposal.initial_recommendation,
        decision_reasons=proposal.decision_reasons,
        questions=proposal.questions,
        additional_feedback=proposal.additional_feedback,
        concerns=concerns,
        confidence=proposal.confidence,
        ethics_concern=proposal.ethics_concern,
        ethics_explanation=proposal.ethics_explanation,
        official_review=False,
    )


def build_venue_paper_review_runtime_config(
    material: VenuePaperReviewMaterial,
    *,
    profile: ModelNodeProfile,
    backend_config: StructuredOpenAICompatibleConfig,
    seed: int = 0,
) -> ModelNodeRuntimeConfig:
    """Build a no-secret, profile-bound invocation config without calling a model."""

    if "venue-paper-review" not in profile.allowed_node_names:
        raise ValueError("selected model profile does not permit venue-paper-review")
    if (backend_config.provider, backend_config.model) != (profile.provider, profile.model):
        raise ValueError("paper-review backend identity differs from its selected profile")
    if backend_config.max_output_tokens < profile.generation.max_output_tokens:
        raise ValueError("paper-review backend output ceiling is below its selected profile")
    allowed_actions = sorted(set(ReviewActionRouter.ROUTES.values()), key=lambda item: item.value)
    policy = NodePolicy(
        policy_id=f"{profile.profile_id}-policy-v1",
        enabled=True,
        allowed_node_names=["venue-paper-review"],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_tool_names=list(profile.admission.allowed_tool_names),
        allowed_action_types=allowed_actions,
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    validate_profile_binding(profile, policy, node_name="venue-paper-review")
    node_input = material.node_input.model_dump(mode="json")
    return ModelNodeRuntimeConfig(
        node_name="venue-paper-review",
        node_input=node_input,
        state_projection=ImmutableStateProjection(
            project_id=material.project_id,
            state_snapshot_id=material.node_input.packet_sha256,
            state_revision=material.project_revision,
            stage="REVIEW",
            claim_ids=material.claim_ids,
            section_ids=material.section_ids,
            metadata={
                "review_id": material.review_id,
                "review_packet_sha256": material.node_input.packet_sha256,
                "paper_text_sha256": material.node_input.paper_text_sha256,
                "paper_locator": material.paper_locator,
            },
        ),
        trigger=ModelNodeTrigger(
            trigger_id=f"review-{material.review_id}",
            reason="Internal whole-paper venue review of the exact registered manuscript.",
        ),
        policy=policy,
        backend=LiveRuntimeBackend(config=backend_config),
        seed=seed,
    )


def _contained_file(root: Path, locator: str) -> Path:
    validate_relative_locator(locator, field_name="model-review paper locator")
    canonical_root = root.resolve(strict=True)
    candidate = root / PurePosixPath(locator)
    if candidate.is_symlink():
        raise ValueError("model-review paper artifact cannot be a symlink")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(canonical_root)
    except ValueError as exc:
        raise ValueError("model-review paper artifact escapes its paper directory") from exc
    if not resolved.is_file():
        raise ValueError("model-review paper artifact must be a regular file")
    return resolved


__all__ = [
    "VenuePaperReviewMaterial",
    "build_internal_model_review_report",
    "build_venue_paper_review_material",
    "build_venue_paper_review_runtime_config",
]

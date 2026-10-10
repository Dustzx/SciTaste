"""Independent, outcome-hidden decision policies for development comparisons.

These are fixed-menu *decision* methods, not adaptations of complete research
agents. The caller owns split isolation and keeps scoring keys out of this module.
"""

from __future__ import annotations

from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from scitaste.evaluation.decision_method_comparison import (
    DecisionMethodRequest,
    DecisionMethodSubmission,
)
from scitaste.model_nodes.models import StructuredModelRequest, StructuredModelResponse
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True)
PolicyKind = Literal["direct", "reflection", "planning"]


class DecisionReflectionEpisode(BaseModel):
    """Prior observed outcome, supplied only from source-disjoint tasks."""

    model_config = _CONFIG

    source_task_cluster_id: str = Field(min_length=1)
    research_state: str = Field(min_length=1)
    action_taken: str = Field(min_length=1)
    observed_outcome: str = Field(min_length=1)


class DecisionPolicyReceipt(BaseModel):
    model_config = _CONFIG

    request_sha256: str
    stage: str
    model_request_fingerprint: str
    raw_response_sha256: str
    served_backend: str
    served_model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class DecisionPolicyRun(BaseModel):
    model_config = _CONFIG

    method_id: str
    method_manifest_sha256: str
    submissions: tuple[DecisionMethodSubmission, ...]
    receipts: tuple[DecisionPolicyReceipt, ...]


class DecisionModelBackend(Protocol):
    name: str
    model: str

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse: ...


def run_decision_policy(
    requests: tuple[DecisionMethodRequest, ...],
    *,
    method_id: str,
    policy_kind: PolicyKind,
    backend: DecisionModelBackend,
    backend_manifest_sha256: str,
    reflection_episodes: tuple[DecisionReflectionEpisode, ...] = (),
    target_task_cluster_ids: frozenset[str] | None = None,
) -> DecisionPolicyRun:
    """Run one frozen policy over development requests, retaining failed rows.

    Reflection refuses shared source-task groups. Planning elicits an
    explicit per-action estimate before a separate final decision. Usage is
    reported from provider receipts; an unknown or failed call never becomes
    a fabricated zero-cost observation.
    """

    if not requests or len({item.request_sha256 for item in requests}) != len(requests):
        raise ValueError("decision requests must be nonempty and unique")
    has_artifacts = any(item.evidence_artifacts for item in requests)
    if has_artifacts and not getattr(backend, "supports_evidence_artifacts", False):
        raise ValueError("text-only decision baselines cannot consume visual artifacts")
    if policy_kind == "reflection":
        if not reflection_episodes or target_task_cluster_ids is None:
            raise ValueError("reflection requires prior episodes and target cluster IDs")
        source_ids = {item.source_task_cluster_id for item in reflection_episodes}
        if source_ids & target_task_cluster_ids:
            raise ValueError("reflection memory overlaps target source-task groups")
    elif reflection_episodes:
        raise ValueError("only reflection may receive prior outcome episodes")
    manifest_sha256 = content_sha256(
        {
            "method_id": method_id,
            "policy_kind": policy_kind,
            "prompt_version": "decision-baselines-v1",
            "backend_manifest_sha256": backend_manifest_sha256,
            "reflection_episodes": [item.model_dump(mode="json") for item in reflection_episodes],
            **(
                {"evidence_transport": getattr(backend, "evidence_transport_manifest", None)}
                if has_artifacts
                else {}
            ),
        }
    )
    submissions: list[DecisionMethodSubmission] = []
    receipts: list[DecisionPolicyReceipt] = []
    for request in requests:
        case_receipts: list[DecisionPolicyReceipt] = []
        selected: str | None = None
        failure: str | None = None
        try:
            common = {
                "decision": request.model_dump(mode="json"),
                "instruction": (
                    "Choose one feasible action based only on visible pre-decision "
                    "evidence. Do not assume hidden outcomes."
                ),
            }
            if policy_kind == "reflection":
                common["prior_observed_episodes"] = [
                    item.model_dump(mode="json") for item in reflection_episodes
                ]
                common["instruction"] += (
                    " Condition on the observed outcomes of the prior, source-disjoint episodes."
                )
            if policy_kind == "planning":
                first, receipt = _call(
                    backend,
                    manifest_sha256=manifest_sha256,
                    request=request,
                    stage="estimate-actions",
                    payload=common,
                    output_schema={
                        "action_scores": {
                            item.action_id: "number from 0 to 1"
                            for item in request.available_actions
                        }
                    },
                )
                case_receipts.append(receipt)
                scores = first.get("action_scores")
                action_ids = {item.action_id for item in request.available_actions}
                if not isinstance(scores, dict) or set(scores) != action_ids:
                    raise ValueError("planning response did not score the exact action menu")
                if any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not 0 <= value <= 1
                    for value in scores.values()
                ):
                    raise ValueError("planning response has invalid action estimates")
                common["estimated_action_scores"] = scores
                common["instruction"] += (
                    " Select after comparing all candidate actions and their estimates."
                )
            answer, receipt = _call(
                backend,
                manifest_sha256=manifest_sha256,
                request=request,
                stage="choose-action",
                payload=common,
                output_schema={
                    "selected_action_id": [item.action_id for item in request.available_actions]
                },
            )
            case_receipts.append(receipt)
            selected = answer.get("selected_action_id")
            if selected not in {item.action_id for item in request.available_actions}:
                raise ValueError("decision response selected an action outside the menu")
        except (ValueError, RuntimeError, OSError, httpx.HTTPError) as exc:
            failure = (
                f"HTTP-{exc.response.status_code}"
                if isinstance(exc, httpx.HTTPStatusError)
                else type(exc).__name__
            )
            selected = None
        receipts.extend(case_receipts)
        complete_usage = failure is None and len(case_receipts) == (
            2 if policy_kind == "planning" else 1
        )
        submissions.append(
            DecisionMethodSubmission(
                method_id=method_id,
                method_manifest_sha256=manifest_sha256,
                request_sha256=request.request_sha256,
                selected_action_id=selected,
                failure_code=failure,
                input_tokens=(
                    sum(item.input_tokens for item in case_receipts) if complete_usage else None
                ),
                output_tokens=(
                    sum(item.output_tokens for item in case_receipts) if complete_usage else None
                ),
                inference_cost_usd=(
                    sum(item.cost_usd for item in case_receipts if item.cost_usd is not None)
                    if complete_usage and all(item.cost_usd is not None for item in case_receipts)
                    else None
                ),
            )
        )
    return DecisionPolicyRun(
        method_id=method_id,
        method_manifest_sha256=manifest_sha256,
        submissions=tuple(submissions),
        receipts=tuple(receipts),
    )


def _call(
    backend: DecisionModelBackend,
    *,
    manifest_sha256: str,
    request: DecisionMethodRequest,
    stage: str,
    payload: dict,
    output_schema: dict,
) -> tuple[dict, DecisionPolicyReceipt]:
    model_request = StructuredModelRequest(
        request_id=f"{request.case_id}:{stage}",
        node_name="scitastebench-decision-policy",
        stage=stage,
        state_snapshot_id=request.case_id,
        expected_backend=backend.name,
        expected_model=backend.model,
        policy_id=manifest_sha256,
        policy_fingerprint=manifest_sha256,
        system_instruction=(
            "You are a research-decision policy. Return only the requested JSON object. "
            "Never invent unavailable evidence or hidden future outcomes."
        ),
        input_payload=payload,
        output_schema=output_schema,
        prompt_version="decision-baselines-v1",
        seed=0,
    )
    response = backend.complete(model_request)
    if not isinstance(response.output_payload, dict):
        raise ValueError("decision response must be a JSON object")
    receipt = DecisionPolicyReceipt(
        request_sha256=request.request_sha256,
        stage=stage,
        model_request_fingerprint=model_request.fingerprint,
        raw_response_sha256=response.raw_response_sha256,
        served_backend=response.backend,
        served_model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cost_usd=response.usage.cost_usd,
    )
    return response.output_payload, receipt


__all__ = [
    "DecisionPolicyReceipt",
    "DecisionPolicyRun",
    "DecisionReflectionEpisode",
    "run_decision_policy",
]

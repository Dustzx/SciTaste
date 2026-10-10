#!/usr/bin/env python3
"""Compile a compact, conditional Scientific Taste policy for ResearchClawBench.

The previous system study injected a long task-level literature synthesis with
an unconditional recommended first action.  That treatment can act as an
extra plan or a retrieval summary rather than a selective policy.  This
successor keeps source grounding but emits only evidence-triggered decision
rules.  It explicitly abstains to the native agent when the current workspace
does not satisfy a rule's trigger or violates a blocking condition.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from compile_researchclawbench_grounded_taste_overlay import (
    GroundedReference,
    GroundedTasteInput,
    _evidence_blocks,
    _grounded_pdf_excerpt,
    _sha256_file,
    _source_id,
    _write_json,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResult, NodeResultStatus
from scitaste.model_nodes.nodes import ModelNode
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_MAX_OVERLAY_BYTES = 7_000
_CompactCondition = Annotated[str, Field(min_length=1, max_length=180)]
_CompactRule = Annotated[str, Field(min_length=1, max_length=300)]
_CompactObligation = Annotated[str, Field(min_length=1, max_length=240)]


class ConditionalTasteClaim(BaseModel):
    """One source-grounded principle abstracted for a decision, not a fact dump."""

    model_config = _CONFIG

    claim_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    claim_type: Literal["ASSUMPTION", "ALGORITHM", "EVALUATION", "LIMITATION"]
    principle: str = Field(min_length=1, max_length=300)
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    evidence_block_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,99}$")
    decision_relevance: str = Field(min_length=1, max_length=240)


class ConditionalResearchAction(BaseModel):
    """An action that becomes advisory only after observable trigger evidence."""

    model_config = _CONFIG

    action_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    action_type: Literal["PROBE", "EXPERIMENT", "ANALYZE", "REFINE", "PIVOT", "STOP"]
    grounded_claim_ids: tuple[str, ...] = Field(min_length=1, max_length=6)
    trigger_conditions: tuple[_CompactCondition, ...] = Field(min_length=1, max_length=3)
    blocking_conditions: tuple[_CompactCondition, ...] = Field(min_length=1, max_length=3)
    instruction: str = Field(min_length=1, max_length=360)
    discriminating_signal: str = Field(min_length=1, max_length=240)
    failure_signal: str = Field(min_length=1, max_length=240)
    next_if_supported: str = Field(min_length=1, max_length=180)
    next_if_failed: str = Field(min_length=1, max_length=180)


class ConditionalTasteOutput(BaseModel):
    """Compact conditional policy; intentionally has no recommended action field."""

    model_config = _CONFIG

    problem_pattern: str = Field(min_length=1, max_length=400)
    mechanism_claims: tuple[ConditionalTasteClaim, ...] = Field(min_length=3, max_length=4)
    decision_rules: tuple[_CompactRule, ...] = Field(min_length=3, max_length=4)
    action_menu: tuple[ConditionalResearchAction, ...] = Field(min_length=2, max_length=3)
    arbitration_rule: str = Field(min_length=1, max_length=520)
    abstain_conditions: tuple[_CompactCondition, ...] = Field(min_length=2, max_length=4)
    evidence_obligations: tuple[_CompactObligation, ...] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def policy_is_conditional_and_closed(self) -> ConditionalTasteOutput:
        claim_ids = tuple(item.claim_id for item in self.mechanism_claims)
        action_ids = tuple(item.action_id for item in self.action_menu)
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("conditional Taste claim IDs must be unique")
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("conditional Taste action IDs must be unique")
        known = set(claim_ids)
        for action in self.action_menu:
            missing = set(action.grounded_claim_ids) - known
            if missing:
                raise ValueError(f"conditional action references unknown claims: {missing}")
        if len({item.action_type for item in self.action_menu}) < 2:
            raise ValueError("conditional Taste requires at least two action types")
        return self


class ConditionalTasteNode(ModelNode[GroundedTasteInput, ConditionalTasteOutput]):
    node_name = "researchclawbench-conditional-taste-abstraction"
    prompt_version = "researchclawbench-conditional-taste-abstraction-v5"
    system_instruction = (
        "Act as SciTaste's source-grounded scientific-decision policy compiler. "
        "Abstract high-quality references into a compact conditional policy, not a "
        "literature summary and not an execution plan. Never recommend a first action "
        "from the task description alone. Every action must require observable workspace "
        "trigger conditions, list blocking conditions, define a discriminating signal, "
        "and specify what to do after support or failure. When triggers are absent, "
        "ambiguous, or conflicting, the policy must abstain and preserve the native "
        "agent's plan. Prefer information gain, falsification, implementation fidelity, "
        "fair baselines, and explicit stop/pivot boundaries over extra experiment volume. "
        "Each abstract principle must cite one supplied source_id and evidence_block_id. "
        "Do not copy long source passages, invent results, expose target-study information, "
        "or encode an unconditional preferred action. Return only the structured policy."
        " Use no more than four principles, four decision rules, three actions, four "
        "abstention conditions, and four evidence obligations. Keep each condition to "
        "one short sentence and remove explanatory repetition across fields."
    )
    input_model = GroundedTasteInput
    output_model = ConditionalTasteOutput

    def _normalize_output_payload(
        self,
        payload: dict[str, Any],
        *,
        input_data: GroundedTasteInput,
        context: NodeContext,
        policy: NodePolicy,
    ) -> dict[str, Any]:
        del input_data, context, policy
        normalized, _ = _bounded_structural_payload_adapter(payload)
        return normalized


def _bounded_structural_payload_adapter(
    payload: Any,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Repair trailing key punctuation without changing any semantic value."""

    if not isinstance(payload, dict):
        raise ValueError("conditional Taste output must be an object")
    normalized = copy.deepcopy(payload)
    actions = normalized.get("action_menu")
    if not isinstance(actions, list):
        return normalized, []
    action_fields = {
        "action_id",
        "action_type",
        "grounded_claim_ids",
        "trigger_conditions",
        "blocking_conditions",
        "instruction",
        "discriminating_signal",
        "failure_signal",
        "next_if_supported",
        "next_if_failed",
    }
    repairs: list[dict[str, str]] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            continue
        for malformed_key in tuple(action):
            normalized_key = re.sub(r"[\s\[\]:]+$", "", malformed_key)
            if normalized_key == malformed_key or normalized_key not in action_fields:
                continue
            if normalized_key in action:
                raise ValueError(f"ambiguous provider keys for {normalized_key}")
            action[normalized_key] = action.pop(malformed_key)
            repairs.append(
                {
                    "path": f"action_menu[{index}]",
                    "operation": "rename-key",
                    "from": malformed_key,
                    "to": normalized_key,
                }
            )
    if len(repairs) > 2:
        raise ValueError("conditional Taste structural repair exceeds two key renames")
    return normalized, repairs


def _verify_grounding(
    packet: ConditionalTasteOutput, references: tuple[GroundedReference, ...]
) -> dict[str, Any]:
    sources = {item.source_id: item for item in references}
    checks = []
    for claim in packet.mechanism_claims:
        source = sources.get(claim.source_id)
        blocks = {} if source is None else {item.block_id: item for item in source.evidence_blocks}
        block = blocks.get(claim.evidence_block_id)
        checks.append(
            {
                "claim_id": claim.claim_id,
                "source_id": claim.source_id,
                "evidence_block_id": claim.evidence_block_id,
                "evidence_block_exists_in_source": block is not None,
                "evidence_block_sha256": None if block is None else block.text_sha256,
            }
        )
    return {
        "accepted": bool(checks)
        and all(item["evidence_block_exists_in_source"] for item in checks),
        "checks": checks,
    }


def _render(packet: ConditionalTasteOutput) -> str:
    lines = [
        "# SciTaste Conditional Policy",
        "No default action. Apply an action only when all IF and no BLOCK conditions hold; "
        "otherwise keep the native plan.",
        f"PATTERN | {packet.problem_pattern}",
        "PRINCIPLES",
    ]
    for claim in packet.mechanism_claims:
        lines.append(
            f"{claim.claim_id} | {claim.claim_type} | {claim.principle} | "
            f"WHEN {claim.decision_relevance} | "
            f"SRC {claim.source_id}/{claim.evidence_block_id}"
        )
    lines.append("RULES")
    lines.extend(packet.decision_rules)
    lines.append("ACTIONS")
    for action in packet.action_menu:
        lines.append(
            f"{action.action_id} | {action.action_type} | "
            f"IF {'; '.join(action.trigger_conditions)} | "
            f"BLOCK {'; '.join(action.blocking_conditions)} | "
            f"DO {action.instruction} | "
            f"SUPPORT {action.discriminating_signal} => {action.next_if_supported} | "
            f"FAIL {action.failure_signal} => {action.next_if_failed} | "
            f"GROUND {','.join(action.grounded_claim_ids)}"
        )
    lines.extend((f"ARBITRATE | {packet.arbitration_rule}", "ABSTAIN"))
    lines.extend(packet.abstain_conditions)
    lines.append("EVIDENCE")
    lines.extend(packet.evidence_obligations)
    overlay = "\n".join(lines).strip() + "\n"
    if len(overlay.encode("utf-8")) > _MAX_OVERLAY_BYTES:
        raise ValueError("conditional Taste overlay exceeds the 7,000-byte treatment ceiling")
    return overlay


def _load_references(
    task_root: Path,
    *,
    additional_references: list[Path],
    additional_origins: list[str],
    excluded_hashes: set[str],
    maximum_characters: int,
) -> tuple[tuple[GroundedReference, ...], list[dict[str, str]]]:
    sources: list[tuple[Path, str, str]] = [
        (path, "BENCHMARK_RELATED_WORK", f"benchmark://{task_root.name}/related_work/{path.name}")
        for path in sorted((task_root / "related_work").glob("*.pdf"))
    ]
    for path, origin in zip(additional_references, additional_origins, strict=True):
        resolved = path.resolve(strict=True)
        if _sha256_file(resolved) in excluded_hashes:
            raise ValueError(f"public literature collides with a held-out source: {resolved.name}")
        sources.append((resolved, "PUBLIC_LITERATURE", origin))
    references = []
    skipped = []
    for index, (path, kind, origin) in enumerate(sources):
        source_id = _source_id(index, path)
        try:
            excerpt = _grounded_pdf_excerpt(path, maximum_characters)
        except ValueError as exc:
            skipped.append(
                {
                    "source": path.name,
                    "origin": origin,
                    "reason": str(exc),
                    "source_sha256": _sha256_file(path),
                }
            )
            continue
        references.append(
            GroundedReference(
                source_id=source_id,
                source=path.name,
                source_kind=kind,
                origin=origin,
                source_sha256=_sha256_file(path),
                evidence_blocks=_evidence_blocks(source_id, excerpt),
            )
        )
    if not references:
        raise ValueError("no related-work source has extractable text")
    return tuple(references), skipped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--additional-reference", type=Path, action="append", default=[])
    parser.add_argument("--additional-reference-origin", action="append", default=[])
    parser.add_argument("--excluded-source-sha256", action="append", default=[])
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml"),
    )
    parser.add_argument("--maximum-characters-per-reference", type=int, default=32_000)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument(
        "--replay-node-result",
        type=Path,
        help="Adopt one saved response after bounded structural validation or repair.",
    )
    parser.add_argument(
        "--replay-designation",
        choices=("development", "formal-treatment-migration-before-agent-execution"),
        default="development",
    )
    args = parser.parse_args()
    if args.allow_api and args.replay_node_result is not None:
        raise ValueError("--allow-api and --replay-node-result are mutually exclusive")
    if not args.allow_api and args.replay_node_result is None:
        raise ValueError("live conditional Taste abstraction requires --allow-api")
    if len(args.additional_reference) != len(args.additional_reference_origin):
        raise ValueError("each additional reference requires one provenance origin")
    excluded_hashes = set(args.excluded_source_sha256)
    if any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in excluded_hashes):
        raise ValueError("excluded source hashes must be lowercase SHA-256 values")
    if not 4_000 <= args.maximum_characters_per_reference <= 48_000:
        raise ValueError("reference excerpt limit must be between 4,000 and 48,000")

    task_root = args.task_root.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    task_info = json.loads((task_root / "task_info.json").read_text(encoding="utf-8"))
    references, skipped = _load_references(
        task_root,
        additional_references=args.additional_reference,
        additional_origins=args.additional_reference_origin,
        excluded_hashes=excluded_hashes,
        maximum_characters=args.maximum_characters_per_reference,
    )
    input_data = GroundedTasteInput(
        task_id=task_root.name,
        task_description=task_info["task"],
        data_manifest=tuple(task_info.get("data", [])),
        references=references,
        decision_goal=(
            "Abstract a compact, source-grounded policy that intervenes only after observable "
            "evidence triggers a discriminating scientific decision and otherwise abstains."
        ),
    )
    bounded_repairs: list[dict[str, str]] = []
    replay_metadata: dict[str, Any] | None = None
    if args.replay_node_result is not None:
        replay_path = args.replay_node_result.resolve(strict=True)
        replay_payload = json.loads(replay_path.read_text(encoding="utf-8"))
        recorded_request_fingerprint = replay_payload["request"].pop("fingerprint", None)
        result = NodeResult[ConditionalTasteOutput].model_validate(replay_payload)
        if recorded_request_fingerprint not in {None, result.request.fingerprint}:
            raise ValueError("recorded replay request fingerprint is invalid")
        expected_input = input_data.model_dump(mode="json")
        if result.request.input_payload.get("input") != expected_input:
            raise ValueError("replay node input differs from the reconstructed grounded input")
        if result.node_name != ConditionalTasteNode.node_name or result.response.tool_calls:
            raise ValueError("replay source violates the conditional Taste node boundary")
        if result.status is NodeResultStatus.ACCEPTED and result.proposal is not None:
            packet = result.proposal
            _, bounded_repairs = _bounded_structural_payload_adapter(result.response.output_payload)
        else:
            normalized_payload, bounded_repairs = _bounded_structural_payload_adapter(
                result.response.output_payload
            )
            packet = ConditionalTasteOutput.model_validate_json(
                json.dumps(normalized_payload, ensure_ascii=False, separators=(",", ":")),
                strict=True,
            )
        replay_metadata = {
            "source_node_result": str(replay_path),
            "source_node_result_sha256": _sha256_file(replay_path),
            "source_status": result.status.value,
            "source_rejection_reasons": result.rejection_reasons,
            "bounded_structural_repairs": bounded_repairs,
            "semantic_values_modified": False,
            "evidence_designation": args.replay_designation,
            "development_only": args.replay_designation == "development",
        }
    else:
        backend_config = load_structured_openai_compatible_config(args.backend.resolve(strict=True))
        backend = StructuredOpenAICompatibleBackend(backend_config)
        policy = NodePolicy(
            policy_id="researchclawbench-conditional-taste-abstraction-v5",
            enabled=True,
            allowed_node_names=[ConditionalTasteNode.node_name],
            expected_backend=backend.name,
            expected_model=backend.model,
            allowed_tool_names=[],
            max_request_bytes=1_500_000,
            max_input_tokens=160_000,
            max_output_tokens=backend_config.max_output_tokens,
            max_total_tokens=170_000,
            max_api_cost_usd=30.0,
            max_latency_ms=int(backend_config.timeout_seconds * 1_000),
        )
        result = ConditionalTasteNode().run(
            input_data,
            context=NodeContext(
                project_id="scitaste-self-development",
                stage="EXPERIMENTATION",
                state_snapshot_id=content_sha256(input_data.model_dump(mode="json")),
                cumulative_api_cost_usd=0.0,
                metadata={
                    "benchmark": "ResearchClawBench",
                    "task_id": task_root.name,
                    "target_study_visible": False,
                    "treatment": "conditional-taste-v5",
                },
            ),
            backend=backend,
            policy=policy,
            request_id=f"researchclawbench-{task_root.name.lower()}-conditional-taste-v5",
        )
        if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
            output.mkdir(parents=True)
            _write_json(output / "GROUNDED_INPUT.json", input_data.model_dump(mode="json"))
            _write_json(output / "NODE_RESULT.json", result.model_dump(mode="json"))
            raise ValueError(
                "conditional Taste abstraction rejected: " + "; ".join(result.rejection_reasons)
            )
        packet = result.proposal
        _, bounded_repairs = _bounded_structural_payload_adapter(result.response.output_payload)
    output.mkdir(parents=True)
    _write_json(output / "GROUNDED_INPUT.json", input_data.model_dump(mode="json"))
    _write_json(output / "NODE_RESULT.json", result.model_dump(mode="json"))
    if replay_metadata is not None:
        _write_json(output / "BOUNDED_REPAIR_REPORT.json", replay_metadata)
    grounding = _verify_grounding(packet, references)
    _write_json(output / "GROUNDING_REPORT.json", grounding)
    if not grounding["accepted"]:
        raise ValueError("conditional Taste policy failed source grounding")
    overlay = _render(packet)
    _write_json(output / "TASTE_CONTROL_PACKET.json", packet.model_dump(mode="json"))
    (output / "TASTE_CONTROL_OVERLAY.md").write_text(overlay, encoding="utf-8")
    receipt = {
        "schema_version": "3.0",
        "benchmark": "ResearchClawBench",
        "task_id": task_root.name,
        "treatment": "conditional-taste-policy-no-unconditional-recommendation",
        "visible_input_sha256": content_sha256(input_data.model_dump(mode="json")),
        "packet_sha256": content_sha256(packet.model_dump(mode="json")),
        "overlay_file_sha256": hashlib.sha256(overlay.encode()).hexdigest(),
        "overlay_bytes": len(overlay.encode()),
        "overlay_byte_ceiling": _MAX_OVERLAY_BYTES,
        "render_format": "compact-lossless-v1",
        "mechanism_claim_count": len(packet.mechanism_claims),
        "conditional_action_count": len(packet.action_menu),
        "grounding_report_sha256": content_sha256(grounding),
        "provider": result.response.backend,
        "model": result.response.model,
        "usage": result.response.usage.model_dump(mode="json"),
        "target_study_visible": False,
        "unconditional_recommended_action_present": False,
        "native_fallback_required_when_abstaining": True,
        "excluded_source_identity_count": len(excluded_hashes),
        "public_literature_origins": args.additional_reference_origin,
        "skipped_sources": skipped,
        "bounded_structural_repairs": bounded_repairs,
        "semantic_values_modified_by_adapter": False,
        "replay_adoption": replay_metadata,
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    _write_json(output / "RECEIPT.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

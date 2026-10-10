#!/usr/bin/env python3
"""Compile a source-grounded SciTaste control packet for ResearchClawBench.

Version 2 addresses a failure observed in the first matched system run: a
plausible abstraction silently changed the source mechanism.  Every mechanism
claim in this packet therefore carries an exact, machine-verified evidence
span, and every action declares which claims it implements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

from compile_researchclawbench_taste_overlay import (
    _sha256_file,
    _write_json,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResultStatus
from scitaste.model_nodes.nodes import ModelNode
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvidenceBlock(BaseModel):
    model_config = _CONFIG

    block_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,99}$")
    text: str = Field(min_length=1, max_length=2_000)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class GroundedReference(BaseModel):
    model_config = _CONFIG

    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    source: str
    source_kind: Literal["BENCHMARK_RELATED_WORK", "PUBLIC_LITERATURE"]
    origin: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_blocks: tuple[EvidenceBlock, ...] = Field(min_length=1, max_length=80)


class GroundedTasteInput(BaseModel):
    model_config = _CONFIG

    task_id: str
    task_description: str = Field(min_length=1, max_length=32_000)
    data_manifest: tuple[dict[str, Any], ...] = Field(max_length=32)
    references: tuple[GroundedReference, ...] = Field(min_length=1, max_length=24)
    decision_goal: str = Field(min_length=1, max_length=2_000)


class GroundedMechanismClaim(BaseModel):
    model_config = _CONFIG

    claim_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    claim_type: Literal[
        "DEFINITION", "ASSUMPTION", "ALGORITHM", "BASELINE", "EVALUATION", "LIMITATION"
    ]
    claim: str = Field(min_length=1, max_length=2_000)
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    evidence_block_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,99}$")
    implementation_implication: str = Field(min_length=1, max_length=2_000)


class GroundedResearchAction(BaseModel):
    model_config = _CONFIG

    action_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    action_type: Literal["PROBE", "EXPERIMENT", "ANALYZE", "REFINE", "PIVOT"]
    grounded_claim_ids: tuple[str, ...] = Field(min_length=1, max_length=12)
    hypothesis: str = Field(min_length=1, max_length=2_000)
    instruction: str = Field(min_length=1, max_length=3_000)
    discriminating_evidence: str = Field(min_length=1, max_length=2_000)
    stop_or_pivot_rule: str = Field(min_length=1, max_length=2_000)


class GroundedTasteOutput(BaseModel):
    model_config = _CONFIG

    problem_pattern: str = Field(min_length=1, max_length=3_000)
    mechanism_claims: tuple[GroundedMechanismClaim, ...] = Field(min_length=4, max_length=16)
    decision_principles: tuple[str, ...] = Field(min_length=3, max_length=8)
    action_menu: tuple[GroundedResearchAction, ...] = Field(min_length=3, max_length=8)
    recommended_action_id: str
    rejected_shortcuts: tuple[str, ...] = Field(min_length=2, max_length=8)
    evidence_obligations: tuple[str, ...] = Field(min_length=3, max_length=10)
    transfer_boundaries: tuple[str, ...] = Field(min_length=2, max_length=8)
    critic_checks: tuple[str, ...] = Field(min_length=3, max_length=10)

    @model_validator(mode="after")
    def references_are_closed(self) -> GroundedTasteOutput:
        action_ids = tuple(item.action_id for item in self.action_menu)
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("action ids must be unique")
        if self.recommended_action_id not in action_ids:
            raise ValueError("recommended action is absent from the action menu")
        claim_ids = tuple(item.claim_id for item in self.mechanism_claims)
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("mechanism claim ids must be unique")
        known = set(claim_ids)
        for action in self.action_menu:
            missing = set(action.grounded_claim_ids) - known
            if missing:
                raise ValueError(f"action references unknown claims: {sorted(missing)}")
        return self


class GroundedTasteNode(ModelNode[GroundedTasteInput, GroundedTasteOutput]):
    node_name = "researchclawbench-grounded-taste-abstraction"
    prompt_version = "researchclawbench-grounded-taste-abstraction-v2"
    system_instruction = (
        "Act as SciTaste's source-grounded reference-to-taste compiler. Convert the supplied "
        "high-quality literature into executable scientific judgment without changing any "
        "mechanism definition. First extract atomic definitions, assumptions, algorithm steps, "
        "baselines, evaluation requirements, and limitations. Every mechanism claim must cite "
        "one source_id and one evidence_block_id from that source. Evidence block identifiers "
        "are immutable content anchors: cite the smallest block that directly supports the "
        "claim and do not invent or alter an identifier. Every "
        "action must name the grounded claims it implements. Never replace an "
        "exact source definition with a plausible heuristic. If sources disagree, preserve the "
        "conflict and make comparison an experiment. Prioritize one coherent source-faithful "
        "mechanism, a fair baseline, a discriminating ablation, and a stop/pivot rule. Do not "
        "invent measurements or treat cited results as observations from the new run. Return "
        "only the compact structured packet."
    )
    input_model = GroundedTasteInput
    output_model = GroundedTasteOutput


def _verify_grounding(
    packet: GroundedTasteOutput, references: tuple[GroundedReference, ...]
) -> dict[str, Any]:
    source_by_id = {item.source_id: item for item in references}
    checks = []
    for claim in packet.mechanism_claims:
        source = source_by_id.get(claim.source_id)
        if source is None:
            raise ValueError(f"unknown claim source: {claim.source_id}")
        block_by_id = {item.block_id: item for item in source.evidence_blocks}
        block = block_by_id.get(claim.evidence_block_id)
        checks.append(
            {
                "claim_id": claim.claim_id,
                "source_id": claim.source_id,
                "evidence_block_id": claim.evidence_block_id,
                "evidence_block_exists_in_source": block is not None,
                "evidence_block_sha256": block.text_sha256 if block is not None else None,
            }
        )
    accepted = all(item["evidence_block_exists_in_source"] for item in checks)
    return {"accepted": accepted, "checks": checks}


def _render(packet: GroundedTasteOutput, references: tuple[GroundedReference, ...]) -> str:
    lines = [
        "This source-grounded Taste packet was compiled before the run.",
        "Cited results are priors, not observations; new claims require new-run evidence.",
        "Do not substitute a different implementation for a grounded definition.",
        "",
        "## Problem pattern",
        "",
        f"- {packet.problem_pattern}",
        "",
        "## Source-grounded mechanism contract",
        "",
    ]
    reference_by_id = {item.source_id: item for item in references}
    for claim in packet.mechanism_claims:
        source = reference_by_id[claim.source_id]
        block = next(
            item for item in source.evidence_blocks if item.block_id == claim.evidence_block_id
        )
        lines.extend(
            [
                f"- `{claim.claim_id}` [{claim.claim_type}] {claim.claim}",
                f"  Source: `{claim.source_id}` / `{block.block_id}`; "
                f"evidence SHA-256: `{block.text_sha256}`",
                f"  Implementation implication: {claim.implementation_implication}",
            ]
        )
    sections = (
        ("Decision principles", packet.decision_principles),
        ("Rejected shortcuts", packet.rejected_shortcuts),
        ("Evidence obligations", packet.evidence_obligations),
        ("Transfer boundaries", packet.transfer_boundaries),
        ("Taste critic checks", packet.critic_checks),
    )
    lines.extend(("", "## Action menu", ""))
    for action in packet.action_menu:
        marker = (
            " (recommended first action)"
            if action.action_id == packet.recommended_action_id
            else ""
        )
        lines.extend(
            [
                f"- `{action.action_id}` [{action.action_type}]{marker}: {action.instruction}",
                f"  Grounding: {', '.join(f'`{item}`' for item in action.grounded_claim_ids)}",
                f"  Hypothesis: {action.hypothesis}",
                f"  Discriminating evidence: {action.discriminating_evidence}",
                f"  Stop/pivot rule: {action.stop_or_pivot_rule}",
            ]
        )
    for heading, values in sections:
        lines.extend(("", f"## {heading}", ""))
        lines.extend(f"- {value}" for value in values)
    return "\n".join(lines).strip() + "\n"


def _source_id(index: int, path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")[:48]
    return f"ref-{index:02d}-{stem}"


def _grounded_pdf_excerpt(path: Path, maximum_characters: int) -> str:
    """Extract reading-order text and repair line-break hyphenation."""

    with tempfile.TemporaryDirectory(prefix="scitaste-rcb-grounded-pdf-") as temporary:
        target = Path(temporary) / "paper.txt"
        completed = subprocess.run(
            ["pdftotext", "-raw", str(path), str(target)],
            check=False,
            capture_output=True,
            timeout=120,
        )
        if completed.returncode != 0 or not target.is_file():
            raise ValueError(f"could not extract public literature: {path.name}")
        text = target.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = " ".join(text.split())
    if not text:
        raise ValueError(f"public literature has no extractable text: {path.name}")
    return text[:maximum_characters]


def _evidence_blocks(source_id: str, excerpt: str) -> tuple[EvidenceBlock, ...]:
    """Create stable, overlapping content anchors without model judgment."""

    words = excerpt.split()
    block_words = 180
    stride = 150
    blocks = []
    for index, start in enumerate(range(0, len(words), stride)):
        text = " ".join(words[start : start + block_words])
        if not text:
            break
        if len(text) > 2_000:
            text = text[:2_000].rsplit(" ", 1)[0]
        blocks.append(
            EvidenceBlock(
                block_id=f"{source_id}-b{index:03d}",
                text=text,
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
        if start + block_words >= len(words):
            break
    return tuple(blocks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--additional-reference", type=Path, action="append", default=[])
    parser.add_argument("--additional-reference-origin", action="append", default=[])
    parser.add_argument(
        "--excluded-source-sha256",
        action="append",
        default=[],
        help="Evaluator-owned target/holdout hashes that public acquisitions must not match",
    )
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml"),
    )
    parser.add_argument("--maximum-characters-per-reference", type=int, default=40_000)
    parser.add_argument("--allow-api", action="store_true")
    args = parser.parse_args()
    if not args.allow_api:
        raise ValueError("live Taste abstraction requires --allow-api")
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
    sources: list[tuple[Path, str, str]] = [
        (path, "BENCHMARK_RELATED_WORK", f"benchmark://{task_root.name}/related_work/{path.name}")
        for path in sorted((task_root / "related_work").glob("*.pdf"))
    ]
    for path, origin in zip(
        args.additional_reference, args.additional_reference_origin, strict=True
    ):
        resolved = path.resolve(strict=True)
        source_hash = _sha256_file(resolved)
        if source_hash in excluded_hashes:
            raise ValueError(
                f"public literature collides with an evaluator-held-out source: {resolved.name}"
            )
        sources.append((resolved, "PUBLIC_LITERATURE", origin))
    references_list = []
    skipped_sources = []
    for index, (path, kind, origin) in enumerate(sources):
        source_id = _source_id(index, path)
        try:
            excerpt = _grounded_pdf_excerpt(path, args.maximum_characters_per_reference)
        except ValueError as exc:
            skipped_sources.append(
                {
                    "source": path.name,
                    "origin": origin,
                    "reason": str(exc),
                    "source_sha256": _sha256_file(path),
                }
            )
            continue
        references_list.append(
            GroundedReference(
                source_id=source_id,
                source=path.name,
                source_kind=kind,
                origin=origin,
                source_sha256=_sha256_file(path),
                evidence_blocks=_evidence_blocks(source_id, excerpt),
            )
        )
    references = tuple(references_list)
    if not references:
        raise ValueError("no related-work source has extractable text")
    input_data = GroundedTasteInput(
        task_id=task_root.name,
        task_description=task_info["task"],
        data_manifest=tuple(task_info.get("data", [])),
        references=references,
        decision_goal=(
            "Execute a source-faithful mechanism comparison and compact discriminating ablation "
            "that can fail honestly while yielding a traceable research report."
        ),
    )
    backend_config = load_structured_openai_compatible_config(args.backend.resolve(strict=True))
    backend = StructuredOpenAICompatibleBackend(backend_config)
    policy = NodePolicy(
        policy_id="researchclawbench-grounded-taste-abstraction-v2",
        enabled=True,
        allowed_node_names=[GroundedTasteNode.node_name],
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
    result = GroundedTasteNode().run(
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
                "public_literature_count": len(args.additional_reference),
            },
        ),
        backend=backend,
        policy=policy,
        request_id=f"researchclawbench-{task_root.name.lower()}-grounded-taste-v2",
    )
    output.mkdir(parents=True)
    _write_json(output / "GROUNDED_INPUT.json", input_data.model_dump(mode="json"))
    _write_json(output / "NODE_RESULT.json", result.model_dump(mode="json"))
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError(
            "grounded Taste abstraction rejected: " + "; ".join(result.rejection_reasons)
        )
    packet = result.proposal
    grounding = _verify_grounding(packet, references)
    _write_json(output / "GROUNDING_REPORT.json", grounding)
    if not grounding["accepted"]:
        raise ValueError("mechanism packet failed source-grounding verification")
    _write_json(output / "TASTE_CONTROL_PACKET.json", packet.model_dump(mode="json"))
    overlay = _render(packet, references)
    (output / "TASTE_CONTROL_OVERLAY.md").write_text(overlay, encoding="utf-8")
    receipt = {
        "schema_version": "2.0",
        "benchmark": "ResearchClawBench",
        "task_id": task_root.name,
        "visible_input_sha256": content_sha256(input_data.model_dump(mode="json")),
        "packet_sha256": content_sha256(packet.model_dump(mode="json")),
        "overlay_file_sha256": hashlib.sha256(overlay.encode("utf-8")).hexdigest(),
        "grounding_report_sha256": content_sha256(grounding),
        "provider": result.response.backend,
        "model": result.response.model,
        "usage": result.response.usage.model_dump(mode="json"),
        "target_study_visible": False,
        "excluded_source_identity_count": len(excluded_hashes),
        "excluded_source_identity_check_passed": True,
        "public_literature_origins": args.additional_reference_origin,
        "skipped_sources": skipped_sources,
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    _write_json(output / "RECEIPT.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

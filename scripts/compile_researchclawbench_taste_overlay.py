#!/usr/bin/env python3
"""Abstract related work into a bounded SciTaste control packet for RCB.

Only agent-visible task bytes are read: ``task_info.json`` and ``related_work``.
The hidden target study and checklist are deliberately outside the input path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResultStatus
from scitaste.model_nodes.nodes import ModelNode
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class VisibleReference(BaseModel):
    model_config = _CONFIG

    source: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    excerpt: str = Field(min_length=1, max_length=32_000)


class RCBTasteAbstractionInput(BaseModel):
    model_config = _CONFIG

    task_id: str
    task_description: str = Field(min_length=1, max_length=32_000)
    data_manifest: tuple[dict[str, Any], ...] = Field(max_length=32)
    related_work: tuple[VisibleReference, ...] = Field(min_length=1, max_length=16)
    decision_goal: str = Field(min_length=1, max_length=2_000)


class RCBResearchAction(BaseModel):
    model_config = _CONFIG

    action_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    action_type: Literal["PROBE", "EXPERIMENT", "ANALYZE", "REFINE", "PIVOT"]
    hypothesis: str = Field(min_length=1, max_length=2_000)
    instruction: str = Field(min_length=1, max_length=3_000)
    discriminating_evidence: str = Field(min_length=1, max_length=2_000)
    stop_or_pivot_rule: str = Field(min_length=1, max_length=2_000)


class RCBTasteAbstractionOutput(BaseModel):
    model_config = _CONFIG

    problem_pattern: str = Field(min_length=1, max_length=3_000)
    decision_principles: tuple[str, ...] = Field(min_length=3, max_length=8)
    action_menu: tuple[RCBResearchAction, ...] = Field(min_length=3, max_length=8)
    recommended_action_id: str
    rejected_shortcuts: tuple[str, ...] = Field(min_length=2, max_length=8)
    evidence_obligations: tuple[str, ...] = Field(min_length=3, max_length=10)
    transfer_boundaries: tuple[str, ...] = Field(min_length=2, max_length=8)
    critic_checks: tuple[str, ...] = Field(min_length=3, max_length=10)

    @model_validator(mode="after")
    def recommendation_is_in_menu(self) -> RCBTasteAbstractionOutput:
        ids = tuple(item.action_id for item in self.action_menu)
        if len(ids) != len(set(ids)):
            raise ValueError("Taste action ids must be unique")
        if self.recommended_action_id not in ids:
            raise ValueError("recommended action is absent from the action menu")
        return self


class RCBTasteAbstractionNode(ModelNode[RCBTasteAbstractionInput, RCBTasteAbstractionOutput]):
    node_name = "researchclawbench-taste-abstraction"
    prompt_version = "researchclawbench-taste-abstraction-v1"
    system_instruction = (
        "Act as SciTaste's reference-to-taste compiler for an autonomous research task. "
        "Transform the visible high-quality related work into procedural scientific judgment: "
        "what choices matter, which experiments discriminate mechanisms, when to stop or pivot, "
        "and which shortcuts would create persuasive but invalid evidence. Do not copy passages, "
        "invent measurements, predict benchmark checklist items, or treat cited results as new "
        "observations. Return a compact JSON packet. The action menu must be executable using the "
        "supplied data and must prioritize one coherent mechanism, a fair baseline, a small "
        "discriminating ablation, traceable artifacts, and explicit failure conditions. The packet "
        "is advisory strategy rather than empirical evidence."
    )
    input_model = RCBTasteAbstractionInput
    output_model = RCBTasteAbstractionOutput


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_excerpt(path: Path, maximum_characters: int) -> str:
    with tempfile.TemporaryDirectory(prefix="scitaste-rcb-pdf-") as temporary:
        target = Path(temporary) / "paper.txt"
        completed = subprocess.run(
            ["pdftotext", "-layout", str(path), str(target)],
            check=False,
            capture_output=True,
            timeout=120,
        )
        if completed.returncode != 0 or not target.is_file():
            raise ValueError(f"could not extract visible related work: {path.name}")
        text = " ".join(target.read_text(encoding="utf-8", errors="replace").split())
    if not text:
        raise ValueError(f"visible related work has no extractable text: {path.name}")
    return text[:maximum_characters]


def _render(packet: RCBTasteAbstractionOutput) -> str:
    actions = []
    for action in packet.action_menu:
        marker = (
            " (recommended first action)"
            if action.action_id == packet.recommended_action_id
            else ""
        )
        actions.append(
            f"- `{action.action_id}` [{action.action_type}]{marker}: {action.instruction}\n"
            f"  Hypothesis: {action.hypothesis}\n"
            f"  Discriminating evidence: {action.discriminating_evidence}\n"
            f"  Stop/pivot rule: {action.stop_or_pivot_rule}"
        )
    sections = (
        ("Problem pattern", (packet.problem_pattern,)),
        ("Decision principles", packet.decision_principles),
        ("Action menu", tuple(actions)),
        ("Rejected shortcuts", packet.rejected_shortcuts),
        ("Evidence obligations", packet.evidence_obligations),
        ("Transfer boundaries", packet.transfer_boundaries),
        ("Taste critic checks", packet.critic_checks),
    )
    lines = [
        "This packet was abstracted from the task-visible related work before the run. ",
        "It guides decisions but contains no observed result and cannot substitute for experiments.",
    ]
    for heading, values in sections:
        lines.extend(("", f"## {heading}", ""))
        if heading == "Action menu":
            lines.extend(values)
        else:
            lines.extend(f"- {value}" for value in values)
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/bailian_qwen38max.taste_review_live_20260916.yaml"),
    )
    parser.add_argument("--maximum-characters-per-reference", type=int, default=24_000)
    parser.add_argument("--allow-api", action="store_true")
    args = parser.parse_args()
    if not args.allow_api:
        raise ValueError("live Taste abstraction requires --allow-api")
    if not 4_000 <= args.maximum_characters_per_reference <= 32_000:
        raise ValueError("reference excerpt limit must be between 4,000 and 32,000")

    task_root = args.task_root.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    task_info_path = task_root / "task_info.json"
    task_info = json.loads(task_info_path.read_text(encoding="utf-8"))
    references = tuple(
        VisibleReference(
            source=path.name,
            source_sha256=_sha256_file(path),
            excerpt=_pdf_excerpt(path, args.maximum_characters_per_reference),
        )
        for path in sorted((task_root / "related_work").glob("*.pdf"))
    )
    input_data = RCBTasteAbstractionInput(
        task_id=task_root.name,
        task_description=task_info["task"],
        data_manifest=tuple(task_info.get("data", [])),
        related_work=references,
        decision_goal=(
            "Choose and execute a compact sequence of analysis, implementation, comparison, "
            "and validation decisions that yields the strongest traceable report under one run."
        ),
    )
    backend_config = load_structured_openai_compatible_config(args.backend.resolve(strict=True))
    backend = StructuredOpenAICompatibleBackend(backend_config)
    policy = NodePolicy(
        policy_id="researchclawbench-taste-abstraction-v1",
        enabled=True,
        allowed_node_names=[RCBTasteAbstractionNode.node_name],
        expected_backend=backend.name,
        expected_model=backend.model,
        allowed_tool_names=[],
        max_request_bytes=1_000_000,
        max_input_tokens=100_000,
        max_output_tokens=backend_config.max_output_tokens,
        max_total_tokens=108_192,
        max_api_cost_usd=20.0,
        max_latency_ms=int(backend_config.timeout_seconds * 1_000),
    )
    result = RCBTasteAbstractionNode().run(
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
            },
        ),
        backend=backend,
        policy=policy,
        request_id=f"researchclawbench-{task_root.name.lower()}-taste-overlay-v1",
    )
    output.mkdir(parents=True)
    _write_json(output / "VISIBLE_INPUT.json", input_data.model_dump(mode="json"))
    _write_json(output / "NODE_RESULT.json", result.model_dump(mode="json"))
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError("Taste abstraction rejected: " + "; ".join(result.rejection_reasons))
    packet = result.proposal
    _write_json(output / "TASTE_CONTROL_PACKET.json", packet.model_dump(mode="json"))
    overlay = _render(packet)
    (output / "TASTE_CONTROL_OVERLAY.md").write_text(overlay, encoding="utf-8")
    receipt = {
        "schema_version": "1.0",
        "benchmark": "ResearchClawBench",
        "task_id": task_root.name,
        "visible_input_sha256": content_sha256(input_data.model_dump(mode="json")),
        "packet_sha256": content_sha256(packet.model_dump(mode="json")),
        "overlay_sha256": content_sha256(overlay),
        "provider": result.response.backend,
        "model": result.response.model,
        "usage": result.response.usage.model_dump(mode="json"),
        "target_study_visible": False,
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    _write_json(output / "RECEIPT.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

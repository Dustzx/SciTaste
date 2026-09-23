#!/usr/bin/env python3
"""Prepare one model-proposed MLRC Perception research arm.

The three conditions share source bytes, model, patch policy, and experiment
budget.  They differ only in decision guidance: no precedent, exact raw
precedent, or a source-grounded Taste abstraction.  This command proposes and
deterministically admits code but never trains or opens held-out data.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from scitaste.evaluation.h4_execution import build_h4_benchmark_action_menu
from scitaste.evaluation.task_patch import (
    BenchmarkEditableFileSnapshot,
    BenchmarkPatchContext,
    BenchmarkPatchPolicy,
    BenchmarkPatchProducer,
)
from scitaste.evaluation.task_patch_generation import (
    BenchmarkPatchGenerationInput,
    BenchmarkPatchGenerationNode,
    BenchmarkResearchActionDirective,
    benchmark_directive_from_taste_packet,
    materialize_benchmark_patch_proposal,
)
from scitaste.model_nodes.models import NodeContext, NodePolicy, NodeResultStatus
from scitaste.model_nodes.openai_compatible import (
    StructuredOpenAICompatibleBackend,
    load_structured_openai_compatible_config,
)
from scitaste.model_nodes.profiles import load_model_node_profile
from scitaste.project.models import content_sha256
from scitaste.taste.deliberation import TasteControlPacket, render_taste_control_packet

_DEFAULT_SOURCE = Path(
    "outputs/projects/scitaste-self-development/evaluations/acquisitions/"
    "mlrc-bench-source-v1/checkout/MLAgentBench/benchmarks_base/"
    "perception_temporal_action_loc"
)
_EDITABLE_PATHS = (
    "configs/core_configs.yaml",
    "libs/modeling/losses.py",
    "libs/modeling/meta_archs.py",
    "methods/MyMethod.py",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _guidance_chunks(text: str) -> tuple[str, ...]:
    chunks: list[str] = []
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        while len(paragraph) > 2_000:
            split = paragraph.rfind(" ", 0, 2_000)
            split = split if split > 0 else 2_000
            chunks.append(paragraph[:split])
            paragraph = paragraph[split:].lstrip()
        if paragraph:
            chunks.append(paragraph)
    if len(chunks) > 32:
        raise ValueError("raw precedent exceeds the guidance channel")
    return tuple(chunks)


def _taste_guidance(path: Path) -> tuple[str, ...]:
    capsule = json.loads(path.read_text(encoding="utf-8"))
    boundary = capsule["transfer_boundary"]
    values = (
        "Decision principle: " + capsule["decision_principle"],
        "Why preferred: " + capsule["why_preferred"],
        "Apply when: " + "; ".join(boundary["applies_when"]),
        "Do not transfer when: " + "; ".join(boundary["fails_when"]),
        "Counterfactual probe: " + boundary["counterfactual_probe"],
    )
    if any(len(item) > 2_000 for item in values):
        raise ValueError("Taste capsule exceeds the patch guidance channel")
    return values


def _taste_packet(path: Path) -> TasteControlPacket:
    packet = TasteControlPacket.model_validate_json(path.read_bytes())
    return packet


def _snapshot(source: Path) -> BenchmarkPatchContext:
    files = []
    for relative in _EDITABLE_PATHS:
        path = source / relative
        raw = path.read_bytes()
        content = raw.decode("utf-8")
        files.append(
            BenchmarkEditableFileSnapshot(
                path=relative,
                sha256=_sha256_bytes(raw),
                size_bytes=len(raw),
                content=content,
            )
        )
    surface = content_sha256({item.path: item.sha256 for item in files})
    spec = content_sha256(
        {
            "task_id": "perception-temporal-action-loc",
            "source_commit": "0d26417034811d2d4587646c4520cc305ea09dd6",
            "editable_paths": list(_EDITABLE_PATHS),
        }
    )
    return BenchmarkPatchContext.create(
        spec_id="mlrc-perception-development-v1",
        spec_fingerprint=spec,
        editable_surface_sha256=surface,
        files=tuple(files),
    )


def _policy(profile_path: Path) -> tuple[Any, NodePolicy]:
    profile = load_model_node_profile(profile_path)
    policy = NodePolicy(
        policy_id="mlrc-perception-development-patch-v1",
        enabled=True,
        allowed_node_names=["benchmark-research-patch"],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_tool_names=list(profile.admission.allowed_tool_names),
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    return profile, policy


def _validate_replacement(path: str, replacement: str) -> None:
    if path.endswith(".py"):
        ast.parse(replacement, filename=path)
    elif path.endswith((".yaml", ".yml")):
        parsed = yaml.safe_load(replacement)
        if not isinstance(parsed, dict):
            raise ValueError(f"replacement YAML is not a mapping: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--condition",
        required=True,
        choices=(
            "native-base",
            "raw-context",
            "full",
            "taste-packet",
            "learned-policy-on",
            "learned-policy-off",
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=_DEFAULT_SOURCE)
    parser.add_argument(
        "--editable-env",
        type=Path,
        default=None,
        help="Current arm source for a repair iteration; task metadata still comes from --source.",
    )
    parser.add_argument("--experiment-feedback-file", type=Path, action="append", default=[])
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--baseline-score", type=float, required=True)
    parser.add_argument("--taste-capsule", type=Path)
    parser.add_argument("--taste-packet", type=Path)
    parser.add_argument(
        "--research-action-type",
        choices=("PROBE", "PILOT", "EXPERIMENT", "ANALYZE", "REFINE", "PIVOT"),
        help="Frozen lifecycle action; exposes the directive but no policy scores.",
    )
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path("configs/model_nodes/deepseek_v41flash.scitastebench_live_20260917.yaml"),
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("configs/model_nodes/profile_deepseek_v41flash_benchmark_patch_v1.yaml"),
    )
    parser.add_argument("--allow-api", action="store_true")
    args = parser.parse_args()
    if not args.allow_api:
        raise ValueError("live research-arm preparation requires --allow-api")
    if (args.condition == "full") != (args.taste_capsule is not None):
        raise ValueError("only the legacy full condition requires --taste-capsule")
    if (args.condition == "taste-packet") != (args.taste_packet is not None):
        raise ValueError("only the taste-packet condition requires --taste-packet")
    if args.taste_packet is not None and args.research_action_type is not None:
        raise ValueError("Taste packet and lifecycle action directives are mutually exclusive")

    repository = Path.cwd().resolve(strict=True)
    output = args.output if args.output.is_absolute() else repository / args.output
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    source_root = args.source if args.source.is_absolute() else repository / args.source
    task_root = source_root.resolve(strict=True)
    env_source = (
        args.editable_env.resolve(strict=True)
        if args.editable_env is not None
        else (task_root / "env").resolve(strict=True)
    )
    research_problem = (task_root / "scripts" / "research_problem.txt").read_text(encoding="utf-8")
    background = (task_root / "scripts" / "background.txt").read_text(encoding="utf-8")
    context = _snapshot(env_source)
    patch_policy = BenchmarkPatchPolicy(
        maximum_files_per_patch=4,
        maximum_replacement_bytes_per_file=262_144,
        maximum_replacement_bytes_total=524_288,
    )
    knowledge_guidance = _guidance_chunks(background) if args.condition == "raw-context" else ()
    taste_guidance = (
        _taste_guidance(args.taste_capsule.resolve(strict=True))
        if args.taste_capsule is not None
        else ()
    )
    control_packet = (
        _taste_packet(args.taste_packet.resolve(strict=True))
        if args.taste_packet is not None
        else None
    )
    action_directive = (
        benchmark_directive_from_taste_packet(control_packet)
        if control_packet is not None
        else None
    )
    if args.research_action_type is not None:
        selected = next(
            action
            for action in build_h4_benchmark_action_menu(iteration=args.iteration)
            if action.type.value == args.research_action_type
        )
        action_directive = BenchmarkResearchActionDirective.create(
            action_id=selected.action_id,
            action_type=selected.type.value,
            instruction=selected.description,
        )
    if control_packet is not None:
        taste_guidance = _guidance_chunks(render_taste_control_packet(control_packet))
    experiment_feedback = tuple(
        feedback_path.resolve(strict=True).read_text(encoding="utf-8", errors="replace")[-2_000:]
        for feedback_path in args.experiment_feedback_file
    )
    input_data = BenchmarkPatchGenerationInput(
        schema_version=(
            "1.2" if control_packet is not None else "1.1" if action_directive else "1.0"
        ),
        task_id="perception-temporal-action-loc",
        research_problem=research_problem,
        primary_metric="mean_average_precision",
        metric_direction="higher",
        baseline_development_score=args.baseline_score,
        current_development_score=args.baseline_score,
        best_development_score=args.baseline_score,
        iteration=args.iteration,
        remaining_experiment_runs=1,
        patch_context=context,
        patch_policy=patch_policy,
        experiment_feedback=experiment_feedback,
        knowledge_guidance=knowledge_guidance,
        taste_guidance=taste_guidance,
        research_action=action_directive,
        taste_control_packet_sha256=(
            control_packet.fingerprint if control_packet is not None else None
        ),
        taste_control_packet_abstained=(
            control_packet.abstained if control_packet is not None else None
        ),
        constraints=(
            "Use only the supplied training and development data; never use held-out labels.",
            "Keep the official training schedule, data paths, metric, and evaluation code "
            "unchanged.",
            "Make one coherent, falsifiable method change rather than a hyperparameter sweep.",
            "The prepared source must remain executable on one 24 GiB GPU.",
        ),
    )
    profile, node_policy = _policy(args.profile.resolve(strict=True))
    backend_config = load_structured_openai_compatible_config(args.backend.resolve(strict=True))
    if (backend_config.provider, backend_config.model) != (profile.provider, profile.model):
        raise ValueError("patch backend identity differs from the model profile")
    backend = StructuredOpenAICompatibleBackend(backend_config)
    node = BenchmarkPatchGenerationNode()
    result = node.run(
        input_data,
        context=NodeContext(
            project_id="scitaste-self-development",
            stage="EXPERIMENTATION",
            state_snapshot_id=context.context_sha256,
            cumulative_api_cost_usd=0.0,
            metadata={"condition": args.condition, "evidence_role": "consumed-development-only"},
        ),
        backend=backend,
        policy=node_policy,
        profile=profile,
        request_id=f"mlrc-perception-{args.condition}-patch-{args.iteration}",
    )
    output.mkdir(parents=True)
    _write_json(output / "PATCH_INPUT.json", input_data.model_dump(mode="json"))
    _write_json(output / "NODE_RESULT.json", result.model_dump(mode="json"))
    if result.status is not NodeResultStatus.ACCEPTED or result.proposal is None:
        raise ValueError(
            "benchmark patch proposal was rejected: " + "; ".join(result.rejection_reasons)
        )
    if result.proposal.decision != "propose":
        raise ValueError("benchmark patch model stopped without a development proposal")
    proposal = materialize_benchmark_patch_proposal(
        result.proposal,
        input_data,
        proposal_id=f"mlrc-perception-{args.condition}-patch-{args.iteration}",
        producer=BenchmarkPatchProducer(
            mode="model",
            producer_id="benchmark-research-patch",
            provider=result.response.backend,
            model=result.response.model,
            request_sha256=result.request.fingerprint,
            response_sha256=result.response.raw_response_sha256,
        ),
    )
    _write_json(output / "PATCH_PROPOSAL.json", proposal.model_dump(mode="json"))
    arm_source = output / "arm_source"
    shutil.copytree(env_source, arm_source)
    for edit in proposal.edits:
        _validate_replacement(edit.path, edit.replacement)
        target = (arm_source / edit.path).resolve()
        target.relative_to(arm_source.resolve())
        if _sha256_bytes(target.read_bytes()) != edit.expected_sha256:
            raise ValueError(f"source changed before patch application: {edit.path}")
        target.write_text(edit.replacement, encoding="utf-8")
    receipt = {
        "schema_version": "1.0",
        "condition": args.condition,
        "evidence_role": "consumed-development-only",
        "formal_evidence_eligible": False,
        "source_commit": "0d26417034811d2d4587646c4520cc305ea09dd6",
        "source_context_sha256": context.context_sha256,
        "proposal_sha256": proposal.fingerprint,
        "request_sha256": result.request.fingerprint,
        "response_sha256": result.response.raw_response_sha256,
        "provider": result.response.backend,
        "model": result.response.model,
        "usage": result.response.usage.model_dump(mode="json"),
        "edited_paths": [item.path for item in proposal.edits],
        "taste_control_packet_sha256": (
            control_packet.fingerprint if control_packet is not None else None
        ),
        "taste_control_packet_abstained": (
            control_packet.abstained if control_packet is not None else None
        ),
        "selected_research_action_id": (
            action_directive.action_id if action_directive is not None else None
        ),
        "research_action_directive_sha256": (
            action_directive.directive_sha256 if action_directive is not None else None
        ),
        "heldout_opened": False,
        "experiment_executed": False,
    }
    receipt["receipt_sha256"] = content_sha256(receipt)
    _write_json(output / "PREPARATION_RECEIPT.json", receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

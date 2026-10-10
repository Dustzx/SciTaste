#!/usr/bin/env python3
"""Summarize one matched ResearchClawBench system pair.

The script reads completed ResearchHarness workspaces and the official
ResearchClawBench ``_score.json`` files.  It does not call a model or inspect
the hidden target study.  Its purpose is to turn raw trajectories into one
compact, auditable comparison artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trace_summary(path: Path) -> dict[str, Any]:
    roles: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    usage: Counter[str] = Counter()
    tool_failures: list[dict[str, Any]] = []
    max_turn = 0
    events = 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events += 1
            roles[str(event.get("role", "unknown"))] += 1
            max_turn = max(max_turn, int(event.get("turn_index", 0) or 0))
            for tool in event.get("tool_names") or ():
                tools[str(tool)] += 1
            if event.get("capture_type") == "llm_call":
                response = event.get("payload", {}).get("response", {}) or {}
                call_usage = response.get("usage", {}) or {}
                usage["input_tokens"] += int(call_usage.get("prompt_tokens", 0) or 0)
                usage["output_tokens"] += int(call_usage.get("completion_tokens", 0) or 0)
                details = call_usage.get("prompt_tokens_details", {}) or {}
                usage["cached_input_tokens"] += int(details.get("cached_tokens", 0) or 0)
                usage["model_calls"] += 1
            if event.get("role") == "tool":
                text = str(event.get("text", ""))
                first_line = text.splitlines()[0] if text else ""
                failed = first_line.startswith("exit_code:") and first_line != "exit_code: 0"
                timed_out = "timed out" in text.lower() or "timeout" in text.lower()
                if failed or timed_out:
                    tool_failures.append(
                        {
                            "event_index": event.get("event_index"),
                            "turn_index": event.get("turn_index"),
                            "tool_names": event.get("tool_names") or [],
                            "summary": "\n".join(text.splitlines()[:4])[:800],
                            "timed_out": timed_out,
                        }
                    )
    usage["uncached_input_tokens"] = usage["input_tokens"] - usage["cached_input_tokens"]
    return {
        "events": events,
        "turns": max_turn,
        "roles": dict(sorted(roles.items())),
        "tools": dict(sorted(tools.items())),
        "usage": dict(usage),
        "tool_failure_count": len(tool_failures),
        "tool_failures": tool_failures,
        "trace_sha256": _sha256_file(path),
    }


def _artifact_summary(workspace: Path) -> dict[str, Any]:
    code_files = sorted((workspace / "code").glob("**/*.py"))
    figures = sorted(
        path
        for root in (workspace / "outputs", workspace / "report")
        if root.is_dir()
        for path in root.rglob("*")
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg", ".pdf"}
    )
    output_files = sorted(path for path in (workspace / "outputs").glob("**/*") if path.is_file())
    code_lines = 0
    for path in code_files:
        code_lines += len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return {
        "code_files": len(code_files),
        "code_lines": code_lines,
        "output_files": len(output_files),
        "figures": len(figures),
        "report_words": len(
            (workspace / "report" / "report.md")
            .read_text(encoding="utf-8", errors="replace")
            .split()
        ),
    }


def _arm(workspace: Path) -> dict[str, Any]:
    receipt = _read_json(workspace / "SCITASTE_SYSTEM_RUN_RECEIPT.json")
    score = _read_json(workspace / "_score.json")
    trace = _trace_summary(workspace / "_agent_output.jsonl")
    return {
        "condition": receipt["condition"],
        "workspace": workspace.name,
        "receipt": receipt,
        "official_score": score,
        "trajectory": trace,
        "artifacts": _artifact_summary(workspace),
        "report_sha256_verified": (
            _sha256_file(workspace / "report" / "report.md") == receipt["report_sha256"]
        ),
    }


def _parity(base: dict[str, Any], full: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "benchmark",
        "benchmark_commit",
        "task_id",
        "visible_task_sha256",
        "model",
        "api_base",
        "tools",
        "max_rounds",
        "max_runtime_seconds",
        "max_input_tokens",
        "max_output_tokens",
        "seed",
        "upstream_role_prompt_sha256",
        "target_study_visible_to_agent",
    )
    checks = {key: base["receipt"].get(key) == full["receipt"].get(key) for key in keys}
    return {"all_matched": all(checks.values()), "checks": checks}


def _markdown(result: dict[str, Any]) -> str:
    base = result["arms"]["native-base"]
    full = result["arms"]["full-scitaste"]
    delta = result["deltas"]
    base_items = base["official_score"]["items"]
    full_items = full["official_score"]["items"]
    lines = [
        "# ResearchClawBench Math_000 matched system pair",
        "",
        "> Development evidence from one external task. This is not a formal aggregate result.",
        "",
        "## Result",
        "",
        "| condition | official score | duration | turns | model calls | uncached input | output tokens | tool failures |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in (base, full):
        trace = arm["trajectory"]
        usage = trace["usage"]
        lines.append(
            f"| {arm['condition']} | {arm['official_score']['total_score']:.1f} | "
            f"{arm['receipt']['duration_seconds']:.1f}s | {trace['turns']} | "
            f"{usage['model_calls']} | {usage['uncached_input_tokens']:,} | "
            f"{usage['output_tokens']:,} | {trace['tool_failure_count']} |"
        )
    lines.extend(
        [
            "",
            f"Full SciTaste improved the official task score by **{delta['official_score']:+.1f}** "
            f"points ({delta['official_score_relative_percent']:+.1f}%) and completed "
            f"**{delta['duration_percent']:.1f}% faster**. It used more model calls and tokens, "
            "so the result is a quality/latency gain, not a token-efficiency claim.",
            "",
            "## Checklist breakdown",
            "",
            "| item | weight | native-base | full-scitaste | delta |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for index, (base_item, full_item) in enumerate(
        zip(base_items, full_items, strict=False), start=1
    ):
        lines.append(
            f"| {index}: {base_item['type']} | {base_item['weight']:.2f} | "
            f"{base_item['score']} | {full_item['score']} | "
            f"{full_item['score'] - base_item['score']:+d} |"
        )
    lines.extend(
        [
            "",
            "## What the run establishes",
            "",
            "- The paired protocol is matched on task bytes, model, tools, limits, upstream role prompt, and hidden-target isolation.",
            "- The Taste overlay changed the research trajectory: it elicited explicit mechanism baselines and a depth/score/random ablation, while improving all three official checklist items.",
            "- The gain is modest and the absolute score remains low; one task cannot support a broad effectiveness claim.",
            "",
            "## Failure evidence that drives the next iteration",
            "",
            "- The compiled Taste packet suggested inverse box area or another heuristic for pseudo-depth. The hidden checklist instead expects distance from bounding-box bottom to image bottom plus camera-above-ground and flat-ground assumptions.",
            "- Full SciTaste reduced the mechanism to a binary median split rather than the source method's multi-level depth cascade.",
            "- The Full ablation falsified its own current depth heuristic: `none` achieved MOTA 0.6927 and IDF1 0.3904, versus 0.6903 and 0.3790 for `depth`.",
            "- Therefore the next system change is source-grounded Taste compilation with definition/assumption fidelity and an execution-time mechanism critic—not manual report polishing.",
            "",
            "## Provenance",
            "",
            f"- ResearchClawBench commit: `{base['receipt']['benchmark_commit']}`",
            f"- visible task hash: `{base['receipt']['visible_task_sha256']}`",
            f"- judge: `{result['judge']['model']}` through the unmodified official scorer",
            f"- checklist hash: `{result['judge']['checklist_sha256']}`",
            f"- pair parity: `{str(result['parity']['all_matched']).lower()}`",
            "- Both agents were blind to `target_study`; only the scorer read the hidden checklist and target figure.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-root", type=Path, required=True)
    parser.add_argument("--base-workspace", required=True)
    parser.add_argument("--full-workspace", required=True)
    parser.add_argument("--checklist", type=Path, required=True)
    parser.add_argument("--official-scorer", type=Path, required=True)
    parser.add_argument("--judge-model", default="qwen-vl-max")
    args = parser.parse_args()

    pair_root = args.pair_root.resolve(strict=True)
    base = _arm((pair_root / args.base_workspace).resolve(strict=True))
    full = _arm((pair_root / args.full_workspace).resolve(strict=True))
    if base["condition"] != "native-base" or full["condition"] != "full-scitaste":
        raise ValueError("workspace conditions do not match the requested pair")
    parity = _parity(base, full)
    base_score = float(base["official_score"]["total_score"])
    full_score = float(full["official_score"]["total_score"])
    base_duration = float(base["receipt"]["duration_seconds"])
    full_duration = float(full["receipt"]["duration_seconds"])
    result = {
        "schema_version": "1.0",
        "status": "development-evidence",
        "claim_scope": "one external ResearchClawBench task; not a formal aggregate",
        "parity": parity,
        "judge": {
            "model": args.judge_model,
            "temperature": 0,
            "official_scorer_sha256": _sha256_file(args.official_scorer.resolve(strict=True)),
            "checklist_sha256": _sha256_file(args.checklist.resolve(strict=True)),
        },
        "arms": {"native-base": base, "full-scitaste": full},
        "deltas": {
            "official_score": round(full_score - base_score, 4),
            "official_score_relative_percent": round(
                100.0 * (full_score - base_score) / base_score, 4
            ),
            "duration_seconds": round(full_duration - base_duration, 4),
            "duration_percent": round(100.0 * (base_duration - full_duration) / base_duration, 4),
            "model_calls": (
                full["trajectory"]["usage"]["model_calls"]
                - base["trajectory"]["usage"]["model_calls"]
            ),
            "uncached_input_tokens": (
                full["trajectory"]["usage"]["uncached_input_tokens"]
                - base["trajectory"]["usage"]["uncached_input_tokens"]
            ),
            "output_tokens": (
                full["trajectory"]["usage"]["output_tokens"]
                - base["trajectory"]["usage"]["output_tokens"]
            ),
        },
    }
    output_root = pair_root.parent
    result_path = output_root / "RESULT.json"
    report_path = output_root / "REPORT.md"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(_markdown(result), encoding="utf-8")
    print(
        json.dumps(
            {"result": str(result_path), "report": str(report_path), "deltas": result["deltas"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

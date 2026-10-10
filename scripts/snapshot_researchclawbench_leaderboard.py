#!/usr/bin/env python3
"""Freeze the public ResearchClawBench leaderboard for ecological comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def _load_protocol(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("protocol must be a YAML mapping")
    return value


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# ResearchClawBench public-agent snapshot",
        "",
        "This is a best-native ecological comparison, not a matched causal "
        "comparison. Models, budgets, configurations, and submission dates differ.",
        "",
        "| public autonomous agent | tasks | mean score | median score | mean cost (USD) |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in report["complete_autonomous_agents"]:
        cost = row["mean_cost_usd"]
        lines.append(
            f"| {row['agent']} | {row['task_count']} | {row['mean_score']:.3f} | "
            f"{row['median_score']:.3f} | {f'{cost:.3f}' if cost is not None else 'n/a'} |"
        )
    lines.extend(
        [
            "",
            f"Snapshot SHA-256: `{report['snapshot_sha256']}`",
            "",
            "Only agents with all registered tasks are shown. Standalone "
            "ResearchHarness model rows are retained in the raw snapshot but excluded "
            "from this framework table by the preregistered inclusion rule.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--snapshot",
        type=Path,
        help=(
            "project an already frozen leaderboard JSON instead of downloading the current endpoint"
        ),
    )
    args = parser.parse_args()

    protocol_path = args.protocol.resolve(strict=True)
    protocol = _load_protocol(protocol_path)
    source = protocol["ecological_comparison"]["source"]
    inclusion_rule = protocol["ecological_comparison"].get(
        "inclusion_rule",
        "Include every public non-ResearchHarness autonomous-agent row with a "
        "score for all registered tasks in the frozen leaderboard snapshot.",
    )
    if args.snapshot is None:
        request = urllib.request.Request(
            source, headers={"User-Agent": "SciTaste-evidence-snapshot"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
        snapshot_origin = "downloaded-at-capture"
    else:
        raw = args.snapshot.resolve(strict=True).read_bytes()
        snapshot_origin = "provided-frozen-snapshot"
    snapshot = json.loads(raw)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("scores"), dict):
        raise ValueError("leaderboard snapshot has an unsupported schema")

    selected_tasks = [item["task_id"] for item in protocol["population"]["tasks"]]
    rows = []
    for agent in snapshot.get("agents", []):
        if str(agent).startswith("ResearchHarness ("):
            continue
        scores = snapshot["scores"].get(agent, {})
        if not all(task_id in scores for task_id in selected_tasks):
            continue
        values = [float(scores[task_id]["score"]) for task_id in selected_tasks]
        costs = [
            float(scores[task_id]["cost_usd"])
            for task_id in selected_tasks
            if scores[task_id].get("cost_usd") is not None
        ]
        rows.append(
            {
                "agent": agent,
                "task_count": len(values),
                "mean_score": round(statistics.fmean(values), 6),
                "median_score": round(statistics.median(values), 6),
                "mean_cost_usd": round(statistics.fmean(costs), 6)
                if len(costs) == len(values)
                else None,
                "scores": dict(zip(selected_tasks, values, strict=True)),
            }
        )
    rows.sort(key=lambda item: (-item["mean_score"], item["agent"]))

    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    snapshot_path = output / "leaderboard.json"
    snapshot_path.write_bytes(raw)
    report = {
        "schema_version": "1.0",
        "source": source,
        "snapshot_origin": snapshot_origin,
        "captured_at": datetime.now(UTC).isoformat(),
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "protocol": str(protocol_path),
        "protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        "selected_tasks": selected_tasks,
        "inclusion_rule": inclusion_rule,
        "causal_interpretation": "prohibited",
        "complete_autonomous_agents": rows,
    }
    (output / "REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "REPORT.md").write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "snapshot_sha256": report["snapshot_sha256"],
                "complete_autonomous_agent_count": len(rows),
                "output": str(output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

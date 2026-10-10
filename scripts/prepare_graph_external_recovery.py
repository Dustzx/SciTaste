"""Retain a failed ARC assignment and freeze a budget-inheriting mapping recovery."""

import argparse
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

from scitaste.benchmark.open_research import digest, verified_asset
from scitaste.model_nodes.session_exchange import retain_json


def prepare(project, campaign, output, *, metadata_timeout_seconds=None, failure_kind=None):
    root, campaign = project.resolve(strict=True), campaign.resolve(strict=True)
    output = output.resolve()
    output.relative_to(root / "evaluations")
    old = json.loads(campaign.read_text())
    assigned = json.loads((campaign.parent / "ASSIGNMENTS.json").read_text())
    run = (root / assigned["autoresearchclaw"]["run"]).resolve(strict=True)
    run.relative_to(root / "evaluations")
    launch = json.loads((run / "EXECUTION_CONTRACT.json").read_text())
    closed = json.loads((run / "SESSION_CLOSED.json").read_text())
    if verified_asset(root, launch["benchmark_campaign"]) != campaign:
        raise ValueError("Original assignment does not bind this campaign")
    if closed["return_code"] == 0 or not closed["source_pin_unchanged"]:
        raise ValueError("Recovery requires a retained unsuccessful unmodified-source run")
    envelope = dict(old["resource_envelope"])
    charged_seconds = math.ceil(
        max(closed["wall_seconds"], time.time() - (run / "EXECUTION_CONTRACT.json").stat().st_mtime)
    )
    envelope["wall_seconds"] -= charged_seconds
    envelope["max_requests"] -= closed["retained_requests"]
    if min(envelope["wall_seconds"], envelope["max_requests"]) <= 0:
        raise ValueError("No original allocation remains")
    if metadata_timeout_seconds is not None and (
        not math.isfinite(metadata_timeout_seconds) or not 0 < metadata_timeout_seconds <= 900
    ):
        raise ValueError("Metadata timeout must be finite and in (0, 900]")
    metadata_recovery = metadata_timeout_seconds is not None
    if failure_kind not in {None, "session-transport-envelope", "process-interruption"}:
        raise ValueError("Unsupported recovery kind")
    transport_recovery = failure_kind == "session-transport-envelope"
    process_recovery = failure_kind == "process-interruption"
    if (transport_recovery or process_recovery) and metadata_recovery:
        raise ValueError("Transport recovery cannot also change metadata settings")
    if process_recovery:
        observation = verified_asset(
            root,
            {
                "locator": (run / closed["observation_locator"]).relative_to(root).as_posix(),
                "sha256": closed["observation_sha256"],
            },
        )
        retained = json.loads(observation.read_text())
        if (
            closed.get("native_close_receipt") is not False
            or retained.get("absence_of_live_arc_process_verified") is not True
            or retained.get("launch_sha256") != digest(run / "EXECUTION_CONTRACT.json")
            or retained.get("launcher_exit_code") != closed["return_code"]
        ):
            raise ValueError("Process recovery must bind the explicit observed interruption")
    preserve_brief = metadata_recovery or transport_recovery or process_recovery
    title = old.get("external_research_title") or (
        verified_asset(root, old["brief"]).read_text().splitlines()[0].lstrip("# ").strip()
    )
    if not title or len(title) > 240:
        raise ValueError("Task needs an explicit short title")
    brief = verified_asset(root, old["execution_brief"]).read_text()
    if not preserve_brief:
        brief += (
            "\n\n# Infrastructure recovery accounting\n"
            f"The original ARC assignment stopped before experiments. This separate recovery has "
            f"{envelope['wall_seconds']} seconds and "
            f"{envelope['max_requests']} requests remaining, "
            "not a reset of the earlier ceiling. "
            "The research task, data and scoring are unchanged. "
            "Use the complete task attachment as instructions; "
            "the short title is for native search.\n"
        )
    output.mkdir(parents=True, exist_ok=False)
    with (output / "EXECUTION_BRIEF.md").open("x") as stream:
        stream.write(brief)

    def binding(path):
        return {"locator": path.relative_to(root).as_posix(), "sha256": digest(path)}

    current = {
        **old,
        "campaign_id": output.name,
        "frozen_at": datetime.now(UTC).isoformat(),
        "arms": ["autoresearchclaw"],
        "execution_brief": binding(output / "EXECUTION_BRIEF.md"),
        "resource_envelope": envelope,
        "external_research_title": title,
        "external_task_mapping": "short topic and byte-preserved native stage attachment",
        **({"metadata_timeout_seconds": metadata_timeout_seconds} if metadata_recovery else {}),
        "engineering_recovery": {
            "original_campaign": binding(campaign),
            "original_launch": binding(run / "EXECUTION_CONTRACT.json"),
            "original_close": binding(run / "SESSION_CLOSED.json"),
            "charged_seconds": charged_seconds,
            "repair_gap_charged_seconds": max(0, charged_seconds - closed["wall_seconds"]),
            "charged_requests": closed["retained_requests"],
            "reason": (
                "Outer launcher terminated without a native close receipt; "
                "cause unknown, preserve observed failure and resume completed native prefix"
                if process_recovery
                else "Session reply envelope rejected additional version metadata; "
                "retain original failure and resume native stages with compatible transport"
                if transport_recovery
                else "Unconfigured arXiv requests read remained blocked; "
                "explicit runtime metadata timeout"
                if metadata_recovery
                else "Complete brief was reused as an overlong native literature query"
            ),
            "native_prefix_continuation": preserve_brief,
            "brief_bytes_preserved": preserve_brief,
            "resume_policy": "upstream native stage resume; no synthetic stage or decision",
            "fresh_response_author": True,
            "replaces_original_assignment": False,
            "new_independent_task": False,
        },
    }
    retain_json(output / "CAMPAIGN.json", current)
    retain_json(
        output / "ASSIGNMENTS.json",
        {"autoresearchclaw": {"run": f"evaluations/{output.name}-arc"}},
    )
    return {"campaign": str(output), "title": title, "remaining": envelope}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "campaign", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--metadata-timeout-seconds", type=float)
    parser.add_argument(
        "--failure-kind", choices=["session-transport-envelope", "process-interruption"]
    )
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                args.project,
                args.campaign,
                args.output,
                metadata_timeout_seconds=args.metadata_timeout_seconds,
                failure_kind=args.failure_kind,
            )
        )
    )

"""Resume a retained planning request, never a completed experiment or API call."""

import json


def planning_resume_stage(cycle, planning, command):
    return pending_resume_stage(cycle, planning, command, stage="next-plan")


def pending_resume_stage(cycle, planning, command, *, stage):
    """Select a bounded new process-attempt ID after checking the original binding.

    The coordinator lock and planner's own process lock prevent concurrent replay.
    Every resumed planner revalidates its original input/contract before consumption.
    """
    pending_path = planning / "SESSION_PENDING.json"
    if not pending_path.is_file() or (planning / "RESULT.json").exists():
        raise ValueError("Only an explicit pending session plan may resume")
    pending = json.loads(pending_path.read_text())
    if pending.get("status") != "awaiting-session-response" or pending.get("api_calls") != 0:
        raise ValueError("Not a pending no-API session request")
    marker = cycle / f"{stage}.started.json"
    original = json.loads(marker.read_text())["command"]
    if original != command or "--allow-api" in command or "--session-exchange" not in command:
        raise ValueError("Session continuation must retain the exact original command")
    contract = json.loads((planning / "CONTRACT.json").read_text())
    exchange = command[command.index("--session-exchange") + 1]
    if contract.get("session_exchange") != exchange:
        raise ValueError("Planning exchange differs from the retained contract")
    from pathlib import Path

    request = Path(pending["request"]).resolve(strict=True)
    request.relative_to(Path(exchange).resolve(strict=True))
    from scitaste.model_nodes.models import StructuredModelRequest

    payload = json.loads(request.read_text())
    recorded_fingerprint = payload.pop("fingerprint")
    bound = StructuredModelRequest.model_validate(payload)
    if (
        recorded_fingerprint != bound.fingerprint
        or request.name != bound.fingerprint + ".request.json"
    ):
        raise ValueError("Retained request fingerprint does not match its contents")
    for index in range(1, 4):
        # Native exposes many bounded node requests during one execution. Limit
        # attempts per request rather than stopping the entire run after three
        # successful handoffs. The executor separately caps unique requests.
        scope = f"-{bound.fingerprint[:16]}" if stage == "execution" else ""
        attempt = f"{stage}-session-resume{scope}-{index:02d}"
        if not (cycle / f"{attempt}.started.json").exists():
            return attempt
    raise ValueError("Three session continuation attempts exhausted; retain pending work")

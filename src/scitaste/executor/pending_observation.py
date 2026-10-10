"""Wait for the same reserved experiment without executing another action."""

import json
import time

from scitaste.executor.base import ExecutionResult, ExecutionStatus


def wait_for_terminal(
    initial, *, observe, output, max_seconds, interval=45, clock=time.monotonic, sleep=time.sleep
):
    if not 0 <= max_seconds <= 7200 or not 1 <= interval <= 60:
        raise ValueError("Observation wait must be explicitly bounded")
    result = ExecutionResult.model_validate(initial)
    deadline = clock() + max_seconds
    while result.status == ExecutionStatus.PLANNED and clock() < deadline:
        sleep(min(interval, max(0, deadline - clock())))
        try:
            observed = ExecutionResult.model_validate(observe())
            if observed.action_id != result.action_id:
                raise ValueError("Observation belongs to a different experiment")
            result = observed
            record = {"result": result.model_dump(mode="json")}
        except (OSError, TimeoutError) as exc:
            record = {"observation_unavailable": type(exc).__name__}
        with output.open("a") as stream:
            stream.write(json.dumps({**record, "automatic_relaunch": False}) + "\n")
    return result

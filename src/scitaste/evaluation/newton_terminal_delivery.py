"""A prospectively declared, common terminal handoff; never another experiment."""

from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.model_nodes.shared_ledger_backend import SharedLedgerStructuredBackend
from scitaste.project.models import content_sha256


def deliver_terminal_hypothesis(*, bridge, environment, output):
    if environment.submission is not None or not environment.experiments_used:
        return
    visible = {
        "problem": environment.research_problem,
        "history": [
            {"tool": s.action.name, "arguments": s.action.args, "observation": s.observation}
            for s in environment.trace.steps
        ],
    }
    request = StructuredModelRequest(
        request_id="common-terminal-delivery",
        node_name="terminal-evidence-delivery",
        stage="EVIDENCE",
        state_snapshot_id=content_sha256(visible),
        expected_backend=bridge.config.provider,
        expected_model=bridge.config.model,
        policy_id="common-terminal-delivery-v1",
        policy_fingerprint=content_sha256({"version": 1, "calls": 1, "extra_queries": 0}),
        system_instruction="The research trajectory has ended. Use only these observations to "
        "submit the best supported law in the exact task format. No more experiments or tools. "
        "Return one JSON object with final_solution (string or null) and rationale (string). "
        "Do not substitute a familiar textbook formula when the measurements contradict it.",
        input_payload=visible,
        output_schema={"type": "object", "required": ["final_solution", "rationale"]},
        prompt_version="common-terminal-v1",
    )
    response = SharedLedgerStructuredBackend(bridge, max_output_tokens=bridge.max_output).complete(
        request
    )
    retain_json(
        output / "TERMINAL_DELIVERY.json",
        {
            "original_stop_reason": environment.finish_reason,
            "original_submission": None,
            "additional_queries": 0,
            "common_protocol_not_original_controller": True,
            "response": response.model_dump(mode="json"),
        },
    )
    hypothesis = response.output_payload["final_solution"]
    if hypothesis is not None:
        environment.final_answer(hypothesis)

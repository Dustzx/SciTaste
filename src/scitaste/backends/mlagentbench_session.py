"""Session-authored completions for the unmodified upstream ResearchAgent.

Only the language-model transport is replaced. Planning, parsing and tool
selection stay upstream; session authorship is never labelled as an API model.
"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge
from scitaste.model_nodes.models import StructuredModelRequest
from scitaste.model_nodes.session_exchange import SessionStructuredBackend


class MLAgentBenchSessionBridge(MLAgentBenchProviderBridge):
    def __init__(self, *, log_root: Path, exchange: Path, wait_seconds=600, max_calls=20):
        self.root = log_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = SimpleNamespace(provider="assistant-session", model="session-authored")
        self.backend = SessionStructuredBackend(
            exchange, wait_seconds=wait_seconds, max_requests=max_calls
        )

    def complete_text(self, prompt, log_file, model, **kwargs):
        if model != self.config.model or not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Session requires its own model identity and a nonempty prompt")
        if len(prompt.encode()) > 100_000:
            raise ValueError("Upstream session prompt exceeds the request bound")
        allowed = {"temperature", "max_tokens_to_sample", "stop_sequences", "json_mode"}
        if set(kwargs) - allowed:
            raise ValueError("Unsupported upstream generation arguments")
        log = Path(log_file).resolve()
        relative = log.relative_to(self.root).as_posix()
        packet = {"prompt": prompt, "generation_constraints": kwargs, "log_identity": relative}
        identity = hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()
        request = StructuredModelRequest(
            request_id="upstream-session-" + identity[:24],
            node_name="upstream-mlagentbench-completion",
            stage="EVIDENCE",
            state_snapshot_id=identity,
            expected_backend=self.config.provider,
            expected_model=self.config.model,
            policy_id="upstream-agent-session-v1",
            policy_fingerprint=hashlib.sha256(b"upstream-text-only-transport-v1").hexdigest(),
            system_instruction=(
                "Supply the next completion for the original upstream research agent prompt. "
                "Preserve its required response format. Return the original completion as a "
                "string in the completion field, without changing the agent or its tools. "
                "Use only supplied observations; never inspect hidden benchmark/scorer files."
            ),
            input_payload=packet,
            output_schema={
                "type": "object",
                "required": ["completion"],
                "properties": {"completion": {"type": "string"}},
                "additionalProperties": False,
            },
            prompt_version="upstream-agent-session-v1",
        )
        response = self.backend.complete(request)
        content = response.output_payload.get("completion")
        if set(response.output_payload) != {"completion"} or not isinstance(content, str):
            raise ValueError("Session must supply exactly one plain-text completion")
        if not content.strip() or len(content.encode()) > 64_000:
            raise ValueError("Session completion is empty or exceeds the byte bound")
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as stream:
            stream.write(prompt + "\n\n" + content + "\n")
        return content

    def accounting(self):
        return {
            "api_calls": 0,
            "session_requests": len(list(self.backend.directory.glob("*.request.json"))),
            "session_responses": len(list(self.backend.directory.glob("*.response.json"))),
            "session_cost_usd": None,
            "actual_tokens": None,
            "cost_semantics": "No API calls; session cost and tokenizer usage unmeasured",
        }

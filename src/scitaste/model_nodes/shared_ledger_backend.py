"""Structured advice charged to the agent's existing serialized provider ledger.

This adapter creates no independent budget and performs no retries. As with the
bridge, one process must serialize all callers. Costs are conservative liability
estimates, not provider invoices. Profile-bearing requests retain their explicit
generation envelope and the underlying provider's live enablement.
"""

import hashlib
import json
import time

from scitaste.backends.base import Usage
from scitaste.backends.mlagentbench import MLAgentBenchProviderBridge
from scitaste.model_nodes.models import StructuredModelRequest, StructuredModelResponse


class SharedLedgerStructuredBackend:
    def __init__(self, bridge: MLAgentBenchProviderBridge, *, max_output_tokens=4096):
        if max_output_tokens <= 0:
            raise ValueError("Positive output limit required")
        self.bridge = bridge
        self.name = bridge.config.provider
        self.model = bridge.config.model
        self.config = bridge.config
        self.max_output_tokens = min(max_output_tokens, bridge.max_output)

    def complete(self, request: StructuredModelRequest) -> StructuredModelResponse:
        if (request.expected_backend, request.expected_model) != (self.name, self.model):
            raise ValueError("Structured request differs from the bound provider")
        envelope = request.generation_envelope
        maximum = self.max_output_tokens
        if envelope is not None:
            if envelope.deterministic_seed_supported:
                raise ValueError("Shared-ledger bridge does not send deterministic seeds")
            if envelope.max_output_tokens > self.max_output_tokens:
                raise ValueError("Generation profile exceeds the configured bridge output ceiling")
            maximum = envelope.max_output_tokens
        prompt = json.dumps(
            {
                "instruction": request.system_instruction
                + "\nReturn only a JSON object satisfying output_schema. Do not echo the "
                "instruction, input, output_schema, or transport wrapper keys in the output.",
                "input": request.input_payload,
                "output_schema": request.output_schema,
            },
            ensure_ascii=False,
        )
        if envelope is not None:
            prompt_bytes = len(prompt.encode("utf-8"))
            if prompt_bytes > envelope.max_request_bytes:
                raise ValueError("Structured prompt exceeds generation profile byte ceiling")
            # Deliberately conservative without a provider tokenizer. This is an
            # admission bound, not reported usage or a claim about actual tokens.
            if prompt_bytes + 1024 + maximum > envelope.context_window_tokens:
                raise ValueError("Structured prompt exceeds conservative context envelope")
        audit = self.bridge.root / "structured_requests"
        audit.mkdir(exist_ok=True)
        # Fingerprints avoid interpolating model/user-controlled request IDs into paths.
        prefix = audit / request.fingerprint
        with prefix.with_suffix(".request.json").open("x") as stream:
            stream.write(request.model_dump_json(indent=2))
        index = len(list(self.bridge.records.glob("*.json")))
        started = time.monotonic()
        content = self.bridge.complete_text(
            prompt,
            prefix.with_suffix(".log"),
            self.model,
            max_tokens_to_sample=maximum,
            stop_sequences=None,
            temperature=0,
            json_mode=True,
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        record = self.bridge.records / f"{index:05d}.json"
        raw = record.with_suffix(".response").read_text()
        provider = json.loads(raw)
        completion = json.loads(record.with_suffix(".completion").read_text())
        served_model = provider.get("model")
        if not isinstance(served_model, str) or not served_model:
            raise ValueError("Actual served model is required; request identity is not evidence")
        if provider["choices"][0]["message"].get("tool_calls"):
            raise ValueError("Structured advice cannot request provider tool execution")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            try:
                payload, end = json.JSONDecoder().raw_decode(content.lstrip())
            except json.JSONDecodeError:
                if request.node_name != "native-action-proposal":
                    raise
                from scitaste.model_nodes.proposal_json_repair import repair_proposal_delimiter

                payload, position = repair_proposal_delimiter(content)
                repair = {
                    "repair": "remove one redundant proposal close before rationale",
                    "removed_character_offset": position,
                    "removed_character": "}",
                    "schema_validated": True,
                }
            else:
                suffix = content.lstrip()[end:].strip()
                if not suffix or any(char not in "} ]\r\n\t" for char in suffix):
                    raise ValueError(
                        "Invalid structured JSON; semantic trailing content rejected"
                    ) from None
                repair = {
                    "repair": "discard redundant closing brackets only",
                    "discarded_suffix": suffix,
                }
            with prefix.with_suffix(".format-recovery.json").open("x") as stream:
                json.dump(
                    {
                        **repair,
                        "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                    },
                    stream,
                )
        if not isinstance(payload, dict):
            raise ValueError("Structured advice must be a JSON object")
        response = StructuredModelResponse(
            request_id=request.request_id,
            request_fingerprint=request.fingerprint,
            output_payload=payload,
            backend=self.name,
            model=served_model,
            raw_response=raw,
            raw_response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            latency_ms=elapsed_ms,
            usage=Usage(
                input_tokens=provider["usage"]["prompt_tokens"],
                output_tokens=provider["usage"]["completion_tokens"],
                cost_usd=completion["liability_usd"],
            ),
        )
        with prefix.with_suffix(".response.json").open("x") as stream:
            stream.write(response.model_dump_json(indent=2))
        with prefix.with_suffix(".accounting.json").open("x") as stream:
            json.dump(
                {
                    "provider_record": str(record.relative_to(self.bridge.root)),
                    "cost_semantics": "conservative USD liability; not invoice or tariff",
                    "shared_budget": True,
                    "seed_sent": False,
                    "profile_id": request.profile_id,
                    "profile_fingerprint": request.profile_fingerprint,
                    "effective_max_output_tokens": maximum,
                },
                stream,
            )
        return response

"""Provider bridge for the real upstream MLAgentBench agent, not a replacement agent.

Install after importing upstream modules, before constructing its agent. Upstream
planning, reflection, parsing and tools are untouched. Tool execution still needs
an isolated environment; installing this bridge does not authorize any tool.
"""

import json
import math
import os
import sys
from pathlib import Path

from scitaste.backends.openai_compatible import HttpxTransport


def provider_ledger_accounting(records: Path) -> dict:
    """One liability view for admission, progress and failure reporting; not a bill."""
    paths = sorted(records.glob("*.json"))
    total, unresolved = 0.0, 0
    for index, path in enumerate(paths):
        if path.name != f"{index:05d}.json":
            raise ValueError("Provider reservation ledger is not contiguous")
        completed = path.with_suffix(".completion")
        row = json.loads((completed if completed.exists() else path).read_text())
        value = row.get("liability_usd")
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Unknown provider liability cannot be treated as zero")
        if row.get("status") != ("completed" if completed.exists() else "reserved"):
            raise ValueError("Provider accounting record has inconsistent status")
        total += value
        unresolved += not completed.exists()
    return {
        "calls": len(paths),
        "liability_usd": total,
        "unresolved_reservations": unresolved,
        "cost_semantics": "usage ceiling plus unresolved reservations; not invoice",
    }


class ProviderBudgetExhausted(RuntimeError):
    """Expected admission stop, carrying numeric diagnostics but no prompt or key."""

    def __init__(self, *, calls, max_calls, spent, reserve, limit):
        super().__init__("MLAgentBench provider budget exhausted before request")
        self.details = {
            "calls": calls,
            "max_calls": max_calls,
            "spent_liability_usd": spent,
            "next_request_reservation_usd": reserve,
            "limit_usd": limit,
            "request_sent": False,
        }


class MLAgentBenchProviderBridge:
    """Single-process, serialized calls with persistent conservative reservations."""

    def __init__(
        self,
        *,
        config,
        log_root: Path,
        max_cost_usd=2.0,
        max_calls=20,
        max_output_tokens=4096,
        max_request_bytes=100_000,
        transport=None,
    ):
        self.config = config
        self.root = log_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.records = self.root / "provider_calls"
        self.records.mkdir(exist_ok=True)
        self.max_cost = max_cost_usd
        self.max_calls = max_calls
        self.max_output = max_output_tokens
        self.max_request_bytes = max_request_bytes
        self.transport = transport or HttpxTransport()
        if max_cost_usd <= 0 or max_calls <= 0 or max_output_tokens <= 0 or max_request_bytes <= 0:
            raise ValueError("provider budgets must be positive")

    def complete_text(self, prompt, log_file, model, **kwargs):
        if model != self.config.model:
            raise ValueError("upstream model differs from the bound provider model")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("a nonempty upstream prompt is required")
        log = Path(log_file).resolve()
        log.relative_to(self.root)
        unsupported = set(kwargs) - {
            "temperature",
            "max_tokens_to_sample",
            "stop_sequences",
            "json_mode",
        }
        if unsupported:
            raise ValueError(f"unsupported upstream completion arguments: {sorted(unsupported)}")
        if "json_mode" in kwargs and type(kwargs["json_mode"]) is not bool:
            raise ValueError("json_mode must be an explicit boolean")
        maximum = min(int(kwargs.get("max_tokens_to_sample", self.max_output)), self.max_output)
        if maximum <= 0 or len(prompt.encode()) > self.max_request_bytes:
            raise ValueError("request exceeds the bounded development interface")
        # Conservative USD liability convention, not an invoice or provider tariff.
        # UTF-8 bytes plus chat overhead deliberately overestimate input tokens.
        reserve = ((len(prompt.encode()) + 1024) * 12 + maximum * 36) / 1e6
        accounting = provider_ledger_accounting(self.records)
        spent = accounting["liability_usd"]
        if accounting["calls"] >= self.max_calls or spent + reserve > self.max_cost:
            raise ProviderBudgetExhausted(
                calls=accounting["calls"],
                max_calls=self.max_calls,
                spent=spent,
                reserve=reserve,
                limit=self.max_cost,
            )
        key = os.environ.get(self.config.api_key_env)
        if not key:
            raise RuntimeError("bound provider credential is unavailable")
        payload = {
            **self.config.extra_body,
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": maximum,
            "temperature": kwargs.get("temperature", 0.5),
            "stop": kwargs.get("stop_sequences", ["Observation:"]),
        }
        if kwargs.get("json_mode"):
            payload["response_format"] = {"type": "json_object"}
        record = self.records / f"{accounting['calls']:05d}.json"
        row = {"request": payload, "status": "reserved", "liability_usd": reserve}
        # Exclusive reservation survives transport failure; never retry implicitly.
        with record.open("x") as stream:
            json.dump(row, stream)
        response = self.transport.post(
            self.config.base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            payload=payload,
            timeout=180,
        )
        response_path = record.with_suffix(".response")
        with response_path.open("x") as stream:
            json.dump(response, stream)
        usage = response.get("usage", {})
        if any(
            type(usage.get(name)) is not int or usage[name] < 0
            for name in ("prompt_tokens", "completion_tokens")
        ):
            raise ValueError("provider usage is missing; reservation remains charged")
        actual = (usage["prompt_tokens"] * 12 + usage["completion_tokens"] * 36) / 1e6
        content = response["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("provider returned no usable agent completion")
        row.update(
            status="completed",
            liability_usd=actual,
            observed_usage_ceiling_usd=actual,
            served_model=response.get("model"),
        )
        # Keep the pre-call reservation immutable. Completion is a separate record.
        with record.with_suffix(".completion").open("x") as stream:
            json.dump(row, stream)
        if actual > reserve:
            raise RuntimeError("usage exceeded reservation; stop before agent continuation")
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as stream:
            stream.write(prompt + "\n\n" + content + "\n")
        cost_path = self.root / "env_log" / "api_cost.json"
        cost_path.parent.mkdir(exist_ok=True)
        cost_path.write_text(
            json.dumps(
                {
                    "total_cost": spent + actual,
                    "cost_semantics": "usage ceiling plus unresolved reservations; not invoice",
                }
            )
        )
        return content

    def complete_text_fast(self, prompt, **kwargs):
        kwargs.setdefault("temperature", 0.01)
        model = kwargs.pop("model", self.config.model)
        return self.complete_text(prompt, model=model, **kwargs)

    def install(self):
        """Patch imported function references, preserving upstream implementation."""
        patched = []
        for name, module in list(sys.modules.items()):
            if not name.startswith("MLAgentBench.") or module is None:
                continue
            for attribute in ("complete_text", "complete_text_fast"):
                if hasattr(module, attribute):
                    setattr(module, attribute, getattr(self, attribute))
                    patched.append(name + "." + attribute)
        if "MLAgentBench.agents.agent_research.complete_text" not in patched:
            raise ValueError("import the actual upstream ResearchAgent before installing")
        return patched

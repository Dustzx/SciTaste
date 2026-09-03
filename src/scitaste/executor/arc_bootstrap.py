"""Process-local compatibility controls before delegating to upstream's CLI."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def main(argv: Sequence[str] | None = None) -> int:
    """Run unmodified ResearchClaw with an explicit per-call output-token ceiling."""

    raw_limit = os.environ.get("SCITASTE_ARC_MAX_OUTPUT_TOKENS", "")
    raw_total_limit = os.environ.get("SCITASTE_ARC_MAX_TOTAL_TOKENS", "")
    telemetry_path = os.environ.get("SCITASTE_ARC_TELEMETRY_PATH", "")
    if os.environ.get("SCITASTE_ARC_OFFLINE", "").casefold() in {"1", "true", "yes"}:
        from researchclaw.literature import search as literature_search

        literature_search.search_papers = lambda *args, **kwargs: []
        literature_search.search_papers_multi_query = lambda *args, **kwargs: []
    if os.environ.get("SCITASTE_ARC_DISABLE_THINKING", "").casefold() in {"1", "true", "yes"}:
        import urllib.request

        upstream_request = urllib.request.Request

        def controlled_request(url: Any, data: Any = None, *args: Any, **kwargs: Any):
            if isinstance(data, bytes):
                try:
                    body = json.loads(data)
                except (TypeError, ValueError):
                    body = None
                if (
                    isinstance(body, dict)
                    and "model" in body
                    and ("messages" in body or "input" in body)
                ):
                    body["enable_thinking"] = False
                    data = json.dumps(body).encode("utf-8")
            return upstream_request(url, data, *args, **kwargs)

        urllib.request.Request = controlled_request
    if raw_limit or raw_total_limit or telemetry_path:
        limit = int(raw_limit) if raw_limit else 0
        total_limit = int(raw_total_limit) if raw_total_limit else 0
        if raw_limit and limit <= 0:
            raise ValueError("SCITASTE_ARC_MAX_OUTPUT_TOKENS must be positive")
        if raw_total_limit and total_limit <= 0:
            raise ValueError("SCITASTE_ARC_MAX_TOTAL_TOKENS must be positive")
        from researchclaw.llm.client import LLMClient

        upstream_chat = LLMClient.chat
        cumulative_tokens = 0
        if telemetry_path and Path(telemetry_path).is_file():
            for line in Path(telemetry_path).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    cumulative_tokens += int(json.loads(line).get("total_tokens", 0) or 0)

        def request_size_upper_bound(args: tuple[Any, ...], kwargs: dict[str, Any]) -> int:
            """Return a conservative token bound without provider-specific tokenizers."""

            payload = {
                "args": args,
                "messages": kwargs.get("messages"),
                "system": kwargs.get("system"),
            }
            rendered = json.dumps(payload, ensure_ascii=False, default=str)
            # These English/code prompts empirically track about four UTF-8 bytes
            # per provider-counted token. Exact usage is still checked after every
            # response, so this estimate only sizes the remaining output allowance.
            return max(1, (len(rendered.encode("utf-8")) + 3) // 4)

        def bounded_chat(self, *args: Any, **kwargs: Any):
            nonlocal cumulative_tokens
            if raw_limit:
                requested = kwargs.get("max_tokens")
                kwargs["max_tokens"] = limit if requested is None else min(int(requested), limit)
            if raw_total_limit:
                remaining = total_limit - cumulative_tokens
                prompt_bound = request_size_upper_bound(args, kwargs)
                available_output = remaining - prompt_bound
                if available_output <= 0:
                    raise RuntimeError(
                        "SciTaste cumulative LLM token budget exhausted before request"
                    )
                requested = int(kwargs.get("max_tokens") or available_output)
                kwargs["max_tokens"] = min(requested, available_output)
            started = time.perf_counter()
            response = upstream_chat(self, *args, **kwargs)
            observed_tokens = int(getattr(response, "total_tokens", 0) or 0)
            cumulative_tokens += observed_tokens
            if telemetry_path:
                record = {
                    "schema_version": "1.0",
                    "model": getattr(response, "model", ""),
                    "prompt_tokens": int(getattr(response, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(response, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(response, "total_tokens", 0) or 0),
                    "latency_seconds": time.perf_counter() - started,
                }
                destination = Path(telemetry_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
            if raw_total_limit and cumulative_tokens > total_limit:
                raise RuntimeError(
                    "SciTaste cumulative LLM token budget exceeded: "
                    f"{cumulative_tokens} > {total_limit}"
                )
            return response

        LLMClient.chat = bounded_chat

    from researchclaw.cli import main as upstream_main

    return upstream_main(list(argv) if argv is not None else None)


if __name__ == "__main__":  # pragma: no cover - exercised in the child process
    raise SystemExit(main())

"""Process-local compatibility controls before delegating to upstream's CLI."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any


def main(argv: Sequence[str] | None = None) -> int:
    """Run unmodified ResearchClaw with an explicit per-call output-token ceiling."""

    raw_limit = os.environ.get("SCITASTE_ARC_MAX_OUTPUT_TOKENS", "")
    if raw_limit:
        limit = int(raw_limit)
        if limit <= 0:
            raise ValueError("SCITASTE_ARC_MAX_OUTPUT_TOKENS must be positive")
        from researchclaw.llm.client import LLMClient

        upstream_chat = LLMClient.chat

        def bounded_chat(self, *args: Any, **kwargs: Any):
            requested = kwargs.get("max_tokens")
            kwargs["max_tokens"] = limit if requested is None else min(int(requested), limit)
            return upstream_chat(self, *args, **kwargs)

        LLMClient.chat = bounded_chat

    from researchclaw.cli import main as upstream_main

    return upstream_main(list(argv) if argv is not None else None)


if __name__ == "__main__":  # pragma: no cover - exercised in the child process
    raise SystemExit(main())

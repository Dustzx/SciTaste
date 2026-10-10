"""Recover one redundant proposal delimiter without editing any scalar value."""

import json
import re


def repair_proposal_delimiter(content: str) -> tuple[dict, int]:
    # Strings are atomic: braces inside code, rationales or escaped quotes are
    # never candidates. Only the observed extra-close-before-rationale is eligible.
    from pydantic import ValidationError

    from scitaste.research_tool_loop import ResearchToolProposalBatch

    tokens = list(re.finditer(r'"(?:[^"\\]|\\.)*"|[^\s]', content))
    candidates = {}
    for index in range(len(tokens) - 4):
        if [token.group() for token in tokens[index : index + 5]] != [
            "}",
            "}",
            ",",
            '"rationale"',
            ":",
        ]:
            continue
        position = tokens[index + 1].start()
        repaired = content[:position] + content[position + 1 :]
        try:
            payload = json.loads(repaired)
            ResearchToolProposalBatch.model_validate(payload)
        except (ValueError, ValidationError):
            continue
        candidates[repaired] = (payload, position)
    if len(candidates) != 1:
        raise ValueError("No unique schema-valid proposal delimiter recovery")
    return next(iter(candidates.values()))

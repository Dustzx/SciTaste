"""Bounded punctuation-only recovery of retained prose JSON; never repairs prose."""

import json


def recover_extra_closing_braces(text: str, *, max_deletions: int = 6):
    """Require a unique recovered byte string; only delete unquoted closing braces."""
    if len(text) > 200000 or not 0 <= max_deletions <= 6:
        raise ValueError("JSON recovery exceeds bounded input or edit limit")
    queue = [(text, [])]
    seen = set()
    solutions = {}
    while queue:
        current, edits = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        if len(seen) > 256:
            raise ValueError("JSON recovery search exceeds bound")
        try:
            parsed = json.loads(current)
        except json.JSONDecodeError as error:
            if len(edits) >= max_deletions:
                continue
            quoted, escaped = False, False
            candidates = []
            for index, char in enumerate(current[: error.pos + 2]):
                if quoted:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        quoted = False
                elif char == '"':
                    quoted = True
                elif char == "}" and abs(index - error.pos) <= 2:
                    candidates.append(index)
            for index in candidates:
                queue.append((current[:index] + current[index + 1 :], [*edits, index]))
        else:
            if isinstance(parsed, dict):
                solutions[current] = (parsed, edits)
    if len(solutions) != 1:
        raise ValueError("No unique punctuation-only JSON recovery")
    normalized, (payload, edits) = next(iter(solutions.items()))
    return payload, normalized, edits

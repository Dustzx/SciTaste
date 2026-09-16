from __future__ import annotations

from collections import Counter

import pytest

from scitaste.evaluation.action_diverse_taste_development import (
    select_balanced_action_turns,
)


def _availability() -> dict[str, dict[str, int]]:
    return {
        "source-a": {"PROBE": 1},
        "source-b": {"PROBE": 1},
        "source-c": {"PROBE": 1},
        "source-d": {"PROBE": 1, "ANALYZE": 2},
        "source-e": {"PROBE": 1, "ANALYZE": 2},
        "source-f": {"PROBE": 1, "ANALYZE": 2},
        "source-g": {"PROBE": 1, "ANALYZE": 2},
        "source-h": {"PROBE": 1, "ANALYZE": 2},
    }


def test_balanced_selection_is_source_unique_deterministic_and_quota_closed() -> None:
    quotas = {"PROBE": 4, "ANALYZE": 4}
    first = select_balanced_action_turns(
        _availability(),
        quotas=quotas,
        salt="fixed-development-salt",
    )
    second = select_balanced_action_turns(
        dict(reversed(tuple(_availability().items()))),
        quotas=quotas,
        salt="fixed-development-salt",
    )

    assert first == second
    assert len(first) == 8
    assert Counter(action for action, _turn in first.values()) == Counter(quotas)
    assert all(turn == _availability()[source][action] for source, (action, turn) in first.items())


def test_balanced_selection_rejects_infeasible_action_coverage() -> None:
    availability = _availability()
    for source in availability.values():
        source.pop("ANALYZE", None)

    with pytest.raises(ValueError, match="no source-unique action-balanced assignment"):
        select_balanced_action_turns(
            availability,
            quotas={"PROBE": 4, "ANALYZE": 4},
            salt="fixed-development-salt",
        )

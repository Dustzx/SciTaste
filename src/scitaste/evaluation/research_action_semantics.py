"""Task-paradigm semantics for high-level autonomous-research actions."""

from __future__ import annotations

from enum import StrEnum

from scitaste.project.models import content_sha256


class ResearchActionSemanticsProfile(StrEnum):
    GENERIC_RESEARCH = "generic-research-v1"
    HIDDEN_LAW_DISCOVERY = "hidden-law-discovery-v1"


_SEMANTICS = {
    ResearchActionSemanticsProfile.GENERIC_RESEARCH: {
        "PROBE": "Make the smallest diagnostic change that can separate explanations.",
        "PILOT": "Run a bounded pilot change before committing to a broad intervention.",
        "EXPERIMENT": "Test the strongest current improvement hypothesis directly.",
        "ANALYZE": "Use observed failures to target the next research change.",
        "REFINE": "Refine the best current mechanism without widening the task scope.",
        "PIVOT": "Change the mechanism when accumulated feedback rejects the current path.",
        "STOP": "Stop when another research action is not scientifically justified.",
    },
    ResearchActionSemanticsProfile.HIDDEN_LAW_DISCOVERY: {
        "PROBE": (
            "Probe broad parameter extremes and isolate one variable at a time to reveal "
            "qualitative dependencies before committing to a formula."
        ),
        "PILOT": (
            "Choose one plausible law family and run a small local pilot that can cheaply reject "
            "it before spending the remaining experiment budget."
        ),
        "EXPERIMENT": (
            "Design decisive experiments where the strongest competing formulas make maximally "
            "different predictions; target falsification rather than more coverage."
        ),
        "ANALYZE": (
            "Analyze the visible observations to compare candidate dependencies, constants, and "
            "units, then run only the single most diagnostic confirmation."
        ),
        "REFINE": (
            "Keep the best-supported functional form and run targeted measurements that refine "
            "its exponents, constants, or boundary behavior."
        ),
        "PIVOT": (
            "Treat the current functional form as rejected; test a qualitatively different "
            "dependency or interaction using observations that distinguish the new family."
        ),
        "STOP": "Submit the strongest law supported by the complete visible experiment history.",
    },
}


def research_action_instruction(
    profile: ResearchActionSemanticsProfile,
    action_type: str,
) -> str:
    try:
        return _SEMANTICS[profile][action_type]
    except KeyError as exc:
        raise ValueError(
            f"action {action_type!r} is unavailable in semantics profile {profile.value!r}"
        ) from exc


def research_action_semantics_sha256(profile: ResearchActionSemanticsProfile) -> str:
    return content_sha256(
        {
            "profile": profile.value,
            "instructions": _SEMANTICS[profile],
        }
    )


__all__ = [
    "ResearchActionSemanticsProfile",
    "research_action_instruction",
    "research_action_semantics_sha256",
]

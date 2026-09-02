"""Decomposed deterministic critics for contract-backed scientific writing."""

from __future__ import annotations

from typing import Protocol

from scitaste.state.research_state import ResearchState, WritingCritique


class WritingCritic(Protocol):
    name: str

    def review(self, state: ResearchState) -> list[WritingCritique]: ...


def _finding(critic: str, message: str, *, severity: str = "error") -> WritingCritique:
    return WritingCritique(critic=critic, severity=severity, message=message)


class SubstanceCritic:
    name = "substance"

    def review(self, state: ResearchState) -> list[WritingCritique]:
        writing = state.writing_state
        if writing is None:
            return [_finding(self.name, "writing state is missing")]
        claims = {claim.claim_id: claim for claim in state.claims}
        used = {
            item for contract in writing.section_contracts for item in contract.required_claim_ids
        }
        return [
            _finding(self.name, f"claim {claim_id} is {claims[claim_id].status}")
            for claim_id in sorted(used)
            if claims[claim_id].status not in {"supported", "partially_supported"}
        ]


class NarrativeCritic:
    name = "narrative"

    def review(self, state: ResearchState) -> list[WritingCritique]:
        if state.narrative_spine is None:
            return [_finding(self.name, "narrative spine is missing")]
        return []


class ClaimEvidenceCritic:
    name = "claim_evidence"

    def review(self, state: ResearchState) -> list[WritingCritique]:
        writing = state.writing_state
        if writing is None:
            return []
        evidence = {item.evidence_id: item for item in state.evidence_graph.items}
        findings: list[WritingCritique] = []
        for contract in writing.section_contracts:
            for claim_id in contract.required_claim_ids:
                linked = [
                    evidence[item]
                    for item in contract.required_evidence_ids
                    if item in evidence
                    and claim_id
                    in {
                        *evidence[item].supports_claim_ids,
                        *evidence[item].relates_to_claim_ids,
                    }
                ]
                if not linked:
                    findings.append(
                        _finding(
                            self.name,
                            f"section {contract.section_name} does not link "
                            f"claim {claim_id} to evidence",
                        )
                    )
        return findings


class RedundancyCritic:
    name = "redundancy"

    def review(self, state: ResearchState) -> list[WritingCritique]:
        drafts = list((state.writing_state.section_drafts if state.writing_state else {}).values())
        normalized = [" ".join(item.split()).casefold() for item in drafts if item.strip()]
        return (
            [_finding(self.name, "duplicate section drafts detected")]
            if len(normalized) != len(set(normalized))
            else []
        )


class StyleCritic:
    name = "style"

    def review(self, state: ResearchState) -> list[WritingCritique]:
        writing = state.writing_state
        if writing is None:
            return []
        return [
            _finding(self.name, f"section {contract.section_name} has no draft")
            for contract in writing.section_contracts
            if not writing.section_drafts.get(contract.section_name, "").strip()
        ]


class VenueStyleCritic:
    name = "venue_style"

    def review(self, state: ResearchState) -> list[WritingCritique]:
        return (
            []
            if state.target_venue
            else [_finding(self.name, "target venue is unspecified", severity="warning")]
        )


class TerminologyCritic:
    name = "terminology"

    def review(self, state: ResearchState) -> list[WritingCritique]:
        drafts = " ".join(
            (state.writing_state.section_drafts if state.writing_state else {}).values()
        )
        if "SciTaste" in drafts and "Sci Taste" in drafts:
            return [_finding(self.name, "inconsistent SciTaste terminology")]
        return []


class CitationCritic:
    name = "citation"

    def review(self, state: ResearchState) -> list[WritingCritique]:
        writing = state.writing_state
        if writing is None:
            return []
        findings: list[WritingCritique] = []
        for contract in writing.section_contracts:
            draft = writing.section_drafts.get(contract.section_name, "")
            for evidence_id in contract.required_evidence_ids:
                if f"[evidence:{evidence_id}]" not in draft:
                    findings.append(
                        _finding(
                            self.name,
                            f"section {contract.section_name} omits evidence {evidence_id}",
                        )
                    )
        return findings


class GlobalCoherenceCritic:
    name = "global_coherence"

    def review(self, state: ResearchState) -> list[WritingCritique]:
        writing = state.writing_state
        if writing is None:
            return []
        contracted = {item.section_name for item in writing.section_contracts}
        drafted = {name for name, text in writing.section_drafts.items() if text.strip()}
        return (
            [_finding(self.name, "not every contracted section has a draft")]
            if contracted - drafted
            else []
        )


class WritingCriticSuite:
    def __init__(self) -> None:
        self.critics: tuple[WritingCritic, ...] = (
            SubstanceCritic(),
            NarrativeCritic(),
            ClaimEvidenceCritic(),
            RedundancyCritic(),
            StyleCritic(),
            VenueStyleCritic(),
            TerminologyCritic(),
            CitationCritic(),
            GlobalCoherenceCritic(),
        )

    def review(self, state: ResearchState) -> list[WritingCritique]:
        return [finding for critic in self.critics for finding in critic.review(state)]

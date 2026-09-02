"""Deterministic contract-backed drafts used by offline acceptance tests."""

from __future__ import annotations

from scitaste.state.research_state import ResearchObligation, WritingState


class ContractDrafter:
    def draft(self, writing: WritingState) -> dict[str, str]:
        drafts: dict[str, str] = {}
        for section in writing.section_contracts:
            paragraphs = sorted(
                (
                    item
                    for item in writing.paragraph_contracts
                    if item.section_name == section.section_name
                ),
                key=lambda item: item.paragraph_index,
            )
            rendered = []
            for paragraph in paragraphs:
                trace = " ".join(
                    [
                        *(f"[claim:{item}]" for item in paragraph.claim_ids),
                        *(f"[evidence:{item}]" for item in paragraph.evidence_ids),
                    ]
                )
                rendered.append(f"{paragraph.intended_takeaway} {trace}".strip())
            drafts[section.section_name] = "\n\n".join(rendered)
        return drafts

    def revise(self, writing: WritingState, obligation: ResearchObligation) -> dict[str, str]:
        drafts = dict(writing.section_drafts)
        section = str(obligation.required_action.get("target_section") or "Discussion")
        evidence = " ".join(
            f"[evidence:{identifier}]" for identifier in obligation.resolution_evidence_ids
        )
        note = (
            f"Review resolution {obligation.obligation_id}: "
            f"{obligation.resolution_summary or 'obligation satisfied'}. {evidence}"
        ).strip()
        drafts[section] = "\n\n".join(filter(None, [drafts.get(section), note]))
        return drafts

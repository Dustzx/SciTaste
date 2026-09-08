"""Deterministic manuscript-role and completeness assessment."""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import content_sha256

ManuscriptRole = Literal["integration-fixture", "research-working-draft"]

RESEARCH_WORKING_DRAFT_MINIMUM_WORDS = 2_500
_REQUIRED_RESEARCH_SECTIONS = (
    "abstract",
    "introduction",
    "method",
    "evaluation",
    "results",
    "limitations",
    "conclusion",
)
_SECTION_ALIASES = {
    "abstract": ("abstract",),
    "introduction": ("introduction",),
    "method": ("method", "methods", "approach", "framework", "system"),
    "evaluation": (
        "evaluation",
        "evaluation protocol",
        "experimental setup",
        "experiments",
    ),
    "results": ("results", "evaluation results", "experimental results"),
    "limitations": ("limitations", "limitations and risks"),
    "conclusion": ("conclusion", "conclusions"),
}
_PLACEHOLDER_PATTERNS = (
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bTBD\b", re.IGNORECASE),
    re.compile(r"\[citation needed\]", re.IGNORECASE),
    re.compile(r"lorem ipsum", re.IGNORECASE),
)
_WORD = re.compile(r"[A-Za-z0-9]+(?:[.'-][A-Za-z0-9]+)*|[\u3400-\u9fff]")
_HEADING = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
_TITLE_BLOCK = re.compile(r"(?ims)^#{1,2}\s+title\s*$\s*(.+?)(?=^#{1,2}\s+|\Z)")


class ManuscriptAssessment(BaseModel):
    """Self-hashed classification evidence for one rendered Markdown manuscript."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    requested_role: ManuscriptRole
    title: str = Field(min_length=1)
    manuscript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    word_count: int = Field(ge=0)
    section_count: int = Field(ge=0)
    sections: tuple[str, ...]
    minimum_research_words: int = RESEARCH_WORKING_DRAFT_MINIMUM_WORDS
    required_research_sections: tuple[str, ...] = _REQUIRED_RESEARCH_SECTIONS
    missing_research_sections: tuple[str, ...]
    placeholder_markers: tuple[str, ...]
    substantive_research_draft: bool
    eligible_for_requested_role: bool
    paper_status: Literal["integration-fixture", "research-working-draft"]
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: object) -> ManuscriptAssessment:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def record_is_self_hashed(self) -> ManuscriptAssessment:
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("manuscript assessment hash mismatch")
        if self.requested_role == "integration-fixture":
            if not self.eligible_for_requested_role or self.paper_status != "integration-fixture":
                raise ValueError("integration fixture assessment is inconsistent")
        else:
            if self.paper_status != "research-working-draft":
                raise ValueError("research draft status is inconsistent")
            if self.eligible_for_requested_role != self.substantive_research_draft:
                raise ValueError("research draft eligibility differs from completeness result")
        return self


def assess_manuscript(markdown: str, *, requested_role: ManuscriptRole) -> ManuscriptAssessment:
    """Classify Markdown without interpreting scientific quality or correctness."""

    title_match = _TITLE_BLOCK.search(markdown)
    title = (
        _plain_heading(title_match.group(1).splitlines()[0])
        if title_match and title_match.group(1).splitlines()
        else "Untitled manuscript"
    )
    body = (
        markdown
        if title_match is None
        else markdown[: title_match.start()] + markdown[title_match.end() :]
    )
    sections = tuple(
        heading
        for heading in (_plain_heading(item) for item in _HEADING.findall(body))
        if heading and heading.casefold() != "title"
    )
    normalized_sections = tuple(_normalize_heading(item) for item in sections)
    present = {
        requirement
        for requirement, aliases in _SECTION_ALIASES.items()
        if any(_matches_section(section, aliases) for section in normalized_sections)
    }
    missing = tuple(item for item in _REQUIRED_RESEARCH_SECTIONS if item not in present)
    placeholders = tuple(
        pattern.pattern for pattern in _PLACEHOLDER_PATTERNS if pattern.search(markdown)
    )
    word_count = len(_WORD.findall(body))
    substantive = (
        word_count >= RESEARCH_WORKING_DRAFT_MINIMUM_WORDS and not missing and not placeholders
    )
    eligible = requested_role == "integration-fixture" or substantive
    status: Literal["integration-fixture", "research-working-draft"] = (
        "research-working-draft"
        if requested_role == "research-working-draft"
        else "integration-fixture"
    )
    return ManuscriptAssessment.create(
        requested_role=requested_role,
        title=title,
        manuscript_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        word_count=word_count,
        section_count=len(sections),
        sections=sections,
        missing_research_sections=missing,
        placeholder_markers=placeholders,
        substantive_research_draft=substantive,
        eligible_for_requested_role=eligible,
        paper_status=status,
    )


def require_requested_manuscript_role(assessment: ManuscriptAssessment) -> None:
    """Fail closed when a short fixture is requested as a research manuscript."""

    if assessment.eligible_for_requested_role:
        return
    details = [
        f"word_count={assessment.word_count}<{assessment.minimum_research_words}",
    ]
    if assessment.missing_research_sections:
        details.append("missing_sections=" + ",".join(assessment.missing_research_sections))
    if assessment.placeholder_markers:
        details.append("placeholder_markers=" + ",".join(assessment.placeholder_markers))
    raise ValueError("research manuscript completeness gate failed: " + "; ".join(details))


def _plain_heading(value: str) -> str:
    return re.sub(r"[*_`]", "", value).strip()


def _normalize_heading(value: str) -> str:
    plain = _plain_heading(value).casefold()
    plain = re.sub(r"^[0-9]+(?:\.[0-9]+)*[.)]?\s*", "", plain)
    return re.sub(r"\s+", " ", plain).strip()


def _matches_section(section: str, aliases: tuple[str, ...]) -> bool:
    return any(section == alias or section.startswith(alias + ":") for alias in aliases)


__all__ = [
    "RESEARCH_WORKING_DRAFT_MINIMUM_WORDS",
    "ManuscriptAssessment",
    "ManuscriptRole",
    "assess_manuscript",
    "require_requested_manuscript_role",
]

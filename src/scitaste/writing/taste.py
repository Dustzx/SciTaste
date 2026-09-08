"""Hierarchical, integrity-first assessment of scientific Writing Taste."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.project.models import content_sha256

WRITING_TASTE_PROFILE_ID = "scitaste-writing-taste-v1"
ANTI_DEFENSIVE_WRITING_SOURCE = (
    "https://github.com/Adkid-Zephyr/anti-defensive-writing-Skill/"
    "blob/b32067b3055d356e007c6986775fee069da3891a/"
    "skills/anti-defensive-writing-en/SKILL.md"
)


class WritingTasteDimension(StrEnum):
    """Independent decisions that together form scientific Writing Taste."""

    SCIENTIFIC_INTEGRITY = "scientific_integrity"
    CLAIM_CALIBRATION = "claim_calibration"
    PRECISION_AND_SCOPE = "precision_and_scope"
    SCIENTIFIC_POSITIONING = "scientific_positioning"
    NARRATIVE_FOCUS = "narrative_focus"
    ARGUMENTATIVE_STRUCTURE = "argumentative_structure"
    EVIDENCE_PRIORITIZATION = "evidence_prioritization"
    READER_GUIDANCE = "reader_guidance"
    ANTI_DEFENSIVE_STYLE = "anti_defensive_style"
    VENUE_FIT = "venue_fit"
    VOICE_AND_TERMINOLOGY = "voice_and_terminology"
    GLOBAL_COHERENCE = "global_coherence"


WRITING_TASTE_PRECEDENCE: tuple[WritingTasteDimension, ...] = (
    WritingTasteDimension.SCIENTIFIC_INTEGRITY,
    WritingTasteDimension.CLAIM_CALIBRATION,
    WritingTasteDimension.PRECISION_AND_SCOPE,
    WritingTasteDimension.SCIENTIFIC_POSITIONING,
    WritingTasteDimension.NARRATIVE_FOCUS,
    WritingTasteDimension.ARGUMENTATIVE_STRUCTURE,
    WritingTasteDimension.EVIDENCE_PRIORITIZATION,
    WritingTasteDimension.GLOBAL_COHERENCE,
    WritingTasteDimension.READER_GUIDANCE,
    WritingTasteDimension.ANTI_DEFENSIVE_STYLE,
    WritingTasteDimension.VENUE_FIT,
    WritingTasteDimension.VOICE_AND_TERMINOLOGY,
)


class WritingTasteLevel(StrEnum):
    PAPER = "paper"
    SECTION = "section"
    PARAGRAPH = "paragraph"
    SENTENCE = "sentence"
    PHRASE = "phrase"


class WritingTasteSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class WritingTasteFinding(BaseModel):
    """One bounded diagnosis; it never edits or suppresses evidence by itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    code: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    dimension: WritingTasteDimension
    level: WritingTasteLevel
    severity: WritingTasteSeverity
    section_name: str | None = None
    paragraph_index: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    excerpts: tuple[str, ...] = Field(default=(), max_length=3)
    source_principle: str = Field(min_length=1)
    preserves_material_limitations: Literal[True] = True
    automatic_rewrite_allowed: Literal[False] = False


class WritingTasteAssessment(BaseModel):
    """Self-hashed advisory assessment separated from mechanical venue readiness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    profile_id: Literal["scitaste-writing-taste-v1"] = WRITING_TASTE_PROFILE_ID
    manuscript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_venue: str | None = None
    precedence: tuple[WritingTasteDimension, ...] = WRITING_TASTE_PRECEDENCE
    findings: tuple[WritingTasteFinding, ...]
    blocking_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)
    integrity_gate_passes: bool
    style_advisory_passes: bool
    scientific_quality_established: Literal[False] = False
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values: object) -> WritingTasteAssessment:
        payload = {"schema_version": "1.0", "profile_id": WRITING_TASTE_PROFILE_ID, **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def verdict_and_hash_are_consistent(self) -> WritingTasteAssessment:
        counts = {
            WritingTasteSeverity.ERROR: self.blocking_count,
            WritingTasteSeverity.WARNING: self.warning_count,
            WritingTasteSeverity.INFO: self.info_count,
        }
        if any(
            sum(item.severity is severity for item in self.findings) != expected
            for severity, expected in counts.items()
        ):
            raise ValueError("writing-taste finding counts are inconsistent")
        if self.integrity_gate_passes != (self.blocking_count == 0):
            raise ValueError("writing-taste integrity verdict is inconsistent")
        if self.style_advisory_passes != (self.warning_count == 0):
            raise ValueError("writing-taste style verdict is inconsistent")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("writing-taste assessment hash mismatch")
        return self


@dataclass(frozen=True)
class _Section:
    name: str
    body: str


_HEADING = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
_WORD = re.compile(r"[A-Za-z0-9]+(?:[.'-][A-Za-z0-9]+)*|[\u3400-\u9fff]")
_PROJECT_REPORT_HEADINGS = {
    "current results",
    "current status",
    "implementation status",
    "implementation progress",
    "artifact-level validation",
    "end-to-end engineering preacceptance",
    "engineering preacceptance",
}
_PROJECT_LOG_TERMS = (
    "repository snapshot",
    "test suite",
    "passing tests",
    "wheel",
    "commit",
    "revision",
    "adapter correction",
    "preacceptance",
    "working tree",
)
_PROCESS_CHRONOLOGY = (
    re.compile(r"\bwe first\b", re.IGNORECASE),
    re.compile(r"\b(?:we then|then we|next,? we)\b", re.IGNORECASE),
    re.compile(r"\bsubsequently\b", re.IGNORECASE),
    re.compile(r"\bduring (?:development|the sequence|the iteration)\b", re.IGNORECASE),
    re.compile(r"\breached revision\b", re.IGNORECASE),
    re.compile(r"\bafter (?:the )?(?:fix|correction|patch|failure)\b", re.IGNORECASE),
)
_DEFENSIVE_PATTERNS = (
    re.compile(r"\bwe (?:do|did) not claim\b", re.IGNORECASE),
    re.compile(r"\bwe (?:therefore )?make no claim\b", re.IGNORECASE),
    re.compile(r"\bwe (?:do|did) not (?:attempt|aim|seek|intend)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:this|the) (?:paper|work|study|result|evidence|draft) "
        r"(?:does not|cannot|is not|has not) (?:claim|prove|establish|demonstrate|show|support)",
        re.IGNORECASE,
    ),
    re.compile(r"\bdoes not yet support\b", re.IGNORECASE),
    re.compile(r"\bnot intended to\b", re.IGNORECASE),
    re.compile(r"\b(?:unfortunately|severely insufficient)\b", re.IGNORECASE),
    re.compile(r"\bonly achieve(?:s|d)?\b", re.IGNORECASE),
    re.compile(r"\bstill lags? (?:far )?behind\b", re.IGNORECASE),
    re.compile(r"\blimited improvement\b", re.IGNORECASE),
)
_CONTRIBUTION_CUE = re.compile(
    r"\b(?:we|this\s+(?:paper|work))\s+"
    r"(?:introduce|propose|present|develop|define)s?\b|"
    r"\bour\s+(?:method|approach|framework|system|contribution)\b",
    re.IGNORECASE,
)
_RESULT_CUE = re.compile(
    r"\b(?:result|evaluation|experiment|evidence|demonstrat|show|improv|outperform|reduce|"
    r"achiev|accuracy|latency|cost)\w*\b|\b\d+(?:\.\d+)?\s*%",
    re.IGNORECASE,
)
_CONCLUSION_NEGATION = re.compile(
    r"\b(?:we do not claim|does not yet|cannot establish|fails? to|not sufficient|"
    r"remains incomplete|still lacks?)\b",
    re.IGNORECASE,
)
_HIGH_ATTENTION_PROJECT_STATUS = (
    "current artifact",
    "current implementation",
    "working draft",
    "engineering preacceptance",
    "passing tests",
    "repository snapshot",
)


def assess_writing_taste(
    markdown: str,
    *,
    target_venue: str | None = None,
) -> WritingTasteAssessment:
    """Diagnose deterministic writing signals without claiming semantic paper quality."""

    findings: list[WritingTasteFinding] = []
    sections = _sections(markdown)
    for section in sections:
        normalized_name = _normalize_heading(section.name)
        if normalized_name in _PROJECT_REPORT_HEADINGS:
            findings.append(
                _finding(
                    code="project-report-heading",
                    dimension=WritingTasteDimension.NARRATIVE_FOCUS,
                    level=WritingTasteLevel.SECTION,
                    severity=WritingTasteSeverity.WARNING,
                    section_name=section.name,
                    message=(
                        f"Section heading {section.name!r} frames the manuscript as a project "
                        "status report rather than a scientific argument."
                    ),
                    recommendation=(
                        "Name the section after the research question, evaluation object, or "
                        "result it establishes."
                    ),
                    excerpts=(section.name,),
                    source_principle="scitaste-narrative-focus-v1",
                )
            )
        if _is_results_section(normalized_name) or normalized_name in _PROJECT_REPORT_HEADINGS:
            log_terms = tuple(
                term for term in _PROJECT_LOG_TERMS if term in section.body.casefold()
            )
            if len(log_terms) >= 2:
                findings.append(
                    _finding(
                        code="project-log-results",
                        dimension=WritingTasteDimension.ARGUMENTATIVE_STRUCTURE,
                        level=WritingTasteLevel.SECTION,
                        severity=WritingTasteSeverity.WARNING,
                        section_name=section.name,
                        message=(
                            "The Results material is dominated by development-state vocabulary "
                            "instead of explicit scientific questions and findings."
                        ),
                        recommendation=(
                            "Organize the section by research question and argumentative duty; "
                            "retain build, revision, and test provenance in an appendix or "
                            "artifact record."
                        ),
                        excerpts=log_terms[:3],
                        source_principle="anti-defensive-writing-derived",
                    )
                )
        chronology = tuple(
            match.group(0)
            for pattern in _PROCESS_CHRONOLOGY
            for match in pattern.finditer(section.body)
        )
        if len(chronology) >= 2:
            findings.append(
                _finding(
                    code="process-chronology",
                    dimension=WritingTasteDimension.ARGUMENTATIVE_STRUCTURE,
                    level=WritingTasteLevel.SECTION,
                    severity=WritingTasteSeverity.WARNING,
                    section_name=section.name,
                    message=(
                        "The section narrates development order instead of the final "
                        "standing logic."
                    ),
                    recommendation=(
                        "Reorder the material as problem, claim, evidence, interpretation, and "
                        "implication; preserve chronological details only when they are "
                        "methodologically material."
                    ),
                    excerpts=chronology[:3],
                    source_principle="anti-defensive-writing-derived",
                )
            )
        findings.extend(_defensive_findings(section))
        findings.extend(_high_attention_status_findings(section))
        findings.extend(_paragraph_findings(section))

    abstract = _first_section(sections, {"abstract"})
    if abstract is not None:
        if not _CONTRIBUTION_CUE.search(abstract.body):
            findings.append(
                _finding(
                    code="abstract-missing-contribution",
                    dimension=WritingTasteDimension.SCIENTIFIC_POSITIONING,
                    level=WritingTasteLevel.SECTION,
                    severity=WritingTasteSeverity.WARNING,
                    section_name=abstract.name,
                    message="The abstract does not state a recognizable contribution.",
                    recommendation=(
                        "State the distinctive approach directly after establishing the problem "
                        "and gap."
                    ),
                    excerpts=(),
                    source_principle="scitaste-abstract-contract-v1",
                )
            )
        if not _RESULT_CUE.search(abstract.body):
            findings.append(
                _finding(
                    code="abstract-missing-evidence",
                    dimension=WritingTasteDimension.EVIDENCE_PRIORITIZATION,
                    level=WritingTasteLevel.SECTION,
                    severity=WritingTasteSeverity.WARNING,
                    section_name=abstract.name,
                    message="The abstract does not expose a concrete result or evidence statement.",
                    recommendation=(
                        "Name the strongest supported result and explain what it establishes."
                    ),
                    excerpts=(),
                    source_principle="scitaste-abstract-contract-v1",
                )
            )

    conclusion = _first_section(sections, {"conclusion", "conclusions"})
    if conclusion is not None:
        matches = tuple(match.group(0) for match in _CONCLUSION_NEGATION.finditer(conclusion.body))
        if matches:
            findings.append(
                _finding(
                    code="conclusion-self-negation",
                    dimension=WritingTasteDimension.ANTI_DEFENSIVE_STYLE,
                    level=WritingTasteLevel.SECTION,
                    severity=WritingTasteSeverity.WARNING,
                    section_name=conclusion.name,
                    message="The conclusion introduces or foregrounds negative qualification.",
                    recommendation=(
                        "End with the bounded supported takeaway. Retain any material limitation "
                        "once in the section where it changes interpretation."
                    ),
                    excerpts=matches[:3],
                    source_principle="anti-defensive-writing-derived",
                )
            )

    ordered = tuple(sorted(findings, key=_finding_sort_key))
    errors = sum(item.severity is WritingTasteSeverity.ERROR for item in ordered)
    warnings = sum(item.severity is WritingTasteSeverity.WARNING for item in ordered)
    infos = sum(item.severity is WritingTasteSeverity.INFO for item in ordered)
    return WritingTasteAssessment.create(
        manuscript_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        target_venue=target_venue,
        precedence=WRITING_TASTE_PRECEDENCE,
        findings=ordered,
        blocking_count=errors,
        warning_count=warnings,
        info_count=infos,
        integrity_gate_passes=errors == 0,
        style_advisory_passes=warnings == 0,
        scientific_quality_established=False,
    )


def write_writing_taste_assessment(
    assessment: WritingTasteAssessment,
    path: str | Path,
) -> Path:
    """Write a deterministic assessment record without modifying the manuscript."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(assessment.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def render_section_drafts_for_taste(section_drafts: dict[str, str]) -> str:
    """Project contract-backed drafts into the same hierarchy used by the assessor."""

    return "\n\n".join(f"# {name}\n\n{text}" for name, text in section_drafts.items())


def _defensive_findings(section: _Section) -> list[WritingTasteFinding]:
    normalized_name = _normalize_heading(section.name)
    if _is_limitation_section(normalized_name):
        return []
    excerpts = tuple(
        match.group(0)
        for pattern in _DEFENSIVE_PATTERNS
        for match in pattern.finditer(section.body)
    )
    if not excerpts:
        return []
    high_attention = normalized_name in {
        "abstract",
        "introduction",
        "conclusion",
        "conclusions",
    }
    return [
        _finding(
            code="defensive-framing",
            dimension=WritingTasteDimension.ANTI_DEFENSIVE_STYLE,
            level=WritingTasteLevel.SECTION,
            severity=(
                WritingTasteSeverity.WARNING if high_attention else WritingTasteSeverity.INFO
            ),
            section_name=section.name,
            message=(
                "The section contains negative or self-protective framing before or instead of "
                "a positive statement of supported scope."
            ),
            recommendation=(
                "Lead with what the evidence establishes. If a qualification affects validity, "
                "scope, safety, ethics, or reproducibility, preserve it once and state it "
                "precisely."
            ),
            excerpts=excerpts[:3],
            source_principle="anti-defensive-writing-derived",
        )
    ]


def _paragraph_findings(section: _Section) -> list[WritingTasteFinding]:
    findings: list[WritingTasteFinding] = []
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", section.body) if item.strip()]
    for index, paragraph in enumerate(paragraphs, start=1):
        word_count = len(_WORD.findall(paragraph))
        if word_count > 240:
            findings.append(
                _finding(
                    code="overloaded-paragraph",
                    dimension=WritingTasteDimension.READER_GUIDANCE,
                    level=WritingTasteLevel.PARAGRAPH,
                    severity=WritingTasteSeverity.INFO,
                    section_name=section.name,
                    paragraph_index=index,
                    message=(
                        f"Paragraph {index} carries {word_count} words and may contain "
                        "multiple jobs."
                    ),
                    recommendation=(
                        "Give the paragraph one argumentative duty and split only at a real "
                        "rhetorical boundary."
                    ),
                    excerpts=(_compact_excerpt(paragraph),),
                    source_principle="scitaste-paragraph-contract-v1",
                )
            )
    return findings


def _high_attention_status_findings(section: _Section) -> list[WritingTasteFinding]:
    normalized_name = _normalize_heading(section.name)
    if normalized_name not in {"abstract", "introduction", "conclusion", "conclusions"}:
        return []
    terms = tuple(
        term for term in _HIGH_ATTENTION_PROJECT_STATUS if term in section.body.casefold()
    )
    if not terms:
        return []
    return [
        _finding(
            code="project-status-framing",
            dimension=WritingTasteDimension.NARRATIVE_FOCUS,
            level=WritingTasteLevel.SECTION,
            severity=WritingTasteSeverity.WARNING,
            section_name=section.name,
            message=(
                "A high-attention section foregrounds project maturity or development status "
                "instead of the scientific contribution."
            ),
            recommendation=(
                "Lead with the supported research contribution and strongest result; move "
                "repository maturity and development-state detail to system validation."
            ),
            excerpts=terms[:3],
            source_principle="anti-defensive-writing-derived",
        )
    ]


def _finding(
    *,
    code: str,
    dimension: WritingTasteDimension,
    level: WritingTasteLevel,
    severity: WritingTasteSeverity,
    message: str,
    recommendation: str,
    excerpts: tuple[str, ...],
    source_principle: str,
    section_name: str | None = None,
    paragraph_index: int | None = None,
) -> WritingTasteFinding:
    identity = json.dumps(
        {
            "code": code,
            "dimension": dimension.value,
            "level": level.value,
            "section_name": section_name,
            "paragraph_index": paragraph_index,
            "message": message,
            "excerpts": excerpts,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return WritingTasteFinding(
        finding_id=hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        code=code,
        dimension=dimension,
        level=level,
        severity=severity,
        section_name=section_name,
        paragraph_index=paragraph_index,
        message=message,
        recommendation=recommendation,
        excerpts=excerpts,
        source_principle=source_principle,
    )


def _sections(markdown: str) -> tuple[_Section, ...]:
    matches = list(_HEADING.finditer(markdown))
    sections: list[_Section] = []
    for index, match in enumerate(matches):
        name = _plain_heading(match.group(1))
        if name.casefold() == "title":
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append(_Section(name=name, body=markdown[match.end() : end].strip()))
    return tuple(sections)


def _first_section(sections: tuple[_Section, ...], names: set[str]) -> _Section | None:
    return next(
        (section for section in sections if _normalize_heading(section.name) in names),
        None,
    )


def _plain_heading(value: str) -> str:
    return re.sub(r"[*_`]", "", value).strip()


def _normalize_heading(value: str) -> str:
    plain = _plain_heading(value).casefold()
    plain = re.sub(r"^[0-9]+(?:\.[0-9]+)*[.)]?\s*", "", plain)
    return re.sub(r"\s+", " ", plain).strip()


def _is_results_section(value: str) -> bool:
    return value in {"results", "evaluation results", "experimental results"} or value.startswith(
        "results:"
    )


def _is_limitation_section(value: str) -> bool:
    return value in {"limitations", "limitations and risks"} or value.startswith("limitations:")


def _compact_excerpt(text: str, *, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _finding_sort_key(item: WritingTasteFinding) -> tuple[int, str, int, str]:
    severity_order = {
        WritingTasteSeverity.ERROR: 0,
        WritingTasteSeverity.WARNING: 1,
        WritingTasteSeverity.INFO: 2,
    }
    return (
        severity_order[item.severity],
        item.section_name or "",
        item.paragraph_index or 0,
        item.code,
    )


__all__ = [
    "ANTI_DEFENSIVE_WRITING_SOURCE",
    "WRITING_TASTE_PRECEDENCE",
    "WRITING_TASTE_PROFILE_ID",
    "WritingTasteAssessment",
    "WritingTasteDimension",
    "WritingTasteFinding",
    "WritingTasteLevel",
    "WritingTasteSeverity",
    "assess_writing_taste",
    "render_section_drafts_for_taste",
    "write_writing_taste_assessment",
]

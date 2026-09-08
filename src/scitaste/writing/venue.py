"""Content-bound venue templates and deterministic submission compliance."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.project.models import content_sha256

_SHA256 = r"^[0-9a-f]{64}$"
_SAFE_ID = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_SAFE_LATEX_NAME = r"^[A-Za-z0-9_-]+$"
_MAX_CONFIG_BYTES = 65_536
_MAX_TEMPLATE_BYTES = 16_777_216
_MAX_TEMPLATE_FILES = 128
_CITATION = re.compile(r"\\cite[pt]?\{([^}]+)\}")
_BRACKET_CITATION = re.compile(r"\[([A-Za-z][A-Za-z0-9_-]*\d{4}[A-Za-z0-9_-]*)\]")
_BIB_ENTRY = re.compile(r"(?im)^\s*@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,")
_HEADING = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_INTERNAL_MARKERS = (
    re.compile(r"\[(?:claim|evidence|obligation):", re.IGNORECASE),
    re.compile(r"\bdiagnosis-factorial-v\d+\b", re.IGNORECASE),
    re.compile(r"\b20\d\d-\d\d-\d\d__[A-Za-z0-9_.-]+__", re.IGNORECASE),
    re.compile(r"(?:^|[\s`])outputs/projects/", re.IGNORECASE),
)


class VenueTemplateAsset(BaseModel):
    """One exact file copied from a venue-provided template archive."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    archive_path: str
    output_name: str
    sha256: str = Field(pattern=_SHA256)

    @field_validator("archive_path")
    @classmethod
    def archive_path_is_safe(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or "\\" in value
            or "//" in value
        ):
            raise ValueError("venue template asset path must be safe and relative")
        return value

    @field_validator("output_name")
    @classmethod
    def output_name_is_safe(cls, value: str) -> str:
        if Path(value).name != value or value in {"", ".", ".."} or "\\" in value:
            raise ValueError("venue template output name must be one safe file name")
        return value


class VenueTemplateConfig(BaseModel):
    """Strict venue contract loaded from a content-bound template archive."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    venue_id: str = Field(pattern=_SAFE_ID)
    venue_name: str = Field(min_length=1)
    template_archive: Path
    expected_archive_sha256: str = Field(pattern=_SHA256)
    style_package: str = Field(pattern=_SAFE_LATEX_NAME)
    bibliography_style: str = Field(pattern=_SAFE_LATEX_NAME)
    assets: tuple[VenueTemplateAsset, ...]
    submission_mode: Literal["anonymous"] = "anonymous"
    max_main_pages: int = Field(ge=1, le=30)
    required_statements: tuple[str, ...]
    recommended_statements: tuple[str, ...] = ()
    statement_page_limits: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def assets_and_statements_are_complete(self) -> VenueTemplateConfig:
        paths = [item.archive_path for item in self.assets]
        outputs = [item.output_name for item in self.assets]
        if not self.assets or len(paths) != len(set(paths)):
            raise ValueError("venue template asset paths must be non-empty and unique")
        if len(outputs) != len(set(outputs)):
            raise ValueError("venue template output names must be unique")
        required_outputs = {
            f"{self.style_package}.sty",
            f"{self.bibliography_style}.bst",
        }
        if not required_outputs.issubset(outputs):
            raise ValueError("venue template must bind its style and bibliography files")
        statements = (*self.required_statements, *self.recommended_statements)
        if (
            not self.required_statements
            or any(not item.strip() for item in statements)
            or len(statements) != len({item.casefold() for item in statements})
        ):
            raise ValueError("venue statements must be non-empty and unique")
        if not set(self.statement_page_limits).issubset(self.required_statements):
            raise ValueError("statement page limits must reference required statements")
        if any(limit < 1 or limit > 10 for limit in self.statement_page_limits.values()):
            raise ValueError("statement page limits must be between 1 and 10 pages")
        return self


class VenueTemplateInspection(BaseModel):
    """Verified venue configuration and archive identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_path: Path
    config_sha256: str = Field(pattern=_SHA256)
    config: VenueTemplateConfig
    archive_sha256: str = Field(pattern=_SHA256)
    asset_sha256: dict[str, str]
    fingerprint: str = Field(pattern=_SHA256)


class VenueSubmissionAssessment(BaseModel):
    """Self-hashed deterministic readiness record for one venue submission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    venue_id: str = Field(pattern=_SAFE_ID)
    venue_name: str
    submission_mode: Literal["anonymous"]
    template_fingerprint: str = Field(pattern=_SHA256)
    manuscript_sha256: str = Field(pattern=_SHA256)
    bibliography_sha256: str = Field(pattern=_SHA256)
    title: str
    title_present: bool
    word_count: int = Field(ge=0)
    abstract_paragraph_count: int = Field(ge=0)
    citation_keys: tuple[str, ...]
    bibliography_keys: tuple[str, ...]
    duplicate_bibliography_keys: tuple[str, ...]
    missing_citation_keys: tuple[str, ...]
    required_statements: tuple[str, ...]
    missing_required_statements: tuple[str, ...]
    recommended_statements: tuple[str, ...]
    missing_recommended_statements: tuple[str, ...]
    statement_order_valid: bool
    statement_page_limits: dict[str, int]
    statement_pages: dict[str, int | None]
    statement_page_limit_violations: tuple[str, ...]
    identity_markers: tuple[str, ...]
    internal_markers: tuple[str, ...]
    compiled: bool
    main_text_pages: int | None = Field(default=None, ge=1)
    max_main_pages: int = Field(ge=1)
    page_limit_satisfied: bool | None
    eligible_for_submission: bool
    record_sha256: str = Field(pattern=_SHA256)

    @classmethod
    def create(cls, **values: object) -> VenueSubmissionAssessment:
        payload = {"schema_version": "1.0", **values}
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )

    @model_validator(mode="after")
    def record_and_verdict_are_consistent(self) -> VenueSubmissionAssessment:
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("venue submission assessment hash mismatch")
        ready = (
            self.compiled
            and self.title_present
            and self.abstract_paragraph_count == 1
            and not self.missing_citation_keys
            and not self.duplicate_bibliography_keys
            and not self.missing_required_statements
            and self.statement_order_valid
            and not self.statement_page_limit_violations
            and not self.identity_markers
            and not self.internal_markers
            and self.page_limit_satisfied is True
        )
        if self.eligible_for_submission != ready:
            raise ValueError("venue submission readiness verdict is inconsistent")
        return self


def inspect_venue_template(path: str | Path) -> VenueTemplateInspection:
    """Load a venue contract and verify every admitted template byte."""

    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("venue template config must be a regular non-symlink file")
    config_path = requested.resolve(strict=True)
    if not config_path.is_file() or config_path.stat().st_size > _MAX_CONFIG_BYTES:
        raise ValueError("venue template config must be a bounded regular file")
    raw = config_path.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("venue template config must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("venue template config must contain a mapping")
    archive_value = payload.get("template_archive")
    if not isinstance(archive_value, str):
        raise ValueError("venue template_archive must be a string")
    archive = Path(os.path.expandvars(archive_value))
    if not archive.is_absolute():
        archive = config_path.parent / archive
    if archive.is_symlink():
        raise ValueError("venue template archive cannot be a symlink")
    payload["template_archive"] = archive.resolve(strict=True)
    config = VenueTemplateConfig.model_validate(payload)
    archive_sha, asset_hashes = _inspect_archive(config)
    semantic = {
        "schema_version": "1.0",
        "config_sha256": hashlib.sha256(raw).hexdigest(),
        "venue": config.model_dump(mode="json", exclude={"template_archive"}),
        "archive_sha256": archive_sha,
        "asset_sha256": asset_hashes,
    }
    return VenueTemplateInspection(
        config_path=config_path,
        config_sha256=semantic["config_sha256"],
        config=config,
        archive_sha256=archive_sha,
        asset_sha256=asset_hashes,
        fingerprint=content_sha256(semantic),
    )


def materialize_venue_assets(
    inspection: VenueTemplateInspection,
    *,
    target_dir: str | Path,
) -> list[Path]:
    """Copy only verified, registered venue assets from the template archive."""

    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or not target.is_dir():
        raise ValueError("venue bundle target must be a regular directory")
    _archive_sha, current = _inspect_archive(inspection.config)
    if current != inspection.asset_sha256:
        raise ValueError("venue template archive changed after inspection")
    written: list[Path] = []
    with zipfile.ZipFile(inspection.config.template_archive) as archive:
        for asset in inspection.config.assets:
            destination = target / asset.output_name
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(destination)
            with destination.open("xb") as stream:
                stream.write(archive.read(asset.archive_path))
            written.append(destination)
    return written


def assess_venue_submission(
    markdown: str,
    bibliography: str,
    *,
    template: VenueTemplateInspection,
    compiled: bool,
    main_text_pages: int | None,
    statement_pages: dict[str, int] | None = None,
) -> VenueSubmissionAssessment:
    """Assess anonymous submission readiness without judging scientific merit."""

    headings = tuple(_plain_heading(item) for item in _HEADING.findall(markdown))
    heading_names = {item.casefold() for item in headings}
    required = template.config.required_statements
    recommended = template.config.recommended_statements
    missing_required = tuple(item for item in required if item.casefold() not in heading_names)
    missing_recommended = tuple(
        item for item in recommended if item.casefold() not in heading_names
    )
    citations = _citation_keys(markdown)
    raw_bibliography_keys = _BIB_ENTRY.findall(bibliography)
    bibliography_keys = tuple(sorted(set(raw_bibliography_keys)))
    duplicate_bibliography_keys = tuple(
        sorted({key for key in raw_bibliography_keys if raw_bibliography_keys.count(key) > 1})
    )
    missing_citations = tuple(sorted(set(citations) - set(bibliography_keys)))
    identities = tuple(sorted(set(_identity_markers(markdown))))
    internal = tuple(pattern.pattern for pattern in _INTERNAL_MARKERS if pattern.search(markdown))
    abstract = _section_body(markdown, "abstract")
    abstract_paragraphs = len(
        [item for item in re.split(r"\n\s*\n", abstract.strip()) if item.strip()]
    )
    page_limit = (
        None if main_text_pages is None else main_text_pages <= template.config.max_main_pages
    )
    observed_statement_pages = {
        name: (statement_pages or {}).get(name) for name in template.config.statement_page_limits
    }
    statement_page_violations = tuple(
        name
        for name, limit in template.config.statement_page_limits.items()
        if observed_statement_pages[name] is None or observed_statement_pages[name] > limit
    )
    title = _manuscript_title(markdown)
    statement_order_valid = _statement_order_is_valid(
        markdown,
        required=required,
        recommended=recommended,
    )
    ready = (
        compiled
        and title != "Untitled manuscript"
        and abstract_paragraphs == 1
        and not missing_citations
        and not duplicate_bibliography_keys
        and not missing_required
        and statement_order_valid
        and not statement_page_violations
        and not identities
        and not internal
        and page_limit is True
    )
    return VenueSubmissionAssessment.create(
        venue_id=template.config.venue_id,
        venue_name=template.config.venue_name,
        submission_mode=template.config.submission_mode,
        template_fingerprint=template.fingerprint,
        manuscript_sha256=hashlib.sha256(markdown.encode()).hexdigest(),
        bibliography_sha256=hashlib.sha256(bibliography.encode()).hexdigest(),
        title=title,
        title_present=title != "Untitled manuscript",
        word_count=len(
            re.findall(
                r"[A-Za-z0-9]+(?:[.'-][A-Za-z0-9]+)*|[\u3400-\u9fff]",
                markdown,
            )
        ),
        abstract_paragraph_count=abstract_paragraphs,
        citation_keys=citations,
        bibliography_keys=bibliography_keys,
        duplicate_bibliography_keys=duplicate_bibliography_keys,
        missing_citation_keys=missing_citations,
        required_statements=required,
        missing_required_statements=missing_required,
        recommended_statements=recommended,
        missing_recommended_statements=missing_recommended,
        statement_order_valid=statement_order_valid,
        statement_page_limits=template.config.statement_page_limits,
        statement_pages=observed_statement_pages,
        statement_page_limit_violations=statement_page_violations,
        identity_markers=identities,
        internal_markers=internal,
        compiled=compiled,
        main_text_pages=main_text_pages,
        max_main_pages=template.config.max_main_pages,
        page_limit_satisfied=page_limit,
        eligible_for_submission=ready,
    )


def require_venue_submission_ready(assessment: VenueSubmissionAssessment) -> None:
    """Fail closed when a rendered bundle violates a deterministic venue gate."""

    if assessment.eligible_for_submission:
        return
    failures: list[str] = []
    if not assessment.compiled:
        failures.append("PDF compilation did not succeed")
    if not assessment.title_present:
        failures.append("an explicit manuscript title is required")
    if assessment.abstract_paragraph_count != 1:
        failures.append("abstract must contain exactly one paragraph")
    if assessment.missing_citation_keys:
        failures.append("missing citations=" + ",".join(assessment.missing_citation_keys))
    if assessment.duplicate_bibliography_keys:
        failures.append(
            "duplicate bibliography keys=" + ",".join(assessment.duplicate_bibliography_keys)
        )
    if assessment.missing_required_statements:
        failures.append("missing statements=" + ",".join(assessment.missing_required_statements))
    if assessment.identity_markers:
        failures.append("identity markers=" + ",".join(assessment.identity_markers))
    if assessment.internal_markers:
        failures.append("internal audit markers remain")
    if assessment.page_limit_satisfied is not True:
        failures.append(
            f"main pages={assessment.main_text_pages}, limit={assessment.max_main_pages}"
        )
    if not assessment.statement_order_valid:
        failures.append("venue statements must be unique, ordered, and terminal")
    if assessment.statement_page_limit_violations:
        failures.append(
            "statement page limits=" + ",".join(assessment.statement_page_limit_violations)
        )
    raise ValueError("venue submission gate failed: " + "; ".join(failures))


def _inspect_archive(config: VenueTemplateConfig) -> tuple[str, dict[str, str]]:
    archive_path = config.template_archive
    if (
        archive_path.is_symlink()
        or not archive_path.is_file()
        or archive_path.stat().st_size > _MAX_TEMPLATE_BYTES
    ):
        raise ValueError("venue template archive must be a bounded regular ZIP file")
    archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if archive_sha != config.expected_archive_sha256:
        raise ValueError("venue template archive hash mismatch")
    expected = {item.archive_path: item for item in config.assets}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_TEMPLATE_FILES:
                raise ValueError("venue template archive contains too many entries")
            total = 0
            seen: set[str] = set()
            for info in infos:
                _validate_archive_member(info)
                if info.filename in seen:
                    raise ValueError("venue template archive contains duplicate paths")
                seen.add(info.filename)
                total += info.file_size
                if total > _MAX_TEMPLATE_BYTES:
                    raise ValueError("venue template archive expands beyond its limit")
            missing = sorted(set(expected) - seen)
            if missing:
                raise ValueError("venue template archive is missing registered assets")
            hashes = {
                asset.output_name: hashlib.sha256(archive.read(asset.archive_path)).hexdigest()
                for asset in config.assets
            }
    except zipfile.BadZipFile as exc:
        raise ValueError("venue template archive is not a valid ZIP file") from exc
    for asset in config.assets:
        if hashes[asset.output_name] != asset.sha256:
            raise ValueError(f"venue template asset hash mismatch: {asset.output_name}")
    return archive_sha, hashes


def _validate_archive_member(info: zipfile.ZipInfo) -> None:
    path = PurePosixPath(info.filename)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in info.filename
        or "//" in info.filename
    ):
        raise ValueError("venue template archive contains an unsafe path")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise ValueError("venue template archive cannot contain symlinks")
    if info.flag_bits & 0x1:
        raise ValueError("venue template archive cannot contain encrypted entries")


def _citation_keys(markdown: str) -> tuple[str, ...]:
    keys: set[str] = set(_BRACKET_CITATION.findall(markdown))
    for match in _CITATION.findall(markdown):
        keys.update(item.strip() for item in match.split(",") if item.strip())
    return tuple(sorted(keys))


def _identity_markers(markdown: str) -> list[str]:
    markers = _EMAIL.findall(markdown)
    for heading in _HEADING.findall(markdown):
        if _plain_heading(heading).casefold() in {
            "acknowledgments",
            "acknowledgements",
            "affiliation",
            "affiliations",
            "author",
            "authors",
            "author information",
        }:
            markers.append(f"heading:{_plain_heading(heading)}")
    return markers


def _section_body(markdown: str, name: str) -> str:
    pattern = re.compile(rf"(?ims)^#{{1,6}}\s+{re.escape(name)}\s*$\s*(.*?)(?=^#{{1,6}}\s+|\Z)")
    match = pattern.search(markdown)
    return match.group(1) if match else ""


def _manuscript_title(markdown: str) -> str:
    body = _section_body(markdown, "title")
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return _plain_heading(lines[0]) if lines else "Untitled manuscript"


def _statement_order_is_valid(
    markdown: str,
    *,
    required: tuple[str, ...],
    recommended: tuple[str, ...],
) -> bool:
    expected = tuple(item.casefold() for item in (*required, *recommended))
    headings = [
        (_plain_heading(match.group(1)).casefold(), match.start())
        for match in _HEADING.finditer(markdown)
    ]
    statement_positions = [(name, position) for name, position in headings if name in set(expected)]
    if not statement_positions:
        return False
    first_position = statement_positions[0][1]
    tail = [name for name, position in headings if position >= first_position]
    if any(name not in set(expected) for name in tail) or len(tail) != len(set(tail)):
        return False
    indices = [expected.index(name) for name in tail]
    conclusion_positions = [
        position for name, position in headings if name in {"conclusion", "conclusions"}
    ]
    return (
        indices == sorted(indices)
        and bool(conclusion_positions)
        and max(conclusion_positions) < first_position
    )


def _plain_heading(value: str) -> str:
    return re.sub(r"[*_`]", "", value).strip()


__all__ = [
    "VenueSubmissionAssessment",
    "VenueTemplateAsset",
    "VenueTemplateConfig",
    "VenueTemplateInspection",
    "assess_venue_submission",
    "inspect_venue_template",
    "materialize_venue_assets",
    "require_venue_submission_ready",
]

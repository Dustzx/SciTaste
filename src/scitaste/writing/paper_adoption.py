"""Adopt one registered paper as a deterministic semantic revision source."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.model_nodes.models import NodeContext, NodePolicy
from scitaste.project import ProjectRun, ProjectRuntime, ProjectSnapshot
from scitaste.project.models import (
    PaperManifest,
    content_sha256,
    validate_entry_id,
    validate_project_id,
    validate_relative_locator,
)
from scitaste.writing.argument import PaperArgumentContract, load_paper_argument_contract
from scitaste.writing.semantic import EvidencePaperDraftNode
from scitaste.writing.semantic_models import (
    EVIDENCE_PAPER_DRAFT_NODE,
    EvidencePaperCitationInput,
    EvidencePaperClaimInput,
    EvidencePaperDraftInput,
    EvidencePaperDraftProposal,
    EvidencePaperDraftSection,
    EvidencePaperParagraph,
    EvidencePaperParagraphRole,
    MaterialWritingLimitation,
    PaperClaimSupport,
)

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_TOP_HEADING = re.compile(r"(?m)^#\s+(.+?)\s*$")
_TITLE = re.compile(r"(?is)\A\s*##\s+Title\s*\n([^\n]+)\s*")
_CITATION = re.compile(r"\\cite[pt]?\{([^{}]+)\}")
_BIB_ENTRY = re.compile(r"(?im)^\s*@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,")
_BIB_TITLE = re.compile(r"(?is)\btitle\s*=\s*[\{\"](.+?)[\}\"]\s*,")
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])(?:\d+(?:\.\d+)?%?)(?![A-Za-z0-9_]|\.\d)")
_MAX_MARKDOWN_BYTES = 8 * 1024 * 1024
_MAX_BIBLIOGRAPHY_BYTES = 8 * 1024 * 1024


class ProjectPaperAdoptionBundle(BaseModel):
    """Self-hashed proof that existing prose became a no-authority semantic source."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    paper_directory: str
    paper_manifest_sha256: str = Field(pattern=_SHA256)
    source_commit: str = Field(pattern=_COMMIT)
    source_markdown_locator: str
    source_markdown_sha256: str = Field(pattern=_SHA256)
    bibliography_locator: str
    bibliography_sha256: str = Field(pattern=_SHA256)
    argument_contract_locator: str
    argument_contract_file_sha256: str = Field(pattern=_SHA256)
    argument_contract_sha256: str = Field(pattern=_SHA256)
    source_input_locator: Literal["SOURCE_INPUT.json"] = "SOURCE_INPUT.json"
    source_input_file_sha256: str = Field(pattern=_SHA256)
    source_input_fingerprint: str = Field(pattern=_SHA256)
    source_proposal_locator: Literal["SOURCE_PROPOSAL.json"] = "SOURCE_PROPOSAL.json"
    source_proposal_file_sha256: str = Field(pattern=_SHA256)
    source_proposal_sha256: str = Field(pattern=_SHA256)
    source_semantic_text_sha256: str = Field(pattern=_SHA256)
    proposal_semantic_text_sha256: str = Field(pattern=_SHA256)
    claim_ids: tuple[str, ...] = Field(min_length=1, max_length=200)
    headline_claim_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    citation_ids: tuple[str, ...] = Field(default=(), max_length=500)
    material_limitation_ids: tuple[str, ...] = Field(default=(), max_length=100)
    admitted_evidence_count: Literal[0] = 0
    all_adopted_claims_unsupported: Literal[True] = True
    semantic_admission_passed: Literal[True] = True
    prose_generation_performed: Literal[False] = False
    model_call_performed: Literal[False] = False
    scientific_evidence_established: Literal[False] = False
    paper_mutation_performed: Literal[False] = False
    record_sha256: str = Field(pattern=_SHA256)

    @field_validator("project_id")
    @classmethod
    def project_is_safe(cls, value: str) -> str:
        return validate_project_id(value)

    @field_validator("run_id", "paper_directory")
    @classmethod
    def identifiers_are_safe(cls, value: str, info: object) -> str:
        return validate_entry_id(value, field_name=str(getattr(info, "field_name", "identifier")))

    @field_validator(
        "source_markdown_locator",
        "bibliography_locator",
        "argument_contract_locator",
    )
    @classmethod
    def source_locators_are_safe(cls, value: str) -> str:
        return validate_relative_locator(value, field_name="paper-adoption source locator")

    @model_validator(mode="after")
    def adoption_is_closed_and_self_hashed(self) -> ProjectPaperAdoptionBundle:
        prefix = ("papers", self.paper_directory)
        for locator in (
            self.source_markdown_locator,
            self.bibliography_locator,
            self.argument_contract_locator,
        ):
            if PurePosixPath(locator).parts[:2] != prefix:
                raise ValueError("paper-adoption sources must belong to the adopted paper")
        for values, label in (
            (self.claim_ids, "claim"),
            (self.headline_claim_ids, "headline claim"),
            (self.citation_ids, "citation"),
            (self.material_limitation_ids, "material limitation"),
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"paper-adoption {label} IDs must be sorted and unique")
        if set(self.headline_claim_ids) - set(self.claim_ids):
            raise ValueError("paper-adoption headline claims must belong to the claim set")
        if self.source_semantic_text_sha256 != self.proposal_semantic_text_sha256:
            raise ValueError("paper adoption must preserve normalized semantic text")
        expected = content_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("project paper-adoption bundle hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> ProjectPaperAdoptionBundle:
        payload = {"schema_version": "1.0", **values}
        payload.pop("record_sha256", None)
        unsigned = cls.model_construct(record_sha256="0" * 64, **payload)
        return cls(
            **payload,
            record_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"record_sha256"})
            ),
        )


@dataclass(frozen=True)
class PreparedProjectPaperAdoption:
    bundle: ProjectPaperAdoptionBundle
    source_input: EvidencePaperDraftInput
    source_proposal: EvidencePaperDraftProposal


@dataclass(frozen=True)
class _ParsedPaper:
    title: str
    abstract_text: str
    abstract_citation_keys: tuple[str, ...]
    sections: tuple[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], ...]


def prepare_project_paper_adoption(
    runtime: ProjectRuntime,
    *,
    project_id: str,
    paper_directory: str,
    run_id: str,
    source_commit: str,
    expected_revision: int,
) -> PreparedProjectPaperAdoption:
    """Project a registered paper into semantic writing contracts without mutation."""

    validate_project_id(project_id)
    validate_entry_id(paper_directory, field_name="paper_directory")
    validate_entry_id(run_id, field_name="run_id")
    snapshot = runtime.open(project_id)
    if snapshot.revision != expected_revision:
        raise ValueError(
            f"stale project revision {expected_revision}; current is {snapshot.revision}"
        )
    if run_id in {item.run_id for item in snapshot.manifest.runs}:
        raise ValueError("paper-adoption run is already registered")
    paper = runtime.open_paper(project_id, paper_directory)
    entry = next(
        (item for item in snapshot.papers if item.directory_name == paper_directory),
        None,
    )
    if entry is None:
        raise ValueError("registered paper entry is unavailable")
    required = {"source-markdown", "bibliography", "paper-argument-contract"}
    if missing := sorted(required - set(paper.files)):
        raise ValueError("paper adoption requires registered files: " + ", ".join(missing))

    project_root = runtime.projects_root / project_id
    paper_root = project_root / "papers" / paper_directory
    markdown_path = _contained_regular_file(paper_root, paper.files["source-markdown"])
    bibliography_path = _contained_regular_file(paper_root, paper.files["bibliography"])
    contract_path = _contained_regular_file(
        paper_root,
        paper.files["paper-argument-contract"],
    )
    markdown_raw = _bounded_bytes(markdown_path, _MAX_MARKDOWN_BYTES, "paper markdown")
    bibliography_raw = _bounded_bytes(
        bibliography_path,
        _MAX_BIBLIOGRAPHY_BYTES,
        "paper bibliography",
    )
    try:
        markdown = markdown_raw.decode("utf-8")
        bibliography = bibliography_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("paper adoption sources must be UTF-8") from exc
    contract = load_paper_argument_contract(contract_path)
    if (
        contract.project_id != project_id
        or contract.paper_id != paper_directory
        or contract.manuscript_sha256 != hashlib.sha256(markdown_raw).hexdigest()
    ):
        raise ValueError("paper argument contract differs from the registered manuscript")

    source_input, source_proposal, semantic_sha256 = _semantic_source(
        markdown=markdown,
        bibliography=bibliography,
        paper=paper,
        contract=contract,
        target_venue=snapshot.manifest.target_venue or paper.venue_id or "unspecified venue",
    )
    input_bytes = _json_bytes(source_input)
    proposal_bytes = _json_bytes(source_proposal)
    bundle = ProjectPaperAdoptionBundle.create(
        project_id=project_id,
        run_id=run_id,
        paper_directory=paper_directory,
        paper_manifest_sha256=entry.manifest_sha256,
        source_commit=source_commit,
        source_markdown_locator=(
            Path("papers") / paper_directory / paper.files["source-markdown"]
        ).as_posix(),
        source_markdown_sha256=hashlib.sha256(markdown_raw).hexdigest(),
        bibliography_locator=(
            Path("papers") / paper_directory / paper.files["bibliography"]
        ).as_posix(),
        bibliography_sha256=hashlib.sha256(bibliography_raw).hexdigest(),
        argument_contract_locator=(
            Path("papers") / paper_directory / paper.files["paper-argument-contract"]
        ).as_posix(),
        argument_contract_file_sha256=hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        argument_contract_sha256=contract.contract_sha256,
        source_input_file_sha256=hashlib.sha256(input_bytes).hexdigest(),
        source_input_fingerprint=source_input.fingerprint,
        source_proposal_file_sha256=hashlib.sha256(proposal_bytes).hexdigest(),
        source_proposal_sha256=content_sha256(source_proposal),
        source_semantic_text_sha256=semantic_sha256,
        proposal_semantic_text_sha256=_proposal_semantic_sha256(
            source_input,
            source_proposal,
        ),
        claim_ids=tuple(sorted(item.claim_id for item in source_input.claims)),
        headline_claim_ids=tuple(
            sorted(item.claim_id for item in source_input.claims if item.headline)
        ),
        citation_ids=tuple(sorted(item.citation_id for item in source_input.citations)),
        material_limitation_ids=tuple(
            sorted(item.limitation_id for item in source_input.material_limitations)
        ),
    )
    return PreparedProjectPaperAdoption(
        bundle=bundle,
        source_input=source_input,
        source_proposal=source_proposal,
    )


def publish_project_paper_adoption(
    runtime: ProjectRuntime,
    *,
    prepared: PreparedProjectPaperAdoption,
    expected_revision: int,
) -> tuple[ProjectSnapshot, ProjectPaperAdoptionBundle]:
    """Publish one prepared adoption as a recoverable project-owned run."""

    bundle = prepared.bundle
    if runtime.open(bundle.project_id).revision != expected_revision:
        raise ValueError("project changed after paper adoption was prepared")
    run = ProjectRun(
        run_id=bundle.run_id,
        provider="scitaste-native",
        model="deterministic-paper-adopter",
        condition="registered-paper-semantic-adoption",
        seed=0,
        status="preparing-paper-adoption",
        evidence_scope="paper-semantics-only-no-scientific-evidence",
        repository_commit=bundle.source_commit,
        paper_directory=bundle.paper_directory,
        paper_manifest_sha256=bundle.paper_manifest_sha256,
        model_calls=0,
        scientific_evidence_established=False,
    )
    snapshot = runtime.begin_run(bundle.project_id, run, expected_revision=expected_revision)
    run_root = runtime.projects_root / bundle.project_id / "runs" / bundle.run_id
    target = run_root / "paper_adoption"
    temporary = Path(tempfile.mkdtemp(prefix=".paper-adoption-", dir=run_root))
    try:
        _write_exclusive(
            temporary / bundle.source_input_locator,
            _json_bytes(prepared.source_input),
        )
        _write_exclusive(
            temporary / bundle.source_proposal_locator,
            _json_bytes(prepared.source_proposal),
        )
        _write_exclusive(temporary / "MANIFEST.json", _json_bytes(bundle))
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    snapshot = runtime.update_run(
        bundle.project_id,
        bundle.run_id,
        expected_revision=snapshot.revision,
        status="complete-paper-adopted",
        stage_path="paper_adoption",
        artifact=f"runs/{bundle.run_id}/paper_adoption/MANIFEST.json",
        adoption_bundle_sha256=bundle.record_sha256,
        source_input_fingerprint=bundle.source_input_fingerprint,
        source_proposal_sha256=bundle.source_proposal_sha256,
    )
    observed = inspect_project_paper_adoption(runtime, bundle.project_id, bundle.run_id)
    if observed.record_sha256 != bundle.record_sha256:
        raise ValueError("published paper adoption differs from prepared bytes")
    return snapshot, observed


def inspect_project_paper_adoption(
    runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
) -> ProjectPaperAdoptionBundle:
    """Reparse and rehash a registered paper-adoption transition."""

    snapshot = runtime.open(project_id)
    run = next((item for item in snapshot.manifest.runs if item.run_id == run_id), None)
    expected_artifact = f"runs/{run_id}/paper_adoption/MANIFEST.json"
    if run is None or run.artifact != expected_artifact or run.stage_path != "paper_adoption":
        raise ValueError("project run does not identify a complete paper adoption")
    project_root = runtime.projects_root / project_id
    manifest_path = _contained_regular_file(project_root, expected_artifact)
    bundle = ProjectPaperAdoptionBundle.model_validate_json(manifest_path.read_bytes())
    if bundle.project_id != project_id or bundle.run_id != run_id:
        raise ValueError("paper-adoption identity differs from its project run")
    if (
        run.status != "complete-paper-adopted"
        or getattr(run, "adoption_bundle_sha256", None) != bundle.record_sha256
        or getattr(run, "model_calls", None) != 0
    ):
        raise ValueError("project run metadata differs from its paper adoption")

    paper = runtime.open_paper(project_id, bundle.paper_directory)
    entry = next(
        (item for item in snapshot.papers if item.directory_name == bundle.paper_directory),
        None,
    )
    if entry is None or entry.manifest_sha256 != bundle.paper_manifest_sha256:
        raise ValueError("adopted paper manifest differs")
    source_paths = {
        "markdown": _contained_regular_file(project_root, bundle.source_markdown_locator),
        "bibliography": _contained_regular_file(project_root, bundle.bibliography_locator),
        "contract": _contained_regular_file(project_root, bundle.argument_contract_locator),
    }
    markdown_raw = _bounded_bytes(source_paths["markdown"], _MAX_MARKDOWN_BYTES, "paper markdown")
    bibliography_raw = _bounded_bytes(
        source_paths["bibliography"],
        _MAX_BIBLIOGRAPHY_BYTES,
        "paper bibliography",
    )
    if (
        hashlib.sha256(markdown_raw).hexdigest() != bundle.source_markdown_sha256
        or hashlib.sha256(bibliography_raw).hexdigest() != bundle.bibliography_sha256
        or hashlib.sha256(source_paths["contract"].read_bytes()).hexdigest()
        != bundle.argument_contract_file_sha256
    ):
        raise ValueError("paper-adoption source bytes differ")
    contract = load_paper_argument_contract(source_paths["contract"])
    if contract.contract_sha256 != bundle.argument_contract_sha256:
        raise ValueError("paper-adoption argument contract differs")
    try:
        markdown = markdown_raw.decode("utf-8")
        bibliography = bibliography_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("paper-adoption sources are not UTF-8") from exc
    expected_input, expected_proposal, semantic_sha256 = _semantic_source(
        markdown=markdown,
        bibliography=bibliography,
        paper=paper,
        contract=contract,
        target_venue=snapshot.manifest.target_venue or paper.venue_id or "unspecified venue",
    )

    stage_root = manifest_path.parent
    input_path = _contained_regular_file(stage_root, bundle.source_input_locator)
    proposal_path = _contained_regular_file(stage_root, bundle.source_proposal_locator)
    input_raw = input_path.read_bytes()
    proposal_raw = proposal_path.read_bytes()
    source_input = EvidencePaperDraftInput.model_validate_json(input_raw)
    source_proposal = EvidencePaperDraftProposal.model_validate_json(proposal_raw)
    if (
        hashlib.sha256(input_raw).hexdigest() != bundle.source_input_file_sha256
        or source_input != expected_input
        or source_input.fingerprint != bundle.source_input_fingerprint
    ):
        raise ValueError("paper-adoption semantic input differs")
    if (
        hashlib.sha256(proposal_raw).hexdigest() != bundle.source_proposal_file_sha256
        or source_proposal != expected_proposal
        or content_sha256(source_proposal) != bundle.source_proposal_sha256
    ):
        raise ValueError("paper-adoption semantic proposal differs")
    if (
        semantic_sha256 != bundle.source_semantic_text_sha256
        or _proposal_semantic_sha256(source_input, source_proposal)
        != bundle.proposal_semantic_text_sha256
    ):
        raise ValueError("paper-adoption normalized prose differs")
    return bundle


def load_project_paper_adoption_source(
    runtime: ProjectRuntime,
    project_id: str,
    run_id: str,
) -> tuple[ProjectPaperAdoptionBundle, EvidencePaperDraftInput, EvidencePaperDraftProposal]:
    """Load semantic source objects only after the complete adoption revalidates."""

    bundle = inspect_project_paper_adoption(runtime, project_id, run_id)
    stage_root = runtime.projects_root / project_id / "runs" / run_id / "paper_adoption"
    source_input = EvidencePaperDraftInput.model_validate_json(
        _contained_regular_file(stage_root, bundle.source_input_locator).read_bytes()
    )
    source_proposal = EvidencePaperDraftProposal.model_validate_json(
        _contained_regular_file(stage_root, bundle.source_proposal_locator).read_bytes()
    )
    return bundle, source_input, source_proposal


def _semantic_source(
    *,
    markdown: str,
    bibliography: str,
    paper: PaperManifest,
    contract: PaperArgumentContract,
    target_venue: str,
) -> tuple[EvidencePaperDraftInput, EvidencePaperDraftProposal, str]:
    parsed = _parse_paper(markdown)
    citation_titles = _bibliography_titles(bibliography)
    used_keys = sorted(
        {
            *parsed.abstract_citation_keys,
            *(
                key
                for _section_name, paragraphs in parsed.sections
                for _text, keys in paragraphs
                for key in keys
            ),
        }
    )
    unknown = sorted(set(used_keys) - set(citation_titles))
    if unknown:
        raise ValueError(
            "paper adoption found citation keys absent from bibliography: " + ", ".join(unknown)
        )
    citation_ids = {
        key: f"citation-{hashlib.sha256(key.encode()).hexdigest()[:16]}" for key in used_keys
    }
    citations = tuple(
        EvidencePaperCitationInput(
            citation_id=citation_ids[key],
            bibtex_key=key,
            title=citation_titles[key],
            relevance="Cited by the adopted registered manuscript.",
        )
        for key in used_keys
    )
    claim_contracts = {item.claim_id: item for item in contract.claims}
    carriers = {item.carrier_id: item for item in contract.carriers}
    claims = tuple(
        EvidencePaperClaimInput(
            claim_id=claim_id,
            statement=" ".join(
                carriers[carrier_id].intended_takeaway for carrier_id in item.primary_carrier_ids
            )
            or contract.central_answer,
            support_status=PaperClaimSupport.UNSUPPORTED,
            headline=item.role == "headline",
        )
        for claim_id, item in sorted(claim_contracts.items())
    )
    limitations = tuple(
        MaterialWritingLimitation(
            limitation_id=item.limitation_id,
            text=item.statement,
            affected_claim_ids=tuple(sorted(item.affected_claim_ids)),
        )
        for item in sorted(contract.material_limitations, key=lambda value: value.limitation_id)
    )
    section_contracts = {item.heading.casefold(): item for item in contract.sections}
    entry_points = {item.location: item for item in contract.entry_points}
    headline_ids = tuple(sorted(item.claim_id for item in claims if item.headline))
    abstract_claims = tuple(
        sorted(
            {
                *headline_ids,
                *(entry_points.get("abstract").claim_ids if entry_points.get("abstract") else ()),
            }
        )
    )
    abstract = EvidencePaperParagraph(
        paragraph_id="adopted-abstract",
        role=EvidencePaperParagraphRole.INTERPRETATION,
        text=parsed.abstract_text,
        claim_ids=abstract_claims,
        citation_ids=tuple(sorted(citation_ids[key] for key in parsed.abstract_citation_keys)),
    )
    adopted_sections = []
    limitation_ids = tuple(sorted(item.limitation_id for item in limitations))
    for section_index, (section_name, raw_paragraphs) in enumerate(parsed.sections, start=1):
        contract_section = section_contracts.get(section_name.casefold())
        section_claims = tuple(sorted(contract_section.claim_ids)) if contract_section else ()
        role = _section_role(section_name)
        paragraphs = []
        for paragraph_index, (text, keys) in enumerate(raw_paragraphs, start=1):
            paragraphs.append(
                EvidencePaperParagraph(
                    paragraph_id=f"adopted-s{section_index:02d}-p{paragraph_index:03d}",
                    role=role,
                    text=text,
                    claim_ids=section_claims,
                    citation_ids=tuple(sorted(citation_ids[key] for key in keys)),
                    limitation_ids=(
                        limitation_ids
                        if role is EvidencePaperParagraphRole.LIMITATION and paragraph_index == 1
                        else ()
                    ),
                )
            )
        adopted_sections.append(
            EvidencePaperDraftSection(
                section_name=section_name,
                paragraphs=tuple(paragraphs),
            )
        )
    complete_text = "\n\n".join(
        [
            parsed.title,
            abstract.text,
            *(paragraph.text for section in adopted_sections for paragraph in section.paragraphs),
        ]
    )
    source_input = EvidencePaperDraftInput(
        manuscript_id=paper.paper_id,
        title_hint=parsed.title,
        target_venue=target_venue,
        central_question=contract.central_question,
        intended_contribution=contract.central_answer,
        claims=claims,
        evidence=(),
        citations=citations,
        material_limitations=limitations,
        required_sections=tuple(item.section_name for item in adopted_sections),
        authorized_numeric_tokens=tuple(sorted(set(_NUMBER.findall(complete_text)))),
        maximum_words=30_000,
    )
    proposal = EvidencePaperDraftProposal(
        input_fingerprint=source_input.fingerprint,
        title=parsed.title,
        abstract=abstract,
        sections=tuple(adopted_sections),
        retained_limitation_ids=limitation_ids,
        observed_numeric_tokens=tuple(sorted(set(_NUMBER.findall(complete_text)))),
    )
    context = NodeContext(
        project_id=paper.project_id,
        stage="COMMUNICATION",
        state_snapshot_id=f"paper-adoption:{paper.paper_id}",
        cumulative_api_cost_usd=0,
        claim_ids=[item.claim_id for item in claims],
        evidence_ids=[],
        section_ids=list(source_input.required_sections),
    )
    policy = NodePolicy(
        policy_id="deterministic-paper-adoption",
        enabled=False,
        allowed_node_names=[EVIDENCE_PAPER_DRAFT_NODE],
        expected_backend="none",
        expected_model="deterministic-paper-adopter",
    )
    rejections = EvidencePaperDraftNode()._proposal_rejections(
        proposal,
        input_data=source_input,
        context=context,
        policy=policy,
    )
    if rejections:
        raise ValueError(
            "registered paper cannot enter semantic revision: " + "; ".join(rejections)
        )
    semantic_sha256 = _parsed_semantic_sha256(parsed)
    if semantic_sha256 != _proposal_semantic_sha256(source_input, proposal):
        raise ValueError("paper adoption parser changed normalized prose")
    return source_input, proposal, semantic_sha256


def _parse_paper(markdown: str) -> _ParsedPaper:
    title_match = _TITLE.match(markdown)
    if title_match is None:
        raise ValueError("paper adoption requires an explicit Markdown Title block")
    title = title_match.group(1).strip()
    headings = list(_TOP_HEADING.finditer(markdown))
    if not headings or headings[0].group(1).strip().casefold() != "abstract":
        raise ValueError("paper adoption requires Abstract as the first top-level section")
    bodies = []
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        bodies.append((match.group(1).strip(), markdown[match.end() : end].strip()))
    abstract_blocks = _paragraph_blocks(bodies[0][1])
    if not abstract_blocks:
        raise ValueError("paper adoption requires a non-empty abstract")
    abstract_text, abstract_keys = _detach_citations("\n\n".join(abstract_blocks))
    sections = []
    for section_name, body in bodies[1:]:
        blocks = _paragraph_blocks(body)
        if not blocks:
            raise ValueError(f"paper adoption section {section_name!r} is empty")
        sections.append(
            (
                section_name,
                tuple(_detach_citations(block) for block in blocks),
            )
        )
    if not 5 <= len(sections) <= 20:
        raise ValueError("paper adoption requires between 5 and 20 top-level sections")
    return _ParsedPaper(
        title=title,
        abstract_text=abstract_text,
        abstract_citation_keys=abstract_keys,
        sections=tuple(sections),
    )


def _paragraph_blocks(body: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in re.split(r"\n[ \t]*\n+", body) if item.strip())


def _detach_citations(text: str) -> tuple[str, tuple[str, ...]]:
    keys = []

    def replace(match: re.Match[str]) -> str:
        keys.extend(item.strip() for item in match.group(1).split(",") if item.strip())
        return ""

    cleaned = _CITATION.sub(replace, text)
    cleaned = re.sub(r"[ \t]+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"~(?=[,.;:]|\s|$)", "", cleaned).strip()
    if not cleaned:
        raise ValueError("paper adoption found an empty paragraph after citation detachment")
    return cleaned, tuple(sorted(set(keys)))


def _bibliography_titles(bibliography: str) -> dict[str, str]:
    matches = list(_BIB_ENTRY.finditer(bibliography))
    entries = {}
    for index, match in enumerate(matches):
        key = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(bibliography)
        block = bibliography[match.start() : end]
        title_match = _BIB_TITLE.search(block)
        title = title_match.group(1) if title_match else key
        title = re.sub(r"[{}]", "", title)
        title = re.sub(r"\s+", " ", title).strip() or key
        if key in entries:
            raise ValueError(f"paper adoption found duplicate BibTeX key {key!r}")
        entries[key] = title
    return entries


def _section_role(section_name: str) -> EvidencePaperParagraphRole:
    normalized = section_name.casefold()
    if "related work" in normalized:
        return EvidencePaperParagraphRole.POSITIONING
    if normalized in {"introduction", "background"}:
        return EvidencePaperParagraphRole.MOTIVATION
    if "limitation" in normalized:
        return EvidencePaperParagraphRole.LIMITATION
    if normalized in {"conclusion", "conclusions"}:
        return EvidencePaperParagraphRole.CONCLUSION
    if any(
        token in normalized
        for token in ("method", "framework", "architecture", "formulation", "protocol")
    ):
        return EvidencePaperParagraphRole.METHOD
    return EvidencePaperParagraphRole.INTERPRETATION


def _parsed_semantic_sha256(parsed: _ParsedPaper) -> str:
    return content_sha256(
        {
            "title": parsed.title,
            "abstract": {
                "text": parsed.abstract_text,
                "citation_keys": parsed.abstract_citation_keys,
            },
            "sections": [
                {
                    "section_name": section_name,
                    "paragraphs": [
                        {"text": text, "citation_keys": keys} for text, keys in paragraphs
                    ],
                }
                for section_name, paragraphs in parsed.sections
            ],
        }
    )


def _proposal_semantic_sha256(
    source_input: EvidencePaperDraftInput,
    proposal: EvidencePaperDraftProposal,
) -> str:
    keys = {item.citation_id: item.bibtex_key for item in source_input.citations}

    def citation_keys(paragraph: EvidencePaperParagraph) -> tuple[str, ...]:
        return tuple(sorted(keys[item] for item in paragraph.citation_ids))

    return content_sha256(
        {
            "title": proposal.title,
            "abstract": {
                "text": proposal.abstract.text,
                "citation_keys": citation_keys(proposal.abstract),
            },
            "sections": [
                {
                    "section_name": section.section_name,
                    "paragraphs": [
                        {
                            "text": paragraph.text,
                            "citation_keys": citation_keys(paragraph),
                        }
                        for paragraph in section.paragraphs
                    ],
                }
                for section in proposal.sections
            ],
        }
    )


def _json_bytes(value: BaseModel) -> bytes:
    return (value.model_dump_json(indent=2) + "\n").encode("utf-8")


def _bounded_bytes(path: Path, limit: int, label: str) -> bytes:
    size = path.stat().st_size
    if size <= 0 or size > limit:
        raise ValueError(f"{label} must be non-empty and no larger than {limit} bytes")
    return path.read_bytes()


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _contained_regular_file(root: Path, locator: str) -> Path:
    root = root.resolve(strict=True)
    current = root
    for part in PurePosixPath(locator).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("paper-adoption paths must not contain symbolic links")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("paper-adoption path escapes its owning root") from exc
    if not resolved.is_file():
        raise ValueError("paper-adoption path must be a regular file")
    return resolved


__all__ = [
    "PreparedProjectPaperAdoption",
    "ProjectPaperAdoptionBundle",
    "inspect_project_paper_adoption",
    "load_project_paper_adoption_source",
    "prepare_project_paper_adoption",
    "publish_project_paper_adoption",
]

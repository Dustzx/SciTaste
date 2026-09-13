"""Unchanged-core Agent Laboratory task and workspace preparation.

This module closes the deterministic boundary between one frozen research brief
and Agent Laboratory's native YAML interface.  Preparation never imports or
executes the upstream system and never reads a provider credential.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.adapter_contract import (
    inspect_adapter_contract,
    load_adapter_contract_manifest,
)
from scitaste.evaluation.resources import load_external_resource_corpus

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MANIFEST_BYTES = 1_048_576
_MAX_TASK_BYTES = 4 * 1_048_576
_MAX_TRACKED_FILES = 4_096
_MAX_TRACKED_BYTES = 512 * 1_048_576


class AgentLaboratoryPreparationBudget(BaseModel):
    """Native workflow shape, not provider-spend authorization."""

    model_config = _CONFIG

    number_of_papers: Literal[1] = 1
    literature_review_papers: int = Field(default=5, ge=1, le=20)
    mle_solver_steps: int = Field(default=3, ge=1, le=20)
    paper_solver_steps: int = Field(default=1, ge=1, le=20)
    parallel_labs: Literal[False] = False
    compile_latex: Literal[False] = False


class AgentLaboratoryPreparationManifest(BaseModel):
    """Exact no-run input translation for one Agent Laboratory trajectory."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    preparation_id: str = Field(pattern=_ID)
    authorization_scope: Literal["prepare-only-no-execution"]
    project_id: str = Field(pattern=_ID)
    external_resource_id: Literal["agent-laboratory"] = "agent-laboratory"
    expected_upstream_commit: str = Field(pattern=_COMMIT)
    upstream_checkout: str = Field(min_length=1, max_length=1_000)
    adapter_contract_ref: str = Field(min_length=1, max_length=1_000)
    adapter_contract_file_sha256: str = Field(pattern=_SHA256)
    adapter_contract_proposal_sha256: str = Field(pattern=_SHA256)
    resource_corpus_ref: str = Field(min_length=1, max_length=1_000)
    resource_corpus_file_sha256: str = Field(pattern=_SHA256)
    resource_corpus_sha256: str = Field(pattern=_SHA256)
    benchmark_resource_id: str = Field(pattern=_ID)
    task_id: str = Field(pattern=_ID)
    task_brief_ref: str = Field(min_length=1, max_length=1_000)
    task_brief_sha256: str = Field(pattern=_SHA256)
    task_brief_bytes: int = Field(ge=1, le=_MAX_TASK_BYTES)
    task_is_held_out: Literal[True] = True
    hidden_evaluation_content_included: Literal[False] = False
    provider_id: Literal["openai"] = "openai"
    model_id: Literal["o3-mini"] = "o3-mini"
    model_revision: Literal["o3-mini-2025-01-31"] = "o3-mini-2025-01-31"
    budget: AgentLaboratoryPreparationBudget = Field(
        default_factory=AgentLaboratoryPreparationBudget
    )
    no_provider_call_performed: Literal[True] = True
    no_upstream_execution_performed: Literal[True] = True

    @model_validator(mode="after")
    def paths_are_normalized(self) -> AgentLaboratoryPreparationManifest:
        for label, value in (
            ("upstream checkout", self.upstream_checkout),
            ("adapter contract", self.adapter_contract_ref),
            ("resource corpus", self.resource_corpus_ref),
            ("task brief", self.task_brief_ref),
        ):
            _validate_relative_path(value, label)
        return self

    @property
    def proposal_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


class AgentLaboratorySourceSnapshot(BaseModel):
    model_config = _CONFIG

    upstream_commit: str = Field(pattern=_COMMIT)
    tracked_file_count: int = Field(ge=1)
    tracked_bytes: int = Field(ge=1)
    tree_sha256: str = Field(pattern=_SHA256)


class AgentLaboratoryPreparationReceipt(BaseModel):
    """Prepared real upstream workspace; execution remains separately gated."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    preparation_id: str
    proposal_sha256: str = Field(pattern=_SHA256)
    adapter_contract_proposal_sha256: str = Field(pattern=_SHA256)
    resource_corpus_sha256: str = Field(pattern=_SHA256)
    task_id: str
    task_brief_sha256: str = Field(pattern=_SHA256)
    task_brief_bytes: int = Field(ge=1)
    task_roundtrip_sha256: str = Field(pattern=_SHA256)
    source_snapshot: AgentLaboratorySourceSnapshot
    materialized_source_tree_sha256: str = Field(pattern=_SHA256)
    config_ref: Literal["upstream/scitaste_agentlab.yaml"] = "upstream/scitaste_agentlab.yaml"
    config_sha256: str = Field(pattern=_SHA256)
    task_copy_ref: Literal["input/task.md"] = "input/task.md"
    argv: tuple[str, ...]
    expected_native_artifacts: tuple[str, ...]
    input_translation_complete: Literal[True] = True
    upstream_source_unchanged: Literal[True] = True
    failure_inclusive_workspace: Literal[True] = True
    ready_for_live_execution: Literal[False] = False
    remaining_execution_blockers: tuple[
        Literal[
            "dependency_environment_unqualified",
            "provider_credential_unbound",
            "sandbox_policy_unqualified",
            "provider_telemetry_unobserved",
            "task_assets_unqualified",
        ],
        ...,
    ]
    no_provider_call_performed: Literal[True] = True
    no_upstream_execution_performed: Literal[True] = True
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def self_hash_is_valid(self) -> AgentLaboratoryPreparationReceipt:
        payload = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != _canonical_sha256(payload):
            raise ValueError("Agent Laboratory preparation receipt hash mismatch")
        return self


class LoadedAgentLaboratoryPreparation(BaseModel):
    model_config = _CONFIG

    path: Path
    file_sha256: str = Field(pattern=_SHA256)
    manifest: AgentLaboratoryPreparationManifest


def load_agent_laboratory_preparation(
    path: str | Path,
) -> LoadedAgentLaboratoryPreparation:
    requested = Path(path)
    if requested.is_symlink():
        raise ValueError("Agent Laboratory preparation manifest cannot be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("Agent Laboratory preparation manifest must be a bounded file")
    raw = resolved.read_bytes()
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("Agent Laboratory preparation manifest must be UTF-8") from exc
    if not isinstance(payload, dict):
        raise ValueError("Agent Laboratory preparation manifest must contain a mapping")
    return LoadedAgentLaboratoryPreparation(
        path=resolved,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=AgentLaboratoryPreparationManifest.model_validate(payload),
    )


def prepare_agent_laboratory_adapter(
    manifest: AgentLaboratoryPreparationManifest,
    *,
    source_root: str | Path,
    output_dir: str | Path,
) -> AgentLaboratoryPreparationReceipt:
    """Compile one exact brief into the pinned native interface without running it."""

    root = Path(source_root).resolve(strict=True)
    contract_path = _resolve_bounded(root, manifest.adapter_contract_ref, expect_file=True)
    corpus_path = _resolve_bounded(root, manifest.resource_corpus_ref, expect_file=True)
    brief_path = _resolve_bounded(root, manifest.task_brief_ref, expect_file=True)
    upstream = _resolve_bounded(root, manifest.upstream_checkout, expect_directory=True)
    _verify_sha256(contract_path, manifest.adapter_contract_file_sha256, "adapter contract")
    _verify_sha256(corpus_path, manifest.resource_corpus_file_sha256, "resource corpus")
    _verify_sha256(brief_path, manifest.task_brief_sha256, "task brief")
    if brief_path.stat().st_size != manifest.task_brief_bytes:
        raise ValueError("task brief byte size differs from the preparation manifest")

    contract = load_adapter_contract_manifest(contract_path)
    corpus = load_external_resource_corpus(corpus_path)
    if contract.manifest.proposal_sha256 != manifest.adapter_contract_proposal_sha256:
        raise ValueError("adapter contract semantic hash differs")
    if corpus.corpus.semantic_sha256 != manifest.resource_corpus_sha256:
        raise ValueError("resource corpus semantic hash differs")
    contract_report = inspect_adapter_contract(
        contract.manifest,
        corpus.corpus,
        source_root=root,
    )
    if not contract_report.proposal_viable:
        raise ValueError("Agent Laboratory adapter contract is not implementation-viable")
    if (
        contract.manifest.external_resource_id != manifest.external_resource_id
        or contract.manifest.expected_upstream_commit != manifest.expected_upstream_commit
    ):
        raise ValueError("adapter contract names another upstream system revision")
    model = contract.manifest.model_translation
    if (
        model.provider_id != manifest.provider_id
        or model.requested_model_id != manifest.model_id
        or model.requested_model_revision != manifest.model_revision
    ):
        raise ValueError("preparation model identity differs from the adapter contract")

    observed_commit = _git(upstream, "rev-parse", "HEAD")
    if observed_commit != manifest.expected_upstream_commit:
        raise ValueError("Agent Laboratory checkout commit differs")
    if _git(upstream, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("Agent Laboratory checkout must be clean")

    brief_bytes = brief_path.read_bytes()
    try:
        brief = brief_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Agent Laboratory task brief must be UTF-8") from exc

    destination = Path(output_dir)
    if destination.exists():
        raise ValueError("Agent Laboratory preparation output already exists")
    parent = destination.parent.resolve(strict=True)
    if parent.is_symlink():
        raise ValueError("Agent Laboratory preparation parent cannot be a symlink")
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=parent))
    try:
        input_root = temporary / "input"
        materialized_upstream = temporary / "upstream"
        input_root.mkdir()
        materialized_upstream.mkdir()
        (input_root / "task.md").write_bytes(brief_bytes)
        source_snapshot = _copy_tracked_checkout(upstream, materialized_upstream)
        config = _native_config(manifest, brief)
        config_bytes = yaml.safe_dump(
            config,
            allow_unicode=True,
            sort_keys=False,
            width=1_000_000,
        ).encode("utf-8")
        config_path = materialized_upstream / "scitaste_agentlab.yaml"
        config_path.write_bytes(config_bytes)
        loaded_config = yaml.safe_load(config_bytes.decode("utf-8"))
        roundtrip = str(loaded_config["research-topic"]).encode("utf-8")
        if roundtrip != brief_bytes:
            raise ValueError("native YAML roundtrip changed the exact task brief")

        materialized_tree = _tree_sha256(materialized_upstream, exclude={"scitaste_agentlab.yaml"})
        if materialized_tree != source_snapshot.tree_sha256:
            raise ValueError("materialized upstream source differs from its clean checkout")
        receipt_payload = {
            "schema_version": "1.0",
            "preparation_id": manifest.preparation_id,
            "proposal_sha256": manifest.proposal_sha256,
            "adapter_contract_proposal_sha256": manifest.adapter_contract_proposal_sha256,
            "resource_corpus_sha256": manifest.resource_corpus_sha256,
            "task_id": manifest.task_id,
            "task_brief_sha256": manifest.task_brief_sha256,
            "task_brief_bytes": len(brief_bytes),
            "task_roundtrip_sha256": hashlib.sha256(roundtrip).hexdigest(),
            "source_snapshot": source_snapshot.model_dump(mode="json"),
            "materialized_source_tree_sha256": materialized_tree,
            "config_ref": "upstream/scitaste_agentlab.yaml",
            "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
            "task_copy_ref": "input/task.md",
            "argv": (
                "{python}",
                "ai_lab_repo.py",
                "--yaml-location",
                "scitaste_agentlab.yaml",
            ),
            "expected_native_artifacts": (
                "upstream/MATH_research_dir",
                "upstream/state_saves",
                "upstream/agent_times_0.txt",
                "stdout.log",
                "stderr.log",
                "provider_telemetry.jsonl",
            ),
            "input_translation_complete": True,
            "upstream_source_unchanged": True,
            "failure_inclusive_workspace": True,
            "ready_for_live_execution": False,
            "remaining_execution_blockers": (
                "dependency_environment_unqualified",
                "provider_credential_unbound",
                "sandbox_policy_unqualified",
                "provider_telemetry_unobserved",
                "task_assets_unqualified",
            ),
            "no_provider_call_performed": True,
            "no_upstream_execution_performed": True,
        }
        receipt = AgentLaboratoryPreparationReceipt(
            **receipt_payload,
            receipt_sha256=_canonical_sha256(receipt_payload),
        )
        (temporary / "PREPARATION_RECEIPT.json").write_text(
            receipt.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
        return receipt
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _native_config(
    manifest: AgentLaboratoryPreparationManifest,
    task_brief: str,
) -> dict[str, object]:
    neutral_note = (
        "Treat the research-topic field as the complete visible task brief. Do not infer hidden "
        "evaluation content, add privileged task guidance, or claim access to unavailable assets."
    )
    asset_note = (
        "The byte-identical starting brief is retained at ../input/task.md for provenance. "
        "Use only assets whose paths and availability are stated in that brief."
    )
    phases = (
        "plan-formulation",
        "data-preparation",
        "running-experiments",
        "results-interpretation",
        "report-writing",
    )
    return {
        "copilot_mode": False,
        "research-topic": task_brief,
        "compile-latex": manifest.budget.compile_latex,
        "llm-backend": manifest.model_id,
        "lit-review-backend": manifest.model_id,
        "language": "English",
        "num-papers-lit-review": manifest.budget.literature_review_papers,
        "num-papers-to-write": manifest.budget.number_of_papers,
        "parallel-labs": manifest.budget.parallel_labs,
        "mlesolver-max-steps": manifest.budget.mle_solver_steps,
        "papersolver-max-steps": manifest.budget.paper_solver_steps,
        "lab-index": 0,
        "load-previous": False,
        "except-if-fail": True,
        "agentRxiv": False,
        "construct-agentRxiv": False,
        "task-notes": {phase: [neutral_note, asset_note] for phase in phases},
    }


def _copy_tracked_checkout(source: Path, destination: Path) -> AgentLaboratorySourceSnapshot:
    raw = _git_bytes(source, "ls-files", "-z")
    relative_paths = [item for item in raw.split(b"\0") if item]
    if not relative_paths or len(relative_paths) > _MAX_TRACKED_FILES:
        raise ValueError("Agent Laboratory tracked-file count is outside preparation bounds")
    entries: list[tuple[str, int, str]] = []
    total = 0
    for encoded in relative_paths:
        try:
            relative = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Agent Laboratory tracked path is not UTF-8") from exc
        _validate_relative_path(relative, "Agent Laboratory tracked path")
        source_path = source.joinpath(*PurePosixPath(relative).parts)
        metadata = source_path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Agent Laboratory tracked source contains a non-regular file")
        size = metadata.st_size
        total += size
        if total > _MAX_TRACKED_BYTES:
            raise ValueError("Agent Laboratory tracked source exceeds preparation byte bounds")
        target = destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        target.chmod(stat.S_IMODE(metadata.st_mode))
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        entries.append((relative, stat.S_IMODE(metadata.st_mode), digest))
    return AgentLaboratorySourceSnapshot(
        upstream_commit=_git(source, "rev-parse", "HEAD"),
        tracked_file_count=len(entries),
        tracked_bytes=total,
        tree_sha256=_entry_tree_sha256(entries),
    )


def _tree_sha256(root: Path, *, exclude: set[str]) -> str:
    entries: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("materialized Agent Laboratory source contains a non-regular file")
        entries.append(
            (
                relative,
                stat.S_IMODE(metadata.st_mode),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return _entry_tree_sha256(entries)


def _entry_tree_sha256(entries: list[tuple[str, int, str]]) -> str:
    return _canonical_sha256(
        [{"path": path, "mode": mode, "sha256": digest} for path, mode, digest in entries]
    )


def _resolve_bounded(
    root: Path,
    locator: str,
    *,
    expect_file: bool = False,
    expect_directory: bool = False,
) -> Path:
    _validate_relative_path(locator, "workspace locator")
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"workspace locator traverses a symlink: {locator}")
    resolved = current.resolve(strict=True)
    resolved.relative_to(root)
    if expect_file and not resolved.is_file():
        raise ValueError(f"workspace locator is not a file: {locator}")
    if expect_directory and not resolved.is_dir():
        raise ValueError(f"workspace locator is not a directory: {locator}")
    return resolved


def _validate_relative_path(value: str, label: str) -> None:
    path = PurePosixPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or not path.parts
        or "//" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{label} must be a normalized relative path")


def _verify_sha256(path: Path, expected: str, label: str) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"{label} SHA-256 differs from the preparation manifest")


def _git(cwd: Path, *arguments: str) -> str:
    return _git_bytes(cwd, *arguments).decode("utf-8").strip()


def _git_bytes(cwd: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("unable to inspect Agent Laboratory Git checkout") from exc
    if len(result.stdout) > 8 * 1_048_576:
        raise ValueError("Agent Laboratory Git inspection output exceeded its bound")
    return result.stdout


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "AgentLaboratoryPreparationBudget",
    "AgentLaboratoryPreparationManifest",
    "AgentLaboratoryPreparationReceipt",
    "AgentLaboratorySourceSnapshot",
    "LoadedAgentLaboratoryPreparation",
    "load_agent_laboratory_preparation",
    "prepare_agent_laboratory_adapter",
]

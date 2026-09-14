"""Typed proposal and deterministic admission for native experiment source."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scitaste.executor.native_sandbox import (
    MetricDirection,
    NativeExperimentDefinition,
    NativeExperimentLimits,
)
from scitaste.project.models import content_sha256

_SHA256 = r"^[0-9a-f]{64}$"
_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_METRIC_NAME = r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$"
_MEASUREMENT_MARKER = "SCITASTE_MEASUREMENTS_JSON="
_MAX_CONFIG_BYTES = 1_048_576
_MAX_SOURCE_BYTES = 262_144
_SUPPORTED_IMPORTS = frozenset(
    {
        "collections",
        "decimal",
        "fractions",
        "functools",
        "hashlib",
        "itertools",
        "json",
        "math",
        "random",
        "re",
        "statistics",
        "string",
    }
)
_BLOCKED_CALLS = frozenset(
    {
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "help",
        "input",
        "locals",
        "memoryview",
        "open",
        "setattr",
        "vars",
        "__import__",
    }
)
_BLOCKED_NODES: tuple[type[ast.AST], ...] = (
    ast.AsyncFor,
    ast.AsyncFunctionDef,
    ast.AsyncWith,
    ast.Await,
    ast.ClassDef,
    ast.Global,
    ast.Nonlocal,
    ast.Yield,
    ast.YieldFrom,
)


class NativeCodeProducer(BaseModel):
    """Provenance for source creation; it confers no execution authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["registered", "model"]
    producer_id: str = Field(min_length=1, pattern=_SAFE_ID)
    provider: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    request_sha256: str | None = Field(default=None, pattern=_SHA256)
    response_sha256: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def mode_matches_provenance(self) -> NativeCodeProducer:
        model_fields = (
            self.provider,
            self.model,
            self.request_sha256,
            self.response_sha256,
        )
        if self.mode == "model" and any(item is None for item in model_fields):
            raise ValueError(
                "model-produced source requires provider, model, request, and response hashes"
            )
        if self.mode == "registered" and any(item is not None for item in model_fields):
            raise ValueError("registered source cannot claim model-call provenance")
        return self


class NativeCodeAdmissionPolicy(BaseModel):
    """Versioned, deterministic static gate applied before runtime isolation."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    policy_id: str = Field(default="scitaste-native-python-v1", pattern=_SAFE_ID)
    max_source_bytes: int = Field(default=65_536, ge=1024, le=262_144)
    max_ast_nodes: int = Field(default=5_000, ge=32, le=20_000)
    max_literal_bytes: int = Field(default=32_768, ge=256, le=131_072)
    allowed_imports: tuple[str, ...] = (
        "collections",
        "decimal",
        "fractions",
        "functools",
        "hashlib",
        "itertools",
        "json",
        "math",
        "random",
        "re",
        "statistics",
        "string",
    )

    @field_validator("allowed_imports")
    @classmethod
    def imports_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) > 64:
            raise ValueError("native code policy requires between 1 and 64 allowed imports")
        if any(not item.isidentifier() or item.startswith("_") for item in value):
            raise ValueError("allowed imports must be public top-level Python identifiers")
        if tuple(sorted(set(value))) != value:
            raise ValueError("allowed imports must be unique and lexically sorted")
        unsupported = sorted(set(value) - _SUPPORTED_IMPORTS)
        if unsupported:
            raise ValueError(
                "native code policy cannot expand the platform import ceiling: "
                + ", ".join(unsupported)
            )
        return value


class NativeCodeExperimentProposal(BaseModel):
    """Experiment identity and runtime limits requested by a source proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    experiment_id: str = Field(min_length=1, pattern=_SAFE_ID)
    primary_metric: str = Field(pattern=_METRIC_NAME)
    metric_direction: MetricDirection
    support_threshold: float
    limits: NativeExperimentLimits = Field(default_factory=NativeExperimentLimits)

    @field_validator("support_threshold", mode="before")
    @classmethod
    def threshold_is_finite(cls, value: object) -> object:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError("native code support_threshold must be finite")
        return value


class NativeCodeProposalConfig(BaseModel):
    """Strict external proposal configuration loaded without granting file authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: str = Field(min_length=1, pattern=_SAFE_ID)
    source_path: Path
    rationale: str = Field(min_length=1, max_length=4_000)
    expected_metrics: tuple[str, ...] = Field(min_length=1, max_length=64)
    producer: NativeCodeProducer
    experiment: NativeCodeExperimentProposal
    policy: NativeCodeAdmissionPolicy = Field(default_factory=NativeCodeAdmissionPolicy)

    @field_validator("expected_metrics")
    @classmethod
    def metrics_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _metric_name_is_valid(item) for item in value):
            raise ValueError("expected metrics require safe metric names")
        if len(set(value)) != len(value):
            raise ValueError("expected metrics must be unique")
        return value

    @model_validator(mode="after")
    def primary_metric_is_expected(self) -> NativeCodeProposalConfig:
        if self.experiment.primary_metric not in self.expected_metrics:
            raise ValueError("the primary metric must appear in expected_metrics")
        return self


class NativeCodePolicyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    policy: NativeCodeAdmissionPolicy
    record_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def self_hash_matches(self) -> NativeCodePolicyRecord:
        _require_self_hash(self)
        return self


class NativeCodeProposalRecord(BaseModel):
    """Content-bound source proposal copied into the owning run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: str = Field(pattern=_SAFE_ID)
    config_sha256: str = Field(pattern=_SHA256)
    source_locator: Literal["proposed.py"] = "proposed.py"
    source_sha256: str = Field(pattern=_SHA256)
    source_bytes: int = Field(ge=0)
    source_lines: int = Field(ge=0)
    rationale: str
    expected_metrics: tuple[str, ...]
    producer: NativeCodeProducer
    experiment: NativeCodeExperimentProposal
    policy_sha256: str = Field(pattern=_SHA256)
    authority: Literal["proposal-only"] = "proposal-only"
    record_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def self_hash_matches(self) -> NativeCodeProposalRecord:
        _require_self_hash(self)
        return self


class NativeCodeViolation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    message: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=0)


class NativeCodeAdmissionRecord(BaseModel):
    """Deterministic verdict; acceptance still requires runtime isolation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    proposal_sha256: str = Field(pattern=_SHA256)
    policy_sha256: str = Field(pattern=_SHA256)
    source_sha256: str = Field(pattern=_SHA256)
    decision: Literal["accepted", "rejected"]
    ast_node_count: int = Field(ge=0)
    literal_bytes: int = Field(ge=0)
    imports: tuple[str, ...]
    violations: tuple[NativeCodeViolation, ...]
    admitted_source_locator: Literal["admitted/experiment.py"] | None = None
    runtime_isolation_required: Literal[True] = True
    record_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def verdict_is_consistent(self) -> NativeCodeAdmissionRecord:
        if self.decision == "accepted":
            if self.violations or self.admitted_source_locator is None:
                raise ValueError(
                    "accepted native code requires no violations and an admitted source"
                )
        elif not self.violations or self.admitted_source_locator is not None:
            raise ValueError("rejected native code requires violations and no admitted source")
        _require_self_hash(self)
        return self


class NativeCodeContextRecord(BaseModel):
    """Run-relative manifest for the complete proposal/admission boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    binding_sha256: str = Field(pattern=_SHA256)
    config_sha256: str = Field(pattern=_SHA256)
    decision: Literal["accepted", "rejected"]
    proposal_locator: str
    proposal_record_sha256: str = Field(pattern=_SHA256)
    proposal_file_sha256: str = Field(pattern=_SHA256)
    policy_locator: str
    policy_record_sha256: str = Field(pattern=_SHA256)
    policy_file_sha256: str = Field(pattern=_SHA256)
    admission_locator: str
    admission_record_sha256: str = Field(pattern=_SHA256)
    admission_file_sha256: str = Field(pattern=_SHA256)
    proposed_source_locator: str
    proposed_source_sha256: str = Field(pattern=_SHA256)
    admitted_source_locator: str | None = None
    admitted_source_sha256: str | None = Field(default=None, pattern=_SHA256)
    record_sha256: str = Field(pattern=_SHA256)

    @field_validator(
        "proposal_locator",
        "policy_locator",
        "admission_locator",
        "proposed_source_locator",
        "admitted_source_locator",
    )
    @classmethod
    def locators_are_safe(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_locator(value)
        return value

    @model_validator(mode="after")
    def verdict_and_hashes_match(self) -> NativeCodeContextRecord:
        if self.decision == "accepted":
            if self.admitted_source_locator is None or self.admitted_source_sha256 is None:
                raise ValueError("accepted code context requires an admitted source")
        elif self.admitted_source_locator is not None or self.admitted_source_sha256 is not None:
            raise ValueError("rejected code context cannot contain an admitted source")
        _require_self_hash(self)
        return self


@dataclass(frozen=True)
class NativeCodeInspection:
    """Mutation-free inspection result used by dry-run and materialization."""

    config_path: Path
    config: NativeCodeProposalConfig
    config_sha256: str
    source: bytes
    policy: NativeCodePolicyRecord
    proposal: NativeCodeProposalRecord
    admission: NativeCodeAdmissionRecord
    binding_sha256: str

    def experiment_definition(self, source_path: Path) -> NativeExperimentDefinition:
        if self.admission.decision != "accepted":
            raise NativeCodeAdmissionError(self.admission)
        return NativeExperimentDefinition(
            schema_version="1.1",
            source_path=source_path,
            required_metrics=self.config.expected_metrics,
            **self.config.experiment.model_dump(mode="python"),
        )


class NativeCodeAdmissionError(ValueError):
    """Raised after a rejected proposal has been inspected or durably recorded."""

    def __init__(self, admission: NativeCodeAdmissionRecord) -> None:
        self.admission = admission
        codes = ", ".join(item.code for item in admission.violations)
        super().__init__(f"native code proposal was rejected by static admission: {codes}")


def load_native_code_proposal_config(path: str | Path) -> NativeCodeProposalConfig:
    """Load a strict proposal and resolve only its declared source path."""

    config, _ = _load_native_code_proposal_config_with_bytes(path)
    return config


def _load_native_code_proposal_config_with_bytes(
    path: str | Path,
) -> tuple[NativeCodeProposalConfig, bytes]:
    config_path = Path(path)
    try:
        config_bytes = _read_bounded_regular_file(
            config_path,
            max_bytes=_MAX_CONFIG_BYTES,
            label="native code proposal config",
        )
        payload = yaml.safe_load(config_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("invalid native code proposal config") from exc
    if not isinstance(payload, dict):
        raise ValueError("native code proposal config must be a mapping")
    source_value = payload.get("source_path")
    if not isinstance(source_value, str) or not source_value.strip():
        raise ValueError("native code proposal source_path must be a non-empty string")
    source_path = Path(source_value)
    if not source_path.is_absolute():
        source_path = config_path.parent / source_path
    payload["source_path"] = source_path.absolute()
    return NativeCodeProposalConfig.model_validate(payload), config_bytes


def inspect_native_code_proposal(path: str | Path) -> NativeCodeInspection:
    """Read exact config/source bytes and produce a deterministic admission verdict."""

    config_path = Path(path)
    config, config_bytes = _load_native_code_proposal_config_with_bytes(config_path)
    source_path = config.source_path
    source = _read_bounded_regular_file(
        source_path,
        max_bytes=_MAX_SOURCE_BYTES,
        label="native code proposal source",
    )
    config_sha256 = _bytes_sha256(config_bytes)
    source_sha256 = _bytes_sha256(source)
    policy_payload = {
        "schema_version": "1.0",
        "policy": config.policy.model_dump(mode="json"),
    }
    policy = NativeCodePolicyRecord(
        **policy_payload,
        record_sha256=content_sha256(policy_payload),
    )
    proposal_payload = {
        "schema_version": "1.0",
        "proposal_id": config.proposal_id,
        "config_sha256": config_sha256,
        "source_locator": "proposed.py",
        "source_sha256": source_sha256,
        "source_bytes": len(source),
        "source_lines": _line_count(source),
        "rationale": config.rationale,
        "expected_metrics": config.expected_metrics,
        "producer": config.producer.model_dump(mode="json"),
        "experiment": config.experiment.model_dump(mode="json"),
        "policy_sha256": policy.record_sha256,
        "authority": "proposal-only",
    }
    proposal = NativeCodeProposalRecord(
        **proposal_payload,
        record_sha256=content_sha256(proposal_payload),
    )
    admission = _admit_source(source, config, proposal, policy)
    binding_sha256 = content_sha256(
        {
            "schema_version": "1.0",
            "config_sha256": config_sha256,
            "source_sha256": source_sha256,
            "policy_sha256": policy.record_sha256,
            "proposal_sha256": proposal.record_sha256,
            "admission_sha256": admission.record_sha256,
        }
    )
    return NativeCodeInspection(
        config_path=config_path.absolute(),
        config=config,
        config_sha256=config_sha256,
        source=source,
        policy=policy,
        proposal=proposal,
        admission=admission,
        binding_sha256=binding_sha256,
    )


def prepare_native_code_experiment(
    path: str | Path,
    *,
    run_root: str | Path,
    inspection: NativeCodeInspection | None = None,
    context_directory: str = "code",
) -> NativeExperimentDefinition:
    """Publish or verify project-owned evidence, then return only admitted source."""

    if inspection is None:
        inspection = inspect_native_code_proposal(path)
    elif Path(path).absolute() != inspection.config_path:
        raise ValueError("native code inspection belongs to another proposal config")
    root = Path(run_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("native code run root must be an existing non-symlink directory")
    if re.fullmatch(_SAFE_ID, context_directory) is None:
        raise ValueError("native code context directory must be one safe path segment")
    context_root = root / "native_execution" / "context" / context_directory
    receipt_path = context_root / "CODE.json"
    if receipt_path.exists():
        definition = _verify_materialized_context(
            inspection,
            root,
            receipt_path,
            context_directory=context_directory,
        )
        if inspection.admission.decision == "rejected":
            raise NativeCodeAdmissionError(inspection.admission)
        return definition
    if context_root.exists():
        raise ValueError("incomplete native code context requires manual inspection")
    native_root = root / "native_execution"
    native_root.mkdir(exist_ok=True)
    if native_root.is_symlink() or not native_root.is_dir():
        raise ValueError("native execution root must be an owned directory")
    context_parent = native_root / "context"
    context_parent.mkdir(exist_ok=True)
    if context_parent.is_symlink() or not context_parent.is_dir():
        raise ValueError("native code context parent must be an owned directory")
    try:
        context_parent.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise ValueError("native code context parent escapes its owning run") from exc
    temporary = Path(tempfile.mkdtemp(prefix=".code.", dir=context_parent))
    try:
        _write_new_file(temporary / "proposed.py", inspection.source)
        _write_new_json(temporary / "POLICY.json", inspection.policy.model_dump(mode="json"))
        _write_new_json(temporary / "PROPOSAL.json", inspection.proposal.model_dump(mode="json"))
        _write_new_json(temporary / "ADMISSION.json", inspection.admission.model_dump(mode="json"))
        admitted_path: Path | None = None
        if inspection.admission.decision == "accepted":
            admitted_path = temporary / "admitted" / "experiment.py"
            _write_new_file(admitted_path, inspection.source)
        final_admitted = context_root / "admitted" / "experiment.py" if admitted_path else None
        record_payload = {
            "schema_version": "1.0",
            "binding_sha256": inspection.binding_sha256,
            "config_sha256": inspection.config_sha256,
            "decision": inspection.admission.decision,
            "proposal_locator": _owned_locator(root, context_root / "PROPOSAL.json"),
            "proposal_record_sha256": inspection.proposal.record_sha256,
            "proposal_file_sha256": _json_sha256(inspection.proposal.model_dump(mode="json")),
            "policy_locator": _owned_locator(root, context_root / "POLICY.json"),
            "policy_record_sha256": inspection.policy.record_sha256,
            "policy_file_sha256": _json_sha256(inspection.policy.model_dump(mode="json")),
            "admission_locator": _owned_locator(root, context_root / "ADMISSION.json"),
            "admission_record_sha256": inspection.admission.record_sha256,
            "admission_file_sha256": _json_sha256(inspection.admission.model_dump(mode="json")),
            "proposed_source_locator": _owned_locator(root, context_root / "proposed.py"),
            "proposed_source_sha256": inspection.proposal.source_sha256,
            "admitted_source_locator": (
                _owned_locator(root, final_admitted) if final_admitted is not None else None
            ),
            "admitted_source_sha256": (
                inspection.proposal.source_sha256 if final_admitted is not None else None
            ),
        }
        record = NativeCodeContextRecord(
            **record_payload,
            record_sha256=content_sha256(record_payload),
        )
        _write_new_json(temporary / "CODE.json", record.model_dump(mode="json"))
        _fsync_directory(temporary)
        os.replace(temporary, context_root)
        _fsync_directory(context_parent)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    definition = _verify_materialized_context(
        inspection,
        root,
        receipt_path,
        context_directory=context_directory,
    )
    if inspection.admission.decision == "rejected":
        raise NativeCodeAdmissionError(inspection.admission)
    return definition


def load_native_code_context_record(
    run_root: str | Path,
    *,
    context_directory: str = "code",
) -> NativeCodeContextRecord | None:
    """Read the self-hashed context receipt for summary/reporting."""

    if re.fullmatch(_SAFE_ID, context_directory) is None:
        raise ValueError("native code context directory must be one safe path segment")
    path = (
        Path(run_root)
        / "native_execution"
        / "context"
        / context_directory
        / "CODE.json"
    )
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("native code context receipt must be a regular file")
    try:
        return NativeCodeContextRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid native code context receipt") from exc


def _admit_source(
    source: bytes,
    config: NativeCodeProposalConfig,
    proposal: NativeCodeProposalRecord,
    policy: NativeCodePolicyRecord,
) -> NativeCodeAdmissionRecord:
    violations: list[NativeCodeViolation] = []
    imports: set[str] = set()
    nodes: list[ast.AST] = []
    literal_bytes = 0
    if len(source) > config.policy.max_source_bytes:
        violations.append(
            _violation(
                "source-size",
                f"source exceeds {config.policy.max_source_bytes} bytes",
            )
        )
    text: str | None
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        text = None
        violations.append(
            _violation("source-encoding", "source must be valid UTF-8", line=exc.start + 1)
        )
    tree: ast.AST | None = None
    if text is not None:
        try:
            tree = ast.parse(text, filename="proposed.py", mode="exec")
        except SyntaxError as exc:
            violations.append(
                _violation(
                    "syntax-error",
                    exc.msg,
                    line=exc.lineno,
                    column=(exc.offset - 1 if exc.offset else None),
                )
            )
        except (MemoryError, RecursionError, ValueError) as exc:
            violations.append(
                _violation(
                    "parser-limit",
                    f"source cannot be safely parsed: {type(exc).__name__}",
                )
            )
    constants: list[str] = []
    if tree is not None:
        nodes = list(ast.walk(tree))
        if len(nodes) > config.policy.max_ast_nodes:
            violations.append(
                _violation(
                    "ast-size",
                    f"source exceeds {config.policy.max_ast_nodes} AST nodes",
                )
            )
        for node in nodes:
            if isinstance(node, ast.Constant):
                if isinstance(node.value, str):
                    constants.append(node.value)
                    literal_bytes += len(node.value.encode("utf-8"))
                elif isinstance(node.value, bytes):
                    literal_bytes += len(node.value)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
                    _check_import(alias.name, node, config.policy, violations)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    violations.append(
                        _at_node("relative-import", "relative imports are not admitted", node)
                    )
                else:
                    imports.add(module)
                    private_names = [
                        alias.name for alias in node.names if alias.name.startswith("_")
                    ]
                    if private_names:
                        violations.append(
                            _at_node(
                                "private-import",
                                f"private imports are not admitted: {', '.join(private_names)}",
                                node,
                            )
                        )
                    if module == "__future__":
                        if any(alias.name != "annotations" for alias in node.names):
                            violations.append(
                                _at_node(
                                    "import-not-allowed",
                                    "only the annotations future import is admitted",
                                    node,
                                )
                            )
                    else:
                        _check_import(module, node, config.policy, violations)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in _BLOCKED_CALLS:
                    violations.append(
                        _at_node(
                            "blocked-call",
                            f"call to {node.func.id!r} is not admitted",
                            node,
                        )
                    )
            if isinstance(node, ast.Name) and _is_dunder(node.id):
                violations.append(
                    _at_node("dunder-access", f"dunder name {node.id!r} is not admitted", node)
                )
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                code = "dunder-access" if _is_dunder(node.attr) else "private-access"
                violations.append(
                    _at_node(code, f"private attribute {node.attr!r} is not admitted", node)
                )
            if isinstance(node, _BLOCKED_NODES):
                violations.append(
                    _at_node(
                        "blocked-syntax",
                        f"{type(node).__name__} syntax is not admitted",
                        node,
                    )
                )
        if literal_bytes > config.policy.max_literal_bytes:
            violations.append(
                _violation(
                    "literal-size",
                    f"literals exceed {config.policy.max_literal_bytes} bytes",
                )
            )
        if not any(_MEASUREMENT_MARKER in item for item in constants):
            violations.append(
                _violation(
                    "measurement-marker",
                    "source must contain the literal SciTaste measurement marker",
                )
            )
        for metric in config.expected_metrics:
            if metric not in constants:
                violations.append(
                    _violation(
                        "expected-metric",
                        f"expected metric {metric!r} is not a literal in source",
                    )
                )
    decision: Literal["accepted", "rejected"] = "rejected" if violations else "accepted"
    admitted_locator = "admitted/experiment.py" if decision == "accepted" else None
    payload = {
        "schema_version": "1.0",
        "proposal_sha256": proposal.record_sha256,
        "policy_sha256": policy.record_sha256,
        "source_sha256": proposal.source_sha256,
        "decision": decision,
        "ast_node_count": len(nodes),
        "literal_bytes": literal_bytes,
        "imports": tuple(sorted(imports)),
        "violations": [item.model_dump(mode="json") for item in violations],
        "admitted_source_locator": admitted_locator,
        "runtime_isolation_required": True,
    }
    return NativeCodeAdmissionRecord(
        **payload,
        record_sha256=content_sha256(payload),
    )


def _verify_materialized_context(
    inspection: NativeCodeInspection,
    run_root: Path,
    receipt_path: Path,
    *,
    context_directory: str = "code",
) -> NativeExperimentDefinition:
    receipt_file = _verified_owned_file(run_root, _owned_locator(run_root, receipt_path))
    try:
        receipt = NativeCodeContextRecord.model_validate_json(
            receipt_file.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid native code context record") from exc
    if (
        receipt.binding_sha256 != inspection.binding_sha256
        or receipt.config_sha256 != inspection.config_sha256
        or receipt.decision != inspection.admission.decision
        or receipt.proposal_record_sha256 != inspection.proposal.record_sha256
        or receipt.policy_record_sha256 != inspection.policy.record_sha256
        or receipt.admission_record_sha256 != inspection.admission.record_sha256
        or receipt.proposed_source_sha256 != inspection.proposal.source_sha256
        or receipt.proposal_file_sha256 != _json_sha256(inspection.proposal.model_dump(mode="json"))
        or receipt.policy_file_sha256 != _json_sha256(inspection.policy.model_dump(mode="json"))
        or receipt.admission_file_sha256
        != _json_sha256(inspection.admission.model_dump(mode="json"))
    ):
        raise ValueError("native code proposal changed since the run was created")
    context_root = run_root / "native_execution" / "context" / context_directory
    expected_locators = {
        "proposal": _owned_locator(run_root, context_root / "PROPOSAL.json"),
        "policy": _owned_locator(run_root, context_root / "POLICY.json"),
        "admission": _owned_locator(run_root, context_root / "ADMISSION.json"),
        "proposed": _owned_locator(run_root, context_root / "proposed.py"),
        "admitted": (
            _owned_locator(run_root, context_root / "admitted" / "experiment.py")
            if receipt.decision == "accepted"
            else None
        ),
    }
    if (
        receipt.proposal_locator != expected_locators["proposal"]
        or receipt.policy_locator != expected_locators["policy"]
        or receipt.admission_locator != expected_locators["admission"]
        or receipt.proposed_source_locator != expected_locators["proposed"]
        or receipt.admitted_source_locator != expected_locators["admitted"]
    ):
        raise ValueError("native code context record locators are not canonical")
    proposal_path = _verified_owned_file(
        run_root, receipt.proposal_locator, receipt.proposal_file_sha256
    )
    policy_path = _verified_owned_file(run_root, receipt.policy_locator, receipt.policy_file_sha256)
    admission_path = _verified_owned_file(
        run_root, receipt.admission_locator, receipt.admission_file_sha256
    )
    proposed_path = _verified_owned_file(
        run_root, receipt.proposed_source_locator, receipt.proposed_source_sha256
    )
    _require_exact_model(proposal_path, NativeCodeProposalRecord, inspection.proposal)
    _require_exact_model(policy_path, NativeCodePolicyRecord, inspection.policy)
    _require_exact_model(admission_path, NativeCodeAdmissionRecord, inspection.admission)
    if proposed_path.read_bytes() != inspection.source:
        raise ValueError("project-owned proposed source does not match its exact input")
    if receipt.decision == "rejected":
        return inspection.experiment_definition(proposed_path)
    assert receipt.admitted_source_locator is not None
    assert receipt.admitted_source_sha256 is not None
    admitted = _verified_owned_file(
        run_root,
        receipt.admitted_source_locator,
        receipt.admitted_source_sha256,
    )
    if admitted.read_bytes() != inspection.source:
        raise ValueError("admitted source differs from the reviewed proposal")
    return inspection.experiment_definition(admitted)


def _require_exact_model(path: Path, model: type[BaseModel], expected: BaseModel) -> None:
    try:
        observed = model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"invalid native code evidence record: {path.name}") from exc
    if observed.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise ValueError(f"native code evidence no longer matches inspection: {path.name}")


def _check_import(
    module: str,
    node: ast.AST,
    policy: NativeCodeAdmissionPolicy,
    violations: list[NativeCodeViolation],
) -> None:
    root = module.partition(".")[0]
    if not root or root not in policy.allowed_imports:
        violations.append(
            _at_node("import-not-allowed", f"import {module!r} is not admitted", node)
        )


def _at_node(code: str, message: str, node: ast.AST) -> NativeCodeViolation:
    return _violation(
        code,
        message,
        line=getattr(node, "lineno", None),
        column=getattr(node, "col_offset", None),
    )


def _violation(
    code: str,
    message: str,
    *,
    line: int | None = None,
    column: int | None = None,
) -> NativeCodeViolation:
    return NativeCodeViolation(code=code, message=message, line=line, column=column)


def _require_self_hash(record: BaseModel) -> None:
    observed = record.model_dump(mode="json").get("record_sha256")
    expected = content_sha256(record.model_dump(mode="json", exclude={"record_sha256"}))
    if observed != expected:
        raise ValueError("native code evidence record hash mismatch")


def _metric_name_is_valid(value: str) -> bool:
    return re.fullmatch(_METRIC_NAME, value) is not None


def _is_dunder(value: str) -> bool:
    return len(value) >= 4 and value.startswith("__") and value.endswith("__")


def _line_count(source: bytes) -> int:
    if not source:
        return 0
    return source.count(b"\n") + (0 if source.endswith(b"\n") else 1)


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_bounded_regular_file(path: Path, *, max_bytes: int, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{label} must be a regular non-symlink file") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"{label} must be a regular non-symlink file")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65_536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise ValueError(f"{label} exceeds the {max_bytes}-byte platform ceiling")
        return payload
    finally:
        os.close(descriptor)


def _owned_locator(run_root: Path, path: Path) -> str:
    try:
        return path.absolute().relative_to(run_root.absolute()).as_posix()
    except ValueError as exc:
        raise ValueError("native code path escapes its owning run") from exc


def _validate_locator(locator: str) -> None:
    candidate = PurePosixPath(locator)
    if (
        not locator
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or candidate.as_posix() != locator
    ):
        raise ValueError("native code context locators must be canonical relative paths")


def _verified_owned_file(run_root: Path, locator: str, expected_sha256: str | None = None) -> Path:
    _validate_locator(locator)
    root = run_root.resolve(strict=True)
    path = run_root / locator
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"native code context locator is not a regular file: {locator}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"native code context locator escapes its run: {locator}") from exc
    if expected_sha256 is not None and _bytes_sha256(resolved.read_bytes()) != expected_sha256:
        raise ValueError(f"native code context artifact hash mismatch: {locator}")
    return resolved


def _write_new_json(path: Path, payload: object) -> None:
    _write_new_file(path, _json_bytes(payload))


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"


def _json_sha256(payload: object) -> str:
    return _bytes_sha256(_json_bytes(payload))


def _write_new_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

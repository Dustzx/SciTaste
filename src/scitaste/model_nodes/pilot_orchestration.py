"""Project-owned orchestration for the bounded model-node engineering pilot."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from scitaste.model_nodes.backends import (
    ScriptedStructuredBackend,
    ScriptedStructuredReply,
)
from scitaste.model_nodes.openai_compatible import (
    StructuredHTTPTransport,
    StructuredOpenAICompatibleBackend,
    StructuredOpenAICompatibleConfig,
)
from scitaste.model_nodes.pilot_models import (
    AcceptanceStatus,
    IndependentOutcomeReview,
    ManualInterventionMeasurement,
    PilotCase,
    PilotCaseResult,
    PilotCondition,
    PilotOutcome,
    PilotProtocol,
    PilotReport,
    ReplayEvidenceRole,
    canonical_sha256,
)
from scitaste.model_nodes.pilot_runner import (
    BackendBinding,
    BoundedPilotRunner,
    expected_request_fingerprint,
    save_pilot_report,
    validate_manual_interventions,
)
from scitaste.model_nodes.replay import RecordingStructuredBackend, ReplayStructuredBackend
from scitaste.project import ProjectRun, ProjectRuntime
from scitaste.project.models import validate_entry_id, validate_project_id
from scitaste.project.runtime import ProjectRevisionConflictError

PILOT_STAGE_PATH = "model_node_pilot"


class OrchestrationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PilotBindingKind(StrEnum):
    SCRIPTED = "scripted"
    RECORDING_SCRIPTED = "recording_scripted"
    REPLAY = "replay"
    LIVE = "live"


class ContentAddressedFile(OrchestrationModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def path_is_safe_relative(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("content-addressed paths must use POSIX separators")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or "//" in value
        ):
            raise ValueError("content-addressed path must be normalized and relative")
        return value


class ProtocolFile(ContentAddressedFile):
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PilotBindingConfig(OrchestrationModel):
    backend_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    kind: PilotBindingKind
    backend_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    replies: ContentAddressedFile | None = None
    live_config: ContentAddressedFile | None = None

    @model_validator(mode="after")
    def files_match_kind(self) -> PilotBindingConfig:
        if self.kind in {PilotBindingKind.SCRIPTED, PilotBindingKind.RECORDING_SCRIPTED}:
            if self.replies is None or self.live_config is not None:
                raise ValueError("scripted bindings require only a replies file")
        elif self.kind is PilotBindingKind.LIVE:
            if self.live_config is None or self.replies is not None:
                raise ValueError("live bindings require only a live_config file")
        elif self.replies is not None or self.live_config is not None:
            raise ValueError("replay bindings derive evidence from the project recording")
        return self


class PilotOrchestrationConfig(OrchestrationModel):
    schema_version: Literal["1.0"] = "1.0"
    config_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    config_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    protocol: ProtocolFile
    bindings: tuple[PilotBindingConfig, ...] = ()
    manual_interventions: ContentAddressedFile | None = None
    independent_review: ContentAddressedFile | None = None
    live_enabled: bool = False
    self_dogfooding_only: Literal[True] = True
    effectiveness_claim: Literal[False] = False

    @model_validator(mode="after")
    def binding_keys_are_unique(self) -> PilotOrchestrationConfig:
        keys = [binding.backend_key for binding in self.bindings]
        if len(keys) != len(set(keys)):
            raise ValueError("binding backend_key values must be unique")
        return self

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self)


class ScriptedReplyBundle(OrchestrationModel):
    schema_version: Literal["1.0"] = "1.0"
    backend_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    fixture_only: Literal[True] = True
    effectiveness_claim: Literal[False] = False
    replies: dict[str, ScriptedStructuredReply]


class ManualInterventionBundle(OrchestrationModel):
    schema_version: Literal["1.0"] = "1.0"
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_scope: Literal["external_observation"] = "external_observation"
    effectiveness_claim: Literal[False] = False
    measurements: tuple[ManualInterventionMeasurement, ...]

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> ManualInterventionBundle:
        case_ids = [item.case_id for item in self.measurements]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("manual measurement case_id values must be unique")
        return self


class IndependentReviewBundle(OrchestrationModel):
    schema_version: Literal["1.0"] = "1.0"
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_scope: Literal["external_independent_review"] = "external_independent_review"
    effectiveness_claim: Literal[False] = False
    review: IndependentOutcomeReview


@dataclass(frozen=True)
class LoadedPilotConfiguration:
    source_path: Path
    source_sha256: str
    config: PilotOrchestrationConfig
    protocol_source_path: Path
    protocol_source_sha256: str
    protocol: PilotProtocol
    replies: Mapping[str, ScriptedReplyBundle]
    live_configs: Mapping[str, StructuredOpenAICompatibleConfig]
    manual_bundle: ManualInterventionBundle | None
    review_bundle: IndependentReviewBundle | None
    missing_non_live_bindings: tuple[str, ...]
    missing_live_bindings: tuple[str, ...]


class PilotOrchestrationError(ValueError):
    """Fail-closed orchestration/configuration error safe for CLI display."""


class PilotRunConflictError(PilotOrchestrationError):
    """Raised when another writer owns or already completed the run."""


def load_pilot_orchestration_config(path: str | Path) -> LoadedPilotConfiguration:
    """Load all declared inputs with duplicate-key, containment, and hash checks."""

    source = Path(path).expanduser().resolve()
    source_bytes, source_data = _load_hashed_yaml(source)
    config = _validate_strict_json(
        PilotOrchestrationConfig,
        source_data,
        label="orchestration configuration",
    )
    root = source.parent
    protocol_path, protocol_bytes, protocol_data = _resolve_hashed_yaml(
        root,
        config.protocol,
    )
    protocol = _validate_strict_json(
        PilotProtocol,
        protocol_data,
        label="pilot protocol",
    )
    if protocol.fingerprint != config.protocol.protocol_sha256:
        raise PilotOrchestrationError("protocol canonical hash drift")

    bindings = {binding.backend_key: binding for binding in config.bindings}
    used_keys: set[str] = set()
    missing_non_live: list[str] = []
    missing_live: list[str] = []
    for case in protocol.cases:
        if case.condition is PilotCondition.DETERMINISTIC_ONLY:
            continue
        assert case.backend_key is not None
        if case.condition is PilotCondition.SCRIPTED_NODE:
            expected_kind = (
                PilotBindingKind.RECORDING_SCRIPTED
                if case.replay_role is ReplayEvidenceRole.RECORDING
                else PilotBindingKind.SCRIPTED
            )
        elif case.condition is PilotCondition.REPLAY_NODE:
            expected_kind = PilotBindingKind.REPLAY
        else:
            expected_kind = PilotBindingKind.LIVE
        binding = bindings.get(case.backend_key)
        if binding is None:
            if case.condition is PilotCondition.LIVE_STRUCTURED_NODE:
                missing_live.append(case.backend_key)
            else:
                missing_non_live.append(case.backend_key)
            continue
        used_keys.add(case.backend_key)
        if binding.kind is not expected_kind:
            raise PilotOrchestrationError(
                f"binding kind drift for {case.backend_key!r}: expected {expected_kind.value}"
            )
        if (binding.backend_id, binding.model_id) != (
            case.expected_backend_id,
            case.expected_model_id,
        ):
            raise PilotOrchestrationError(f"binding identity drift for {case.backend_key!r}")
    unused = sorted(set(bindings) - used_keys)
    if unused:
        raise PilotOrchestrationError(f"bindings are not declared by the protocol: {unused}")

    replies: dict[str, ScriptedReplyBundle] = {}
    live_configs: dict[str, StructuredOpenAICompatibleConfig] = {}
    for key, binding in bindings.items():
        if binding.replies is not None:
            _, _, data = _resolve_hashed_yaml(root, binding.replies)
            bundle = _validate_strict_json(
                ScriptedReplyBundle,
                data,
                label=f"scripted reply bundle for {key!r}",
            )
            if (bundle.backend_id, bundle.model_id) != (
                binding.backend_id,
                binding.model_id,
            ):
                raise PilotOrchestrationError(f"scripted reply identity drift for {key!r}")
            replies[key] = bundle
        if binding.live_config is not None:
            _, _, data = _resolve_hashed_yaml(root, binding.live_config)
            live_config = _validate_strict_json(
                StructuredOpenAICompatibleConfig,
                data,
                label=f"live backend configuration for {key!r}",
            )
            if (live_config.provider, live_config.model) != (
                binding.backend_id,
                binding.model_id,
            ):
                raise PilotOrchestrationError(f"live config identity drift for {key!r}")
            live_configs[key] = live_config

    manual_bundle = _load_optional_bundle(
        root,
        config.manual_interventions,
        ManualInterventionBundle,
    )
    if manual_bundle is not None:
        if manual_bundle.protocol_sha256 != protocol.fingerprint:
            raise PilotOrchestrationError("manual evidence protocol hash drift")
        validate_manual_interventions(
            protocol,
            {item.case_id: item for item in manual_bundle.measurements},
        )
    review_bundle = _load_optional_bundle(
        root,
        config.independent_review,
        IndependentReviewBundle,
    )
    if review_bundle is not None and review_bundle.protocol_sha256 != protocol.fingerprint:
        raise PilotOrchestrationError("review evidence protocol hash drift")

    return LoadedPilotConfiguration(
        source_path=source,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        config=config,
        protocol_source_path=protocol_path,
        protocol_source_sha256=hashlib.sha256(protocol_bytes).hexdigest(),
        protocol=protocol,
        replies=replies,
        live_configs=live_configs,
        manual_bundle=manual_bundle,
        review_bundle=review_bundle,
        missing_non_live_bindings=tuple(sorted(missing_non_live)),
        missing_live_bindings=tuple(sorted(missing_live)),
    )


def _load_optional_bundle(
    root: Path,
    reference: ContentAddressedFile | None,
    model_type: type[OrchestrationModel],
) -> Any:
    if reference is None:
        return None
    _, _, data = _resolve_hashed_yaml(root, reference)
    return _validate_strict_json(model_type, data, label="external evidence bundle")


def _resolve_hashed_yaml(
    root: Path,
    reference: ContentAddressedFile,
) -> tuple[Path, bytes, Any]:
    candidate = root / PurePosixPath(reference.path)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise PilotOrchestrationError(
            f"content-addressed path is missing or escapes its config directory: {reference.path}"
        ) from exc
    raw, data = _load_hashed_yaml(resolved)
    observed = hashlib.sha256(raw).hexdigest()
    if observed != reference.sha256:
        raise PilotOrchestrationError(f"content hash drift for {reference.path!r}")
    return resolved, raw, data


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise PilotOrchestrationError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_hashed_yaml(path: Path) -> tuple[bytes, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = path.read_bytes()
    try:
        data = yaml.load(raw.decode("utf-8"), Loader=_UniqueKeyLoader)
    except UnicodeDecodeError as exc:
        raise PilotOrchestrationError(f"configuration is not UTF-8: {path.name}") from exc
    except yaml.YAMLError as exc:
        raise PilotOrchestrationError(f"configuration is not valid YAML: {path.name}") from exc
    if not isinstance(data, dict):
        raise PilotOrchestrationError(f"configuration root must be a mapping: {path.name}")
    return raw, data


def _strict_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _validate_strict_json(
    model_type: type[BaseModel],
    value: Any,
    *,
    label: str,
) -> Any:
    try:
        return model_type.model_validate_json(_strict_json(value), strict=True)
    except ValidationError as exc:
        failures = []
        for error in exc.errors(include_url=False, include_input=False):
            location = ".".join(str(part) for part in error["loc"]) or "root"
            failures.append(f"{location}: {error['type']} ({error['msg']})")
        raise PilotOrchestrationError(f"invalid {label}: {'; '.join(failures)}") from None


class PilotRunManifest(OrchestrationModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    run_id: str
    registered_revision: int = Field(ge=0)
    created_at: datetime
    protocol_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manual_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    review_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    config_live_enabled: bool
    cli_live_opt_in: bool
    live_execution_authorized: bool
    self_dogfooding_only: Literal[True] = True
    effectiveness_claim: Literal[False] = False
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **payload: Any) -> PilotRunManifest:
        unsigned = cls.model_construct(manifest_sha256="0" * 64, **payload)
        digest = canonical_sha256(unsigned.model_dump(mode="json", exclude={"manifest_sha256"}))
        return cls.model_validate({**payload, "manifest_sha256": digest})

    @model_validator(mode="after")
    def validate_manifest(self) -> PilotRunManifest:
        validate_project_id(self.project_id)
        validate_entry_id(self.run_id, field_name="run_id")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if self.live_execution_authorized != (self.config_live_enabled and self.cli_live_opt_in):
            raise ValueError("live authorization must require config and CLI opt-in")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("manifest_sha256 does not match run manifest")
        return self


class PilotCaseCheckpoint(OrchestrationModel):
    schema_version: Literal["1.0"] = "1.0"
    case_index: int = Field(ge=0)
    case_id: str
    completed_at: datetime
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    measurement_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    recording_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    predecessor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: PilotCaseResult
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **payload: Any) -> PilotCaseCheckpoint:
        unsigned = cls.model_construct(checkpoint_sha256="0" * 64, **payload)
        digest = canonical_sha256(unsigned.model_dump(mode="json", exclude={"checkpoint_sha256"}))
        return cls.model_validate({**payload, "checkpoint_sha256": digest})

    @model_validator(mode="after")
    def verify_checkpoint(self) -> PilotCaseCheckpoint:
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"checkpoint_sha256"}))
        if self.checkpoint_sha256 != expected:
            raise ValueError("checkpoint_sha256 does not match checkpoint content")
        return self


class PilotVerificationRecord(OrchestrationModel):
    schema_version: Literal["1.0"] = "1.0"
    verified_at: datetime
    project_id: str
    run_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_count: int = Field(ge=0)
    chain_head_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recording_sha256_by_pair: dict[str, str]
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acceptance_status: AcceptanceStatus
    verification_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, **payload: Any) -> PilotVerificationRecord:
        unsigned = cls.model_construct(verification_sha256="0" * 64, **payload)
        digest = canonical_sha256(unsigned.model_dump(mode="json", exclude={"verification_sha256"}))
        return cls.model_validate({**payload, "verification_sha256": digest})

    @model_validator(mode="after")
    def verify_record(self) -> PilotVerificationRecord:
        if self.verified_at.tzinfo is None or self.verified_at.utcoffset() is None:
            raise ValueError("verified_at must be timezone-aware")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"verification_sha256"}))
        if self.verification_sha256 != expected:
            raise ValueError("verification_sha256 does not match verification content")
        return self


class PilotRunSummary(OrchestrationModel):
    schema_version: Literal["1.0"] = "1.0"
    status: str
    project_id: str
    run_id: str
    project_revision: int = Field(ge=0)
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    verification_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    case_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    planned_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    acceptance_status: str
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    latency_ms: float | None = Field(default=None, ge=0.0)
    run_locator: str


class _AttemptMarker(OrchestrationModel):
    schema_version: Literal["1.0"] = "1.0"
    attempt_id: str
    case_index: int = Field(ge=0)
    case_id: str
    started_at: datetime
    predecessor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _FailureRecord(OrchestrationModel):
    schema_version: Literal["1.0"] = "1.0"
    attempt_id: str
    failed_at: datetime
    case_index: int = Field(ge=0)
    case_id: str
    error_code: str
    detail: Literal["case execution failed; inspect configuration and provider logs"]


CaseHook = Callable[[PilotCase], None]


class ProjectPilotOrchestrator:
    """Execute a pilot beneath one registered ``ProjectRuntime`` run."""

    def __init__(
        self,
        runtime: ProjectRuntime,
        *,
        live_transport: StructuredHTTPTransport | None = None,
        before_case: CaseHook | None = None,
    ) -> None:
        self.runtime = runtime
        self.live_transport = live_transport
        self.before_case = before_case

    def plan(
        self,
        *,
        project_id: str,
        run_id: str,
        expected_revision: int,
        config_path: str | Path,
        allow_live: bool = False,
    ) -> PilotRunSummary:
        loaded = load_pilot_orchestration_config(config_path)
        snapshot = self._validate_project(
            loaded,
            project_id=project_id,
            run_id=run_id,
            expected_revision=expected_revision,
            require_new=True,
        )
        measurement_ids = (
            {item.case_id for item in loaded.manual_bundle.measurements}
            if loaded.manual_bundle is not None
            else set()
        )
        required_measurements = {
            case.case_id
            for case in loaded.protocol.cases
            if case.manual_intervention_requirement is not None
        }
        live_authorized = self._live_authorized(loaded, allow_live=allow_live)
        live_case_count = sum(
            case.condition is PilotCondition.LIVE_STRUCTURED_NODE for case in loaded.protocol.cases
        )
        bound_live_case_count = live_case_count - len(loaded.missing_live_bindings)
        blocked = (
            len(loaded.missing_non_live_bindings)
            + len(required_measurements - measurement_ids)
            + (loaded.review_bundle is None)
            + len(loaded.missing_live_bindings)
            + (0 if live_authorized else bound_live_case_count)
        )
        return PilotRunSummary(
            status="planned",
            project_id=project_id,
            run_id=run_id,
            project_revision=snapshot.revision,
            protocol_sha256=loaded.protocol.fingerprint,
            config_sha256=loaded.config.fingerprint,
            case_count=len(loaded.protocol.cases),
            completed_count=0,
            planned_count=len(loaded.protocol.cases),
            blocked_count=blocked,
            acceptance_status="not_evaluated",
            run_locator=self._run_locator(project_id, run_id),
        )

    def execute(
        self,
        *,
        project_id: str,
        run_id: str,
        expected_revision: int,
        config_path: str | Path,
        resume: bool = False,
        allow_live: bool = False,
    ) -> PilotRunSummary:
        loaded = load_pilot_orchestration_config(config_path)
        if loaded.missing_non_live_bindings:
            raise PilotOrchestrationError(
                "missing non-live bindings: " + ", ".join(loaded.missing_non_live_bindings)
            )
        snapshot = self._validate_project(
            loaded,
            project_id=project_id,
            run_id=run_id,
            expected_revision=expected_revision,
            require_new=not resume,
        )
        live_authorized = self._live_authorized(loaded, allow_live=allow_live)
        if resume:
            registered_revision = snapshot.revision
            run = self._registered_run(snapshot.manifest.runs, run_id)
            self._require_pilot_run(run)
        else:
            snapshot = self.runtime.begin_run(
                project_id,
                ProjectRun(
                    run_id=run_id,
                    provider="bounded-model-node-pilot",
                    model="mixed-pinned-identities",
                    condition="bounded-model-node-pilot",
                    seed=0,
                    status="running",
                    evidence_scope="engineering-only",
                    stage_path=PILOT_STAGE_PATH,
                ),
                expected_revision=expected_revision,
            )
            registered_revision = snapshot.revision

        stage = self._run_stage(project_id, run_id)
        with _exclusive_lock(stage / ".pilot.lock"):
            return self._execute_locked(
                loaded,
                project_id=project_id,
                run_id=run_id,
                registered_revision=registered_revision,
                stage=stage,
                resume=resume,
                allow_live=allow_live,
                live_authorized=live_authorized,
            )

    def status(self, *, project_id: str, run_id: str) -> PilotRunSummary:
        snapshot = self.runtime.open(project_id)
        registered_run = self._registered_run(snapshot.manifest.runs, run_id)
        self._require_pilot_run(registered_run)
        stage = self._run_stage(project_id, run_id)
        manifest = _load_model(stage / "manifest.json", PilotRunManifest)
        protocol = _load_model(stage / "protocol.json", PilotProtocol)
        config = _load_model(stage / "orchestration.json", PilotOrchestrationConfig)
        self._verify_run_identity(
            manifest,
            protocol,
            project_id=project_id,
            run_id=run_id,
        )
        self._verify_snapshots(manifest, protocol, config)
        measurements = self._load_owned_measurements(stage, manifest, protocol)
        review = self._load_owned_review(stage, manifest, protocol)
        checkpoints = self._load_checkpoint_prefix(
            stage,
            manifest=manifest,
            protocol=protocol,
            config=config,
            measurements=measurements,
        )
        report_path = stage / "report.json"
        if not report_path.exists():
            return PilotRunSummary(
                status=registered_run.status,
                project_id=project_id,
                run_id=run_id,
                project_revision=snapshot.revision,
                protocol_sha256=manifest.protocol_sha256,
                config_sha256=manifest.config_sha256,
                case_count=len(protocol.cases),
                completed_count=len(checkpoints),
                planned_count=len(protocol.cases) - len(checkpoints),
                blocked_count=1,
                acceptance_status="not_evaluated",
                run_locator=self._run_locator(project_id, run_id),
            )
        report = _load_model(report_path, PilotReport)
        if tuple(item.result for item in checkpoints) != report.case_results:
            raise PilotOrchestrationError("report results do not match the checkpoint chain")
        if report.protocol_sha256 != manifest.protocol_sha256:
            raise PilotOrchestrationError("report protocol hash drift")
        if report.independent_outcome_review != review:
            raise PilotOrchestrationError("report independent-review evidence drift")
        verification = _load_model(
            stage / "verification.json",
            PilotVerificationRecord,
        )
        expected_head = (
            checkpoints[-1].checkpoint_sha256 if checkpoints else manifest.manifest_sha256
        )
        if (
            verification.project_id != project_id
            or verification.run_id != run_id
            or verification.manifest_sha256 != manifest.manifest_sha256
            or verification.protocol_sha256 != manifest.protocol_sha256
            or verification.config_sha256 != manifest.config_sha256
            or verification.checkpoint_count != len(checkpoints)
            or verification.chain_head_sha256 != expected_head
            or verification.report_sha256 != report.report_sha256
            or verification.acceptance_status is not report.acceptance.overall_status
            or verification.recording_sha256_by_pair != self._recording_hashes(stage, protocol)
        ):
            raise PilotOrchestrationError("verification record does not match project evidence")
        return self._summary(
            project_id=project_id,
            run_id=run_id,
            revision=snapshot.revision,
            manifest=manifest,
            report=report,
            verification=verification,
            run_status="verified",
        )

    def _execute_locked(
        self,
        loaded: LoadedPilotConfiguration,
        *,
        project_id: str,
        run_id: str,
        registered_revision: int,
        stage: Path,
        resume: bool,
        allow_live: bool,
        live_authorized: bool,
    ) -> PilotRunSummary:
        manual_hash = (
            canonical_sha256(loaded.manual_bundle) if loaded.manual_bundle is not None else None
        )
        review_hash = (
            canonical_sha256(loaded.review_bundle) if loaded.review_bundle is not None else None
        )
        if resume:
            manifest = _load_model(stage / "manifest.json", PilotRunManifest)
            expected = {
                "project_id": project_id,
                "run_id": run_id,
                "protocol_source_sha256": loaded.protocol_source_sha256,
                "protocol_sha256": loaded.protocol.fingerprint,
                "config_source_sha256": loaded.source_sha256,
                "config_sha256": loaded.config.fingerprint,
                "manual_bundle_sha256": manual_hash,
                "review_bundle_sha256": review_hash,
                "config_live_enabled": loaded.config.live_enabled,
                "cli_live_opt_in": allow_live,
                "live_execution_authorized": live_authorized,
            }
            drift = [name for name, value in expected.items() if getattr(manifest, name) != value]
            if drift:
                raise PilotOrchestrationError("resume input drift: " + ", ".join(sorted(drift)))
            protocol = _load_model(stage / "protocol.json", PilotProtocol)
            config = _load_model(stage / "orchestration.json", PilotOrchestrationConfig)
            self._verify_snapshots(manifest, protocol, config)
            self._verify_owned_external(stage, loaded, manifest)
        else:
            manifest = PilotRunManifest.create(
                schema_version="1.0",
                project_id=project_id,
                run_id=run_id,
                registered_revision=registered_revision,
                created_at=datetime.now(UTC),
                protocol_source_sha256=loaded.protocol_source_sha256,
                protocol_sha256=loaded.protocol.fingerprint,
                config_source_sha256=loaded.source_sha256,
                config_sha256=loaded.config.fingerprint,
                manual_bundle_sha256=manual_hash,
                review_bundle_sha256=review_hash,
                config_live_enabled=loaded.config.live_enabled,
                cli_live_opt_in=allow_live,
                live_execution_authorized=live_authorized,
                self_dogfooding_only=True,
                effectiveness_claim=False,
            )
            _write_model_exclusive(stage / "manifest.json", manifest)
            _write_model_exclusive(stage / "protocol.json", loaded.protocol)
            _write_model_exclusive(stage / "orchestration.json", loaded.config)
            if loaded.manual_bundle is not None:
                _write_model_exclusive(
                    stage / "external/manual_interventions.json",
                    loaded.manual_bundle,
                )
            if loaded.review_bundle is not None:
                _write_model_exclusive(
                    stage / "external/independent_review.json",
                    loaded.review_bundle,
                )

        if (stage / "report.json").exists() or (stage / "verification.json").exists():
            raise FileExistsError("pilot report destination already exists")

        measurements = self._load_owned_measurements(stage, manifest, loaded.protocol)
        review = self._load_owned_review(stage, manifest, loaded.protocol)
        self._archive_incomplete_markers(stage)
        checkpoints = self._load_checkpoint_prefix(
            stage,
            manifest=manifest,
            protocol=loaded.protocol,
            config=loaded.config,
            measurements=measurements,
        )
        self._archive_orphan_recordings(stage, loaded.protocol, checkpoints)
        backends = self._build_backends(
            loaded,
            stage=stage,
            live_authorized=live_authorized,
        )
        runner = BoundedPilotRunner(backends=backends)
        runner.reset()
        predecessor = checkpoints[-1].checkpoint_sha256 if checkpoints else manifest.manifest_sha256
        for case_index in range(len(checkpoints), len(loaded.protocol.cases)):
            case = loaded.protocol.cases[case_index]
            attempt_id = f"attempt-{time.time_ns()}-{os.getpid()}"
            marker_path = stage / ".incomplete" / f"{attempt_id}.json"
            marker = _AttemptMarker(
                attempt_id=attempt_id,
                case_index=case_index,
                case_id=case.case_id,
                started_at=datetime.now(UTC),
                predecessor_sha256=predecessor,
            )
            _write_model_exclusive(marker_path, marker)
            try:
                if self.before_case is not None:
                    self.before_case(case)
                result = runner.execute_case(
                    case,
                    manual_intervention=measurements.get(case.case_id),
                )
                recording_sha = self._case_recording_sha(stage, case)
                checkpoint = PilotCaseCheckpoint.create(
                    schema_version="1.0",
                    case_index=case_index,
                    case_id=case.case_id,
                    completed_at=datetime.now(UTC),
                    protocol_sha256=manifest.protocol_sha256,
                    config_sha256=manifest.config_sha256,
                    case_sha256=canonical_sha256(case),
                    binding_sha256=self._binding_sha256(
                        loaded.config,
                        case,
                        live_authorized=live_authorized,
                    ),
                    measurement_sha256=(
                        canonical_sha256(measurements[case.case_id])
                        if case.case_id in measurements
                        else None
                    ),
                    recording_sha256=recording_sha,
                    predecessor_sha256=predecessor,
                    result=result,
                )
                _write_model_exclusive(
                    self._checkpoint_path(stage, case_index, case.case_id),
                    checkpoint,
                )
                marker_path.unlink()
                checkpoints.append(checkpoint)
                predecessor = checkpoint.checkpoint_sha256
            except Exception:
                attempt_locator = self._archive_failed_attempt(
                    stage,
                    marker_path=marker_path,
                    marker=marker,
                    case=case,
                )
                try:
                    self.runtime.update_run(
                        project_id,
                        run_id,
                        expected_revision=registered_revision,
                        status="failed",
                        last_failed_attempt=attempt_locator,
                    )
                except (FileNotFoundError, FileExistsError, ValueError):
                    pass
                raise PilotOrchestrationError(
                    f"pilot case {case.case_id!r} failed; archived failed-attempt evidence"
                ) from None

        current = self.runtime.open(project_id)
        if current.revision != registered_revision:
            raise ProjectRevisionConflictError(
                f"stale project revision {registered_revision}; current is {current.revision}"
            )
        report = runner.build_report(
            loaded.protocol,
            tuple(item.result for item in checkpoints),
            report_id=f"{run_id}-report",
            generated_at=datetime.now(UTC),
            independent_outcome_review=review,
        )
        save_pilot_report(report, stage / "report.json")
        verification = PilotVerificationRecord.create(
            schema_version="1.0",
            verified_at=datetime.now(UTC),
            project_id=project_id,
            run_id=run_id,
            manifest_sha256=manifest.manifest_sha256,
            protocol_sha256=manifest.protocol_sha256,
            config_sha256=manifest.config_sha256,
            checkpoint_count=len(checkpoints),
            chain_head_sha256=predecessor,
            recording_sha256_by_pair=self._recording_hashes(stage, loaded.protocol),
            report_sha256=report.report_sha256,
            acceptance_status=report.acceptance.overall_status,
        )
        _write_model_exclusive(stage / "verification.json", verification)
        completed = self.runtime.update_run(
            project_id,
            run_id,
            expected_revision=registered_revision,
            status=(
                "complete"
                if report.acceptance.overall_status is AcceptanceStatus.PASS
                else "blocked"
            ),
            artifact=f"runs/{run_id}/{PILOT_STAGE_PATH}/report.json",
            protocol_sha256=manifest.protocol_sha256,
            config_sha256=manifest.config_sha256,
            report_sha256=report.report_sha256,
            acceptance_status=report.acceptance.overall_status.value,
        )
        return self._summary(
            project_id=project_id,
            run_id=run_id,
            revision=completed.revision,
            manifest=manifest,
            report=report,
            verification=verification,
            run_status=(
                "complete"
                if report.acceptance.overall_status is AcceptanceStatus.PASS
                else "blocked"
            ),
        )

    def _validate_project(
        self,
        loaded: LoadedPilotConfiguration,
        *,
        project_id: str,
        run_id: str,
        expected_revision: int,
        require_new: bool,
    ) -> Any:
        validate_project_id(project_id)
        validate_entry_id(run_id, field_name="run_id")
        project_ids = {case.context.value.project_id for case in loaded.protocol.cases}
        if project_ids != {project_id}:
            raise PilotOrchestrationError(
                "protocol NodeContext project_id does not match the owning project"
            )
        snapshot = self.runtime.open(project_id)
        if snapshot.revision != expected_revision:
            raise ProjectRevisionConflictError(
                f"stale project revision {expected_revision}; current is {snapshot.revision}"
            )
        known = {run.run_id for run in snapshot.manifest.runs}
        run_path = self._run_stage(project_id, run_id).parent
        if require_new and (run_id in known or os.path.lexists(run_path)):
            raise FileExistsError(f"pilot run already exists: {run_id}")
        if not require_new and run_id not in known:
            raise PilotOrchestrationError(f"unknown project run {run_id!r}")
        return snapshot

    @staticmethod
    def _registered_run(runs: list[ProjectRun], run_id: str) -> ProjectRun:
        try:
            return next(run for run in runs if run.run_id == run_id)
        except StopIteration as exc:
            raise PilotOrchestrationError(f"unknown project run {run_id!r}") from exc

    @staticmethod
    def _require_pilot_run(run: ProjectRun) -> None:
        if run.condition != "bounded-model-node-pilot" or run.stage_path != PILOT_STAGE_PATH:
            raise PilotOrchestrationError("registered run is not a bounded model-node pilot")

    @staticmethod
    def _verify_run_identity(
        manifest: PilotRunManifest,
        protocol: PilotProtocol,
        *,
        project_id: str,
        run_id: str,
    ) -> None:
        if manifest.project_id != project_id or manifest.run_id != run_id:
            raise PilotOrchestrationError("pilot manifest belongs to another project run")
        if {case.context.value.project_id for case in protocol.cases} != {project_id}:
            raise PilotOrchestrationError("pilot protocol belongs to another project")

    @staticmethod
    def _live_authorized(
        loaded: LoadedPilotConfiguration,
        *,
        allow_live: bool,
    ) -> bool:
        if not (loaded.config.live_enabled and allow_live):
            return False
        live_cases = [
            case
            for case in loaded.protocol.cases
            if case.condition is PilotCondition.LIVE_STRUCTURED_NODE
        ]
        bindings = {item.backend_key: item for item in loaded.config.bindings}
        for case in live_cases:
            assert case.backend_key is not None
            binding = bindings.get(case.backend_key)
            if binding is None:
                continue
            live_config = loaded.live_configs[binding.backend_key]
            if not live_config.live_enabled:
                raise PilotOrchestrationError(
                    "live execution requested but the compatible backend remains disabled"
                )
        return bool(live_cases)

    def _build_backends(
        self,
        loaded: LoadedPilotConfiguration,
        *,
        stage: Path,
        live_authorized: bool,
    ) -> dict[str, BackendBinding]:
        cases_by_key = {
            case.backend_key: case for case in loaded.protocol.cases if case.backend_key is not None
        }
        backends: dict[str, BackendBinding] = {}
        for binding in loaded.config.bindings:
            case = cases_by_key[binding.backend_key]
            if binding.kind in {
                PilotBindingKind.SCRIPTED,
                PilotBindingKind.RECORDING_SCRIPTED,
            }:
                bundle = loaded.replies[binding.backend_key]
                scripted = ScriptedStructuredBackend(
                    name=binding.backend_id,
                    model=binding.model_id,
                    replies=dict(bundle.replies),
                )
                if binding.kind is PilotBindingKind.RECORDING_SCRIPTED:
                    recording_path = self._recording_path(stage, case)
                    backends[binding.backend_key] = RecordingStructuredBackend(
                        scripted,
                        recording_path,
                    )
                else:
                    backends[binding.backend_key] = scripted
            elif binding.kind is PilotBindingKind.REPLAY:
                recording_path = self._recording_path(stage, case)
                backends[binding.backend_key] = lambda path=recording_path: ReplayStructuredBackend(
                    path
                )
            elif live_authorized:
                backends[binding.backend_key] = StructuredOpenAICompatibleBackend(
                    loaded.live_configs[binding.backend_key],
                    transport=self.live_transport,
                )
        return backends

    @staticmethod
    def _verify_snapshots(
        manifest: PilotRunManifest,
        protocol: PilotProtocol,
        config: PilotOrchestrationConfig,
    ) -> None:
        if protocol.fingerprint != manifest.protocol_sha256:
            raise PilotOrchestrationError("project-owned protocol snapshot hash drift")
        if config.fingerprint != manifest.config_sha256:
            raise PilotOrchestrationError("project-owned config snapshot hash drift")

    def _verify_owned_external(
        self,
        stage: Path,
        loaded: LoadedPilotConfiguration,
        manifest: PilotRunManifest,
    ) -> None:
        if loaded.manual_bundle is None:
            if (stage / "external/manual_interventions.json").exists():
                raise PilotOrchestrationError("unexpected project-owned manual evidence")
        else:
            owned = _load_model(
                stage / "external/manual_interventions.json",
                ManualInterventionBundle,
            )
            if owned != loaded.manual_bundle or canonical_sha256(owned) != (
                manifest.manual_bundle_sha256
            ):
                raise PilotOrchestrationError("project-owned manual evidence drift")
        if loaded.review_bundle is None:
            if (stage / "external/independent_review.json").exists():
                raise PilotOrchestrationError("unexpected project-owned review evidence")
        else:
            owned_review = _load_model(
                stage / "external/independent_review.json",
                IndependentReviewBundle,
            )
            if owned_review != loaded.review_bundle or canonical_sha256(owned_review) != (
                manifest.review_bundle_sha256
            ):
                raise PilotOrchestrationError("project-owned independent review drift")

    def _load_owned_measurements(
        self,
        stage: Path,
        manifest: PilotRunManifest,
        protocol: PilotProtocol,
    ) -> dict[str, ManualInterventionMeasurement]:
        path = stage / "external/manual_interventions.json"
        if manifest.manual_bundle_sha256 is None:
            if path.exists():
                raise PilotOrchestrationError("unexpected project-owned manual evidence")
            return {}
        bundle = _load_model(path, ManualInterventionBundle)
        if canonical_sha256(bundle) != manifest.manual_bundle_sha256:
            raise PilotOrchestrationError("manual evidence snapshot hash drift")
        if bundle.protocol_sha256 != protocol.fingerprint:
            raise PilotOrchestrationError("manual evidence protocol hash drift")
        return validate_manual_interventions(
            protocol,
            {item.case_id: item for item in bundle.measurements},
        )

    @staticmethod
    def _load_owned_review(
        stage: Path,
        manifest: PilotRunManifest,
        protocol: PilotProtocol,
    ) -> IndependentOutcomeReview | None:
        path = stage / "external/independent_review.json"
        if manifest.review_bundle_sha256 is None:
            if path.exists():
                raise PilotOrchestrationError("unexpected project-owned review evidence")
            return None
        bundle = _load_model(path, IndependentReviewBundle)
        if canonical_sha256(bundle) != manifest.review_bundle_sha256:
            raise PilotOrchestrationError("review evidence snapshot hash drift")
        if bundle.protocol_sha256 != protocol.fingerprint:
            raise PilotOrchestrationError("review evidence protocol hash drift")
        return bundle.review

    def _load_checkpoint_prefix(
        self,
        stage: Path,
        *,
        manifest: PilotRunManifest,
        protocol: PilotProtocol,
        config: PilotOrchestrationConfig,
        measurements: Mapping[str, ManualInterventionMeasurement],
    ) -> list[PilotCaseCheckpoint]:
        root = stage / "cases"
        existing = {path.name for path in root.glob("*.json")} if root.exists() else set()
        checkpoints: list[PilotCaseCheckpoint] = []
        predecessor = manifest.manifest_sha256
        missing_seen = False
        expected_existing: set[str] = set()
        for index, case in enumerate(protocol.cases):
            path = self._checkpoint_path(stage, index, case.case_id)
            if not path.exists():
                missing_seen = True
                continue
            if missing_seen:
                raise PilotOrchestrationError("checkpoint chain has a non-contiguous case")
            expected_existing.add(path.name)
            checkpoint = _load_model(path, PilotCaseCheckpoint)
            self._verify_checkpoint_binding(
                checkpoint,
                case=case,
                case_index=index,
                manifest=manifest,
                config=config,
                measurement=measurements.get(case.case_id),
                predecessor=predecessor,
                stage=stage,
            )
            checkpoints.append(checkpoint)
            predecessor = checkpoint.checkpoint_sha256
        if existing != expected_existing:
            raise PilotOrchestrationError("case evidence directory contains unknown checkpoints")
        return checkpoints

    def _verify_checkpoint_binding(
        self,
        checkpoint: PilotCaseCheckpoint,
        *,
        case: PilotCase,
        case_index: int,
        manifest: PilotRunManifest,
        config: PilotOrchestrationConfig,
        measurement: ManualInterventionMeasurement | None,
        predecessor: str,
        stage: Path,
    ) -> None:
        expected_recording = self._case_recording_sha(stage, case)
        expected_measurement = canonical_sha256(measurement) if measurement is not None else None
        expected = {
            "case_index": case_index,
            "case_id": case.case_id,
            "protocol_sha256": manifest.protocol_sha256,
            "config_sha256": manifest.config_sha256,
            "case_sha256": canonical_sha256(case),
            "binding_sha256": self._binding_sha256(
                config,
                case,
                live_authorized=manifest.live_execution_authorized,
            ),
            "measurement_sha256": expected_measurement,
            "recording_sha256": expected_recording,
            "predecessor_sha256": predecessor,
        }
        drift = [name for name, value in expected.items() if getattr(checkpoint, name) != value]
        if drift:
            raise PilotOrchestrationError(
                f"checkpoint evidence drift for {case.case_id!r}: {', '.join(sorted(drift))}"
            )
        if checkpoint.result.case_id != case.case_id:
            raise PilotOrchestrationError("checkpoint result belongs to a different case")
        if checkpoint.result.manual_intervention != measurement:
            raise PilotOrchestrationError("checkpoint measurement evidence drift")
        result = checkpoint.result
        expected_shape = {
            "condition": case.condition,
            "node_type": case.node_type,
            "expected_outcome": result.outcome in case.allowed_outcomes,
            "replay_pair_id": case.replay_pair_id,
            "replay_role": case.replay_role,
            "manual_intervention_requirement": case.manual_intervention_requirement,
        }
        shape_drift = [
            name for name, value in expected_shape.items() if getattr(result, name) != value
        ]
        if shape_drift:
            raise PilotOrchestrationError(
                f"checkpoint result contract drift for {case.case_id!r}: "
                + ", ".join(sorted(shape_drift))
            )
        identity_expected = (
            case.condition is not PilotCondition.DETERMINISTIC_ONLY
            and result.outcome is not PilotOutcome.PLANNED
        )
        has_complete_identity = result.backend_id is not None and result.model_id is not None
        if has_complete_identity != identity_expected:
            raise PilotOrchestrationError("checkpoint result identity shape drift")
        identity_drifts = (
            (
                result.backend_id != case.expected_backend_id,
                "response backend differs from pinned backend",
            ),
            (
                result.model_id != case.expected_model_id,
                "response model differs from pinned model",
            ),
        )
        for drifted, required_reason in identity_drifts:
            if not drifted or not identity_expected:
                continue
            if result.outcome is not PilotOutcome.REJECTED or required_reason not in (
                result.rejection_reasons
            ):
                raise PilotOrchestrationError(
                    "checkpoint contains an unacknowledged identity drift"
                )
        if result.invoked and result.request_fingerprint != expected_request_fingerprint(case):
            raise PilotOrchestrationError("checkpoint request fingerprint drift")

    @staticmethod
    def _binding_sha256(
        config: PilotOrchestrationConfig,
        case: PilotCase,
        *,
        live_authorized: bool,
    ) -> str:
        binding = next(
            (item for item in config.bindings if item.backend_key == case.backend_key),
            None,
        )
        return canonical_sha256(
            {
                "condition": case.condition.value,
                "expected_backend_id": case.expected_backend_id,
                "expected_model_id": case.expected_model_id,
                "binding": binding.model_dump(mode="json") if binding is not None else None,
                "live_execution_authorized": (
                    live_authorized
                    if case.condition is PilotCondition.LIVE_STRUCTURED_NODE
                    else False
                ),
            }
        )

    def _archive_incomplete_markers(self, stage: Path) -> None:
        incomplete = stage / ".incomplete"
        if not incomplete.exists():
            return
        for marker_path in sorted(incomplete.glob("*.json")):
            marker = _load_model(marker_path, _AttemptMarker)
            attempt = stage / "attempts" / marker.attempt_id
            attempt.mkdir(parents=True, exist_ok=False)
            os.replace(marker_path, attempt / "incomplete-case.json")
            _write_model_exclusive(
                attempt / "failure.json",
                _FailureRecord(
                    attempt_id=marker.attempt_id,
                    failed_at=datetime.now(UTC),
                    case_index=marker.case_index,
                    case_id=marker.case_id,
                    error_code="interrupted_attempt",
                    detail="case execution failed; inspect configuration and provider logs",
                ),
            )

    def _archive_orphan_recordings(
        self,
        stage: Path,
        protocol: PilotProtocol,
        checkpoints: list[PilotCaseCheckpoint],
    ) -> None:
        completed_ids = {checkpoint.case_id for checkpoint in checkpoints}
        for case in protocol.cases:
            if case.replay_role is not ReplayEvidenceRole.RECORDING:
                continue
            path = self._recording_path(stage, case)
            if path.exists() and case.case_id not in completed_ids:
                attempt_id = f"orphan-recording-{time.time_ns()}-{os.getpid()}"
                attempt = stage / "attempts" / attempt_id
                attempt.mkdir(parents=True, exist_ok=False)
                os.replace(path, attempt / "orphan-recording.jsonl")
                _write_model_exclusive(
                    attempt / "failure.json",
                    _FailureRecord(
                        attempt_id=attempt_id,
                        failed_at=datetime.now(UTC),
                        case_index=protocol.cases.index(case),
                        case_id=case.case_id,
                        error_code="orphan_recording",
                        detail="case execution failed; inspect configuration and provider logs",
                    ),
                )

    def _archive_failed_attempt(
        self,
        stage: Path,
        *,
        marker_path: Path,
        marker: _AttemptMarker,
        case: PilotCase,
    ) -> str:
        attempt = stage / "attempts" / marker.attempt_id
        attempt.mkdir(parents=True, exist_ok=False)
        if marker_path.exists():
            os.replace(marker_path, attempt / "incomplete-case.json")
        if case.replay_role is ReplayEvidenceRole.RECORDING:
            recording = self._recording_path(stage, case)
            if recording.exists():
                os.replace(recording, attempt / "incomplete-recording.jsonl")
        _write_model_exclusive(
            attempt / "failure.json",
            _FailureRecord(
                attempt_id=marker.attempt_id,
                failed_at=datetime.now(UTC),
                case_index=marker.case_index,
                case_id=marker.case_id,
                error_code="case_execution_error",
                detail="case execution failed; inspect configuration and provider logs",
            ),
        )
        return f"{PILOT_STAGE_PATH}/attempts/{marker.attempt_id}"

    @staticmethod
    def _checkpoint_path(stage: Path, case_index: int, case_id: str) -> Path:
        return stage / "cases" / f"{case_index:04d}__{case_id}.json"

    @staticmethod
    def _recording_path(stage: Path, case: PilotCase) -> Path:
        if case.replay_pair_id is None:
            raise PilotOrchestrationError("recording path requested for an unpaired case")
        validate_entry_id(case.replay_pair_id, field_name="replay_pair_id")
        return stage / "recordings" / f"{case.replay_pair_id}.jsonl"

    def _case_recording_sha(self, stage: Path, case: PilotCase) -> str | None:
        if case.replay_pair_id is None:
            return None
        path = self._recording_path(stage, case)
        if not path.is_file():
            raise PilotOrchestrationError(
                f"paired case {case.case_id!r} has no exact recording evidence"
            )
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _recording_hashes(
        self,
        stage: Path,
        protocol: PilotProtocol,
    ) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for case in protocol.cases:
            if case.replay_pair_id is None or case.replay_pair_id in hashes:
                continue
            path = self._recording_path(stage, case)
            if not path.is_file():
                raise PilotOrchestrationError(f"missing recording for pair {case.replay_pair_id!r}")
            hashes[case.replay_pair_id] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes

    @staticmethod
    def _summary(
        *,
        project_id: str,
        run_id: str,
        revision: int,
        manifest: PilotRunManifest,
        report: PilotReport,
        verification: PilotVerificationRecord,
        run_status: str,
    ) -> PilotRunSummary:
        statistics = report.statistics
        return PilotRunSummary(
            status=run_status,
            project_id=project_id,
            run_id=run_id,
            project_revision=revision,
            protocol_sha256=manifest.protocol_sha256,
            config_sha256=manifest.config_sha256,
            report_sha256=report.report_sha256,
            verification_sha256=verification.verification_sha256,
            case_count=statistics.case_count,
            completed_count=len(report.case_results),
            planned_count=statistics.planned_count,
            blocked_count=sum(
                metric.status is AcceptanceStatus.BLOCKED for metric in report.acceptance.metrics
            ),
            acceptance_status=report.acceptance.overall_status.value,
            input_tokens=statistics.input_tokens,
            output_tokens=statistics.output_tokens,
            total_tokens=statistics.total_tokens,
            cost_usd=statistics.cost_usd,
            latency_ms=statistics.latency_ms,
            run_locator=f"projects/{project_id}/runs/{run_id}/{PILOT_STAGE_PATH}",
        )

    def _run_stage(self, project_id: str, run_id: str) -> Path:
        validate_project_id(project_id)
        validate_entry_id(run_id, field_name="run_id")
        stage = (
            self.runtime.outputs_root / "projects" / project_id / "runs" / run_id / PILOT_STAGE_PATH
        )
        if os.path.lexists(stage):
            try:
                resolved = stage.resolve(strict=True)
            except (FileNotFoundError, RuntimeError) as exc:
                raise PilotOrchestrationError("pilot run stage is not a valid directory") from exc
            if resolved != stage or not stage.is_dir():
                raise PilotOrchestrationError("pilot run stage escapes its project-owned path")
        return stage

    @staticmethod
    def _run_locator(project_id: str, run_id: str) -> str:
        return f"projects/{project_id}/runs/{run_id}/{PILOT_STAGE_PATH}"


def _load_model(path: Path, model_type: type[BaseModel]) -> Any:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"), strict=True)
    except ValueError as exc:
        raise PilotOrchestrationError(f"invalid project-owned evidence: {path.name}") from exc


def _write_model_exclusive(path: Path, value: BaseModel) -> None:
    payload = (
        json.dumps(
            value.model_dump(mode="json", exclude_computed_fields=True),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise FileExistsError(f"refusing to overwrite project evidence: {path}") from exc
        temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PilotRunConflictError("another writer owns this pilot run") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

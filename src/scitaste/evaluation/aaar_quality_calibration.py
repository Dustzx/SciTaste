"""No-run local calibration plan for real AAAR reference-quality projections."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from scitaste.backends.local_transformers import load_local_transformers_config
from scitaste.evaluation.aaar_quality_projection import AaarQualityProjectionReport
from scitaste.model_nodes.facade import ImmutableStateProjection
from scitaste.model_nodes.models import NodePolicy
from scitaste.model_nodes.openai_compatible import structured_model_messages
from scitaste.model_nodes.profiles import ModelNodeProfile, load_model_node_profile_set
from scitaste.model_nodes.runtime import ModelNodeTrigger
from scitaste.model_nodes.runtime_config import (
    LocalRuntimeBackend,
    ModelNodeRuntimeConfig,
)
from scitaste.taste.reference_quality import ReferenceQualityInput
from scitaste.taste.semantic import ReferenceQualityNode

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_ID = r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$"
_RUN_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_SHA256 = r"^[0-9a-f]{64}$"
_MAX_CONTROL_BYTES = 16 * 1_048_576


class AaarQualityCalibrationItem(BaseModel):
    """One exact no-run invocation selected for instrument calibration."""

    model_config = _CONFIG

    source_id: str = Field(pattern=_ID)
    screening_id: str = Field(pattern=_ID)
    selection_role: Literal["maximum-context-stress", "maximum-redaction-stress"]
    projection_locator: str = Field(min_length=1, max_length=1_000)
    projection_file_sha256: str = Field(pattern=_SHA256)
    projection_file_bytes: int = Field(gt=0)
    source_projection_sha256: str = Field(pattern=_SHA256)
    prompt_utf8_bytes: int = Field(gt=0)
    structured_request_utf8_bytes: int = Field(gt=0)
    exact_input_tokens: int | None = Field(default=None, gt=0)
    runtime_config_locator: str = Field(min_length=1, max_length=1_000)
    runtime_config_sha256: str = Field(pattern=_SHA256)


class AaarQualityCalibrationPlan(BaseModel):
    """Content-free receipt for a two-item local model calibration proposal."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(pattern=_ID)
    project_id: str = Field(pattern=_ID)
    intended_run_id: str = Field(pattern=_RUN_ID)
    expected_project_revision: int = Field(ge=0)
    planned_at: datetime
    planner_implementation_sha256: str = Field(pattern=_SHA256)
    projection_report_locator: str = Field(min_length=1, max_length=2_000)
    projection_report_file_sha256: str = Field(pattern=_SHA256)
    projection_report_sha256: str = Field(pattern=_SHA256)
    profile_set_locator: str = Field(min_length=1, max_length=2_000)
    profile_set_file_sha256: str = Field(pattern=_SHA256)
    profile_id: str = Field(pattern=_ID)
    profile_sha256: str = Field(pattern=_SHA256)
    backend_config_locator: str = Field(min_length=1, max_length=2_000)
    backend_config_file_sha256: str = Field(pattern=_SHA256)
    provider: Literal["local-transformers"] = "local-transformers"
    model: str = Field(min_length=1, max_length=300)
    checkpoint_path: str = Field(min_length=1, max_length=2_000)
    checkpoint_sha256: str = Field(pattern=_SHA256)
    checkpoint_bytes: int = Field(gt=0)
    checkpoint_rehash_performed: Literal[False] = False
    checkpoint_rehash_required_at_execution: Literal[True] = True
    calibration_item_count: Literal[2] = 2
    items: tuple[AaarQualityCalibrationItem, AaarQualityCalibrationItem]
    total_projection_bytes: int = Field(gt=0)
    maximum_prompt_utf8_bytes: int = Field(gt=0)
    exact_token_count_status: Literal[
        "pending-python312-local-gpu-environment",
        "verified-local-tokenizer",
    ] = "pending-python312-local-gpu-environment"
    maximum_exact_input_tokens: int | None = Field(default=None, gt=0)
    tokenizer_version: str | None = Field(default=None, min_length=1, max_length=100)
    tokenizer_load_performed: bool = False
    model_load_performed: Literal[False] = False
    max_context_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    gpu_device_count: Literal[1] = 1
    gpu_device_class: Literal["NVIDIA GeForce RTX 3090"] = "NVIDIA GeForce RTX 3090"
    maximum_gpu_hours: float = Field(default=1.0, gt=0, le=1.0)
    network_access: Literal[False] = False
    api_calls: Literal[0] = 0
    source_upload: Literal[False] = False
    model_calls_performed: Literal[False] = False
    gpu_execution_performed: Literal[False] = False
    human_review_performed: Literal[False] = False
    authorizes_execution: Literal[False] = False
    scientific_role: Literal["instrument-calibration-only"] = "instrument-calibration-only"
    effectiveness_claim_authorized: Literal[False] = False

    @field_validator("planned_at")
    @classmethod
    def planned_time_is_aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("AAAR calibration-plan timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def cohort_is_closed(self) -> AaarQualityCalibrationPlan:
        if len({item.source_id for item in self.items}) != 2:
            raise ValueError("AAAR calibration cohort must contain two distinct sources")
        if {item.selection_role for item in self.items} != {
            "maximum-context-stress",
            "maximum-redaction-stress",
        }:
            raise ValueError("AAAR calibration cohort must cover both declared stress roles")
        if self.total_projection_bytes != sum(item.projection_file_bytes for item in self.items):
            raise ValueError("AAAR calibration projection byte total differs")
        if self.maximum_prompt_utf8_bytes != max(item.prompt_utf8_bytes for item in self.items):
            raise ValueError("AAAR calibration maximum prompt byte count differs")
        exact = [item.exact_input_tokens for item in self.items]
        if self.exact_token_count_status == "verified-local-tokenizer":
            if any(value is None for value in exact) or not self.tokenizer_load_performed:
                raise ValueError("verified AAAR token counts require the local tokenizer")
            if self.tokenizer_version is None or self.maximum_exact_input_tokens != max(exact):
                raise ValueError("AAAR calibration exact token summary differs")
        elif any(value is not None for value in exact) or any(
            value is not None for value in (self.maximum_exact_input_tokens, self.tokenizer_version)
        ) or self.tokenizer_load_performed:
            raise ValueError("pending AAAR token counts cannot contain tokenizer evidence")
        return self

    @computed_field
    @property
    def report_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json", exclude={"report_sha256"}))


def materialize_aaar_quality_calibration_plan(
    *,
    projection_report_path: str | Path,
    backend_config_path: str | Path,
    profile_set_path: str | Path,
    profile_id: str,
    output_directory: str | Path,
    plan_id: str,
    intended_run_id: str,
    expected_project_revision: int,
    planned_at: datetime,
    perform_tokenizer_preflight: bool = False,
) -> AaarQualityCalibrationPlan:
    """Materialize two exact runtime configs without loading or calling the model."""

    projection_source, projection_raw, projection_report = _load_projection_report(
        projection_report_path
    )
    backend_source = Path(backend_config_path).resolve(strict=True)
    backend_raw = _bounded_regular_bytes(backend_source)
    backend_config = load_local_transformers_config(backend_source)
    if backend_config.provider != "local-transformers":
        raise ValueError("AAAR local calibration requires provider local-transformers")
    if not backend_config.execution_enabled:
        raise ValueError("AAAR local calibration backend capability is disabled")
    if backend_config.checkpoint_sha256 is None:
        raise ValueError("AAAR local calibration requires a checkpoint content hash")
    profile_source = Path(profile_set_path).resolve(strict=True)
    profile_raw = _bounded_regular_bytes(profile_source)
    loaded_profiles = load_model_node_profile_set(profile_source)
    try:
        profile = loaded_profiles.profiles[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown AAAR local calibration profile {profile_id!r}") from exc
    if not profile.local_execution_permitted or profile.live_execution_permitted:
        raise ValueError("AAAR local calibration profile must permit only local execution")
    if (profile.provider, profile.model) != (
        backend_config.provider,
        backend_config.model_identity,
    ):
        raise ValueError("AAAR local calibration backend identity differs from its profile")
    if profile.generation.max_output_tokens > backend_config.max_new_tokens:
        raise ValueError("AAAR local calibration profile exceeds backend output tokens")
    if profile.generation.context_window_tokens > backend_config.max_context_tokens:
        raise ValueError("AAAR local calibration profile exceeds backend context tokens")
    checkpoint = backend_config.model_path.expanduser()
    if checkpoint.is_symlink():
        raise ValueError("AAAR local calibration checkpoint cannot be a symlink")
    checkpoint = checkpoint.resolve(strict=True)
    checkpoint_bytes = _checkpoint_size(checkpoint)
    tokenizer = None
    tokenizer_version = None
    if perform_tokenizer_preflight:
        try:
            import transformers
            from transformers import AutoTokenizer
        except ImportError as exc:  # pragma: no cover - optional environment boundary
            raise RuntimeError(
                "AAAR tokenizer preflight requires the local-gpu Transformers dependency"
            ) from exc
        tokenizer = AutoTokenizer.from_pretrained(
            checkpoint,
            local_files_only=True,
            trust_remote_code=False,
        )
        tokenizer_version = transformers.__version__

    candidates = []
    root = projection_source.parent
    for item in projection_report.items:
        source = _resolve_beneath(root, item.projection_locator)
        if source is None or source.is_symlink():
            raise ValueError("AAAR calibration projection locator is unsafe")
        raw = _bounded_regular_bytes(source)
        if hashlib.sha256(raw).hexdigest() != item.projection_file_sha256:
            raise ValueError("AAAR calibration projection file hash drifted")
        input_data = ReferenceQualityInput.model_validate_json(raw, strict=True)
        if (
            input_data.source_id != item.source_id
            or input_data.screening_id != item.screening_id
            or input_data.source_projection_sha256 != item.source_projection_sha256
        ):
            raise ValueError("AAAR calibration projection identity drifted")
        candidates.append((item, source, raw, input_data))
    if len(candidates) < 2:
        raise ValueError("AAAR calibration requires at least two projected sources")
    context_stress = max(candidates, key=lambda value: (len(value[2]), value[0].source_id))
    redaction_stress = max(
        (value for value in candidates if value[0].source_id != context_stress[0].source_id),
        key=lambda value: (value[0].redaction_count, -len(value[2]), value[0].source_id),
    )
    selected = (
        ("maximum-context-stress", context_stress),
        ("maximum-redaction-stress", redaction_stress),
    )

    target = Path(output_directory)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        calibration_items: list[AaarQualityCalibrationItem] = []
        for selection_role, (item, _, raw, input_data) in selected:
            runtime_config, prompt_bytes, request_bytes, input_tokens = _runtime_config(
                input_data,
                profile=profile,
                backend=LocalRuntimeBackend(config=backend_config),
                project_id=projection_report.project_id,
                expected_project_revision=expected_project_revision,
                tokenizer=tokenizer,
            )
            relative = PurePosixPath("invocations", f"{input_data.source_id}.json")
            destination = staging.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            text = runtime_config.model_dump_json(indent=2, exclude_computed_fields=True) + "\n"
            destination.write_text(text, encoding="utf-8")
            calibration_items.append(
                AaarQualityCalibrationItem(
                    source_id=item.source_id,
                    screening_id=item.screening_id,
                    selection_role=selection_role,
                    projection_locator=item.projection_locator,
                    projection_file_sha256=item.projection_file_sha256,
                    projection_file_bytes=len(raw),
                    source_projection_sha256=item.source_projection_sha256,
                    prompt_utf8_bytes=prompt_bytes,
                    structured_request_utf8_bytes=request_bytes,
                    exact_input_tokens=input_tokens,
                    runtime_config_locator=relative.as_posix(),
                    runtime_config_sha256=hashlib.sha256(text.encode()).hexdigest(),
                )
            )
        plan = AaarQualityCalibrationPlan(
            plan_id=plan_id,
            project_id=projection_report.project_id,
            intended_run_id=intended_run_id,
            expected_project_revision=expected_project_revision,
            planned_at=planned_at,
            planner_implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            projection_report_locator=str(projection_source),
            projection_report_file_sha256=hashlib.sha256(projection_raw).hexdigest(),
            projection_report_sha256=projection_report.report_sha256,
            profile_set_locator=str(profile_source),
            profile_set_file_sha256=hashlib.sha256(profile_raw).hexdigest(),
            profile_id=profile.profile_id,
            profile_sha256=profile.fingerprint,
            backend_config_locator=str(backend_source),
            backend_config_file_sha256=hashlib.sha256(backend_raw).hexdigest(),
            model=backend_config.model_identity,
            checkpoint_path=str(checkpoint),
            checkpoint_sha256=backend_config.checkpoint_sha256,
            checkpoint_bytes=checkpoint_bytes,
            items=tuple(calibration_items),
            total_projection_bytes=sum(item.projection_file_bytes for item in calibration_items),
            maximum_prompt_utf8_bytes=max(item.prompt_utf8_bytes for item in calibration_items),
            exact_token_count_status=(
                "verified-local-tokenizer"
                if perform_tokenizer_preflight
                else "pending-python312-local-gpu-environment"
            ),
            maximum_exact_input_tokens=(
                max(item.exact_input_tokens for item in calibration_items)
                if perform_tokenizer_preflight
                else None
            ),
            tokenizer_version=tokenizer_version,
            tokenizer_load_performed=perform_tokenizer_preflight,
            max_context_tokens=backend_config.max_context_tokens,
            max_output_tokens=backend_config.max_new_tokens,
        )
        (staging / "REPORT.json").write_text(plan.model_dump_json(indent=2) + "\n")
        os.rename(staging, target)
        return plan
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _runtime_config(
    input_data: ReferenceQualityInput,
    *,
    profile: ModelNodeProfile,
    backend: LocalRuntimeBackend,
    project_id: str,
    expected_project_revision: int,
    tokenizer: Any | None,
) -> tuple[ModelNodeRuntimeConfig, int, int, int | None]:
    policy = NodePolicy(
        policy_id="local-qwen3vl2b-reference-quality-v1",
        enabled=True,
        allowed_node_names=[ReferenceQualityNode.node_name],
        expected_backend=profile.provider,
        expected_model=profile.model,
        allowed_tool_names=list(profile.admission.allowed_tool_names),
        max_request_bytes=profile.admission.max_request_bytes,
        max_input_tokens=profile.admission.max_input_tokens,
        max_output_tokens=profile.admission.max_output_tokens,
        max_total_tokens=profile.admission.max_total_tokens,
        max_api_cost_usd=profile.cumulative_project.max_api_cost_usd,
        max_latency_ms=profile.admission.max_latency_ms,
    )
    projection = ImmutableStateProjection(
        project_id=project_id,
        state_snapshot_id=input_data.source_projection_sha256,
        state_revision=expected_project_revision,
        stage=input_data.decision_stage,
        evidence_ids=(input_data.source_id,),
    )
    config = ModelNodeRuntimeConfig(
        node_name=ReferenceQualityNode.node_name,
        request_id=f"calibrate-{input_data.source_id}",
        node_input=input_data.model_dump(mode="json"),
        state_projection=projection,
        trigger=ModelNodeTrigger(
            trigger_id=f"calibrate-{input_data.source_id}",
            reason="Calibrate source-grounded reference-quality judgments locally.",
        ),
        policy=policy,
        backend=backend,
        seed=0,
    )
    request = ReferenceQualityNode()._build_request(
        input_data,
        context=projection.to_node_context(),
        policy=policy,
        request_id=config.request_id or f"calibrate-{input_data.source_id}",
        seed=config.seed,
        profile=profile,
    )
    request_bytes = len(
        json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    messages = structured_model_messages(request)
    prompt_bytes = sum(len(message["content"].encode()) for message in messages)
    input_tokens = None
    if tokenizer is not None:
        rendered = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        encoded = tokenizer(rendered, add_special_tokens=False)
        input_tokens = len(encoded["input_ids"])
        if input_tokens > profile.admission.max_input_tokens:
            raise ValueError("AAAR calibration input exceeds profile token admission")
        if input_tokens + profile.generation.max_output_tokens > backend.config.max_context_tokens:
            raise ValueError("AAAR calibration request exceeds local model context")
    return config, prompt_bytes, request_bytes, input_tokens


def _load_projection_report(
    path: str | Path,
) -> tuple[Path, bytes, AaarQualityProjectionReport]:
    source = Path(path).resolve(strict=True)
    raw = _bounded_regular_bytes(source)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("AAAR quality projection report must be UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("AAAR quality projection report must contain an object")
    recorded = payload.pop("report_sha256", None)
    report = AaarQualityProjectionReport.model_validate(payload)
    if recorded != report.report_sha256:
        raise ValueError("AAAR quality projection report hash mismatch")
    if not (
        report.ready_item_count == report.item_count
        and report.role_complete_item_count == report.item_count
    ):
        raise ValueError("AAAR quality projection population is incomplete")
    return source, raw, report


def _bounded_regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_CONTROL_BYTES:
        raise ValueError("AAAR calibration control file must be bounded and regular")
    return path.read_bytes()


def _resolve_beneath(root: Path, locator: str) -> Path | None:
    pure = PurePosixPath(locator)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    current = root
    for part in pure.parts:
        current /= part
        if current.is_symlink():
            return None
    resolved = current.resolve(strict=False)
    return resolved if resolved.is_relative_to(root) else None


def _checkpoint_size(path: Path) -> int:
    if not path.is_dir():
        raise ValueError("AAAR local calibration checkpoint path is not a directory")
    total = 0
    files = 0
    for item in path.rglob("*"):
        if item.is_symlink():
            raise ValueError("AAAR local calibration checkpoint contains a symlink")
        if item.is_file():
            total += item.stat().st_size
            files += 1
    if files == 0:
        raise ValueError("AAAR local calibration checkpoint is empty")
    return total


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


__all__ = [
    "AaarQualityCalibrationItem",
    "AaarQualityCalibrationPlan",
    "materialize_aaar_quality_calibration_plan",
]

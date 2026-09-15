"""Prepare and verify label-isolated MLRC Perception runtime views.

This is a task-specific bridge from the acquired MLRC bytes to the generic
SciTaste benchmark runners.  It does not authorize or perform model, GPU, API,
development, or held-out execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scitaste.evaluation.dataset_materialization import load_dataset_materialization_receipt
from scitaste.evaluation.task_runtime import hash_benchmark_tree
from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_MAX_MANIFEST_BYTES = 1_048_576
_MAX_JSON_BYTES = 67_108_864
_PROJECTION_RECEIPT = "RUNTIME_RECEIPT.json"


class FileBinding(BaseModel):
    model_config = _CONFIG

    locator: str
    sha256: str = Field(pattern=_SHA256)


class MLRCPerceptionRuntimeManifest(BaseModel):
    """Immutable inputs and commands for the split Perception runtime."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    runtime_id: str
    source_checkout: str
    repository_commit: str = Field(pattern=_COMMIT)
    require_clean_checkout: Literal[True] = True
    visible_root: str
    visible_tree_sha256: str = Field(pattern=_SHA256)
    materialization_receipt: FileBinding
    development_view: str
    development_view_sha256: str = Field(pattern=_SHA256)
    heldout_view: str
    heldout_view_sha256: str = Field(pattern=_SHA256)
    heldout_feature_directories: tuple[str, str]
    heldout_label_locator: str
    heldout_label_sha256: str = Field(pattern=_SHA256)
    projection_root: str
    python_executable: str
    python_package_root: str
    python_package_tree_sha256: str = Field(pattern=_SHA256)
    required_versions: dict[str, str] = Field(min_length=4, max_length=32)
    development_entrypoint: FileBinding
    heldout_inference_entrypoint: FileBinding
    objective_scorer: FileBinding
    scorer_parity_receipt: FileBinding
    development_command: tuple[str, ...]
    heldout_inference_command: tuple[str, ...]
    objective_score_command: tuple[str, ...]
    primary_metric: Literal["mean_average_precision"] = "mean_average_precision"
    tiou_thresholds: tuple[float, float, float, float, float] = (0.1, 0.2, 0.3, 0.4, 0.5)
    agent_network_access: Literal[False] = False
    heldout_labels_visible_to_model: Literal[False] = False
    model_execution_authorized: Literal[False] = False
    benchmark_execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def boundaries_are_distinct(self) -> MLRCPerceptionRuntimeManifest:
        _safe_relative(self.source_checkout)
        _safe_relative(self.visible_root)
        _safe_relative(self.development_view)
        _safe_relative(self.heldout_view)
        _safe_relative(self.heldout_label_locator)
        _safe_relative(self.projection_root)
        _safe_relative(self.python_executable)
        _safe_relative(self.python_package_root)
        for binding in (
            self.materialization_receipt,
            self.development_entrypoint,
            self.heldout_inference_entrypoint,
            self.objective_scorer,
            self.scorer_parity_receipt,
        ):
            _safe_relative(binding.locator)
        for value in self.heldout_feature_directories:
            _safe_relative(value)
        if self.heldout_label_locator in self.heldout_feature_directories:
            raise ValueError("held-out labels cannot be an inference feature directory")
        if len(set(self.required_versions)) != len(self.required_versions):
            raise ValueError("runtime package names must be unique")
        return self

    @property
    def fingerprint(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


class MLRCPerceptionRuntimeInspection(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    runtime_id: str
    manifest_sha256: str = Field(pattern=_SHA256)
    manifest_fingerprint: str = Field(pattern=_SHA256)
    source_ready: bool
    data_ready: bool
    environment_ready: bool
    projection_ready: bool
    development_ready: bool
    heldout_inference_ready: bool
    scorer_ready: bool
    blocker_codes: tuple[str, ...]
    observed_source_commit: str | None = Field(default=None, pattern=_COMMIT)
    development_view_sha256: str | None = Field(default=None, pattern=_SHA256)
    heldout_view_sha256: str | None = Field(default=None, pattern=_SHA256)
    environment_probe_sha256: str | None = Field(default=None, pattern=_SHA256)
    scorer_parity_receipt_sha256: str | None = Field(default=None, pattern=_SHA256)
    no_model_execution_performed: Literal[True] = True
    no_gpu_work_performed: Literal[True] = True
    no_api_call_performed: Literal[True] = True
    no_benchmark_execution_performed: Literal[True] = True


class MLRCPerceptionRuntimeReceipt(BaseModel):
    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    runtime_id: str
    manifest_sha256: str = Field(pattern=_SHA256)
    manifest_fingerprint: str = Field(pattern=_SHA256)
    repository_commit: str = Field(pattern=_COMMIT)
    materialization_receipt_sha256: str = Field(pattern=_SHA256)
    development_view_sha256: str = Field(pattern=_SHA256)
    inference_view_locator: str
    inference_view_sha256: str = Field(pattern=_SHA256)
    inference_file_count: int = Field(gt=0)
    inference_total_bytes: int = Field(gt=0)
    redacted_manifest_sha256: str = Field(pattern=_SHA256)
    heldout_label_sha256: str = Field(pattern=_SHA256)
    development_entrypoint_sha256: str = Field(pattern=_SHA256)
    heldout_inference_entrypoint_sha256: str = Field(pattern=_SHA256)
    objective_scorer_sha256: str = Field(pattern=_SHA256)
    python_package_tree_sha256: str = Field(pattern=_SHA256)
    environment_probe_sha256: str = Field(pattern=_SHA256)
    development_data_contains_heldout_paths: Literal[False] = False
    inference_view_contains_labels: Literal[False] = False
    scorer_labels_mounted_in_candidate_sandbox: Literal[False] = False
    exact_prediction_hash_required_for_scoring: Literal[True] = True
    model_execution_performed: Literal[False] = False
    gpu_work_performed: Literal[False] = False
    api_calls_performed: Literal[False] = False
    benchmark_execution_performed: Literal[False] = False
    receipt_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def receipt_is_self_hashed(self) -> MLRCPerceptionRuntimeReceipt:
        _safe_relative(self.inference_view_locator)
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("MLRC Perception runtime receipt hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> MLRCPerceptionRuntimeReceipt:
        values.pop("receipt_sha256", None)
        unsigned = cls.model_construct(schema_version="1.0", receipt_sha256="0" * 64, **values)
        return cls(
            schema_version="1.0",
            **values,
            receipt_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"receipt_sha256"})
            ),
        )


def load_mlrc_perception_runtime_manifest(
    path: str | Path,
) -> tuple[MLRCPerceptionRuntimeManifest, str]:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("MLRC Perception runtime manifest must be a bounded regular file")
    raw = source.read_bytes()
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError("MLRC Perception runtime manifest must contain one mapping")
    return MLRCPerceptionRuntimeManifest.model_validate(payload), hashlib.sha256(raw).hexdigest()


def inspect_mlrc_perception_runtime(
    manifest: MLRCPerceptionRuntimeManifest,
    *,
    manifest_sha256: str,
    workspace_root: str | Path,
) -> MLRCPerceptionRuntimeInspection:
    root = Path(workspace_root).resolve(strict=True)
    blockers: list[str] = []
    observed_commit: str | None = None

    checkout = _under(root, manifest.source_checkout, directory=True)
    if checkout is None:
        blockers.append("source-checkout-unavailable")
    else:
        try:
            observed_commit = _git(checkout, "rev-parse", "HEAD")
            dirty = bool(_git(checkout, "status", "--porcelain=v1", "--untracked-files=all"))
        except ValueError:
            blockers.append("source-checkout-git-invalid")
        else:
            if observed_commit != manifest.repository_commit:
                blockers.append("source-commit-mismatch")
            if dirty:
                blockers.append("source-checkout-dirty")
        visible = _under(checkout, manifest.visible_root, directory=True)
        if visible is None or hash_benchmark_tree(visible)[0] != manifest.visible_tree_sha256:
            blockers.append("visible-tree-mismatch")

    for label, binding in (
        ("materialization-receipt", manifest.materialization_receipt),
        ("development-entrypoint", manifest.development_entrypoint),
        ("heldout-inference-entrypoint", manifest.heldout_inference_entrypoint),
        ("objective-scorer", manifest.objective_scorer),
        ("scorer-parity-receipt", manifest.scorer_parity_receipt),
    ):
        if not _binding_matches(root, binding):
            blockers.append(f"{label}-mismatch")

    receipt_path = _under(root, manifest.materialization_receipt.locator, directory=False)
    if receipt_path is not None:
        try:
            receipt = load_dataset_materialization_receipt(receipt_path)
        except ValueError:
            blockers.append("materialization-receipt-invalid")
        else:
            if receipt.task_spec_fingerprint != (
                "e7c6ae4e84f201cb9b2adfbdeb0d9180f8b60bde4a8007662c9e7c3876139cca"
            ):
                blockers.append("materialization-task-binding-mismatch")

    development_hash = _verified_tree(root, manifest.development_view, blockers, "development")
    heldout_hash = _verified_tree(root, manifest.heldout_view, blockers, "heldout")
    if development_hash is not None and development_hash != manifest.development_view_sha256:
        blockers.append("development-view-mismatch")
    if heldout_hash is not None and heldout_hash != manifest.heldout_view_sha256:
        blockers.append("heldout-view-mismatch")
    heldout = _under(root, manifest.heldout_view, directory=True)
    if heldout is not None:
        for locator in manifest.heldout_feature_directories:
            if _under(heldout, locator, directory=True) is None:
                blockers.append(f"heldout-feature-unavailable:{locator}")
        label = _under(heldout, manifest.heldout_label_locator, directory=False)
        if label is None or _sha256_file(label) != manifest.heldout_label_sha256:
            blockers.append("heldout-label-mismatch")

    package_root = _under(root, manifest.python_package_root, directory=True)
    package_hash = None if package_root is None else _tree_hash(package_root)[0]
    if package_hash != manifest.python_package_tree_sha256:
        blockers.append("python-package-tree-mismatch")
    environment_probe = _probe_environment(manifest, root, checkout)
    if environment_probe is None:
        blockers.append("environment-probe-failed")
    parity_path = _under(root, manifest.scorer_parity_receipt.locator, directory=False)
    if parity_path is None or not _parity_receipt_matches(parity_path, manifest):
        blockers.append("scorer-parity-invalid")

    source_blockers = {
        item for item in blockers if item.startswith("source-") or item.startswith("visible-")
    }
    data_blockers = {
        item
        for item in blockers
        if item.startswith(("materialization-", "development-view", "heldout-"))
    }
    entrypoint_blockers = {item for item in blockers if item.endswith("entrypoint-mismatch")}
    scorer_blockers = {
        item
        for item in blockers
        if item
        in {
            "objective-scorer-mismatch",
            "scorer-parity-receipt-mismatch",
            "scorer-parity-invalid",
        }
    }
    environment_blockers = {
        item for item in blockers if item.startswith(("python-package-", "environment-"))
    }
    projection = _under(root, manifest.projection_root, directory=True)
    projection_ready = False
    if projection is not None:
        try:
            loaded = load_mlrc_perception_runtime_receipt(projection / _PROJECTION_RECEIPT)
            projection_ready = (
                loaded.manifest_sha256 == manifest_sha256
                and loaded.manifest_fingerprint == manifest.fingerprint
                and loaded.heldout_label_sha256 == manifest.heldout_label_sha256
                and loaded.objective_scorer_sha256 == manifest.objective_scorer.sha256
                and _projection_matches(root, manifest, loaded)
            )
        except (OSError, ValueError):
            blockers.append("projection-receipt-invalid")
        if not projection_ready and "projection-receipt-invalid" not in blockers:
            blockers.append("projection-content-mismatch")

    source_ready = not source_blockers
    data_ready = not data_blockers
    environment_ready = not environment_blockers
    return MLRCPerceptionRuntimeInspection(
        runtime_id=manifest.runtime_id,
        manifest_sha256=manifest_sha256,
        manifest_fingerprint=manifest.fingerprint,
        source_ready=source_ready,
        data_ready=data_ready,
        environment_ready=environment_ready,
        projection_ready=projection_ready,
        development_ready=(
            source_ready and data_ready and environment_ready and not entrypoint_blockers
        ),
        heldout_inference_ready=(
            source_ready
            and data_ready
            and environment_ready
            and projection_ready
            and not entrypoint_blockers
        ),
        scorer_ready=data_ready and not scorer_blockers,
        blocker_codes=tuple(sorted(set(blockers))),
        observed_source_commit=observed_commit,
        development_view_sha256=development_hash,
        heldout_view_sha256=heldout_hash,
        environment_probe_sha256=environment_probe,
        scorer_parity_receipt_sha256=(
            manifest.scorer_parity_receipt.sha256 if not scorer_blockers else None
        ),
    )


def prepare_mlrc_perception_runtime(
    manifest: MLRCPerceptionRuntimeManifest,
    *,
    manifest_sha256: str,
    workspace_root: str | Path,
    allow_projection: bool = False,
) -> MLRCPerceptionRuntimeReceipt:
    if not allow_projection:
        raise ValueError("MLRC Perception runtime projection requires explicit authorization")
    root = Path(workspace_root).resolve(strict=True)
    preflight = inspect_mlrc_perception_runtime(
        manifest,
        manifest_sha256=manifest_sha256,
        workspace_root=root,
    )
    allowed = {"projection-receipt-invalid"}
    if set(preflight.blocker_codes) - allowed:
        raise ValueError(
            f"MLRC Perception runtime is not projection-ready: {preflight.blocker_codes}"
        )
    target = root.joinpath(*PurePosixPath(manifest.projection_root).parts)
    if target.exists() or target.is_symlink():
        raise FileExistsError(target)
    heldout = _under(root, manifest.heldout_view, directory=True)
    label_path = _under(heldout, manifest.heldout_label_locator, directory=False)
    package_root = _under(root, manifest.python_package_root, directory=True)
    if heldout is None or label_path is None or package_root is None:
        raise ValueError("MLRC Perception runtime inputs are unavailable")
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=parent))
    try:
        data = temporary / "inference" / "data"
        data.mkdir(parents=True)
        for locator in manifest.heldout_feature_directories:
            source = _under(heldout, locator, directory=True)
            if source is None:
                raise ValueError(f"held-out feature tree is unavailable: {locator}")
            destination = data.joinpath(*PurePosixPath(locator).parts)
            _hardlink_tree(source, destination)
        ground_truth = _load_json(label_path)
        redacted = _redact_ground_truth(ground_truth)
        redacted_path = data.joinpath(*PurePosixPath(manifest.heldout_label_locator).parts)
        redacted_path.parent.mkdir(parents=True, exist_ok=True)
        redacted_raw = (
            json.dumps(redacted, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        redacted_path.write_bytes(redacted_raw)
        _make_read_only(temporary / "inference")
        inference_hash, inference_count, inference_bytes = _tree_hash(temporary / "inference")
        environment_probe = _probe_environment(
            manifest,
            root,
            _under(root, manifest.source_checkout, directory=True),
        )
        if environment_probe is None:
            raise ValueError("MLRC Perception Python 3.12 environment probe failed")
        receipt = MLRCPerceptionRuntimeReceipt.create(
            runtime_id=manifest.runtime_id,
            manifest_sha256=manifest_sha256,
            manifest_fingerprint=manifest.fingerprint,
            repository_commit=manifest.repository_commit,
            materialization_receipt_sha256=manifest.materialization_receipt.sha256,
            development_view_sha256=manifest.development_view_sha256,
            inference_view_locator=f"{manifest.projection_root}/inference",
            inference_view_sha256=inference_hash,
            inference_file_count=inference_count,
            inference_total_bytes=inference_bytes,
            redacted_manifest_sha256=hashlib.sha256(redacted_raw).hexdigest(),
            heldout_label_sha256=manifest.heldout_label_sha256,
            development_entrypoint_sha256=manifest.development_entrypoint.sha256,
            heldout_inference_entrypoint_sha256=manifest.heldout_inference_entrypoint.sha256,
            objective_scorer_sha256=manifest.objective_scorer.sha256,
            python_package_tree_sha256=manifest.python_package_tree_sha256,
            environment_probe_sha256=environment_probe,
        )
        _write_new_json(temporary / _PROJECTION_RECEIPT, receipt.model_dump(mode="json"))
        os.replace(temporary, target)
        return receipt
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def load_mlrc_perception_runtime_receipt(path: str | Path) -> MLRCPerceptionRuntimeReceipt:
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError("MLRC Perception runtime receipt is invalid")
    return MLRCPerceptionRuntimeReceipt.model_validate_json(source.read_bytes(), strict=True)


def _probe_environment(
    manifest: MLRCPerceptionRuntimeManifest,
    root: Path,
    checkout: Path | None,
) -> str | None:
    if checkout is None:
        return None
    python = _under(root, manifest.python_executable, directory=False)
    packages = _under(root, manifest.python_package_root, directory=True)
    task_source = _under(checkout, manifest.visible_root, directory=True)
    if python is None or packages is None or task_source is None or not os.access(python, os.X_OK):
        return None
    versions = json.dumps(manifest.required_versions, sort_keys=True)
    script = (
        "import importlib.metadata as m,json,sys,torch\n"
        "expected=json.loads(sys.argv[1])\n"
        "observed={name:m.version(name) for name in expected}\n"
        "assert observed==expected,(observed,expected)\n"
        "import h5py,tensorboard,nms_1d_cpu,evaluation,methods,train\n"
        "segments=torch.tensor([[0.,1.],[0.1,0.9]])\n"
        "scores=torch.tensor([0.9,0.8])\n"
        "assert nms_1d_cpu.nms(segments,scores,0.5).tolist()==[0]\n"
        "print(json.dumps({'python':sys.version.split()[0],'versions':observed,'task_imports':True,'nms_cpu':True,'cuda_used':False},sort_keys=True,separators=(',',':')))\n"
    )
    environment = {
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": f"{packages}:{task_source}",
        "TZ": "UTC",
    }
    try:
        completed = subprocess.run(
            (str(python), "-c", script, versions),
            cwd=task_source,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=30,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode or completed.stderr:
        return None
    return hashlib.sha256(completed.stdout).hexdigest()


def _redact_ground_truth(payload: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for video_id in sorted(payload):
        value = payload[video_id]
        if not isinstance(value, dict) or not isinstance(value.get("metadata"), dict):
            raise ValueError("held-out ground truth has an invalid video record")
        metadata = value["metadata"]
        try:
            projected = {
                "split": "test",
                "video_id": str(metadata["video_id"]),
                "frame_rate": float(metadata["frame_rate"]),
                "num_frames": int(metadata["num_frames"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("held-out inference metadata is incomplete") from exc
        if projected["video_id"] != video_id:
            raise ValueError("held-out video identity mismatch")
        redacted[video_id] = {"action_localisation": [], "metadata": projected}
    if not redacted:
        raise ValueError("held-out ground truth is empty")
    return redacted


def _projection_matches(
    root: Path,
    manifest: MLRCPerceptionRuntimeManifest,
    receipt: MLRCPerceptionRuntimeReceipt,
) -> bool:
    inference = _under(root, receipt.inference_view_locator, directory=True)
    if inference is None:
        return False
    observed_hash, observed_count, observed_bytes = _tree_hash(inference)
    if (
        observed_hash != receipt.inference_view_sha256
        or observed_count != receipt.inference_file_count
        or observed_bytes != receipt.inference_total_bytes
    ):
        return False
    redacted_path = _under(inference / "data", manifest.heldout_label_locator, directory=False)
    if redacted_path is None or _sha256_file(redacted_path) != receipt.redacted_manifest_sha256:
        return False
    redacted = _load_json(redacted_path)
    for value in redacted.values():
        if not isinstance(value, dict) or value.get("action_localisation") != []:
            return False
        if set(value) != {"action_localisation", "metadata"}:
            return False
    return True


def _parity_receipt_matches(
    path: Path,
    manifest: MLRCPerceptionRuntimeManifest,
) -> bool:
    try:
        payload = _load_json(path)
    except (OSError, ValueError):
        return False
    try:
        scores_match = abs(
            float(payload.get("scorer_average_map")) - float(payload.get("upstream_average_map"))
        ) <= float(payload.get("absolute_tolerance"))
    except (TypeError, ValueError):
        return False
    return (
        payload.get("fixed_upstream_commit") == manifest.repository_commit
        and payload.get("scorer_sha256") == manifest.objective_scorer.sha256
        and payload.get("ground_truth_sha256") == manifest.heldout_label_sha256
        and payload.get("label_count") == 63
        and payload.get("prediction_count") == 126
        and payload.get("parity_verified") is True
        and payload.get("same_annotation_bytes") is True
        and payload.get("same_microseconds_to_seconds_conversion") is True
        and payload.get("same_label_id_semantics") is True
        and payload.get("model_execution_performed") is False
        and payload.get("gpu_work_performed") is False
        and payload.get("api_calls_performed") is False
        and scores_match
    )


def _binding_matches(root: Path, binding: FileBinding) -> bool:
    path = _under(root, binding.locator, directory=False)
    return path is not None and _sha256_file(path) == binding.sha256


def _verified_tree(root: Path, locator: str, blockers: list[str], label: str) -> str | None:
    path = _under(root, locator, directory=True)
    if path is None:
        blockers.append(f"{label}-view-unavailable")
        return None
    try:
        return _tree_hash(path)[0]
    except ValueError:
        blockers.append(f"{label}-view-unsafe")
        return None


def _tree_hash(path: Path) -> tuple[str, int, int]:
    root = path.resolve(strict=True)
    entries: list[dict[str, object]] = []
    total = 0
    for candidate in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if candidate.is_symlink():
            raise ValueError("runtime tree contains a symbolic link")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise ValueError("runtime tree contains a special entry")
        size = candidate.stat().st_size
        digest = _sha256_file(candidate)
        total += size
        entries.append(
            {"path": candidate.relative_to(root).as_posix(), "size": size, "sha256": digest}
        )
    if not entries:
        raise ValueError("runtime tree is empty")
    return content_sha256({"schema_version": "1.0", "entries": entries}), len(entries), total


def _hardlink_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for candidate in sorted(
        source.rglob("*"),
        key=lambda item: item.relative_to(source).as_posix(),
    ):
        if candidate.is_symlink():
            raise ValueError("held-out feature tree contains a symbolic link")
        relative = candidate.relative_to(source)
        target = destination / relative
        if candidate.is_dir():
            target.mkdir(exist_ok=True)
        elif candidate.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(candidate, target)
        else:
            raise ValueError("held-out feature tree contains a special entry")


def _make_read_only(root: Path) -> None:
    for candidate in sorted(root.rglob("*"), reverse=True):
        mode = 0o555 if candidate.is_dir() else 0o444
        candidate.chmod(mode)
    root.chmod(0o555)


def _under(root: Path | None, locator: str, *, directory: bool) -> Path | None:
    if root is None:
        return None
    try:
        candidate = root.joinpath(*PurePosixPath(locator).parts)
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_relative_to(root.resolve(strict=True)):
        return None
    if directory and not resolved.is_dir():
        return None
    if not directory and not resolved.is_file():
        return None
    return resolved


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("runtime locator must be a safe relative path")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError("runtime JSON input exceeds its byte limit")
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("runtime JSON input must contain a mapping")
    return payload


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(root), *arguments),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if completed.returncode:
        raise ValueError("Git inspection failed")
    return completed.stdout.strip()


def _write_new_json(path: Path, payload: object) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("inspect", "prepare"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    parser.add_argument("--allow-projection", action="store_true")
    args = parser.parse_args(argv)
    manifest, manifest_sha256 = load_mlrc_perception_runtime_manifest(args.manifest)
    if args.command == "prepare":
        payload: BaseModel = prepare_mlrc_perception_runtime(
            manifest,
            manifest_sha256=manifest_sha256,
            workspace_root=args.workspace_root,
            allow_projection=args.allow_projection,
        )
    else:
        payload = inspect_mlrc_perception_runtime(
            manifest,
            manifest_sha256=manifest_sha256,
            workspace_root=args.workspace_root,
        )
    print(json.dumps(payload.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MLRCPerceptionRuntimeInspection",
    "MLRCPerceptionRuntimeManifest",
    "MLRCPerceptionRuntimeReceipt",
    "inspect_mlrc_perception_runtime",
    "load_mlrc_perception_runtime_manifest",
    "load_mlrc_perception_runtime_receipt",
    "prepare_mlrc_perception_runtime",
]

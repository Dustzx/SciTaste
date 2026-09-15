from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scitaste.evaluation.task_execution import (
    load_benchmark_resource_verification_receipt,
    verify_benchmark_execution_resources,
)
from scitaste.executor import (
    ExecutionStatus,
    MetricDirection,
    NativeExecutionProfile,
    NativeExecutionStore,
    NativeExperimentDefinition,
    NativeExperimentLimits,
    NativeExperimentRunner,
    NativeExternalResourceInput,
    NativeGPUDeviceRequest,
    NativeGPUInventory,
    NativeGPURequest,
    NativePythonRuntimeRequest,
    SciTasteNativeExecutor,
    inspect_native_execution_profile,
    load_native_execution_profile_request,
    load_prepared_native_execution_profile_record,
    native_external_tree_sha256,
    preflight_native_resources,
    prepare_native_execution_profile,
)
from scitaste.project.models import content_sha256
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_profile(path: Path, dataset: Path, digest: str) -> None:
    path.write_text(
        "\n".join(
            [
                "schema_version: '1.0'",
                "profile_id: dataset-cpu-test",
                "datasets:",
                "  - dataset_id: scores",
                f"    source_path: {dataset.name}",
                f"    expected_sha256: '{digest}'",
                "    max_files: 1",
                "    max_total_bytes: 1024",
                "gpu:",
                "  enabled: false",
                "  devices: []",
                "  max_gpu_hours: 0",
                "network_access: false",
                "writable_workspace: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _state() -> ResearchState:
    return ResearchState(
        project_id="native-profile-test",
        research_direction="Execute against a bound dataset",
        target_domain="autonomous-research",
    )


def _action() -> ResearchAction:
    return ResearchAction(
        action_id="act-native-profile",
        type=MetaAction.COLLECT_EVIDENCE,
        description="Run the registered dataset experiment.",
        parameters={"experiment_id": "dataset-test"},
    )


def test_dataset_profile_is_materialized_read_only_and_bound_to_execution(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    resources.mkdir()
    dataset = resources / "scores.json"
    dataset.write_text('{"values":[0.2,0.4]}\n', encoding="utf-8")
    profile_path = resources / "profile.yaml"
    _write_profile(profile_path, dataset, _sha256(dataset))
    inspection = inspect_native_execution_profile(profile_path)
    run_root = tmp_path / "run"
    run_root.mkdir()
    prepared = prepare_native_execution_profile(inspection, run_root=run_root)
    source = run_root / "experiment.py"
    source.write_text(
        "import json\n"
        "from pathlib import Path\n"
        "data=json.loads(Path('/datasets/scores').read_text())\n"
        "blocked=0\n"
        "try:\n"
        "    Path('/datasets/scores').write_text('changed')\n"
        "except OSError:\n"
        "    blocked=1\n"
        "payload={'schema_version':'1.0','measurements':["
        "{'replicate_id':'bound-data','metrics':{'score_delta':sum(data['values']),"
        "'dataset_write_blocked':float(blocked)}}]}\n"
        "print('SCITASTE_MEASUREMENTS_JSON='+json.dumps(payload))\n",
        encoding="utf-8",
    )
    definition = NativeExperimentDefinition(
        schema_version="1.1",
        experiment_id="dataset-test",
        source_path=source,
        primary_metric="score_delta",
        metric_direction=MetricDirection.MAXIMIZE,
        support_threshold=0.5,
        required_metrics=("score_delta", "dataset_write_blocked"),
    )
    runner = NativeExperimentRunner(definition, execution_profile=prepared)
    if not runner.availability().available:
        pytest.skip(f"bubblewrap resource isolation unavailable: {runner.availability().reason}")
    executor = SciTasteNativeExecutor(
        workspace=run_root / "native_execution",
        artifact_root=run_root,
        experiment_runner=runner,
    )

    result = executor.execute(_state(), _action())

    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.data["metrics"] == {
        "dataset_write_blocked": 1.0,
        "score_delta": pytest.approx(0.6),
    }
    assert result.data["execution_profile_id"] == "dataset-cpu-test"
    assert result.data["dataset_mounts"] == ["/datasets/scores"]
    execution_path = next(
        run_root / locator for locator in result.artifacts if locator.endswith("execution.json")
    )
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    assert execution["datasets"][0]["content_sha256"] == _sha256(dataset)
    assert execution["gpu_devices"] == "not-mounted"
    record_path = run_root / result.data["execution_record"]
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert any(locator.endswith("PROFILE.json") for locator in record["input_sha256"])
    assert any(locator.endswith("datasets/scores") for locator in record["input_sha256"])

    prepared.datasets[0].materialized_path.write_text("drift\n", encoding="utf-8")
    assert runner.availability().available is False
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        NativeExecutionStore(run_root / "native_execution", artifact_root=run_root).verify()


def test_profile_rejects_hash_drift_symlinks_and_declared_bounds(tmp_path: Path) -> None:
    dataset = tmp_path / "scores.json"
    dataset.write_text("{}\n", encoding="utf-8")
    profile_path = tmp_path / "profile.yaml"
    _write_profile(profile_path, dataset, "0" * 64)
    with pytest.raises(ValueError, match="content hash mismatch"):
        inspect_native_execution_profile(profile_path)

    linked = tmp_path / "linked.json"
    linked.symlink_to(dataset)
    _write_profile(profile_path, linked, _sha256(dataset))
    with pytest.raises(ValueError, match="cannot be symlinks"):
        inspect_native_execution_profile(profile_path)

    dataset.write_text("x" * 2048, encoding="utf-8")
    _write_profile(profile_path, dataset, _sha256(dataset))
    with pytest.raises(ValueError, match="declared bounds"):
        inspect_native_execution_profile(profile_path)


def test_campaign_reopens_verified_resource_record_without_rehashing(tmp_path: Path) -> None:
    dataset = tmp_path / "scores.json"
    dataset.write_text('{"values":[0.2,0.4]}\n', encoding="utf-8")
    profile_path = tmp_path / "profile.yaml"
    _write_profile(profile_path, dataset, _sha256(dataset))
    inspection = inspect_native_execution_profile(profile_path)
    run_root = tmp_path / "run"
    run_root.mkdir()
    prepared = prepare_native_execution_profile(inspection, run_root=run_root)
    receipt_path = run_root / "RESOURCE_VERIFICATION.json"
    expected = verify_benchmark_execution_resources(
        prepared,
        receipt_path=receipt_path,
        verified_during_materialization=True,
    )

    requested = load_native_execution_profile_request(profile_path)
    reopened = load_prepared_native_execution_profile_record(requested, run_root=run_root)
    receipt = load_benchmark_resource_verification_receipt(receipt_path, reopened)

    assert reopened.record_sha256 == prepared.record_sha256
    assert receipt.receipt_sha256 == expected.receipt_sha256
    assert receipt.verification_basis == "verified-materialization"


def test_schema_1_profile_fingerprint_remains_backward_compatible() -> None:
    inspection = inspect_native_execution_profile(
        "configs/experiments/native_execution_dataset_cpu_v1.yaml"
    )

    assert inspection.fingerprint == (
        "f353115217cfa07a93b51108b9d8f1252ece371c391f1d97990bd92eb21af183"
    )
    assert inspection.external_resources == ()


def test_directory_profile_binds_tree_paths_and_rejects_rehashed_omission(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "tree"
    (dataset / "nested").mkdir(parents=True)
    (dataset / "a.txt").write_text("alpha\n", encoding="utf-8")
    (dataset / "nested/b.txt").write_text("beta\n", encoding="utf-8")
    entries = [
        {
            "path": path.relative_to(dataset).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(dataset.rglob("*"))
        if path.is_file()
    ]
    digest = content_sha256({"schema_version": "1.0", "entries": entries})
    profile_path = tmp_path / "tree-profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "schema_version: '1.0'",
                "profile_id: tree-profile",
                "datasets:",
                "  - dataset_id: tree",
                "    source_path: tree",
                f"    expected_sha256: '{digest}'",
                "    max_files: 2",
                "    max_total_bytes: 1024",
                "gpu: {enabled: false, devices: [], max_gpu_hours: 0}",
                "network_access: false",
                "writable_workspace: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    inspection = inspect_native_execution_profile(profile_path)
    run_root = tmp_path / "run"
    run_root.mkdir()
    prepared = prepare_native_execution_profile(inspection, run_root=run_root)
    assert prepared.datasets[0].kind == "directory"
    assert prepared.datasets[0].file_count == 2
    assert (prepared.datasets[0].materialized_path / "nested/b.txt").read_text() == "beta\n"

    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    manifest.pop("record_sha256")
    manifest["datasets"] = []
    manifest["record_sha256"] = content_sha256(manifest)
    prepared.manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="prepared native datasets"):
        prepare_native_execution_profile(inspection, run_root=run_root)


def test_gpu_profile_preflight_validates_identity_and_budget_contract(monkeypatch) -> None:
    import scitaste.executor.native_profile as native_profile

    inventory = NativeGPUInventory(
        index=0,
        uuid="GPU-00000000-0000-0000-0000-000000000000",
        name="NVIDIA GeForce RTX 3090",
        memory_total_mb=24576,
        device_nodes=("/dev/null",),
    )
    monkeypatch.setattr(native_profile, "_query_nvidia_inventory", lambda: ((inventory,), None))
    accepted = NativeExecutionProfile(
        profile_id="local-3090",
        gpu=NativeGPURequest(
            enabled=True,
            devices=(
                NativeGPUDeviceRequest(
                    index=0,
                    expected_name="NVIDIA GeForce RTX 3090",
                    min_memory_mb=24000,
                ),
            ),
            max_gpu_hours=0.1,
        ),
    )
    result = preflight_native_resources(accepted)
    assert result.available is True
    assert result.gpu_devices == (inventory,)

    rejected = accepted.model_copy(
        update={
            "gpu": accepted.gpu.model_copy(
                update={
                    "devices": (
                        accepted.gpu.devices[0].model_copy(
                            update={"expected_name": "Different GPU"}
                        ),
                    )
                }
            )
        }
    )
    result = preflight_native_resources(rejected)
    assert result.available is False
    assert "name does not match" in (result.reason or "")


def test_disabled_gpu_profile_cannot_smuggle_devices_or_budget() -> None:
    with pytest.raises(ValueError, match="disabled native GPU access"):
        NativeGPURequest(
            enabled=False,
            devices=(NativeGPUDeviceRequest(index=0),),
            max_gpu_hours=1.0,
        )


def test_external_model_and_python_trees_are_bound_mounted_and_reverified(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    (runtime / "bin").mkdir(parents=True)
    (runtime / "lib").mkdir()
    (runtime / "bin/python3.11").write_text("runtime\n", encoding="utf-8")
    (runtime / "bin/python3.11").chmod(0o755)
    packages = tmp_path / "packages"
    packages.mkdir()
    (packages / "dependency.py").write_text("VALUE = 1\n", encoding="utf-8")
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"model_type":"test"}\n', encoding="utf-8")
    profile_path = tmp_path / "external-profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "schema_version: '1.1'",
                "profile_id: external-test",
                "datasets: []",
                "external_resources:",
                "  - resource_id: python-base",
                "    resource_kind: python-runtime",
                "    source_path: runtime",
                f"    expected_sha256: '{native_external_tree_sha256(runtime)}'",
                "  - resource_id: python-packages",
                "    resource_kind: python-packages",
                "    source_path: packages",
                f"    expected_sha256: '{native_external_tree_sha256(packages)}'",
                "  - resource_id: model",
                "    resource_kind: model",
                "    source_path: model",
                f"    expected_sha256: '{native_external_tree_sha256(model)}'",
                "python_runtime:",
                "  executable: /runtime/python-base/bin/python3.11",
                "  python_paths: [/runtime/python-packages]",
                "  library_paths: [/runtime/python-base/lib]",
                "gpu: {enabled: false, devices: [], max_gpu_hours: 0}",
                "network_access: false",
                "writable_workspace: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    inspection = inspect_native_execution_profile(profile_path)
    run_root = tmp_path / "run"
    run_root.mkdir()
    prepared = prepare_native_execution_profile(inspection, run_root=run_root)

    assert [item.mount_path for item in prepared.external_resources] == [
        "/runtime/python-base",
        "/runtime/python-packages",
        "/models/model",
    ]
    assert preflight_native_resources(inspection.profile, prepared=prepared).available is True
    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.1"
    assert manifest["external_resources"][2]["content_sha256"] == (
        native_external_tree_sha256(model)
    )

    source = run_root / "experiment.py"
    source.write_text("pass\n", encoding="utf-8")
    runner = NativeExperimentRunner(
        _definition_for_external(source),
        bubblewrap="/bin/true",
        execution_profile=prepared,
    )
    command = runner._command(source)
    assert "/runtime/python-base/bin/python3.11" in command
    assert "/models/model" in command
    assert "/runtime/python-packages" in command

    (model / "config.json").write_text('{"model_type":"drifted"}\n', encoding="utf-8")
    unavailable = preflight_native_resources(inspection.profile, prepared=prepared)
    assert unavailable.available is False
    assert "content hash mismatch" in (unavailable.reason or "")


def _definition_for_external(source: Path) -> NativeExperimentDefinition:
    return NativeExperimentDefinition(
        schema_version="1.0",
        experiment_id="external-test",
        source_path=source,
        primary_metric="score",
        metric_direction=MetricDirection.MAXIMIZE,
        support_threshold=1.0,
    )


def test_external_runtime_rejects_unbound_paths_and_unsafe_symlinks(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "python").write_text("runtime\n", encoding="utf-8")
    (runtime / "python").chmod(0o755)
    resource = NativeExternalResourceInput(
        resource_id="runtime",
        resource_kind="python-runtime",
        source_path=runtime,
        expected_sha256=native_external_tree_sha256(runtime),
    )
    with pytest.raises(ValueError, match="inside a runtime resource"):
        NativeExecutionProfile(
            schema_version="1.1",
            profile_id="bad-runtime",
            external_resources=(resource,),
            python_runtime=NativePythonRuntimeRequest(executable="/usr/bin/python3"),
        )

    outside = tmp_path / "outside"
    outside.write_text("outside\n", encoding="utf-8")
    (runtime / "escape").symlink_to("../outside")
    with pytest.raises(ValueError, match="symlink escapes"):
        native_external_tree_sha256(runtime, allow_internal_symlinks=True)


def test_local_3090_profile_runs_a_real_isolated_inventory_measurement(
    tmp_path: Path,
) -> None:
    inspection = inspect_native_execution_profile(
        "configs/experiments/native_execution_local_3090_v1.yaml"
    )
    preflight = preflight_native_resources(
        inspection.profile,
        require_materialized_datasets=False,
    )
    if not preflight.available:
        pytest.skip(f"registered local 3090 is unavailable: {preflight.reason}")
    run_root = tmp_path / "gpu-run"
    run_root.mkdir()
    prepared = prepare_native_execution_profile(inspection, run_root=run_root)
    source = run_root / "experiment.py"
    source.write_text(
        "import json, os, subprocess\n"
        "checked=subprocess.run(["
        "'/usr/bin/nvidia-smi','--query-gpu=index,name,memory.total',"
        "'--format=csv,noheader,nounits'],capture_output=True,text=True,"
        "timeout=5,check=True)\n"
        "visible='NVIDIA GeForce RTX 3090' in checked.stdout\n"
        "bounded=os.environ.get('CUDA_VISIBLE_DEVICES') == '0'\n"
        "payload={'schema_version':'1.0','measurements':["
        "{'replicate_id':'local-device','metrics':{"
        "'gpu_inventory_visible':float(visible),"
        "'cuda_visibility_bound':float(bounded)}}]}\n"
        "print('SCITASTE_MEASUREMENTS_JSON='+json.dumps(payload))\n",
        encoding="utf-8",
    )
    definition = NativeExperimentDefinition(
        schema_version="1.1",
        experiment_id="gpu-test",
        source_path=source,
        primary_metric="gpu_inventory_visible",
        metric_direction=MetricDirection.MAXIMIZE,
        support_threshold=1.0,
        required_metrics=("gpu_inventory_visible", "cuda_visibility_bound"),
        limits=NativeExperimentLimits(
            timeout_seconds=15.0,
            cpu_seconds=10,
            max_memory_mb=1024,
            max_output_bytes=65_536,
            max_open_files=32,
            max_processes=16,
        ),
    )
    action = ResearchAction(
        action_id="act-local-gpu",
        type=MetaAction.COLLECT_EVIDENCE,
        description="Measure the admitted local NVIDIA device inside Bubblewrap.",
        parameters={"experiment_id": "gpu-test"},
    )
    runner = NativeExperimentRunner(definition, execution_profile=prepared)
    availability = runner.availability()
    if not availability.available:
        pytest.skip(f"isolated local 3090 is unavailable: {availability.reason}")
    executor = SciTasteNativeExecutor(
        workspace=run_root / "native_execution",
        artifact_root=run_root,
        experiment_runner=runner,
    )

    result = executor.execute(_state(), action)

    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.data["metrics"]["gpu_inventory_visible"] == 1.0
    assert result.data["metrics"]["cuda_visibility_bound"] == 1.0
    assert result.data["gpu_device_count"] == 1
    assert result.cost["gpu_hours"] > 0.0
    execution_path = next(
        run_root / locator for locator in result.artifacts if locator.endswith("execution.json")
    )
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    assert execution["gpu_devices"][0]["name"] == "NVIDIA GeForce RTX 3090"
    assert execution["gpu_hours"] == pytest.approx(result.cost["gpu_hours"])
    assert execution["elapsed_seconds"] >= execution["gpu_allocation_seconds"]

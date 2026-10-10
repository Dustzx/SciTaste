#!/usr/bin/env python3
"""Package and execute one same-prefix MLRC Meta-Learning development fork.

Pure-stdlib launcher: bundle creation runs locally; ``run`` can execute the
same bundle in a dedicated Python 3.12 environment on the remote GPU host.
It never opens the official test split, retries a branch, or overwrites output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ACTIONS = ("euclidean-prototypes", "unit-normalized-prototypes")
REQUIRED_DATASETS_PER_ROLE = 10
PREDICTION_COUNT = 1000
CPU_SLOTS = 4
FORK_ROLE = "mlrc-meta-visual-fork-remote-execution-bundle"
CANDIDATE_ROLE = "mlrc-meta-agent-candidate-development-bundle"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("runtime bundle must not contain symbolic links")
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = _sha256(path)
    return hashes


def _data_tree_identity(root: Path) -> dict[str, int | str]:
    """Bind transferred image bytes, not only the development split names."""

    digest = hashlib.sha256()
    count = 0
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("development data tree must not contain symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(size).encode("ascii") + b"\0")
        digest.update(_sha256(path).encode("ascii") + b"\n")
        count += 1
        total_bytes += size
    if not count:
        raise ValueError("development data tree is empty")
    return {
        "sha256": digest.hexdigest(),
        "file_count": count,
        "payload_bytes": total_bytes,
    }


def _development_data(data_root: Path, split_sha256: str | None = None) -> dict:
    if not data_root.is_dir() or data_root.is_symlink():
        raise ValueError("development data root must be a real directory")
    splits_file = data_root / "info/meta_splits.txt"
    if not splits_file.is_file() or splits_file.is_symlink():
        raise ValueError("official development split file is missing")
    if split_sha256 is not None and _sha256(splits_file) != split_sha256:
        raise ValueError("development split bytes differ from the package")
    splits = json.loads(splits_file.read_text(encoding="utf-8"))
    if set(splits) != {"meta-train", "meta-test"}:
        raise ValueError("development data contains an unexpected split role")
    for role in ("meta-train", "meta-test"):
        names = splits[role]
        if (
            not isinstance(names, list)
            or len(names) != REQUIRED_DATASETS_PER_ROLE
            or len(set(names)) != len(names)
            or any(not isinstance(name, str) or not name for name in names)
        ):
            raise ValueError("development split has the wrong dataset population")
    names = set(splits["meta-train"]) | set(splits["meta-test"])
    if len(names) != 20 or "AWA" in names:
        raise ValueError("development data includes test-only or duplicate datasets")
    if {path.name for path in data_root.iterdir() if path.is_dir()} != names | {"info"}:
        raise ValueError("development data directory differs from the declared split")
    for name in names:
        if not (data_root / name / "labels.csv").is_file():
            raise ValueError(f"development dataset metadata missing: {name}")
    return {"split_sha256": _sha256(splits_file), "dataset_names": sorted(names)}


def package(
    *,
    frozen_root: Path,
    runtime_source: Path,
    data_root: Path,
    data_manifest: Path,
    requirements: Path,
    output_root: Path,
) -> Path:
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError("execution bundle must be new")
    frozen = json.loads((frozen_root / "MANIFEST.json").read_text(encoding="utf-8"))
    if frozen.get("role") != "visual-fork-development-qualification-prepared":
        raise ValueError("input is not the frozen visual-fork branch pair")
    if set(frozen["actions"]) != set(ACTIONS):
        raise ValueError("frozen visual-fork action population changed")
    for action in ACTIONS:
        observed = _file_hashes(frozen_root / "branches" / action)
        if observed != frozen["actions"][action]["method_files"]:
            raise ValueError(f"frozen branch bytes differ: {action}")
    data_receipt = json.loads(data_manifest.read_text(encoding="utf-8"))
    if (
        _sha256(data_manifest) != frozen["development_data_manifest_sha256"]
        or data_receipt.get("source_task_id") != "meta-learning"
        or data_receipt.get("heldout_opened") is not False
        or len(data_receipt.get("datasets", [])) != 20
    ):
        raise ValueError("development data manifest differs from the frozen fork")
    data_info = _development_data(data_root)
    data_tree = _data_tree_identity(data_root)
    if not (runtime_source / "cdmetadl").is_dir() or not (runtime_source / "api.py").is_file():
        raise ValueError("official MLRC runtime source is incomplete")
    if not requirements.is_file() or requirements.is_symlink():
        raise ValueError("remote environment lock is missing")
    output_root.mkdir(parents=True)
    runtime = output_root / "runtime"
    runtime.mkdir()
    shutil.copytree(
        runtime_source / "cdmetadl",
        runtime / "cdmetadl",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(runtime_source / "api.py", runtime / "api.py")
    branches = output_root / "branches"
    branches.mkdir()
    for action in ACTIONS:
        shutil.copytree(frozen_root / "branches" / action, branches / action)
    shutil.copy2(Path(__file__), output_root / "runner.py")
    shutil.copy2(requirements, output_root / "requirements.lock")
    files = _file_hashes(output_root)
    manifest = {
        "schema_version": "1.0",
        "role": "mlrc-meta-visual-fork-remote-execution-bundle",
        "frozen_branch_manifest_sha256": _sha256(frozen_root / "MANIFEST.json"),
        "development_data_manifest_sha256": _sha256(data_manifest),
        "development_split_sha256": data_info["split_sha256"],
        "development_data_tree": data_tree,
        "development_datasets": data_info["dataset_names"],
        "actions": list(ACTIONS),
        "prediction_count_per_action": PREDICTION_COUNT,
        "official_scorer_sha256": files["runtime/cdmetadl/scoring/scoring.py"],
        "files": files,
        "formal_evidence_eligible": False,
    }
    (output_root / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output_root


def _idle_gpu(index: int) -> dict:
    if index < 0:
        raise ValueError("GPU index must be nonnegative")
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    for line in result.stdout.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != 3:
            continue
        gpu, used, utilization = (int(value) for value in values)
        if gpu == index:
            if used >= 1024 or utilization >= 10:
                raise RuntimeError("selected remote GPU is occupied; no branch was launched")
            return {"index": gpu, "memory_used_mib": used, "utilization_percent": utilization}
    raise ValueError("selected GPU index is absent from the remote host")


def package_candidate(
    *, base_bundle: Path, method_source: Path, provenance: Path, output_root: Path
) -> Path:
    """Freeze an agent's complete method tree against the same official runtime.

    This is a submission interface, not a sandbox or proof of agent identity.
    Execution of generated code requires a separately isolated/admitted workspace.
    The baseline/fork bundle and running experiments are never modified.
    """
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError("candidate bundle must be new")
    if method_source.is_symlink() or not method_source.is_dir():
        raise ValueError("candidate method must be a real directory")
    if output_root.resolve().is_relative_to(method_source.resolve()):
        raise ValueError("candidate output must be outside the method source")
    base = json.loads((base_bundle / "MANIFEST.json").read_text())
    if base.get("role") != FORK_ROLE or _file_hashes(base_bundle) != {
        **base["files"],
        "MANIFEST.json": _sha256(base_bundle / "MANIFEST.json"),
    }:
        raise ValueError("base runtime differs from its frozen fork bundle")
    if provenance.is_symlink() or not provenance.is_file():
        raise ValueError("candidate provenance must be a regular JSON file")
    identity = json.loads(provenance.read_text())
    for field in ("system_id", "system_revision", "trajectory_sha256", "budget_contract_sha256"):
        if not isinstance(identity.get(field), str) or not identity[field].strip():
            raise ValueError(f"candidate provenance missing {field}")
    for field in ("trajectory_sha256", "budget_contract_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", identity[field]):
            raise ValueError(f"invalid candidate provenance digest: {field}")
    methods = _file_hashes(method_source)
    if "model.py" not in methods or any(
        name.endswith(".pyc") or "__pycache__" in Path(name).parts for name in methods
    ):
        raise ValueError("candidate needs model.py and must not contain Python caches")
    output_root.mkdir(parents=True)
    shutil.copytree(base_bundle / "runtime", output_root / "runtime")
    shutil.copy2(base_bundle / "requirements.lock", output_root / "requirements.lock")
    shutil.copytree(method_source, output_root / "branches" / "agent-candidate")
    shutil.copy2(provenance, output_root / "CANDIDATE_PROVENANCE.json")
    shutil.copy2(Path(__file__), output_root / "runner.py")
    if _file_hashes(output_root / "branches" / "agent-candidate") != methods:
        raise ValueError("candidate source changed during packaging")
    manifest = {
        **base,
        "role": CANDIDATE_ROLE,
        "actions": ["agent-candidate"],
        "base_execution_bundle_sha256": _sha256(base_bundle / "MANIFEST.json"),
        "candidate_provenance": identity,
        "agent_identity_verified": False,
        "formal_evidence_eligible": False,
        "files": _file_hashes(output_root),
    }
    manifest.pop("frozen_branch_manifest_sha256", None)
    (output_root / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return output_root


def cpu_bounded_command(command: list[str]) -> list[str]:
    """Restrict trusted scoring as well as untrusted candidate ingestion."""
    return [
        sys.executable,
        "-c",
        "import os,sys; "
        f"os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:{CPU_SLOTS}]); "
        "os.execv(sys.argv[1], sys.argv[1:])",
        *command,
    ]


def _run_logged(
    command: list[str], *, cwd: Path, env: dict[str, str], log: Path, timeout: float
) -> None:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    wall_timeout = False
    with log.open("xb") as stream:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            result = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            wall_timeout = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise TimeoutError("official MLRC branch exceeded its wall ceiling") from exc
        finally:
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            usage = {
                "wall_seconds": time.monotonic() - started,
                "wall_ceiling_seconds": timeout,
                "child_user_cpu_seconds": after.ru_utime - before.ru_utime,
                "child_system_cpu_seconds": after.ru_stime - before.ru_stime,
                "returncode": process.returncode,
                "wall_timeout_triggered": wall_timeout,
                "scope": "this wrapper and its reaped descendants; not host-wide usage",
            }
            with log.with_suffix(".resource.json").open("x") as receipt:
                json.dump(usage, receipt, indent=2, sort_keys=True)
    if result != 0:
        cpu_seconds = usage["child_user_cpu_seconds"] + usage["child_system_cpu_seconds"]
        raise RuntimeError(
            f"official MLRC command failed with exit code {result}; "
            f"recorded child CPU seconds={cpu_seconds:.2f}"
        )


def candidate_sandbox_command(
    command: list[str],
    *,
    bundle: Path,
    data_root: Path,
    output_root: Path,
    gpu_index: int,
    gpu_uuid: str,
    wall_seconds: int,
) -> list[str]:
    """Restrict generated methods to explicit mounts and one GPU device node.

    This development sandbox is not a held-out label firewall: the official
    development split is visible. No host home, credentials, other project
    directory, network namespace or other GPU device node is mounted.
    """
    bubblewrap = shutil.which("bwrap")
    if bubblewrap is None:
        raise RuntimeError("agent candidates require bubblewrap; no host-execution fallback")
    if gpu_index < 0 or not re.fullmatch(r"GPU-[A-Za-z0-9-]+", gpu_uuid):
        raise ValueError("candidate GPU identity is invalid")
    roots = [path.resolve(strict=True) for path in (bundle, data_root, output_root)]
    for index, root in enumerate(roots):
        if root == Path("/") or len(root.parts) < 4:
            raise ValueError("candidate mounts must be specific task directories")
        if any(root.is_relative_to(other) or other.is_relative_to(root) for other in roots[:index]):
            raise ValueError("candidate writable and read-only roots must be disjoint")
    arguments = [
        bubblewrap,
        "--die-with-parent",
        "--unshare-all",
        "--new-session",
        "--clearenv",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]
    # Bind only interpreter/runtime trees, never the containing user's home.
    system_roots = (
        Path("/usr"),
        Path("/bin"),
        Path("/lib"),
        Path("/lib64"),
        Path(sys.base_prefix),
        Path(sys.prefix),
    )
    mounted: set[str] = set()
    for path in system_roots:
        name = str(path)
        if name in mounted or not path.exists():
            continue
        if path == Path("/"):
            raise ValueError("interpreter runtime cannot require a root filesystem mount")
        arguments += ["--ro-bind", name, name]
        mounted.add(name)
    cache = Path("/etc/ld.so.cache")
    if cache.is_file():
        arguments += ["--ro-bind", str(cache), str(cache)]
    for root in roots[:2]:
        arguments += ["--ro-bind", str(root), str(root)]
    arguments += ["--bind", str(roots[2]), str(roots[2])]
    for node in (f"/dev/nvidia{gpu_index}", "/dev/nvidiactl", "/dev/nvidia-uvm"):
        if not Path(node).exists():
            raise ValueError(f"required selected GPU device node is missing: {node}")
        arguments += ["--dev-bind", node, node]
    optional = Path("/dev/nvidia-uvm-tools")
    if optional.exists():
        arguments += ["--dev-bind", str(optional), str(optional)]
    for name, value in {
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        "CUDA_VISIBLE_DEVICES": gpu_uuid,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(roots[0] / "runtime"),
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
        "MPLCONFIGDIR": "/tmp/matplotlib",
        "XDG_CACHE_HOME": "/tmp/cache",
    }.items():
        arguments += ["--setenv", name, value]
    # Restrict CPU affinity and individual output files without limiting CUDA's
    # large virtual address reservations. Wall timeout still kills the namespace.
    limits = (
        "import os,resource,sys;"
        f"os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:{CPU_SLOTS}]);"
        # RLIMIT_CPU sums all threads' CPU time; it is not elapsed wall time.
        f"resource.setrlimit(resource.RLIMIT_CPU,"
        f"({wall_seconds * CPU_SLOTS},{wall_seconds * CPU_SLOTS}));"
        "resource.setrlimit(resource.RLIMIT_FSIZE,(536870912,536870912));"
        "resource.setrlimit(resource.RLIMIT_CORE,(0,0));"
        "os.execv(sys.argv[1],sys.argv[1:])"
    )
    return [
        *arguments,
        "--chdir",
        str(roots[0] / "runtime"),
        sys.executable,
        "-c",
        limits,
        *command,
    ]


def _official_score(path: Path) -> float:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("official scorer produced an empty score file")
    label, separator, raw = lines[0].partition(":")
    if label != "overall_score" or not separator:
        raise ValueError("official scorer did not emit overall_score")
    score = float(raw.strip())
    # The upstream chance-normalized balanced accuracy can be negative.
    # For at least two ways its theoretical range is contained in [-1, 1].
    if not math.isfinite(score) or not -1 <= score <= 1:
        raise ValueError("official overall score is invalid")
    return score


def run_branch(
    *,
    bundle: Path,
    data_root: Path,
    action: str,
    gpu_index: int,
    output_root: Path,
    wall_seconds: int,
) -> Path:
    bundle = bundle.resolve(strict=True)
    data_root = data_root.resolve(strict=True)
    output_root = output_root.resolve(strict=False)
    if sys.version_info[:2] != (3, 12):
        raise ValueError("visual-fork execution requires Python 3.12")
    if action not in (*ACTIONS, "agent-candidate") or wall_seconds < 60:
        raise ValueError("invalid action or wall ceiling")
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError("branch output must be new and exclusive")
    manifest = json.loads((bundle / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("role") not in {FORK_ROLE, CANDIDATE_ROLE}:
        raise ValueError("invalid visual-fork execution bundle")
    expected_actions = ["agent-candidate"] if manifest["role"] == CANDIDATE_ROLE else list(ACTIONS)
    if manifest["actions"] != expected_actions or action not in expected_actions:
        raise ValueError("action differs from the frozen bundle population")
    if _file_hashes(bundle) != {
        **manifest["files"],
        "MANIFEST.json": _sha256(bundle / "MANIFEST.json"),
    }:
        raise ValueError("visual-fork execution bundle bytes changed")
    data_info = _development_data(data_root, manifest["development_split_sha256"])
    if data_info["dataset_names"] != manifest["development_datasets"]:
        raise ValueError("remote development dataset names differ")
    gpu = _idle_gpu(gpu_index)
    if _data_tree_identity(data_root) != manifest["development_data_tree"]:
        raise ValueError("remote development image bytes differ from the frozen bundle")
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str((bundle / "runtime").resolve(strict=True))
    imports = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import torch, torchvision, absl, pandas, sklearn, PIL, scipy, "
                "numpy, jinja2, matplotlib, seaborn; "
                "assert torch.cuda.is_available()"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    if imports.returncode != 0:
        raise RuntimeError("remote Python 3.12 GPU dependencies are unavailable")
    gpu = _idle_gpu(gpu_index)
    output_root.mkdir(parents=True)
    started = time.monotonic()
    attempt = {
        "schema_version": "1.0",
        "action": action,
        "gpu_at_launch": gpu,
        "bundle_manifest_sha256": _sha256(bundle / "MANIFEST.json"),
        "data_split_sha256": data_info["split_sha256"],
        "started_at_utc": datetime.now(UTC).isoformat(),
        "wall_ceiling_seconds": wall_seconds,
        "execution_isolation": (
            "bubblewrap-candidate" if manifest["role"] == CANDIDATE_ROLE else "trusted-frozen-fork"
        ),
        "convolution_backend": "torch-native-cudnn-disabled",
        "cpu_affinity_slots": CPU_SLOTS,
        "cpu_time_ceiling_seconds": wall_seconds * CPU_SLOTS,
        "status": "started",
    }
    (output_root / "ATTEMPT.json").write_text(
        json.dumps(attempt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    runtime = bundle / "runtime"
    ingestion = output_root / "ingestion_output"
    scoring = output_root / "scoring_output"
    try:
        ingestion_command = [
            sys.executable,
            "-c",
            "import runpy, torch; torch.backends.cudnn.enabled = False; "
            "runpy.run_module('cdmetadl.ingestion.ingestion', run_name='__main__')",
            "--seed=93",
            "--verbose=False",
            "--debug_mode=1",
            "--image_size=128",
            "--overwrite_previous_results=False",
            "--max_time=1000",
            f"--test_tasks_per_dataset={PREDICTION_COUNT // 10}",
            f"--input_data_dir={data_root.resolve(strict=True)}",
            f"--submission_dir={(bundle / 'branches' / action).resolve(strict=True)}",
            f"--output_dir_ingestion={ingestion}",
        ]
        if manifest["role"] == CANDIDATE_ROLE:
            gpu_uuid = subprocess.run(
                ["nvidia-smi", f"--id={gpu_index}", "--query-gpu=uuid", "--format=csv,noheader"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            ingestion_command = candidate_sandbox_command(
                ingestion_command,
                bundle=bundle,
                data_root=data_root,
                output_root=output_root,
                gpu_index=gpu_index,
                gpu_uuid=gpu_uuid,
                wall_seconds=wall_seconds,
            )
        _run_logged(
            ingestion_command,
            cwd=runtime,
            env=env,
            log=output_root / "ingestion.log",
            timeout=wall_seconds,
        )
        predictions = tuple(ingestion.glob("task_*.predict"))
        if manifest["role"] == CANDIDATE_ROLE and any(
            path.is_symlink() for path in output_root.rglob("*")
        ):
            raise ValueError("candidate output links cannot cross into host-owned scoring")
        if len(predictions) != PREDICTION_COUNT or not (ingestion / "metadata_ingestion").is_file():
            raise ValueError("official ingestion did not produce the full task population")
        remaining = wall_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("no scoring time remains inside the wall ceiling")
        scoring_env = env.copy()
        scoring_env["CUDA_VISIBLE_DEVICES"] = ""
        # The trusted scorer also needs a CPU bound: tensor libraries otherwise
        # create host-wide thread pools even after isolated ingestion finishes.
        for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            scoring_env[variable] = "4"
        _run_logged(
            cpu_bounded_command(
                [
                    sys.executable,
                    "-m",
                    "cdmetadl.scoring.scoring",
                    "--seed=93",
                    "--verbose=False",
                    "--debug_mode=1",
                    "--private_information=False",
                    "--overwrite_previous_results=False",
                    f"--test_tasks_per_dataset={PREDICTION_COUNT // 10}",
                    f"--input_data_dir={data_root.resolve(strict=True)}",
                    f"--results_dir={ingestion}",
                    f"--output_dir_scoring={scoring}",
                ]
            ),
            cwd=runtime,
            env=scoring_env,
            log=output_root / "scoring.log",
            timeout=remaining,
        )
        score_path = scoring / "scores.txt"
        score = _official_score(score_path)
        result = {
            **attempt,
            "status": "complete",
            "overall_score": score,
            "score_file_sha256": _sha256(score_path),
            "prediction_count": len(predictions),
            "elapsed_seconds": time.monotonic() - started,
            "scoring_cpu_limit": 4,
            "finished_at_utc": datetime.now(UTC).isoformat(),
        }
    except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
        result = {
            **attempt,
            "status": "failed",
            "failure_type": type(exc).__name__,
            "failure_summary": str(exc)[:300],
            "elapsed_seconds": time.monotonic() - started,
            "finished_at_utc": datetime.now(UTC).isoformat(),
        }
        (output_root / "RUN_RESULT.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise
    (output_root / "RUN_RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("package")
    pack.add_argument("--frozen-root", required=True, type=Path)
    pack.add_argument("--runtime-source", required=True, type=Path)
    pack.add_argument("--data-root", required=True, type=Path)
    pack.add_argument("--data-manifest", required=True, type=Path)
    pack.add_argument("--requirements", required=True, type=Path)
    pack.add_argument("--output-root", required=True, type=Path)
    candidate = commands.add_parser("package-candidate")
    candidate.add_argument("--base-bundle", required=True, type=Path)
    candidate.add_argument("--method-source", required=True, type=Path)
    candidate.add_argument("--provenance", required=True, type=Path)
    candidate.add_argument("--output-root", required=True, type=Path)
    run = commands.add_parser("run")
    run.add_argument("--bundle", required=True, type=Path)
    run.add_argument("--data-root", required=True, type=Path)
    run.add_argument("--action", required=True, choices=(*ACTIONS, "agent-candidate"))
    run.add_argument("--gpu-index", required=True, type=int)
    run.add_argument("--output-root", required=True, type=Path)
    run.add_argument("--wall-seconds", type=int, default=1200)
    args = parser.parse_args()
    if args.command == "package":
        result = package(
            frozen_root=args.frozen_root,
            runtime_source=args.runtime_source,
            data_root=args.data_root,
            data_manifest=args.data_manifest,
            requirements=args.requirements,
            output_root=args.output_root,
        )
    elif args.command == "package-candidate":
        result = package_candidate(
            base_bundle=args.base_bundle,
            method_source=args.method_source,
            provenance=args.provenance,
            output_root=args.output_root,
        )
    else:
        result = run_branch(
            bundle=args.bundle,
            data_root=args.data_root,
            action=args.action,
            gpu_index=args.gpu_index,
            output_root=args.output_root,
            wall_seconds=args.wall_seconds,
        )
    print(result)


if __name__ == "__main__":
    main()

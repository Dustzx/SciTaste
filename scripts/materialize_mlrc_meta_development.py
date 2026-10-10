"""Materialize only the official MLRC meta-learning development split.

The acquired AWA archive belongs to the later test split and is never opened.
This command performs local extraction only; it does not run a benchmark.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "outputs/projects/scitaste-self-development"
ACQUISITION = PROJECT / "evaluations/acquisitions/mlrc-first-preflight-assets-v1"
SOURCE_PREPARE = (
    PROJECT
    / "evaluations/acquisitions/mlrc-bench-source-v1/checkout"
    / "MLAgentBench/benchmarks_base/meta-learning/scripts/prepare.py"
)
POLICY = ROOT / "configs/evaluation/acquisition/mlrc_first_preflight_license_policy_v1.yaml"
DESTINATION = PROJECT / "evaluations/materializations/mlrc-meta-learning-development-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _official_development_sets() -> tuple[dict[str, int], dict[str, int]]:
    tree = ast.parse(SOURCE_PREPARE.read_text(encoding="utf-8"))
    assignments: dict[str, dict[str, int]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in {"set_0", "set_1", "set_2"}:
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict) or not all(
                isinstance(key, str) and isinstance(item, int) for key, item in value.items()
            ):
                raise ValueError(f"invalid official {target.id} mapping")
            assignments[target.id] = value
    if set(assignments) != {"set_0", "set_1", "set_2"}:
        raise ValueError("official meta-learning split declarations changed")
    if len(assignments["set_0"]) != 10 or len(assignments["set_1"]) != 10:
        raise ValueError("official development split is no longer 10+10 datasets")
    if "AWA" in assignments["set_0"] or "AWA" in assignments["set_1"]:
        raise ValueError("AWA entered the development split")
    if "AWA" not in assignments["set_2"]:
        raise ValueError("AWA test-split identity changed")
    return assignments["set_0"], assignments["set_1"]


def _extract_archive(archive_path: Path, target: Path, expected: dict) -> tuple[int, int]:
    count = 0
    expanded = 0
    dataset_name = archive_path.name.removesuffix(".zip")
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) != expected["member_count"]:
            raise ValueError(f"archive member count changed: {archive_path.name}")
        seen: set[str] = set()
        for info in infos:
            pure = PurePosixPath(info.filename)
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or "\\" in info.filename
                or not pure.parts
                or pure.parts[0] != dataset_name
                or info.filename in seen
                or stat.S_ISLNK(info.external_attr >> 16)
            ):
                raise ValueError(f"unsafe archive member: {info.filename}")
            seen.add(info.filename)
            if info.is_dir():
                continue
            if len(pure.parts) != 2 and not (len(pure.parts) == 3 and pure.parts[1] == "images"):
                raise ValueError(f"unexpected dataset layout: {info.filename}")
            if len(pure.parts) == 2 and pure.parts[1] not in {"info.json", "labels.csv"}:
                raise ValueError(f"unexpected dataset metadata: {info.filename}")
            destination = target.joinpath(*pure.parts[1:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("xb") as sink:
                shutil.copyfileobj(source, sink, length=1024 * 1024)
            if destination.stat().st_size != info.file_size:
                raise ValueError(f"archive member size changed: {info.filename}")
            count += 1
            expanded += info.file_size
        if not (target / "info.json").is_file() or not (target / "labels.csv").is_file():
            raise ValueError(f"dataset metadata missing: {dataset_name}")
        if not (target / "images").is_dir():
            raise ValueError(f"dataset images missing: {dataset_name}")
    if expanded != expected["expanded_bytes"]:
        raise ValueError(f"archive expanded bytes differ from qualification: {archive_path.name}")
    return count, expanded


def materialize() -> Path:
    set_0, set_1 = _official_development_sets()
    receipt = json.loads((ACQUISITION / "RECEIPT.json").read_text(encoding="utf-8"))
    qualification = json.loads(
        (ACQUISITION / "ARCHIVE_QUALIFICATION.json").read_text(encoding="utf-8")
    )
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    if qualification["receipt_sha256"] != receipt["receipt_sha256"]:
        raise ValueError("archive qualification belongs to another acquisition")
    if DESTINATION.exists() or DESTINATION.is_symlink():
        raise FileExistsError(DESTINATION)
    source_root = ROOT / receipt["destination_root"]
    if source_root.resolve(strict=True) != (ACQUISITION / "raw").resolve(strict=True):
        raise ValueError("acquired source root changed")
    acquired = {item["asset_id"]: item for item in receipt["assets"]}
    qualified = {item["asset_id"]: item for item in qualification["assets"]}
    bindings = {item["asset_id"]: item for item in policy["asset_bindings"]}
    profiles = {item["profile_id"]: item for item in policy["profiles"]}
    if shutil.disk_usage(DESTINATION.parent).free < 2 * 1024**3:
        raise ValueError("less than 2 GiB free for development materialization")
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".mlrc-meta-development-", dir=DESTINATION.parent))
    try:
        data = staging / "data"
        data.mkdir()
        manifest: list[dict] = []
        for split_name, mapping in (("set_0", set_0), ("set_1", set_1)):
            for name, dataset_id in mapping.items():
                asset_id = f"meta-{dataset_id}-{name.lower().replace('_', '-')}-mini"
                item = acquired[asset_id]
                checked = qualified[asset_id]
                binding = bindings[asset_id]
                profile = profiles[binding["profile_id"]]
                if (
                    item["task_id"] != "meta-learning"
                    or checked["task_id"] != "meta-learning"
                    or not checked["safe"]
                    or profile["ingestion_status"] != "verified"
                ):
                    raise ValueError(f"unqualified development asset: {asset_id}")
                archive = source_root / item["destination"]
                if not archive.resolve(strict=True).is_relative_to(
                    source_root.resolve(strict=True)
                ):
                    raise ValueError(f"archive escaped acquired root: {asset_id}")
                if archive.is_symlink() or archive.stat().st_size != item["size_bytes"]:
                    raise ValueError(f"archive bytes changed: {asset_id}")
                observed_hash = _sha256(archive)
                if observed_hash != item["sha256"]:
                    raise ValueError(f"archive hash changed: {asset_id}")
                count, size = _extract_archive(archive, data / name, checked)
                manifest.append(
                    {
                        "set": split_name,
                        "dataset": name,
                        "asset_id": asset_id,
                        "archive_sha256": observed_hash,
                        "file_count": count,
                        "expanded_bytes": size,
                    }
                )
        info = data / "info"
        info.mkdir()
        (info / "meta_splits.txt").write_text(
            json.dumps({"meta-train": list(set_0), "meta-test": list(set_1)}, indent=4) + "\n",
            encoding="utf-8",
        )
        (staging / "MANIFEST.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "role": "consumed-development-only",
                    "source_task_id": "meta-learning",
                    "official_prepare_sha256": _sha256(SOURCE_PREPARE),
                    "acquisition_receipt_sha256": receipt["receipt_sha256"],
                    "archive_qualification_sha256": qualification["report_sha256"],
                    "license_policy_sha256": _sha256(POLICY),
                    "heldout_opened": False,
                    "excluded_test_datasets": list(_official_test_set()),
                    "datasets": manifest,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.rename(staging, DESTINATION)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return DESTINATION


def _official_test_set() -> dict[str, int]:
    tree = ast.parse(SOURCE_PREPARE.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "set_2"
        ):
            return ast.literal_eval(node.value)
    raise ValueError("official test split missing")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="extract local development archives")
    args = parser.parse_args()
    if not args.execute:
        parser.error("explicit --execute is required for local extraction")
    print(materialize())

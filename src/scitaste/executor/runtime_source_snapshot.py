"""Preserve contract-bound Native source bytes without claiming environment replay."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from scitaste.model_nodes.session_exchange import retain_json


def retain_bound_sources(run: Path, *, before_first_action: bool = False) -> dict:
    """Capture only exact contract matches; never reconstruct missing versions."""
    run = run.resolve(strict=True)
    contract_path = run / "CONTRACT.json"
    contract = json.loads(contract_path.read_text())
    if before_first_action:
        if (run / "loop/TRAJECTORY.jsonl").exists():
            raise ValueError("Launch snapshot must precede the first research action")
    elif not (run / "RESULT.json").is_file():
        raise ValueError("Retrospective capture requires terminal research, not a live mutation")
    package = Path(__file__).resolve().parent.parent
    sources = {}
    for name, expected in contract["source_sha256"].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Bound runtime source escapes the package")
        path = package.joinpath(*relative.parts).resolve(strict=True)
        path.relative_to(package)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Current source no longer matches launch binding: {name}")
        sources[name] = raw
    # Validate all preimages before creating a snapshot. Existing exact copies are
    # idempotent; differing evidence is never overwritten.
    directory = run / "runtime-source-snapshot"
    if directory.is_symlink():
        raise ValueError("Retained source directory cannot be a symlink")
    for name, raw in sources.items():
        target = directory / name
        if target.is_symlink():
            raise ValueError("Retained source file cannot be a symlink")
        target.parent.resolve().relative_to(directory.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(raw)
        except FileExistsError:
            if target.read_bytes() != raw:
                raise ValueError(f"Retained runtime source differs: {name}") from None
    manifest = {
        "schema_version": "1.0",
        "scope": "exact-contract-bound-module-bytes-not-full-environment-replay",
        "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        "capture_timing": "before-first-action" if before_first_action else "after-terminal",
        "source_sha256": contract["source_sha256"],
        "source_count": len(sources),
        "missing_versions_reconstructed": False,
        "research_results_changed": False,
    }
    retain_json(directory / "MANIFEST.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True, type=Path)
    args = parser.parse_args()
    result = retain_bound_sources(args.source_run)
    print(json.dumps({"source_count": result["source_count"], "scope": result["scope"]}))


if __name__ == "__main__":
    main()

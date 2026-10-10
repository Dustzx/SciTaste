"""Supervise prepared-source qualification to a separately frozen Taste successor.

Discovery/acquisition must have been selected and bound under existing permissions.
This worker never invents a URL, invokes a paid API, admits a raw observation, or
mutates an active research library. Actual model/reviewer suppliers service the
retained requests; absence or rejection is preserved rather than bypassed.
"""

import argparse
import fcntl
import json
import subprocess
import sys
import time
from pathlib import Path

from scitaste.benchmark.open_research import digest
from scitaste.model_nodes.session_exchange import retain_json
from scitaste.taste.reference_quality import ReferenceQualityInput
from scitaste.taste.reviewed_library import reviewed_development_cases


def read_bound(project, binding):
    path = (project / binding["locator"]).resolve(strict=True)
    path.relative_to(project)
    if digest(path) != binding["sha256"]:
        raise ValueError("Source-maintenance binding changed")
    return path


def run(
    *,
    project,
    prepared_source,
    base_library,
    output,
    code_root,
    wall_seconds=3600,
    quality_session_reuse_from=None,
    continue_from=None,
):
    project = project.resolve(strict=True)
    prepared, base, output = (
        prepared_source.resolve(strict=True),
        base_library.resolve(strict=True),
        output.resolve(),
    )
    code_root = code_root.resolve(strict=True)
    if Path.cwd().resolve() != code_root:
        raise ValueError("Run the repository-backed maintenance worker from its code root")
    for path in (prepared, base, output):
        path.relative_to(project / "evaluations")
    if not 600 <= wall_seconds <= 14400:
        raise ValueError("Source maintenance requires a bounded original allocation")
    source = ReferenceQualityInput.model_validate_json((prepared / "INPUT.json").read_bytes())

    def binding(path):
        return {"locator": path.relative_to(project).as_posix(), "sha256": digest(path)}

    contract = {
        "prepared_input": binding(prepared / "INPUT.json"),
        "prepared_profile": binding(prepared / "PROFILE.json"),
        "prepared_manifest": binding(prepared / "SOURCE_MANIFEST.json"),
        "base_library": binding(base / "TASTE_LIBRARY.jsonl"),
        "base_manifest": binding(base / "MANIFEST.json"),
        "wall_seconds": wall_seconds,
        "source_id": source.source_id,
        "api_calls_enabled": False,
        "active_library_modified": False,
        "activation_authorized": False,
        "formal_evidence_eligible": False,
    }
    if quality_session_reuse_from is not None:
        previous = quality_session_reuse_from.resolve(strict=True)
        previous.relative_to(project / "evaluations")
        contract["reused_quality_result"] = binding(previous / "RESULT.json")
    parent = None
    inherited_deadline = None
    if continue_from is not None:
        if quality_session_reuse_from is not None:
            raise ValueError("Choose parent continuation or quality-only recovery")
        parent = continue_from.resolve(strict=True)
        parent.relative_to(project / "evaluations")
        prior = json.loads((parent / "CONTRACT.json").read_text())
        failure = json.loads((parent / "abstraction/RESULT.json").read_text())
        qualified = json.loads((parent / "quality/RESULT.json").read_text())
        if (
            parent == output
            or prior.get("continued_source")
            or any(prior[key] != contract[key] for key in contract)
            or not qualified["source_qualified"]
            or failure["receipt"]["outcome"] != "rejected"
            or failure["receipt"]["result"]["rejection_reasons"]
            != ["project revision changed while the model-node backend was running"]
        ):
            raise ValueError("Continuation needs unchanged source and metadata-only rejection")
        inherited_deadline = json.loads((parent / "START.json").read_text())["deadline_unix"]
        contract["continued_source"] = {
            "contract": binding(parent / "CONTRACT.json"),
            "original_failure": binding(parent / "RESULT.json"),
            "quality": binding(parent / "quality/RESULT.json"),
            "abstraction": binding(parent / "abstraction/RESULT.json"),
            "original_deadline_unix": inherited_deadline,
            "new_scientific_model_responses": 0,
        }
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        retain_json(output / "CONTRACT.json", contract)
        launch = output / "START.json"
        if not launch.exists():
            retain_json(
                launch,
                {"deadline_unix": inherited_deadline or time.time() + wall_seconds},
            )
        deadline = json.loads(launch.read_text())["deadline_unix"]
        for key in (
            "prepared_input",
            "prepared_profile",
            "prepared_manifest",
            "base_library",
            "base_manifest",
        ):
            read_bound(project, contract[key])
        if "reused_quality_result" in contract:
            read_bound(project, contract["reused_quality_result"])
        if (output / "RESULT.json").exists():
            result = json.loads((output / "RESULT.json").read_text())
            for key in ("successor", "successor_manifest"):
                if key in result:
                    read_bound(project, result[key])
            for receipt in result.get("reused_phase_receipts", []):
                read_bound(project, receipt)
            return result

        observations = {"new_phase_invocations": 0, "reused_phase_receipts": []}

        def finish(status, **extra):
            result = {
                "status": status,
                "source_id": source.source_id,
                "active_library_modified": False,
                "activation_authorized": False,
                "formal_evidence_eligible": False,
                **observations,
                **extra,
            }
            retain_json(output / "RESULT.json", result)
            return result

        def phase(name, extra=()):
            directory = output / name
            result_path = directory / "RESULT.json"
            if result_path.exists():
                result = json.loads(result_path.read_text())
                if result["input_sha256"] != contract["prepared_input"]["sha256"]:
                    raise ValueError("Source phase belongs to a different input")
                node_input = result["receipt"]["result"]["request"]["input_payload"]["input"]
                if name == "quality" and ReferenceQualityInput.model_validate(node_input) != source:
                    raise ValueError("Retained quality receipt assessed a different source")
                observations["reused_phase_receipts"].append(binding(result_path))
                return result
            if parent is not None and name == "quality":
                import shutil

                original = parent / "quality/RESULT.json"
                directory.mkdir()
                shutil.copy2(original, result_path)
                observations["reused_phase_receipts"].append(binding(original))
                return json.loads(original.read_text())
            if parent is not None and name == "abstraction":
                extra = (*extra, "--reuse-session-from", str(parent / "abstraction"))
            started = output / f"{name}.started.json"
            if started.exists():
                # Do not duplicate an ambiguous model execution after interruption.
                raise ValueError(
                    "Prior source phase has no terminal receipt; inspect it before recovery"
                )
            if time.time() >= deadline:
                raise TimeoutError("Original maintenance deadline reached")
            command = [
                sys.executable,
                "-m",
                "scripts.run_reference_quality_session",
                "--project",
                str(project),
                "--input",
                str(prepared / "INPUT.json"),
                "--profile",
                str(prepared / "PROFILE.json"),
                "--output",
                str(directory),
                *extra,
            ]
            retain_json(
                started,
                {"command": command, "started_unix": time.time(), "automatic_model_retry": False},
            )
            with (output / f"{name}.log").open("x") as log:
                observations["new_phase_invocations"] += 1
                process = subprocess.Popen(
                    command, cwd=code_root, stdout=log, stderr=subprocess.STDOUT
                )
                try:
                    code = process.wait(timeout=max(0.01, deadline - time.time()))
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise TimeoutError("Owned source phase exceeded original allocation") from None
            if code != 0 or not result_path.exists():
                raise RuntimeError("Source phase stopped; retained log, no automatic rerun")
            result = json.loads(result_path.read_text())
            if result["input_sha256"] != contract["prepared_input"]["sha256"]:
                raise ValueError("Source phase belongs to a different input")
            return result

        try:
            quality = phase(
                "quality",
                ("--reuse-session-from", str(quality_session_reuse_from))
                if quality_session_reuse_from is not None
                else (),
            )
            if not quality["source_qualified"]:
                return finish("source-not-qualified", library_admitted=False)
            abstraction = phase(
                "abstraction", ("--abstract-after-quality", str(output / "quality/RESULT.json"))
            )
            if not abstraction["abstraction_produced"]:
                return finish("abstraction-not-admitted", library_admitted=False)
            # Existing reviewer compiler/importer owns identities, grounding and disputes.
            from scripts.review_grounded_source_session import finish as review_finish
            from scripts.review_grounded_source_session import prepare as review_prepare

            review = output / "independent-review"
            if not (review / "PROTOCOL.json").exists():
                review_prepare(project, output / "abstraction/RUNTIME_RECEIPT.json", review)
            while True:
                if (review / "FINAL.json").exists():
                    final = json.loads((review / "FINAL.json").read_text())
                    # Accepted chains are independently reverified below. Never
                    # re-finalize a sealed review with a new timestamp/identity.
                    if not final["accepted"]:
                        return finish("independent-review-rejected", library_admitted=False)
                    break
                if time.time() >= deadline:
                    return finish("review-response-missing-at-deadline", library_admitted=False)
                paths = [
                    review / f"{role}-{suffix}.json"
                    for role in ("primary-a", "primary-b")
                    for suffix in ("response", "observation")
                ]
                if all(path.is_file() for path in paths):
                    roles = ["primary-a", "primary-b"]
                    if all(
                        (review / f"adjudicator-{suffix}.json").exists()
                        for suffix in ("response", "observation")
                    ):
                        roles.append("adjudicator")
                    metadata = {}
                    for role in roles:
                        observed = json.loads((review / f"{role}-observation.json").read_text())
                        metadata[role] = {
                            key: observed[key]
                            for key in ("session_id", "started_at", "completed_at")
                        }
                    # Distinct immutable metadata versions permit actual adjudication arrival.
                    meta_path = review / (
                        "SESSION_ADJUDICATION.json"
                        if "adjudicator" in metadata
                        else "SESSION_METADATA.json"
                    )
                    retain_json(meta_path, metadata)
                    status = review_finish(project, review, meta_path)
                    if status["status"] == "reviewed":
                        if not status["accepted"]:
                            return finish("independent-review-rejected", library_admitted=False)
                        break
                time.sleep(min(5, max(0.01, deadline - time.time())))
            cases = reviewed_development_cases(
                evidence_root=code_root,
                outputs_root=project.parent.parent,
                accepted_set=review / "FINAL.json",
                quality_result=output / "quality/RESULT.json",
            )
            # Recheck every old case through its original quality/independent-review bindings.
            old_manifest = json.loads((base / "MANIFEST.json").read_text())
            old_cases = []
            for item in old_manifest["source_bindings"]:
                accepted, old_quality = (
                    code_root / item["accepted_set"],
                    code_root / item["quality_result"],
                )
                if (
                    digest(accepted) != item["accepted_set_sha256"]
                    or digest(old_quality) != item["quality_result_sha256"]
                ):
                    raise ValueError("Base source review changed")
                old_cases.extend(
                    reviewed_development_cases(
                        evidence_root=code_root,
                        outputs_root=project.parent.parent,
                        accepted_set=accepted,
                        quality_result=old_quality,
                    )
                )
            prior = "".join(case.model_dump_json() + "\n" for case in old_cases).encode()
            if prior != (base / "TASTE_LIBRARY.jsonl").read_bytes():
                raise ValueError("Base library differs from reviewed source material")
            combined = [*old_cases, *cases]
            if len({case.case_id for case in combined}) != len(combined):
                raise ValueError("Repeated case is not new source coverage")
            successor = output / "successor"
            successor.mkdir(exist_ok=True)
            library_path = successor / "TASTE_LIBRARY.jsonl"
            raw = "".join(case.model_dump_json() + "\n" for case in combined).encode()
            if library_path.exists():
                if library_path.read_bytes() != raw:
                    raise ValueError("Successor library changed")
            else:
                with library_path.open("xb") as stream:
                    stream.write(raw)
            import hashlib

            manifest = {
                "schema_version": "1.0",
                "case_count": len(combined),
                "library_sha256": hashlib.sha256(raw).hexdigest(),
                "source_bindings": [
                    *old_manifest["source_bindings"],
                    {
                        "accepted_set": (review / "FINAL.json").relative_to(code_root).as_posix(),
                        "accepted_set_sha256": digest(review / "FINAL.json"),
                        "quality_result": (output / "quality/RESULT.json")
                        .relative_to(code_root)
                        .as_posix(),
                        "quality_result_sha256": digest(output / "quality/RESULT.json"),
                    },
                ],
                "source_independence_established": False,
                "human_verified": False,
                "formal_evidence_eligible": False,
                "scientific_effectiveness_demonstrated": False,
            }
            retain_json(successor / "MANIFEST.json", manifest)
            return finish(
                "reviewed-successor-prepared",
                library_admitted=True,
                successor=binding(library_path),
                successor_manifest=binding(successor / "MANIFEST.json"),
                automatically_activated=False,
            )
        except Exception as exc:
            return finish(
                "maintenance-interrupted",
                error_type=type(exc).__name__,
                detail=str(exc),
                library_admitted=False,
                automatic_retry=False,
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "prepared-source", "base-library", "output", "code-root"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--wall-seconds", type=int, default=3600)
    parser.add_argument("--quality-session-reuse-from", type=Path)
    parser.add_argument(
        "--continue-from",
        type=Path,
        help="Revalidate unchanged advice after metadata-only rejection within original deadline",
    )
    print(json.dumps(run(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()

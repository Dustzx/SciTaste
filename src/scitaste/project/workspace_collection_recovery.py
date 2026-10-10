"""Recover only derived experience collection, never research execution or credit."""

import fcntl
import hashlib
import json
import os

from scitaste.taste.collect_experience import collect


def ensure_workspace_collection(project, execution):
    project, execution = project.resolve(strict=True), execution.resolve(strict=True)
    execution.relative_to(project)
    original = execution / "experience/COLLECTION.json"
    recovery = execution / "experience-recovery"
    recovered = recovery / "COLLECTION.json"
    recovery.mkdir(exist_ok=True)
    with (recovery / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        existing = [p for p in (original, recovered) if p.exists()]
        if len(existing) > 1:
            raise ValueError("Ambiguous original and recovered experience collections")
        if existing:
            if json.loads(existing[0].read_text())["source_run_id"] != execution.name:
                raise ValueError("Experience collection belongs to another execution")
            return existing[0]
        result = execution / "RESULT.json"
        if json.loads(result.read_text())["controller_owner"] != "scitaste-native":
            raise ValueError("Only recorded Native execution can recover collection")
        plan = execution / "TASTE_SAMPLING_PLAN.json"
        binding = {
            "sampling_plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
            "execution_result_sha256": hashlib.sha256(result.read_bytes()).hexdigest(),
        }
        # Partial attempts are preserved. One call makes at most one new attempt;
        # three interrupted attempts require diagnosis rather than an endless loop.
        for index in range(1, 4):
            attempt = recovery / f"attempt-{index:02d}"
            inputs = recovery / f"attempt-{index:02d}.inputs.json"
            if inputs.exists():
                if json.loads(inputs.read_text()) != binding:
                    raise ValueError("Collection recovery inputs changed")
            else:
                if attempt.exists():
                    raise ValueError("Unbound collection recovery attempt")
                with inputs.open("x") as stream:
                    json.dump(binding, stream, indent=2)
            receipt = attempt / "COLLECTION.json"
            if receipt.is_file():
                break
            if attempt.exists():
                continue
            collect(plan, project.parent.parent, attempt, all_actions=True)
            break
        else:
            raise ValueError("Collection recovery attempts exhausted; inspect retained failures")
        payload = json.loads(receipt.read_text())
        if payload["source_run_id"] != execution.name:
            raise ValueError("Recovered collection belongs to another execution")
        # Atomic no-overwrite publication. Candidate paths remain in the preserved
        # attempt; no partial files or original captures are moved or rewritten.
        os.link(receipt, recovered)
        return recovered

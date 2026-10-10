#!/usr/bin/env python3
"""Collect an existing remote MLRC pair and register its real project status.

This command observes one job; it never starts, retries, or stops GPU work.
Completed outcomes pass through the frozen decision scorer before publication.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from scitaste.project import ProjectRuntime
from scitaste.project.models import ProjectRun, validate_entry_id

if __package__:
    from .score_mlrc_meta_decision import score
else:
    from score_mlrc_meta_decision import score


def remote_observation(host: str, remote_root: str, env: dict[str, str]) -> dict:
    """Read state and verify that an active PID belongs to this exact queue."""
    program = """
import json
from pathlib import Path
root = Path(REMOTE_ROOT)
state_path = root / 'STATE.json'
state = json.loads(state_path.read_text())
pid = state['pid']
if not isinstance(pid, int) or pid <= 0:
    raise ValueError('invalid queue PID')
try:
    command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\\0')
    alive = (str(root).encode() in command and
             any(part.endswith(b'/run_mlrc_meta_remote_pair.py') for part in command))
except FileNotFoundError:
    alive = False
if not alive:
    state = json.loads(state_path.read_text())
cancellation_path = root / 'CANCELLED.json'
cancellation = json.loads(cancellation_path.read_text()) if cancellation_path.exists() else None
print(json.dumps({'state': state, 'process_alive': alive, 'cancellation': cancellation}))
""".replace("REMOTE_ROOT", repr(remote_root))
    response = subprocess.run(
        [
            "ssh",
            "-T",
            "-o",
            "PreferredAuthentications=password",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "ConnectTimeout=8",
            host,
            "python3 -c " + shlex.quote(program),
        ],
        env=env,
        start_new_session=True,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    observation = json.loads(response.stdout)
    observation["observed_at_utc"] = datetime.now(UTC).isoformat()
    observation["host"] = host
    observation["remote_root"] = remote_root
    return observation


def project_status(observation: dict) -> str:
    cancellation = observation.get("cancellation")
    if cancellation is not None:
        if (
            observation["process_alive"]
            or cancellation.get("status") != "cancelled"
            or cancellation.get("pid") != observation["state"]["pid"]
            or cancellation.get("completed_actions") != observation["state"]["completed_actions"]
        ):
            raise ValueError("cancellation receipt conflicts with observed queue")
        return "cancelled"
    status = observation["state"]["status"]
    if status == "complete":
        return "completed"
    if status in {"failed", "wait-expired"}:
        return "failed" if status == "failed" else "blocked-resource"
    if status not in {"waiting-for-gpu", "running"}:
        raise ValueError("unknown remote queue state")
    if not observation["process_alive"]:
        return "interrupted"
    return "queued" if status == "waiting-for-gpu" else "running"


def collect(
    *,
    outputs: Path,
    project_id: str,
    run_id: str,
    host: str,
    remote_root: str,
    local_evaluation_id: str,
    decisions: Path,
    decision_bundle: Path,
    execution_bundle: Path,
    credentials: Path,
    credential_name: str,
) -> dict:
    validate_entry_id(local_evaluation_id, field_name="local evaluation")
    validate_entry_id(run_id, field_name="run")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", host):
        raise ValueError("SSH host must be a configured host alias")
    remote = PurePosixPath(remote_root)
    if not remote.is_absolute() or ".." in remote.parts or len(remote.parts) < 5:
        raise ValueError("remote queue root must be a specific absolute task directory")
    runtime = ProjectRuntime(outputs)
    snapshot = runtime.open(project_id)
    project = runtime.projects_root / project_id
    local = project / "evaluations" / local_evaluation_id
    for path in (decisions, decision_bundle, execution_bundle):
        if not path.resolve(strict=True).is_relative_to(project):
            raise ValueError("decision and bundle inputs must belong to the project")
    env = os.environ.copy()
    env.update(
        {
            "SCITASTE_ASKPASS_CREDENTIAL_FILE": str(credentials.resolve(strict=True)),
            "SCITASTE_ASKPASS_CREDENTIAL_NAME": credential_name,
            "SSH_ASKPASS": str(
                Path(__file__).with_name("ssh_askpass_resource_registry.py").resolve()
            ),
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": ":0",
        }
    )
    observation = remote_observation(host, str(remote), env)
    status = project_status(observation)
    local.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "rsync",
            "-rt",
            "--safe-links",
            "-e",
            "ssh -T -o PreferredAuthentications=password -o PubkeyAuthentication=no "
            "-o ClearAllForwardings=yes -o ConnectTimeout=8",
            f"{host}:{shlex.quote(str(remote))}/",
            str(local) + "/",
        ],
        env=env,
        start_new_session=True,
        check=True,
        timeout=180,
    )
    score_path = local / "DECISION_RESULT.json"
    result = None
    if status == "completed":
        if score_path.exists():
            # Revalidate against the current exact receipts, without replacing
            # the published result or charging any experiment/model budget.
            result = score(decisions, decision_bundle, execution_bundle, local, None)
            if json.loads(score_path.read_text()) != result:
                raise ValueError("completed evidence changed after result publication")
        else:
            result = score(decisions, decision_bundle, execution_bundle, local, score_path)
    stage = project / "runs" / run_id / "experiment"
    artifact = f"runs/{run_id}/experiment/RESULT.json"
    entries = {item.run_id: item for item in snapshot.manifest.runs}
    if run_id not in entries:
        snapshot = runtime.begin_run(
            project_id,
            ProjectRun(
                run_id=run_id,
                provider="bailian",
                model="qwen3.7-max-2026-06-08",
                condition="independent-image-decision-policies",
                seed=98,
                status=status,
                evidence_scope="development-instrument-qualification; one source research task",
                stage_path="experiment",
                artifact=artifact,
                remote_host=host,
                remote_queue_root=str(remote),
                remote_queue_pid=observation["state"]["pid"],
                formal_evidence_eligible=False,
            ),
            expected_revision=snapshot.manifest.revision,
        )
    else:
        existing = entries[run_id]
        if getattr(existing, "remote_host", None) != host or getattr(
            existing, "remote_queue_root", None
        ) != str(remote):
            raise ValueError("registered run belongs to a different remote queue")
        if existing.status != status:
            snapshot = runtime.update_run(
                project_id,
                run_id,
                expected_revision=snapshot.manifest.revision,
                status=status,
            )
    stage.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "observation": observation,
        "evaluation_locator": str(local.relative_to(project)),
        "decision_result_locator": str(score_path.relative_to(project)) if result else None,
        "formal_evidence_eligible": False,
        "research_task_count": 1,
        "gpu_experiments_completed": len(observation["state"]["completed_actions"]),
        "raw_official_scores": result["raw_official_scores"] if result else None,
    }
    temporary = stage / "RESULT.pending"
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(stage / "RESULT.json")
    return {
        "project_revision": snapshot.manifest.revision,
        "run_id": run_id,
        "status": status,
        "gpu_experiments_completed": payload["gpu_experiments_completed"],
        "artifact": artifact,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--remote-root", required=True)
    parser.add_argument("--local-evaluation-id", required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--decision-bundle", type=Path, required=True)
    parser.add_argument("--execution-bundle", type=Path, required=True)
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--credential-name", default="SCITASTE_GPU_3090_2_SSH_PASSWORD")
    args = parser.parse_args()
    print(
        json.dumps(
            collect(
                outputs=args.outputs_root,
                project_id=args.project_id,
                run_id=args.run_id,
                host=args.host,
                remote_root=args.remote_root,
                local_evaluation_id=args.local_evaluation_id,
                decisions=args.decisions,
                decision_bundle=args.decision_bundle,
                execution_bundle=args.execution_bundle,
                credentials=args.credentials_file,
                credential_name=args.credential_name,
            ),
            sort_keys=True,
        )
    )

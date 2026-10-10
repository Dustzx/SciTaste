"""Native action handler for explicitly bound remote MLRC development candidates.

The existing SciTasteNativeExecutor supplies the ResearchExecutor interface.
This handler never selects a research action, retries a launch, or treats an
imported historical outcome as a newly executed native experiment.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.project.models import content_sha256
from scitaste.schema.actions import MetaAction, ResearchAction
from scitaste.state.research_state import ResearchState


@dataclass(frozen=True)
class RemoteMLRCBinding:
    candidate_id: str
    host: str
    python: str
    bundle: str
    bundle_manifest_sha256: str
    data_root: str
    output_root: str
    gpu_index: int
    action: str = "agent-candidate"
    wall_seconds: int = 1200
    observation_only: bool = False

    def __post_init__(self) -> None:
        for value in (self.candidate_id, self.host):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
                raise ValueError("candidate and SSH alias require safe identifiers")
        if not re.fullmatch(r"[a-f0-9]{64}", self.bundle_manifest_sha256):
            raise ValueError("remote candidate needs an exact bundle commitment")
        for value in (self.python, self.bundle, self.data_root, self.output_root):
            path = PurePosixPath(value)
            if not path.is_absolute() or ".." in path.parts or len(path.parts) < 4:
                raise ValueError("remote paths must be explicit task-owned paths")
        if self.gpu_index < 0 or not 60 <= self.wall_seconds <= 7200:
            raise ValueError("invalid remote experiment limits")
        if self.action not in {
            "agent-candidate",
            "euclidean-prototypes",
            "unit-normalized-prototypes",
        }:
            raise ValueError("unsupported registered MLRC action")
        if not self.observation_only and self.action != "agent-candidate":
            raise ValueError("new Native execution accepts isolated agent candidates only")


_REMOTE = r"""
import hashlib,json,math,os,subprocess,sys
from pathlib import Path
b=json.loads(sys.argv[1]); launch=sys.argv[2]=='launch'
bundle=Path(b['bundle']); root=Path(b['output_root'])
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((bundle/'MANIFEST.json').read_text())
assert sha(bundle/'MANIFEST.json')==b['bundle_manifest_sha256'], 'bundle identity changed'
if launch:
    assert manifest['role']=='mlrc-meta-agent-candidate-development-bundle'
    runner=bundle/'runner.py'
    assert sha(runner)==manifest['files']['runner.py'], 'runner identity changed'
    assert not root.exists(), 'existing output cannot be relaunched'
    uuid=subprocess.check_output(['nvidia-smi','--id='+str(b['gpu_index']),
      '--query-gpu=uuid','--format=csv,noheader'],text=True).strip()
    occupied=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid',
      '--format=csv,noheader'],text=True).splitlines()
    assert uuid not in {line.strip() for line in occupied}, 'selected GPU occupied'
    # Reserve launch independently of the runner's eventual output creation.
    marker=root.with_name(root.name+'.launch.json')
    with marker.open('x') as f: json.dump(b,f,sort_keys=True)
    command=[b['python'],str(runner),'run','--bundle',str(bundle),
      '--data-root',b['data_root'],'--action',b['action'],'--gpu-index',str(b['gpu_index']),
      '--output-root',str(root),'--wall-seconds',str(b['wall_seconds'])]
    with root.with_name(root.name+'.launch.log').open('xb') as log:
        child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,
          stderr=subprocess.STDOUT,start_new_session=True)
    marker_pid=marker.with_suffix('.pid')
    marker_pid.write_text(str(child.pid))
    child.wait()
receipt=root/'RUN_RESULT.json'
if not receipt.is_file():
    marker=root.with_name(root.name+'.launch.json')
    pidfile=marker.with_suffix('.pid')
    pid=None; alive=None
    if marker.is_file() and pidfile.is_file():
        assert json.loads(marker.read_text())==b, 'remote launch binding changed'
        pid=int(pidfile.read_text()); assert pid>0
        try:
            args=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            alive=(str(bundle/'runner.py').encode() in args and str(root).encode() in args)
        except FileNotFoundError: alive=False
    # Recheck after the process observation to avoid a completion race.
    if not receipt.is_file():
        print(json.dumps({'status':'interrupted' if alive is False else 'unresolved',
          'pid':pid,'process_alive':alive,'reason':'No terminal receipt; do not relaunch.'}))
        sys.exit(0)
r=json.loads(receipt.read_text())
if not b['observation_only']:
    marker=root.with_name(root.name+'.launch.json')
    assert marker.is_file() and json.loads(marker.read_text())==b, 'native action binding differs'
assert r['bundle_manifest_sha256']==b['bundle_manifest_sha256'] and r['action']==b['action']
if r['status']=='complete':
    assert r['prediction_count']==manifest['prediction_count_per_action']
    score=root/'scoring_output/scores.txt'
    assert not score.is_symlink() and sha(score)==r['score_file_sha256']
    label,sep,value=score.read_text().splitlines()[0].partition(':')
    value=float(value)
    assert label=='overall_score' and sep and math.isfinite(value) and -1<=value<=1
    assert value==r['overall_score']
    if not b['observation_only']: assert r['execution_isolation']=='bubblewrap-candidate'
print(json.dumps({'status':r['status'],'receipt':r,'receipt_sha256':sha(receipt)}))
"""


class RemoteMLRCActionHandler:
    """Bind to Native EXPERIMENT/ANALYZE handlers; reconnect without relaunching."""

    def __init__(
        self,
        *,
        project_id: str,
        binding: RemoteMLRCBinding,
        workspace: Path,
        artifact_root: Path | None = None,
        ssh_environment: dict[str, str] | None = None,
        allow_launch: bool = False,
    ) -> None:
        self.project_id = project_id
        self.binding = binding
        self.workspace = workspace.resolve()
        self.artifact_root = (artifact_root or workspace).resolve()
        self.workspace.relative_to(self.artifact_root)
        self.ssh_environment = ssh_environment or {}
        self.allow_launch = allow_launch

    def _request(self, launch: bool, action_sha256: str) -> dict:
        command = [
            self.binding.python,
            "-c",
            _REMOTE,
            json.dumps({**asdict(self.binding), "native_action_sha256": action_sha256}),
            "launch" if launch else "observe",
        ]
        env = os.environ.copy()
        env.update(self.ssh_environment)
        result = subprocess.run(
            [
                "ssh",
                "-T",
                "-o",
                "ClearAllForwardings=yes",
                "-o",
                "ConnectTimeout=8",
                self.binding.host,
                shlex.join(command),
            ],
            env=env,
            capture_output=True,
            text=True,
            start_new_session=True,
            timeout=self.binding.wall_seconds + 180 if launch else 30,
            check=True,
        )
        return json.loads(result.stdout)

    def __call__(self, state: ResearchState, action: ResearchAction) -> ExecutionResult:
        if state.project_id != self.project_id:
            raise ValueError("remote experiment belongs to a different project")
        expected_type = (
            MetaAction.ANALYZE if self.binding.observation_only else MetaAction.EXPERIMENT
        )
        if action.type != expected_type or action.parameters != {
            "candidate_id": self.binding.candidate_id
        }:
            raise ValueError("selected action differs from the registered remote binding")
        identity = content_sha256(
            {
                "project_id": self.project_id,
                "binding": asdict(self.binding),
                "action": action.model_dump(mode="json"),
            }
        )
        self.workspace.mkdir(parents=True, exist_ok=True)
        claim = self.workspace / f"{identity}.claim.json"
        result_path = self.workspace / f"{identity}.result.json"
        if result_path.is_file():
            return ExecutionResult.model_validate_json(result_path.read_text())
        launch = False
        if not self.binding.observation_only and self.allow_launch:
            ceiling = self.binding.wall_seconds / 3600
            for maximum, used, needed in (
                (state.resource_budget.max_experiments, state.resource_usage.experiments, 1),
                (state.resource_budget.gpu_hours, state.resource_usage.gpu_hours, ceiling),
                (
                    state.resource_budget.max_wall_time_hours,
                    state.resource_usage.wall_time_hours,
                    ceiling,
                ),
            ):
                if not claim.exists() and maximum is not None and maximum - used < needed:
                    raise ValueError("remaining research budget cannot cover this remote attempt")
            try:
                with claim.open("x") as stream:
                    stream.write(json.dumps({"binding_sha256": identity, "launch_attempted": True}))
                launch = True
            except FileExistsError:
                pass  # A prior call may still be running; observation is safe, relaunch is not.
        started_at = datetime.now(UTC)
        try:
            observed = self._request(launch, identity)
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            return ExecutionResult(
                result_id=f"remote-mlrc-{identity}",
                action_id=action.action_id,
                status=ExecutionStatus.PLANNED,
                executor="scitaste-native-remote-mlrc",
                observations=[
                    "Remote observation unresolved; observe this action again without relaunch."
                ],
                data={"binding_sha256": identity, "launch_attempted": claim.exists()},
                error=type(exc).__name__,
            )
        receipt = observed.get("receipt", {})
        status = {
            "complete": ExecutionStatus.SUCCEEDED,
            "failed": ExecutionStatus.FAILED,
            "interrupted": ExecutionStatus.FAILED,
        }.get(observed["status"], ExecutionStatus.PLANNED)
        cost = {}
        if not self.binding.observation_only and receipt:
            elapsed = float(receipt["elapsed_seconds"])
            cost = {
                "experiments": 1.0,
                "wall_time_hours": elapsed / 3600,
                "gpu_hours": elapsed / 3600,
            }
        result = ExecutionResult(
            result_id=f"remote-mlrc-{identity}",
            action_id=action.action_id,
            status=status,
            executor="scitaste-native-remote-mlrc",
            started_at=started_at,
            finished_at=datetime.now(UTC),
            cost=cost,
            observations=[
                f"Remote development {observed['status']}; "
                f"official score={receipt.get('overall_score')}"
            ],
            artifacts=[result_path.relative_to(self.artifact_root).as_posix()] if receipt else [],
            data={
                **observed,
                "binding_sha256": identity,
                "primary_metric": "normalized_balanced_accuracy",
                "primary_value": receipt.get("overall_score"),
                "observation_only": self.binding.observation_only,
                "historical_import_not_native_execution": self.binding.observation_only,
                "gpu_cost_basis": (
                    "single-card ingestion/scoring elapsed-time reservation, "
                    "not measured utilization"
                ),
                "formal_evidence_eligible": False,
                "cost_complete": self.binding.observation_only or bool(receipt),
            },
        )
        if status in {ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED}:
            try:
                with result_path.open("x") as stream:
                    stream.write(result.model_dump_json(indent=2) + "\n")
            except FileExistsError:
                return ExecutionResult.model_validate_json(result_path.read_text())
        return result

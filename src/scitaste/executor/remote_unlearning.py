"""One-launch SSH callback for shared-tool unlearning development experiments."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from scitaste.executor.base import ExecutionResult, ExecutionStatus
from scitaste.executor.unlearning_resource import RemoteUnlearningResource
from scitaste.executor.unlearning_result import collect_unlearning_result

_REMOTE = r"""
import hashlib,json,os,subprocess,sys
from pathlib import Path
b=json.loads(sys.argv[1]); launch=sys.argv[2]=='launch'
root=Path(b['root']); output=root/'result'; marker=root/'LAUNCH.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if launch:
    assert not output.exists(), 'existing result cannot be relaunched'
    actual={p.relative_to(root/'candidate').as_posix():sha(p)
      for p in (root/'candidate/methods').glob('*.py') if not p.is_symlink()}
    assert actual==b['candidate_sha256'], 'candidate changed'
    for name,digest in b['runtime_sha256'].items():
        assert sha(Path(b['code'])/name)==digest, 'runtime changed'
    with marker.open('x') as f: json.dump(b,f,sort_keys=True)
    uuid=subprocess.check_output(['nvidia-smi','--id='+str(b['gpu_index']),
      '--query-gpu=uuid','--format=csv,noheader'],text=True).strip()
    command=[b['python'],b['code']+'/scripts/run_mlrc_unlearning_development.py',
      '--source',b['base']+'/upstream-env','--assets',b['base']+'/assets',
      '--candidate',str(root/'candidate'),'--output',str(output),
      '--gpu-index',str(b['gpu_index']),'--gpu-uuid',uuid,
      '--wall-seconds',str(b['wall_seconds']),'--seed',str(b['seed'])]
    env=os.environ.copy();env['PYTHONPATH']=b['base']+'/dependencies'
    with (root/'launch.log').open('xb') as log:
        child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,
          stderr=subprocess.STDOUT,start_new_session=True,env=env)
    (root/'PID').write_text(str(child.pid))
    child.wait()
if marker.exists():
    assert json.loads(marker.read_text())==b, 'launch binding differs'
files={}
for path in [output/'CONTRACT.json',output/'PROCESS_RESULT.json',output/'SCORE.json',
             *sorted((output/'exchange').glob('replica-*/RECEIPT.json'))]:
    if path.exists():
        assert not path.is_symlink() and path.is_file() and path.stat().st_size<1000000
        files[path.relative_to(output).as_posix()]=json.loads(path.read_text())
alive=None
if (root/'PID').exists():
    pid=int((root/'PID').read_text())
    try:
        argv=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        alive=(str(output).encode() in argv and
          (b['code']+'/scripts/run_mlrc_unlearning_development.py').encode() in argv)
    except FileNotFoundError: alive=False
diagnostics=[]
if alive is False and files.get('PROCESS_RESULT.json',{}).get('status')=='FAILED':
    for log in sorted(output.glob('worker-[0-9][0-9].log'))[:10]:
        if log.is_file() and not log.is_symlink():
            with log.open('rb') as stream:
                stream.seek(max(0,log.stat().st_size-8000))
                tail=stream.read(8000).decode('utf-8',errors='replace')
            if 'Traceback' in tail or 'Error' in tail:
                diagnostics.append({'worker':log.name,'tail':tail})
print(json.dumps({'files':files,'process_alive':alive,'candidate_worker_diagnostics':diagnostics}))
"""


class RemoteUnlearningExperiment:
    """Callable shared-tool backend with explicit observe(), no implicit relaunch.

    Local output must be a new task-owned directory. API/SSH credentials are
    inherited only via the caller's environment, never placed in the binding.
    """

    def __init__(
        self,
        *,
        run_id: str,
        output: Path,
        code_root: Path,
        ssh_environment: dict[str, str],
        gpu_index: int = 3,
        wall_seconds: int = 1800,
        resource: RemoteUnlearningResource | None = None,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
            raise ValueError("Invalid run identity")
        if resource is not None:
            gpu_index = resource.gpu_index
        if not 0 <= gpu_index < 64 or not 60 <= wall_seconds <= 7200:
            raise ValueError("Invalid execution limits")
        self.run_id, self.output, self.code_root = run_id, output, code_root
        self.output.mkdir(parents=True, exist_ok=True)
        self.environment = {**os.environ, **ssh_environment}
        self.gpu_index, self.wall_seconds = gpu_index, wall_seconds
        self.resource = resource

    def _pending(self, reason: str) -> dict:
        return ExecutionResult(
            action_id=self.run_id,
            executor="scitaste-native-remote-unlearning",
            status=ExecutionStatus.PLANNED,
            observations=[reason],
            data={"primary_value": None, "cost_complete": False, "formal_evidence_eligible": False},
        ).model_dump(mode="json")

    def _request(self, binding: dict, launch: bool) -> dict:
        ssh, target = self._connection(binding)
        command = [
            binding["python"],
            "-c",
            _REMOTE,
            json.dumps(binding),
            "launch" if launch else "observe",
        ]
        result = subprocess.run(
            [*ssh, "-T", target, shlex.join(command)],
            env=self.environment,
            start_new_session=True,
            capture_output=True,
            text=True,
            check=True,
            timeout=self.wall_seconds + 120 if launch else 30,
        )
        return json.loads(result.stdout)

    @staticmethod
    def _connection(binding):
        command = ["ssh", "-o", "ClearAllForwardings=yes", "-o", "ConnectTimeout=10"]
        if "resource" not in binding:
            return command, "4090-2"  # Historical bindings retain their original route.
        resource = RemoteUnlearningResource.model_validate(binding["resource"])
        host = resource.host
        return [*command, "-p", str(host.connection_port)], (
            host.connection_user + "@" + host.connection_host
        )

    def _collect(self, binding: dict, observed: dict) -> dict:
        files = observed["files"]
        if "CONTRACT.json" not in files:
            return self._pending("Remote contract not yet collected; observe without relaunch.")
        contract = files["CONTRACT.json"]
        for name in ("seed", "wall_seconds", "gpu_index"):
            if contract.get(name) != binding[name]:
                raise ValueError(f"Collected run limit differs: {name}")
        if contract["candidate_sha256"] != binding["candidate_sha256"]:
            raise ValueError("Collected candidate differs from frozen source")
        expected_runtime = {Path(k).name: v for k, v in binding["runtime_sha256"].items()}
        if contract["runtime_sha256"] != expected_runtime:
            raise ValueError("Collected runtime differs from frozen execution")
        collected = self.output / "collected"
        for name, value in files.items():
            if name not in {
                "CONTRACT.json",
                "PROCESS_RESULT.json",
                "SCORE.json",
            } and not re.fullmatch(
                r"exchange/replica-0[0-9]/RECEIPT.json",
                name,
            ):
                raise ValueError("Unexpected remote artifact")
            path = collected / name
            path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(value, sort_keys=True, indent=2) + "\n"
            if path.exists():
                if path.read_text() != text:
                    raise ValueError("Immutable remote evidence changed")
            else:
                with path.open("x") as stream:
                    stream.write(text)
        digest = hashlib.sha256((collected / "CONTRACT.json").read_bytes()).hexdigest()
        result = collect_unlearning_result(collected, action_id=self.run_id, contract_sha256=digest)
        result = result.model_copy(
            update={
                "data": {
                    **result.data,
                    "remote_process_alive": observed.get("process_alive"),
                    "candidate_worker_diagnostics": observed.get(
                        "candidate_worker_diagnostics", []
                    ),
                    "collected_replica_receipts": sum(
                        name.endswith("/RECEIPT.json") for name in files
                    ),
                }
            }
        )
        if result.status == ExecutionStatus.PLANNED and observed.get("process_alive") is False:
            result = result.model_copy(
                update={
                    "status": ExecutionStatus.FAILED,
                    "error": "Remote supervisor exited without terminal receipt; cost incomplete.",
                }
            )
        if result.status != ExecutionStatus.PLANNED:
            result_path = self.output / "EXECUTION_RESULT.json"
            if result_path.exists():
                return ExecutionResult.model_validate_json(result_path.read_text()).model_dump(
                    mode="json"
                )
            with result_path.open("x") as stream:
                stream.write(result.model_dump_json(indent=2) + "\n")
        return result.model_dump(mode="json")

    def observe(self) -> dict:
        binding = json.loads((self.output / "BINDING.json").read_text())
        try:
            return self._collect(binding, self._request(binding, False))
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
            return self._pending(
                f"Observation unavailable ({type(exc).__name__}); do not relaunch."
            )

    def __call__(self, workspace: Path) -> dict:
        marker = self.output / "BINDING.json"
        if marker.exists():
            return self.observe()
        names = [
            "scripts/run_mlrc_unlearning_development.py",
            "scripts/mlrc_unlearning_worker.py",
            "scripts/mlrc_meta_visual_fork_runtime.py",
            "src/scitaste/evaluation/mlrc_unlearning.py",
            "src/scitaste/evaluation/unlearning_exchange.py",
        ]
        candidate = {}
        for path in sorted((workspace / "methods").glob("*.py")):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 150_000:
                raise ValueError("Invalid candidate source")
            candidate[f"methods/{path.name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
        if "methods/MyMethod.py" not in candidate:
            raise ValueError("Missing candidate method")
        base = "/data/zfx/scitaste/mlrc-unlearning-dev-20260925"
        binding = {
            "root": base + "/agents/" + self.run_id,
            "base": base,
            "code": base + "/code",
            "python": "/data/zfx/scitaste/mlrc-meta-dev-20260925/venv/bin/python",
            "candidate_sha256": candidate,
            "runtime_sha256": {
                name: hashlib.sha256((self.code_root / name).read_bytes()).hexdigest()
                for name in names
            },
            "gpu_index": self.gpu_index,
            "wall_seconds": self.wall_seconds,
            "seed": 42,
        }
        if self.resource is not None:
            binding.update(
                root=self.resource.base + "/agents/" + self.run_id,
                base=self.resource.base,
                code=self.resource.code,
                python=self.resource.python,
                seed=self.resource.seed,
                host_alias=self.resource.host.connection_alias,
                resource=self.resource.model_dump(mode="json"),
            )
        with marker.open("x") as stream:
            json.dump(binding, stream, indent=2)
        ssh, target = self._connection(binding)
        try:
            subprocess.run(
                [
                    *ssh,
                    "-T",
                    target,
                    shlex.join(["mkdir", "-p", binding["root"] + "/candidate/methods"]),
                ],
                env=self.environment,
                start_new_session=True,
                check=True,
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                [
                    "rsync",
                    "-a",
                    "-e",
                    shlex.join(ssh),
                    str(workspace / "methods") + "/",
                    target + ":" + binding["root"] + "/candidate/methods/",
                ],
                env=self.environment,
                start_new_session=True,
                check=True,
                capture_output=True,
                timeout=60,
            )
            return self._collect(binding, self._request(binding, True))
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
            return self._pending(
                f"Launch/observation unresolved ({type(exc).__name__}); observe only."
            )

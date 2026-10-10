"""Network-isolated, resource-bounded Python for benchmark code assistance."""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from scitaste.project.models import content_sha256

_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
_SHA256 = r"^[0-9a-f]{64}$"


class SandboxedPythonPolicy(BaseModel):
    """Frozen limits and binary identities for one code-tool condition."""

    model_config = _CONFIG

    schema_version: Literal["1.0"] = "1.0"
    implementation: Literal["bubblewrap-python-stdin-v1"] = "bubblewrap-python-stdin-v1"
    bubblewrap_path: str
    bubblewrap_sha256: str = Field(pattern=_SHA256)
    python_path: str
    python_sha256: str = Field(pattern=_SHA256)
    timeout_seconds: int = Field(ge=1, le=60)
    cpu_seconds: int = Field(ge=1, le=60)
    memory_mib: int = Field(ge=64, le=4_096)
    max_output_bytes: int = Field(ge=1_024, le=4_000_000)
    max_processes: int = Field(ge=1, le=64)
    network_access: Literal[False] = False
    host_worktree_access: Literal[False] = False
    policy_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def policy_is_closed(self) -> SandboxedPythonPolicy:
        expected = content_sha256(self.model_dump(mode="json", exclude={"policy_sha256"}))
        if self.policy_sha256 != expected:
            raise ValueError("sandboxed Python policy hash mismatch")
        return self

    @classmethod
    def create(cls, **values: object) -> SandboxedPythonPolicy:
        payload = {"schema_version": "1.0", **values}
        payload.pop("policy_sha256", None)
        unsigned = cls.model_construct(policy_sha256="0" * 64, **payload)
        return cls(
            **payload,
            policy_sha256=content_sha256(
                unsigned.model_dump(mode="json", exclude={"policy_sha256"})
            ),
        )


class BubblewrapPythonCodeRunner:
    """Execute model-authored Python without network or project-file visibility."""

    def __init__(
        self,
        *,
        python_executable: str | Path = "/usr/bin/python3.12",
        bubblewrap_executable: str | Path = "/usr/bin/bwrap",
        timeout_seconds: int = 8,
        cpu_seconds: int = 6,
        memory_mib: int = 512,
        max_output_bytes: int = 128_000,
        max_processes: int = 16,
    ) -> None:
        python_path = _executable(python_executable, "Python")
        bwrap_path = _executable(bubblewrap_executable, "bubblewrap")
        if not python_path.is_relative_to(Path("/usr")):
            raise ValueError("sandboxed Python must reside under the read-only /usr binding")
        self.policy = SandboxedPythonPolicy.create(
            bubblewrap_path=str(bwrap_path),
            bubblewrap_sha256=_sha256_file(bwrap_path),
            python_path=str(python_path),
            python_sha256=_sha256_file(python_path),
            timeout_seconds=timeout_seconds,
            cpu_seconds=cpu_seconds,
            memory_mib=memory_mib,
            max_output_bytes=max_output_bytes,
            max_processes=max_processes,
            network_access=False,
            host_worktree_access=False,
        )

    @property
    def fingerprint(self) -> str:
        return self.policy.policy_sha256

    def run(self, code: str) -> JsonValue:
        if not code.strip():
            raise ValueError("sandboxed Python received empty code")
        encoded = code.encode()
        if len(encoded) > 32_000:
            raise ValueError("sandboxed Python code exceeds byte limit")
        command = self._command()
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                env={"HOME": "/tmp", "LANG": "C.UTF-8", "PATH": "/usr/bin"},
                start_new_session=True,
            )
            timed_out = False
            try:
                process.communicate(input=encoded, timeout=self.policy.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
            stdout, stdout_truncated = _read_bounded(
                stdout_file,
                self.policy.max_output_bytes,
            )
            stderr, stderr_truncated = _read_bounded(
                stderr_file,
                self.policy.max_output_bytes,
            )
        return {
            "tool": "sandboxed_python",
            "status": "timeout" if timed_out else ("ok" if process.returncode == 0 else "error"),
            "returncode": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "policy_sha256": self.policy.policy_sha256,
        }

    def _command(self) -> list[str]:
        memory_bytes = self.policy.memory_mib * 1_048_576
        output_bytes = self.policy.max_output_bytes + 1
        bindings: list[str] = ["--ro-bind", "/usr", "/usr"]
        for path in ("/lib", "/lib64"):
            if Path(path).exists():
                bindings.extend(("--ro-bind", path, path))
        return [
            self.policy.bubblewrap_path,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            *bindings,
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/home",
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "PATH",
            "/usr/bin",
            "--chdir",
            "/tmp",
            "/usr/bin/prlimit",
            f"--as={memory_bytes}",
            f"--cpu={self.policy.cpu_seconds}",
            f"--fsize={output_bytes}",
            "--nofile=64",
            f"--nproc={self.policy.max_processes}",
            "--",
            self.policy.python_path,
            "-I",
            "-",
        ]


class ScientificPythonPolicy(SandboxedPythonPolicy):
    schema_version: Literal["1.1"] = "1.1"
    implementation: Literal["bubblewrap-scientific-python-v1"] = "bubblewrap-scientific-python-v1"
    runtime_root: str
    package_versions: dict[str, str]


class ScientificPythonCodeRunner(BubblewrapPythonCodeRunner):
    """Expose only the selected Python runtime, never the surrounding project.

    A separate runtime binding supports the project's Python 3.12 installation and
    its NumPy/SciPy packages. No credential environment, worktree or network is bound.
    """

    def __init__(self, *, runtime_root, python_executable, **limits):
        import importlib.metadata

        root = Path(runtime_root).resolve(strict=True)
        executable = _executable(python_executable, "Python")
        if root in {Path("/"), Path.home(), Path("/home"), Path("/tmp")}:
            raise ValueError("A dedicated Python runtime directory is required")
        if not executable.is_relative_to(root / "bin") or not (root / "lib").is_dir():
            raise ValueError("Python must belong to the declared isolated runtime")
        # Reuse bounded process/output handling, but use a separately versioned policy.
        super().__init__(python_executable="/usr/bin/python3", **limits)
        values = self.policy.model_dump(exclude={"policy_sha256"})
        values.update(
            schema_version="1.1",
            implementation="bubblewrap-scientific-python-v1",
            python_path=str(executable),
            python_sha256=_sha256_file(executable),
            runtime_root=str(root),
            package_versions={
                name: importlib.metadata.version(name) for name in ("numpy", "scipy")
            },
        )
        self.policy = ScientificPythonPolicy.create(**values)

    def _command(self):
        command = super()._command()
        position = command.index("--proc")
        command[position:position] = [
            "--ro-bind",
            self.policy.runtime_root,
            self.policy.runtime_root,
        ]
        command[command.index("--chdir") : command.index("--chdir")] = [
            "--setenv",
            "OPENBLAS_NUM_THREADS",
            "1",
            "--setenv",
            "OMP_NUM_THREADS",
            "1",
        ]
        return command


def _executable(path: str | Path, label: str) -> Path:
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError(f"{label} path is not an executable regular file")
    return resolved


def _read_bounded(handle, maximum: int) -> tuple[str, bool]:
    handle.seek(0)
    payload = handle.read(maximum + 1)
    truncated = len(payload) > maximum
    return payload[:maximum].decode("utf-8", errors="replace"), truncated


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["BubblewrapPythonCodeRunner", "SandboxedPythonPolicy"]

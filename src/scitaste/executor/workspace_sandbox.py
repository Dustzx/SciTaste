"""CPU workspace filesystem boundary shared by benchmark code execution."""

import shlex
import sys
from pathlib import Path


def command(workspace, argv, *, network=True, readonly=None, cwd=None):
    workspace = Path(workspace).resolve(strict=True)
    result = [
        "/usr/bin/env",
        "-i",
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
    ]
    if not network:
        result += ["--unshare-net"]
    result += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for name in (
        "/usr",
        "/bin",
        "/lib",
        "/lib64",
        "/etc/ssl",
        "/etc/fonts",
        "/etc/resolv.conf",
        "/etc/hosts",
    ):
        if Path(name).exists():
            result += ["--ro-bind", name, name]
    result += ["--ro-bind", sys.prefix, sys.prefix, "--bind", str(workspace), str(workspace)]
    for source, target in (readonly or {}).items():
        result += ["--ro-bind", str(Path(source).resolve(strict=True)), str(target)]
    environment = {
        "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "CUDA_VISIBLE_DEVICES": "",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "MPLCONFIGDIR": "/tmp/matplotlib",
        "XDG_CACHE_HOME": "/tmp/cache",
        "PYTHONNOUSERSITE": "1",
        "PIP_NO_INDEX": "1",
    }
    for name, value in environment.items():
        result += ["--setenv", name, value]
    result += ["--chdir", str(cwd or workspace), *argv]
    return result


def isolated_bash_class(original, *, protected_paths=()):
    class IsolatedBash(original):
        def call(self, params, **kwargs):
            supplied = self.parse_json_args(params)
            workspace = Path(kwargs["workspace_root"]).resolve(strict=True)
            cwd = Path(supplied.get("workdir") or workspace)
            if not cwd.is_absolute():
                cwd = workspace / cwd
            cwd = cwd.resolve(strict=True)
            cwd.relative_to(workspace)
            readonly = {}
            for relative in protected_paths:
                protected = workspace / relative
                protected.resolve().relative_to(workspace)
                if protected.exists():
                    readonly[protected] = str(protected)
            argv = command(
                workspace,
                ["/bin/bash", "-c", supplied["command"]],
                cwd=cwd,
                readonly=readonly,
            )
            return super().call(
                {**supplied, "command": shlex.join(argv), "workdir": str(workspace)}, **kwargs
            )

    return IsolatedBash

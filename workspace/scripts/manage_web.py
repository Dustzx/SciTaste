#!/usr/bin/env python3
"""Install and manage the SciTaste local user service, without root access."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = "fastresearch-web.service"


def call(*args):
    subprocess.run(["systemctl", "--user", *args], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "start", "stop", "restart", "status", "logs"])
    args = parser.parse_args()
    if args.action == "install":
        config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd/user"
        config.mkdir(parents=True, exist_ok=True)
        backend_python = ROOT / ".venv/bin/python"
        interpreter = str(backend_python) if backend_python.is_file() else sys.executable
        unit = (ROOT / "deploy" / SERVICE).read_text().replace("@ROOT@", str(ROOT)).replace("@PYTHON@", interpreter)
        (config / SERVICE).write_text(unit)
        call("daemon-reload")
        call("enable", "--now", SERVICE)
        print("SciTaste installed at http://127.0.0.1:8765 (starts with the user session).")
    elif args.action == "logs":
        subprocess.run(["journalctl", "--user", "-u", SERVICE, "-n", "60", "--no-pager"], check=True)
    elif args.action == "status":
        call("status", SERVICE, "--no-pager", "--lines=8")
    else:
        call(args.action, SERVICE)


if __name__ == "__main__":
    main()

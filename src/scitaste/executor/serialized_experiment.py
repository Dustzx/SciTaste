"""Serialize this host's launches and retain ownership across ambiguous remote results."""

import fcntl
import json
from pathlib import Path


class SerializedExperiment:
    def __init__(self, experiment, lock_path):
        self.experiment = experiment
        self.lock_path = Path(lock_path).resolve()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lease = self.lock_path.with_suffix(".lease.json")
        self.owner = str(experiment.output.resolve())

    @staticmethod
    def terminal(result):
        return str(result.get("status", "")).upper() in {"SUCCEEDED", "FAILED", "CANCELLED"} and (
            result.get("data", {}).get("remote_process_alive") is False
        )

    def __call__(self, workspace):
        with self.lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.lease.exists():
                raise RuntimeError("GPU launch ownership unresolved; observe existing run first")
            with self.lease.open("x") as stream:
                json.dump({"owner": self.owner}, stream)
            # Exceptions deliberately preserve ownership: don't assume no remote process.
            result = self.experiment(workspace)
            if self.terminal(result):
                self.lease.unlink()
            return result

    def observe(self):
        with self.lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.lease.exists() and json.loads(self.lease.read_text())["owner"] != self.owner:
                raise RuntimeError("Cannot clear another experiment's GPU ownership")
            result = self.experiment.observe()
            if self.lease.exists() and self.terminal(result):
                self.lease.unlink()
            return result

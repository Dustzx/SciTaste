#!/usr/bin/env python3
"""Enter the complete owned SciTaste CLI from the product workspace."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    bundle = ROOT / "backend/scitaste"
    if not (bundle / "src/scitaste").is_dir():
        bundle = ROOT.parent
    interpreter = ROOT / ".venv/bin/python"
    if not interpreter.is_file():
        interpreter = bundle / ".venv/bin/python"
    if not interpreter.is_file() or not (bundle / "src/scitaste/cli.py").is_file():
        raise SystemExit("请先在 SciTaste 仓库配置 Python 3.12 环境")
    # The local migration uses an outputs symlink; the public workspace owns
    # its own outputs tree, shared by this CLI and the web adapter.
    os.chdir(bundle if (ROOT / "backend/scitaste").is_dir() else ROOT)
    os.environ["PYTHONPATH"] = str(bundle / "src")
    os.execv(str(interpreter), [str(interpreter), "-m", "scitaste.cli", *sys.argv[1:]])

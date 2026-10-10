#!/usr/bin/env python3
"""Return one ignored resource credential to SSH_ASKPASS without logging it."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    path = Path(os.environ["SCITASTE_ASKPASS_CREDENTIAL_FILE"])
    name = os.environ["SCITASTE_ASKPASS_CREDENTIAL_NAME"]
    if not name.isidentifier() or not path.is_file() or path.is_symlink():
        raise ValueError("invalid SSH credential binding")
    if path.stat().st_mode & 0o077:
        raise ValueError("SSH credential file must be mode 0600")
    matches = []
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key == name and value:
            matches.append(value)
    if len(matches) != 1:
        raise ValueError("SSH credential binding must be unique and nonempty")
    sys.stdout.write(matches[0])


if __name__ == "__main__":
    main()

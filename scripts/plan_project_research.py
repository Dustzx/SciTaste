"""Compatibility entry for project research planning with legacy adapter inventory."""

import sys
from pathlib import Path

from scitaste.project.research_planning import main as package_main


def main():
    if not any(arg == "--code-root" or arg.startswith("--code-root=") for arg in sys.argv[1:]):
        sys.argv.extend(["--code-root", str(Path.cwd())])
    package_main()


if __name__ == "__main__":
    main()

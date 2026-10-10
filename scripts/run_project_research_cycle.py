"""Compatibility entrypoint for the packaged research-cycle coordinator."""

from scitaste.project.research_cycle import main as main
from scitaste.project.research_cycle import sha as sha

if __name__ == "__main__":
    main()

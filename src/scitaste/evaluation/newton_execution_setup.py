"""One shared, explicitly enabled numerical-analysis condition for both systems."""

import sys

from scitaste.evaluation.interactive_research import InteractiveResearchLimits
from scitaste.evaluation.sandboxed_code import ScientificPythonCodeRunner


def execution_setup(task, *, live, allow_code):
    if task.code_assisted != allow_code:
        raise ValueError("Task code-assistance declaration must match explicit execution opt-in")
    runner = (
        ScientificPythonCodeRunner(
            runtime_root=sys.base_prefix,
            python_executable=sys.executable,
            memory_mib=2048,
            timeout_seconds=20,
            cpu_seconds=15,
        )
        if allow_code
        else None
    )
    limits = InteractiveResearchLimits(
        max_turns=12 if allow_code else 8,
        max_experiments=24,
        max_experiments_per_turn=6,
        max_code_calls=4 if allow_code else 0,
        max_total_tokens=200_000,
        max_api_cost_usd=8 if live else 0,
        require_cost_telemetry=False,
    )
    return limits, runner

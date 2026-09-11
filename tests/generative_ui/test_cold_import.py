from __future__ import annotations

import subprocess
import sys


def test_generative_ui_and_lazy_writing_api_import_in_a_fresh_interpreter() -> None:
    code = """
import scitaste.generative_ui
from scitaste.writing import prepare_project_paper_revision_context
assert callable(prepare_project_paper_revision_context)
"""

    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )

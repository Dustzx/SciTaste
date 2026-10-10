"""Explicit report partitions keep immutable experimental evidence available."""

import pytest

from scitaste.writing.report_import import split_report_appendix


def test_appendix_partition_is_lossless_and_ignores_fenced_heading():
    main = (
        "# Scientific report\n\n"
        + "Measured β evidence remains unchanged. " * 25
        + "\n```text\n## Complete appendix\n```\n\n"
    )
    appendix = "## Complete appendix\n\nFull raw records.\n"
    before, after = split_report_appendix(main + appendix, "Complete appendix")
    assert before == main
    assert after == appendix
    assert (before + after).encode() == (main + appendix).encode()


def test_appendix_partition_rejects_ambiguous_or_non_appendix_boundaries():
    main = "# Report\n\n" + "Observed scientific evidence. " * 25
    with pytest.raises(ValueError, match="exactly once"):
        split_report_appendix(main + "\n## Appendix\nA\n## Appendix\nB\n", "Appendix")
    with pytest.raises(ValueError, match="identify an appendix"):
        split_report_appendix(main + "\n## Methods\n", "Methods")

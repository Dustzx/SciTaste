"""Source visibility without executable mutation or discarded evidence."""

import copy
import hashlib
import json

from scitaste.executor.research_history import compact_tool_history, workspace_history_view


def row(tool, arguments, observations, status="SUCCEEDED"):
    return {
        "proposal": {"tool": tool, "arguments": copy.deepcopy(arguments)},
        "selected": {"parameters": {"tool": tool, "arguments": arguments}},
        "result": {"status": status, "observations": observations, "data": {}, "error": None},
    }


def test_hidden_write_does_not_erase_a_later_explicit_read():
    source = "# current algorithm\n" + "print('inspect me')\n" * 300
    history = [
        row("Write", {"path": "model.py", "content": source}, ["written"]),
        row("Read", {"path": "model.py"}, [source]),
    ]
    before = copy.deepcopy(history)
    assert compact_tool_history(history, keep_latest_source=False)[1]["result"]["observations"] == [
        source
    ]
    assert workspace_history_view(history)[1]["observations"] == [source]
    assert history == before


def test_deduplication_requires_an_earlier_visible_byte_identical_write():
    history = [
        row("Read", {"path": "model.py"}, ["old source"]),
        row("Write", {"path": "model.py", "content": "new source"}, ["written"]),
        row("Read", {"path": "model.py"}, ["new source", "partial new source"]),
    ]
    projected = compact_tool_history(history)
    assert projected[0]["result"]["observations"] == ["old source"]
    assert projected[2]["result"]["observations"][0]["source_body_omitted"] is True
    assert projected[2]["result"]["observations"][1] == "partial new source"


def test_large_reads_are_explicitly_bounded_but_measured_results_are_not_hidden():
    source = "头部可见\n" + "middle source line\n" * 5000 + "\n末尾可见"
    measurement = "measured result, not source\n" * 3000
    history = [
        row("Read", {"path": "large.py"}, [source]),
        row("Bash", {"command": "analyze existing.csv"}, [measurement]),
    ]
    view = workspace_history_view(history)
    read = view[0]["observations"][0]
    assert read["sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert read["prefix"].startswith("头部可见")
    assert read["suffix"].endswith("末尾可见")
    assert len(json.dumps(read, ensure_ascii=False).encode()) <= 32768
    assert "not visible evidence" in read["authority"]
    assert view[1]["observations"] == [measurement]

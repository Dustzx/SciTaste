"""Expose pytest failures as public GitHub check annotations."""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree


def _escape(value: str, *, property_value: bool = False) -> str:
    escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        escaped = escaped.replace(":", "%3A").replace(",", "%2C")
    return escaped


def _annotation(test_case: ElementTree.Element, detail: ElementTree.Element) -> str:
    path = test_case.attrib.get("file", ".github/workflows/ci.yml")
    line = test_case.attrib.get("line", "1")
    identity = ".".join(
        part
        for part in (
            test_case.attrib.get("classname", "pytest"),
            test_case.attrib.get("name", "failure"),
        )
        if part
    )
    message = detail.attrib.get("message", "")
    body = (detail.text or "").strip()
    combined = "\n".join(part for part in (message, body) if part).strip()
    if not combined:
        combined = "pytest exited unsuccessfully without a failure message"
    combined = combined[-8_000:]
    return (
        f"::error file={_escape(path, property_value=True)},"
        f"line={line},title={_escape(identity, property_value=True)}::"
        f"{_escape(combined)}"
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        raise SystemExit("usage: report_pytest_failures.py JUNIT_XML")
    report = Path(arguments[0])
    try:
        root = ElementTree.parse(report).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        print(f"::error title=pytest report unavailable::{_escape(str(exc))}")
        return 1

    failures: list[str] = []
    for test_case in root.iter("testcase"):
        for kind in ("failure", "error"):
            detail = test_case.find(kind)
            if detail is not None:
                failures.append(_annotation(test_case, detail))
    for annotation in failures[:20]:
        print(annotation)
    if len(failures) > 20:
        print(f"::warning title=pytest failures truncated::{len(failures) - 20} more failures")
    if not failures:
        print("::error title=pytest failed::No failing testcase was present in the JUnit report")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

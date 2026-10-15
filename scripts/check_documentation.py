"""Check the documentation inventory, navigation and preserved reference bytes.

Standard library only; reads local files and never executes research or imports
the SciTaste runtime. Historical verbatim snapshots keep their original context.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def check(root: Path) -> dict:
    root = root.resolve()
    docs = root / "docs"
    catalog = json.loads((docs / "catalog.json").read_text())
    migration = json.loads((docs / "migration-20261012.json").read_text())
    entries = catalog["documents"]
    paths = [item["path"] for item in entries]
    actual = {p.relative_to(docs).as_posix() for p in docs.rglob("*.md")}
    errors = []
    if len(paths) != len(set(paths)) or set(paths) != actual:
        errors.append(
            {
                "inventory_missing": sorted(actual - set(paths)),
                "inventory_stale": sorted(set(paths) - actual),
                "duplicate_paths": len(paths) != len(set(paths)),
            }
        )
    for path in paths:
        if Path(path).is_absolute() or ".." in Path(path).parts:
            errors.append({"unsafe_inventory_path": path})

    def hash_file(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    redactions = {item["path"]: item for item in migration.get("privacy_redactions", [])}

    def retained_or_redacted(path: str, original: str) -> bool:
        candidate = root / path
        if not candidate.is_file():
            return False
        actual = hash_file(candidate)
        redaction = redactions.get(path, {})
        return actual == original or (
            redaction.get("original_sha256") == original
            and redaction.get("public_sha256") == actual
            and redaction.get("reason") == "owner-required privacy redaction"
        )

    for item in migration["protected"]:
        if not retained_or_redacted(item["path"], item["sha256"]):
            errors.append({"preserved_reference_changed": item["path"]})
    for item in migration["snapshots"]:
        if not retained_or_redacted(item["snapshot"], item["sha256"]):
            errors.append({"snapshot_changed": item["snapshot"]})
    for item in migration["moves"]:
        if (root / item["old"]).exists() or not (root / item["new"]).is_file():
            errors.append({"incomplete_move": item["old"]})
        if item["new"].startswith("docs/archive/"):
            if not retained_or_redacted(item["new"], item["original_sha256"]):
                errors.append({"archived_record_changed": item["new"]})

    # Source-preserving snapshots are historical data, not active navigation.
    # Their indexes link the current migration map and canonical documentation.
    checked_links = 0
    for item in entries:
        if item["role"] == "historical-record":
            continue
        p = docs / item["path"]
        if not p.is_file():
            continue
        text = re.sub(r"(?ms)^```.*?^```[^\n]*$", "", p.read_text())
        for target in re.findall(r"(?<!!)\[[^\]\n]*\]\(([^)\n]+)\)", text):
            if re.match(r"^(?:[a-z]+:|/|#)", target):
                continue
            part = target.split("#")[0].split("?", 1)[0]
            if not part or any(c in part for c in " <>{}"):
                continue
            checked_links += 1
            candidate = p.parent / part
            if not candidate.exists():
                errors.append({"broken_link": item["path"], "target": target})
    mutable_root = {
        item["path"]
        for item in entries
        if "/" not in item["path"] and item["role"] != "frozen-reference"
    }
    if mutable_root != {"README.md", "ARCHITECTURE.md", "ROADMAP.md", "INNOVATION_MAP.md"}:
        errors.append({"unexpected_root_documents": sorted(mutable_root)})
    return {
        "status": "FAIL" if errors else "PASS",
        "documents": len(actual),
        "active_relative_links_checked": checked_links,
        "preserved_references": len(migration["protected"]),
        "verbatim_snapshots": len(migration["snapshots"])
        - sum(item["snapshot"] in redactions for item in migration["snapshots"]),
        "privacy_redactions": len(redactions),
        "moves": len(migration["moves"]),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = check(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

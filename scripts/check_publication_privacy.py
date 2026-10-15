"""Check publication boundaries without embedding private identities in source.

An optional local policy supplies private terms and reviewed media hashes. Findings
contain paths and rule names only; matching text and policy values are never logged.
This checks the selected tree, not previously published Git history or image pixels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

PRIVATE_DIRECTORIES = (
    "private/",
    "report/",
    "reports/",
    "workspace/report/",
    "workspace/reports/",
    "workspace/outputs/",
    "workspace/cache/",
    "workspace/data/research_profiles/",
    "workspace/data/research_introductions/",
    "workspace/web/assets/projects/",
    "workspace/web/assets/research-introductions/",
    "workspace/scripts/cvpr_",
)
PRIVATE_RECORDS = {
    "STATUS_BOARD.json",
    "EXPERIENCE_POOL.json",
    "SHARED_RACE.json",
    "API_LEDGER.json",
    "PREDICTIONS.json",
    "calls.jsonl",
}


def check(root: Path, policy: dict, staged: bool = False, ref: str | None = None) -> dict:
    paths = subprocess.check_output(
        ["git", "ls-tree", "-rz", "--name-only", ref] if ref else ["git", "ls-files", "-z"],
        cwd=root,
    ).split(b"\0")
    terms = [
        re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", re.I)
        for term in policy.get("private_terms", [])
        if term
    ]
    host_path = re.compile(
        rb"(?<![A-Za-z0-9.])/(?:home/(?!example/|user/|runner/)[^/\s\"']+|media/[^/\s\"']+/[^/\s\"']+)/"
    )
    media_manifest = root / "site/assets/platform-screenshots.json"
    if ref:
        media = subprocess.run(
            ["git", "show", ref + ":site/assets/platform-screenshots.json"],
            cwd=root,
            capture_output=True,
        )
        reviewed_media = (
            json.loads(media.stdout).get("approved_media_sha256", {})
            if media.returncode == 0
            else {}
        )
    else:
        reviewed_media = (
            json.loads(media_manifest.read_text()).get("approved_media_sha256", {})
            if media_manifest.is_file()
            else {}
        )
    reviewed_media.update(policy.get("approved_media_sha256", {}))
    findings = []
    if ref:
        message = subprocess.check_output(
            ["git", "log", "-1", "--format=%B", ref], cwd=root
        ).decode()
        if any(term.search(message) for term in terms):
            findings.append({"path": "<commit-message>", "rules": ["private-identity-in-message"]})
    scanned = 0
    for raw in paths:
        if not raw:
            continue
        name = raw.decode()
        path = root / name
        if name.startswith("third_party/") or (not ref and not staged and not path.is_file()):
            continue
        body = (
            subprocess.check_output(["git", "show", (ref or "") + ":" + name], cwd=root)
            if staged or ref
            else path.read_bytes()
        )
        scanned += 1
        reasons = []
        if (
            name.startswith(PRIVATE_DIRECTORIES)
            or path.name in PRIVATE_RECORDS
            or path.name == ".env"
            or (path.name.startswith(".env.") and path.name != ".env.example")
        ):
            reasons.append("private-record-path")
        if any(term.search(name) for term in terms):
            reasons.append("private-identity-in-path")
        if host_path.search(body):
            reasons.append("personal-machine-path")
        try:
            content = body.decode("utf-8")
        except UnicodeDecodeError:
            content = None
        if content is not None and any(term.search(content) for term in terms):
            reasons.append("private-identity-in-content")
        if name.startswith("site/assets/platform-") and path.suffix in {".png", ".webp", ".jpg"}:
            if hashlib.sha256(body).hexdigest() != reviewed_media.get(name):
                reasons.append("platform-screenshot-needs-review")
        if name == "workspace/data/research_registry.json":
            registry = json.loads(body)
            if registry.get("ideas") or registry.get("research_candidates"):
                reasons.append("private-research-planning")
        if reasons:
            findings.append({"path": name, "rules": reasons})
    return {
        "status": "FAIL" if findings else "PASS",
        "files_checked": scanned,
        "local_identity_policy_loaded": bool(terms),
        "findings": findings,
        "scope": "selected tree; history and screenshot pixels require separate review",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--policy", type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--staged", action="store_true")
    source.add_argument("--ref", help="inspect committed bytes instead of working files")
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text()) if args.policy else {}
    result = check(args.root.resolve(), policy, args.staged, args.ref)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
